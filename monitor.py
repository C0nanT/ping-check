#!/usr/bin/env python3
"""Monitor de conexão: grava amostras periódicas em SQLite.

Cada ciclo (INTERVAL s) mede, em paralelo:
  - ping ao gateway (modem)      -> problema local/WiFi
  - ping a 1.1.1.1 e 8.8.8.8     -> problema do provedor/internet
  - resolução DNS                -> problema de DNS
  - sinal WiFi (/proc/net/wireless)
A cada WIFI_INFO_EVERY s grava também BSSID/canal/taxa via nmcli.
Quedas (status != ok) viram linhas na tabela `outages` com início/fim.
Ao abrir uma queda `falha_internet`, roda um tracepath em segundo plano e grava o caminho em `rotas`.
A cada VELOCIDADE_A_CADA min (internet no ar), faz um teste de velocidade em segundo plano e grava em
`velocidade`, com a latência parado/baixando/enviando em `latencia_carga`.
"""
import concurrent.futures as cf
import json
import os
import re
import signal
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conexao.db")
INTERVAL = 5            # segundos entre ciclos
PING_COUNT = 4          # pacotes por alvo por ciclo
PING_SPACING = 0.2      # s entre pacotes
PING_TIMEOUT = 1        # s de espera por resposta
DNS_HOST = "google.com"
DNS_TIMEOUT = 3
DNS_CMD = ["getent", "ahosts"]   # + DNS_HOST; resolve via NSS, como os programas do sistema
WIFI_INFO_EVERY = 60
INTERNET_TARGETS = {"cf": "1.1.1.1", "google": "8.8.8.8"}
ROTA_ALVO = "1.1.1.1"
# + alvo. tracepath usa UDP: sem root nem capability. stdbuf -oL: no timeout, os saltos já impressos não se perdem.
TRACEPATH_CMD = ["stdbuf", "-oL", "tracepath", "-n", "-m", "15"]
TRACEPATH_TIMEOUT = 60  # cada salto sem resposta leva ~3 s: 15 saltos mudos ≈ 45 s

# Teste de velocidade: ~35 MB por teste (~1,7 GB/dia no padrão de 30 min). VELOCIDADE_A_CADA=0 desliga.
VELOCIDADE_A_CADA = float(os.environ.get("VELOCIDADE_A_CADA", "30"))   # minutos
VELOCIDADE_PRIMEIRO = 60            # s depois de o monitor iniciar
VELOCIDADE_HOST = "https://speed.cloudflare.com"
DOWN_BYTES = 25_000_000
UP_BYTES = 10_000_000
FASE_TIMEOUT = 30                   # s por fase (download, upload)
# o User-Agent padrão do urllib leva 403 da Cloudflare
VELOCIDADE_HEADERS = {"User-Agent": "ping-check/1.0 (monitor de conexao)"}
LAT_ALVO = "1.1.1.1"
LAT_PARADO = 5                      # s de ping antes do download
LAT_INTERVALO = "0.2"               # menor intervalo de ping permitido sem root

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,          -- ISO local
    epoch         REAL NOT NULL,
    iface         TEXT,
    gateway       TEXT,
    gw_loss_pct   REAL, gw_avg_ms REAL, gw_max_ms REAL, gw_jitter_ms REAL,
    cf_loss_pct   REAL, cf_avg_ms REAL, cf_max_ms REAL, cf_jitter_ms REAL,
    gg_loss_pct   REAL, gg_avg_ms REAL, gg_max_ms REAL, gg_jitter_ms REAL,
    dns_ok        INTEGER, dns_ms REAL,
    wifi_quality  REAL,                   -- link quality (0-70)
    wifi_dbm      REAL,                   -- nível do sinal em dBm
    status        TEXT NOT NULL           -- ok | degradado | sem_wifi | falha_lan | falha_internet | falha_dns
);
CREATE INDEX IF NOT EXISTS idx_checks_epoch ON checks(epoch);

CREATE TABLE IF NOT EXISTS wifi_info (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, epoch REAL NOT NULL,
    ssid TEXT, bssid TEXT, chan INTEGER, freq TEXT, rate TEXT, signal_pct INTEGER
);

CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    start_ts TEXT NOT NULL, start_epoch REAL NOT NULL,
    end_ts TEXT, end_epoch REAL,
    duration_s REAL,
    samples INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, start_ts TEXT NOT NULL, end_ts TEXT, note TEXT
);

-- caminho até a internet, medido uma vez no início de cada queda falha_internet
CREATE TABLE IF NOT EXISTS rotas (
    id INTEGER PRIMARY KEY,
    outage_id INTEGER NOT NULL,
    ts TEXT NOT NULL, epoch REAL NOT NULL,
    alvo TEXT NOT NULL,
    saltos TEXT,                          -- JSON: [{n, ip|null, ms|null}]
    ultimo_ok INTEGER,                    -- número do último salto que respondeu
    saida TEXT,                           -- saída bruta do tracepath
    erro TEXT
);
CREATE INDEX IF NOT EXISTS idx_rotas_outage ON rotas(outage_id);

-- teste de velocidade; a linha é aberta no início (fim_epoch NULL = em andamento) e fechada no fim
CREATE TABLE IF NOT EXISTS velocidade (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL, epoch REAL NOT NULL,    -- início
    fim_epoch REAL,
    down_mbps REAL, up_mbps REAL,
    bytes_down INTEGER, bytes_up INTEGER,
    erro TEXT
);
CREATE INDEX IF NOT EXISTS idx_velocidade_epoch ON velocidade(epoch);

-- latência até LAT_ALVO durante o teste de velocidade (bufferbloat); tabela própria porque não há migração
CREATE TABLE IF NOT EXISTS latencia_carga (
    velocidade_id INTEGER PRIMARY KEY,
    ocioso_ms REAL, down_ms REAL, up_ms REAL,  -- medianas
    down_perda REAL, up_perda REAL             -- %
);
"""

RTT_RE = re.compile(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")
LOSS_RE = re.compile(r"([\d.]+)% packet loss")
RESPOSTA_RE = re.compile(r"icmp_seq=(\d+) .*time=([\d.]+) ms")
ENVIADOS_RE = re.compile(r"(\d+) packets transmitted")
SALTO_RE = re.compile(r"^\s*(\d+):\s+(?:(no reply)|(\S+)\s+([\d.]+)ms)")


def now():
    t = time.time()
    return t, datetime.fromtimestamp(t).isoformat(timespec="seconds")


def default_route():
    """Retorna (gateway, iface) da rota padrão, ou (None, None)."""
    try:
        out = subprocess.run(["ip", "route", "show", "default"],
                             capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"default via (\S+) dev (\S+)", out)
        if m:
            return m.group(1), m.group(2)
    except Exception:
        pass
    return None, None


def parse_ping(out):
    """Lê a saída do `ping -q` e retorna dict loss/avg/max/jitter.

    Sem linha de perda, loss fica 100; sem linha de RTT, avg/max/jitter ficam None.
    """
    res = {"loss": 100.0, "avg": None, "max": None, "jitter": None}
    m = LOSS_RE.search(out)
    if m:
        res["loss"] = float(m.group(1))
    m = RTT_RE.search(out)
    if m:
        res["avg"], res["max"], res["jitter"] = float(m.group(2)), float(m.group(3)), float(m.group(4))
    return res


def parse_ping_respostas(out):
    """Lê a saída do `ping` sem `-q` (uma linha por resposta) e retorna {mediana, perda}.

    Enviados vêm do resumo; sem resumo (ping interrompido), do maior icmp_seq. Sem resposta: mediana None, perda 100.
    """
    resp = RESPOSTA_RE.findall(out)
    tempos = [float(t) for _, t in resp]
    m = ENVIADOS_RE.search(out)
    enviados = int(m.group(1)) if m else max((int(seq) for seq, _ in resp), default=0)
    if not tempos or not enviados:
        return {"mediana": None, "perda": 100.0}
    return {"mediana": statistics.median(tempos), "perda": 100.0 * max(0, enviados - len(tempos)) / enviados}


def ping(host):
    """Retorna dict loss/avg/max/jitter. Loss 100 se tudo falhou."""
    res = {"loss": 100.0, "avg": None, "max": None, "jitter": None}
    if not host:
        return res
    try:
        out = subprocess.run(
            ["ping", "-n", "-q", "-c", str(PING_COUNT), "-i", str(PING_SPACING),
             "-W", str(PING_TIMEOUT), host],
            capture_output=True, text=True,
            timeout=PING_COUNT * PING_SPACING + PING_TIMEOUT + 3).stdout
    except Exception:
        return res
    return parse_ping(out)


def dns_check():
    """Retorna (ok, ms). Subprocesso com timeout: no limite o filho é morto,
    então nenhuma thread do pool fica presa numa resolução que não volta."""
    t0 = time.monotonic()
    try:
        r = subprocess.run(DNS_CMD + [DNS_HOST], capture_output=True, text=True,
                           timeout=DNS_TIMEOUT)
    except Exception:
        return 0, None
    if r.returncode != 0 or not r.stdout.strip():
        return 0, None
    return 1, (time.monotonic() - t0) * 1000


def wifi_signal(iface):
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                if iface and line.strip().startswith(iface + ":"):
                    parts = line.split()
                    return float(parts[2].rstrip(".")), float(parts[3].rstrip("."))
    except Exception:
        pass
    return None, None


def wifi_info():
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "IN-USE,SSID,BSSID,CHAN,FREQ,RATE,SIGNAL",
             "dev", "wifi", "list", "--rescan", "no"],
            capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.startswith("*"):
            # campos separados por ':' com ':' escapado como '\:' no BSSID
            fields = re.split(r"(?<!\\):", line)
            fields = [x.replace("\\:", ":") for x in fields]
            if len(fields) >= 7:
                _, ssid, bssid, chan, freq, rate, sig = fields[:7]
                return ssid, bssid, int(chan or 0), freq, rate, int(sig or 0)
    return None


def parse_tracepath(out):
    """Lê a saída do `tracepath -n` e retorna (saltos, ultimo_ok).

    saltos = [{n, ip, ms}] em ordem, um por número de salto; "no reply" vira ip/ms None.
    ultimo_ok = número do último salto que respondeu, ou None. A linha [LOCALHOST] (`1?:`) é ignorada.
    """
    saltos = {}
    for line in out.splitlines():
        m = SALTO_RE.match(line)
        if not m:
            continue
        n = int(m.group(1))
        if m.group(3) and (n not in saltos or saltos[n]["ip"] is None):
            saltos[n] = {"n": n, "ip": m.group(3), "ms": float(m.group(4))}
        else:
            saltos.setdefault(n, {"n": n, "ip": None, "ms": None})
    lista = [saltos[n] for n in sorted(saltos)]
    ok = [s["n"] for s in lista if s["ip"]]
    return lista, (ok[-1] if ok else None)


def tracepath(alvo):
    """Roda o tracepath; retorna dict saltos/ultimo_ok/saida/erro. Nunca levanta exceção."""
    res = {"saltos": [], "ultimo_ok": None, "saida": None, "erro": None}
    try:
        r = subprocess.run(TRACEPATH_CMD + [alvo], capture_output=True, text=True, timeout=TRACEPATH_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        res["saida"] = out
        res["saltos"], res["ultimo_ok"] = parse_tracepath(out)
        res["erro"] = f"tempo esgotado ({TRACEPATH_TIMEOUT} s)"
        return res
    except Exception as e:
        res["erro"] = str(e)
        return res
    res["saida"] = r.stdout
    res["saltos"], res["ultimo_ok"] = parse_tracepath(r.stdout)
    if r.returncode != 0 and not res["saltos"]:
        res["erro"] = (r.stderr.strip() or f"código de saída {r.returncode}")[:500]
    return res


def gravar_rota(db, outage_id, epoch, ts, alvo, res):
    db.execute("INSERT INTO rotas(outage_id, ts, epoch, alvo, saltos, ultimo_ok, saida, erro) VALUES(?,?,?,?,?,?,?,?)",
               (outage_id, ts, epoch, alvo, json.dumps(res["saltos"]), res["ultimo_ok"], res["saida"], res["erro"]))


def hora_de_testar(agora, inicio, ultimo, status, a_cada_min):
    """Teste de velocidade agora? Primeiro VELOCIDADE_PRIMEIRO s após iniciar, depois a cada a_cada_min,
    nunca com a internet fora do ar; a_cada_min = 0 desliga."""
    if a_cada_min <= 0 or status not in ("ok", "degradado"):
        return False
    if ultimo is None:
        return agora - inicio >= VELOCIDADE_PRIMEIRO
    return agora - ultimo >= a_cada_min * 60


def mbps(n_bytes, segundos):
    return n_bytes * 8 / segundos / 1e6 if segundos > 0 else None


def baixar():
    """GET de DOWN_BYTES; (bytes, s) contando do primeiro byte da resposta (exclui DNS/TLS) até o fim."""
    req = urllib.request.Request(f"{VELOCIDADE_HOST}/__down?bytes={DOWN_BYTES}", headers=VELOCIDADE_HEADERS)
    with urllib.request.urlopen(req, timeout=FASE_TIMEOUT) as r:
        t0 = time.monotonic()
        prazo, n = t0 + FASE_TIMEOUT, 0
        while True:
            b = r.read(65536)
            if not b:
                break
            n += len(b)
            if time.monotonic() > prazo:
                raise TimeoutError(f"download passou de {FASE_TIMEOUT} s")
    return n, time.monotonic() - t0


class CorpoUpload:
    """Corpo do POST lido sob demanda: a primeira leitura marca o início do envio (já depois de DNS/TLS)
    e cada leitura confere o prazo da fase."""

    def __init__(self, n, prazo=FASE_TIMEOUT):
        self.resta, self.prazo, self.inicio = n, prazo, None
        self._bloco = b"0" * 65536

    def read(self, tam=65536):
        agora = time.monotonic()
        if self.inicio is None:
            self.inicio = agora
        elif agora - self.inicio > self.prazo:
            raise TimeoutError(f"upload passou de {self.prazo} s")
        tam = min(tam if tam and tam > 0 else 65536, self.resta, len(self._bloco))
        self.resta -= tam
        return self._bloco[:tam]


def enviar():
    """POST de UP_BYTES; (bytes, s) do início do envio até o fim da resposta."""
    corpo = CorpoUpload(UP_BYTES)
    req = urllib.request.Request(f"{VELOCIDADE_HOST}/__up", data=corpo, method="POST",
                                 headers={**VELOCIDADE_HEADERS, "Content-Length": str(UP_BYTES),
                                          "Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=FASE_TIMEOUT) as r:
        r.read()
    return UP_BYTES, time.monotonic() - corpo.inicio


def ping_parado():
    out = subprocess.run(["ping", "-n", "-i", LAT_INTERVALO, "-w", str(LAT_PARADO), LAT_ALVO],
                         capture_output=True, text=True, timeout=LAT_PARADO + 5).stdout
    return parse_ping_respostas(out)


def ping_continuo():
    """Ping até LAT_ALVO durante uma fase; o prazo (-w) é só uma rede de segurança, parar_ping() o encerra."""
    return subprocess.Popen(["ping", "-n", "-i", LAT_INTERVALO, "-w", str(FASE_TIMEOUT + 5), LAT_ALVO],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def parar_ping(proc):
    proc.send_signal(signal.SIGINT)    # SIGINT: o ping imprime o resumo antes de sair
    try:
        out, _ = proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return parse_ping_respostas(out)


def _com_ping(fase):
    """Roda fase() com ping contínuo ao lado; devolve (resultado, latência ou None). Falha do ping não afeta a fase."""
    try:
        proc = ping_continuo()
    except Exception:
        proc = None
    try:
        r = fase()
    finally:
        lat = None
        if proc is not None:
            try:
                lat = parar_ping(proc)
            except Exception:
                lat = None
    return r, lat


def teste_velocidade():
    """Latência parado → download (com ping) → upload (com ping). Nunca levanta exceção: falha vira `erro`."""
    res = {"down_mbps": None, "up_mbps": None, "bytes_down": None, "bytes_up": None,
           "erro": None, "carga": None, "fim_epoch": None}
    try:
        parado = ping_parado()
    except Exception:
        parado = None
    lat_down = lat_up = None
    try:
        (n, seg), lat_down = _com_ping(baixar)
        res["bytes_down"], res["down_mbps"] = n, mbps(n, seg)
        (n, seg), lat_up = _com_ping(enviar)
        res["bytes_up"], res["up_mbps"] = n, mbps(n, seg)
    except Exception as e:
        res["erro"] = (str(e) or type(e).__name__)[:300]
    res["fim_epoch"] = time.time()
    if parado or lat_down or lat_up:
        campo = lambda lat, k: lat[k] if lat else None   # fase sem medida de latência -> None
        res["carga"] = {"ocioso_ms": campo(parado, "mediana"), "down_ms": campo(lat_down, "mediana"),
                        "up_ms": campo(lat_up, "mediana"), "down_perda": campo(lat_down, "perda"),
                        "up_perda": campo(lat_up, "perda")}
    return res


def iniciar_velocidade(db, epoch, ts):
    """Abre a linha do teste (fim_epoch NULL = em andamento: o painel não chama de instável a lentidão que ele causa)."""
    return db.execute("INSERT INTO velocidade(ts, epoch) VALUES(?, ?)", (ts, epoch)).lastrowid


def gravar_velocidade(db, vid, res):
    db.execute("UPDATE velocidade SET fim_epoch=?, down_mbps=?, up_mbps=?, bytes_down=?, bytes_up=?, erro=? WHERE id=?",
               (res["fim_epoch"], res["down_mbps"], res["up_mbps"], res["bytes_down"], res["bytes_up"], res["erro"], vid))
    c = res["carga"]
    if c:
        db.execute("INSERT OR REPLACE INTO latencia_carga(velocidade_id, ocioso_ms, down_ms, up_ms, down_perda, up_perda) "
                   "VALUES(?,?,?,?,?,?)", (vid, c["ocioso_ms"], c["down_ms"], c["up_ms"], c["down_perda"], c["up_perda"]))


def fim_velocidade(db, vid, res):
    gravar_velocidade(db, vid, res)
    _, ts = now()
    if res["erro"]:
        print(f"[{ts}] teste de velocidade falhou: {res['erro']}", flush=True)
    else:
        print(f"[{ts}] velocidade: baixar {res['down_mbps']:.1f} / enviar {res['up_mbps']:.1f} Mbps", flush=True)


def marcar_interrompidos(db):
    """Testes que ficaram abertos (monitor parou ou caiu no meio) deixam de contar como em andamento."""
    db.execute("UPDATE velocidade SET erro='interrompido' WHERE fim_epoch IS NULL AND erro IS NULL")


class Fundo:
    """Tarefas demoradas (ex.: tracepath) fora do ciclo de INTERVAL s, no máximo uma por nome.

    Cada tarefa roda numa thread daemon: o monitor para sem esperar por ela, e a que estiver em andamento
    é descartada. O resultado só é gravado em colher(), chamado pela thread principal, porque a conexão
    SQLite é de uma thread só.
    """

    def __init__(self):
        self._tarefas = {}   # nome -> (Future, gravar(db, resultado))

    def ocupado(self, nome):
        return nome in self._tarefas

    def iniciar(self, nome, fn, gravar):
        fut = cf.Future()

        def roda():
            try:
                fut.set_result(fn())
            except BaseException as e:
                fut.set_exception(e)
        self._tarefas[nome] = (fut, gravar)
        threading.Thread(target=roda, name=nome, daemon=True).start()

    def colher(self, db):
        for nome, (fut, gravar) in list(self._tarefas.items()):
            if not fut.done():
                continue
            del self._tarefas[nome]
            if fut.exception():
                print(f"erro na tarefa {nome}: {fut.exception()!r}", flush=True)
            else:
                gravar(db, fut.result())


def classify(iface, gw, cf_, gg, dns_ok):
    inet_loss = min(cf_["loss"], gg["loss"])
    if not iface:
        return "sem_wifi"
    if gw["loss"] == 100:
        return "falha_lan"
    if inet_loss == 100:
        return "falha_internet"
    if not dns_ok:
        return "falha_dns"
    avgs = [t["avg"] for t in (cf_, gg) if t["avg"] is not None]
    lento = bool(avgs) and min(avgs) > 150
    if gw["loss"] > 0 or inet_loss > 0 or lento:
        return "degradado"
    return "ok"


def main():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.execute("PRAGMA journal_mode=WAL")
    marcar_interrompidos(db)
    inicio, start_ts = now()
    run_id = db.execute("INSERT INTO runs(start_ts, note) VALUES(?, ?)",
                        (start_ts, " ".join(sys.argv[1:]) or None)).lastrowid
    db.commit()

    stop = {"flag": False}

    def handle(sig, _frm):
        stop["flag"] = True
    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    pool = cf.ThreadPoolExecutor(max_workers=6)
    fundo = Fundo()
    open_outage = None  # (id, status)
    last_wifi_info = 0.0
    ultimo_velocidade = None
    print(f"[{start_ts}] monitor iniciado -> {DB_PATH}", flush=True)

    while not stop["flag"]:
        cycle_start = time.monotonic()
        epoch, ts = now()
        gateway, iface = default_route()

        f_gw = pool.submit(ping, gateway)
        f_cf = pool.submit(ping, INTERNET_TARGETS["cf"])
        f_gg = pool.submit(ping, INTERNET_TARGETS["google"])
        f_dns = pool.submit(dns_check)
        gw, cf_, gg = f_gw.result(), f_cf.result(), f_gg.result()
        try:
            # dns_check já respeita DNS_TIMEOUT; a folga é só rede de segurança
            dns_ok, dns_ms = f_dns.result(timeout=DNS_TIMEOUT + 1)
        except Exception:
            dns_ok, dns_ms = 0, None
        q, dbm = wifi_signal(iface)
        status = classify(iface, gw, cf_, gg, dns_ok)

        try:
            db.execute(
                """INSERT INTO checks(ts, epoch, iface, gateway,
                   gw_loss_pct, gw_avg_ms, gw_max_ms, gw_jitter_ms,
                   cf_loss_pct, cf_avg_ms, cf_max_ms, cf_jitter_ms,
                   gg_loss_pct, gg_avg_ms, gg_max_ms, gg_jitter_ms,
                   dns_ok, dns_ms, wifi_quality, wifi_dbm, status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ts, epoch, iface, gateway,
                 gw["loss"], gw["avg"], gw["max"], gw["jitter"],
                 cf_["loss"], cf_["avg"], cf_["max"], cf_["jitter"],
                 gg["loss"], gg["avg"], gg["max"], gg["jitter"],
                 dns_ok, dns_ms, q, dbm, status))

            # rastreia quedas (qualquer status != ok/degradado)
            is_down = status not in ("ok", "degradado")
            if open_outage and (not is_down or open_outage[1] != status):
                db.execute(
                    "UPDATE outages SET end_ts=?, end_epoch=?, duration_s=?-start_epoch WHERE id=?",
                    (ts, epoch, epoch, open_outage[0]))
                print(f"[{ts}] fim de {open_outage[1]}", flush=True)
                open_outage = None
            if is_down:
                if open_outage:
                    db.execute("UPDATE outages SET samples=samples+1 WHERE id=?", (open_outage[0],))
                else:
                    oid = db.execute(
                        "INSERT INTO outages(status, start_ts, start_epoch) VALUES(?,?,?)",
                        (status, ts, epoch)).lastrowid
                    open_outage = (oid, status)
                    print(f"[{ts}] QUEDA: {status}", flush=True)
                    # um diagnóstico por queda (e um por vez): só em falha_internet o roteador responde e há caminho a medir
                    if status == "falha_internet" and not fundo.ocupado("rota"):
                        fundo.iniciar("rota", lambda: tracepath(ROTA_ALVO),
                                      lambda db_, res, oid=oid, e=epoch, t=ts: gravar_rota(db_, oid, e, t, ROTA_ALVO, res))

            if not fundo.ocupado("velocidade") and hora_de_testar(epoch, inicio, ultimo_velocidade, status, VELOCIDADE_A_CADA):
                ultimo_velocidade = epoch
                vid = iniciar_velocidade(db, epoch, ts)
                fundo.iniciar("velocidade", teste_velocidade, lambda db_, res, vid=vid: fim_velocidade(db_, vid, res))

            fundo.colher(db)

            if epoch - last_wifi_info >= WIFI_INFO_EVERY:
                info = wifi_info()
                if info:
                    db.execute(
                        "INSERT INTO wifi_info(ts, epoch, ssid, bssid, chan, freq, rate, signal_pct) "
                        "VALUES(?,?,?,?,?,?,?,?)", (ts, epoch, *info))
                last_wifi_info = epoch
            db.commit()
        except sqlite3.Error as e:
            print(f"[{ts}] erro sqlite: {e}", flush=True)

        elapsed = time.monotonic() - cycle_start
        end = time.monotonic() + max(0.0, INTERVAL - elapsed)
        while not stop["flag"] and time.monotonic() < end:
            time.sleep(0.2)

    epoch, ts = now()
    if open_outage:
        db.execute("UPDATE outages SET end_ts=?, end_epoch=?, duration_s=?-start_epoch WHERE id=?",
                   (ts, epoch, epoch, open_outage[0]))
    db.execute("UPDATE runs SET end_ts=? WHERE id=?", (ts, run_id))
    marcar_interrompidos(db)
    db.commit()
    db.close()
    pool.shutdown(wait=False, cancel_futures=True)
    print(f"[{ts}] monitor parado", flush=True)


if __name__ == "__main__":
    main()
