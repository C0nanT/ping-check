#!/usr/bin/env python3
"""Painel web da conexão: lê conexao.db (somente leitura) e serve gráficos em http://127.0.0.1:8080"""
import errno
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta, time as dtime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conexao.db")
# pedido de teste completo para o monitor (o painel não escreve no banco); mesmo nome em monitor.py
PEDIDO = os.path.join(os.path.dirname(DB), "pedido_teste_completo")
PEDIDO_VALIDADE = 600   # s: o monitor descarta pedido mais velho
# s entre testes completos pedidos pelo botão: o Cloudflare bloqueia (429, por ~1 h) quem baixa muitos GB seguidos
MANUAL_INTERVALO = 3600
PORT = int(os.environ.get("PORT", 8080))
MAX_PONTOS = 600
INTERVALO = 5           # mesmo INTERVAL do monitor.py
PARADO_APOS = 60        # s sem amostra nova = monitor parado
CAIU = ("sem_wifi", "falha_lan", "falha_internet", "falha_dns")
CAMPOS = ("gw", "cf", "gg", "gwl", "cfl", "ggl", "dns", "dbm")


def conectar():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args)]


def tem_tabela(c, nome):
    """Tabelas novas só existem depois que o monitor reinicia com o SCHEMA novo; o painel (mode=ro) não as cria."""
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone() is not None


COLUNAS = (("gw_avg_ms", "gw"), ("cf_avg_ms", "cf"), ("gg_avg_ms", "gg"), ("gw_loss_pct", "gwl"),
           ("cf_loss_pct", "cfl"), ("gg_loss_pct", "ggl"), ("dns_ms", "dns"), ("wifi_dbm", "dbm"))
assert tuple(a for _, a in COLUNAS) == CAMPOS


MAX_PERIODO = 30 * 86400    # s: período mais longo que a API aceita


def periodo(agora, minutos=60, de=None, ate=None):
    """(de, ate) em epoch: os últimos `minutos`, ou de `de` a `ate` quando os dois vêm. `ate` no futuro vira
    agora; período maior que MAX_PERIODO é cortado no começo. ValueError se o início não for antes do fim."""
    if de is None and ate is None:
        de, ate = agora - max(1, minutos) * 60, agora
    elif de is None or ate is None:
        raise ValueError("informe o início (de) e o fim (ate) do período")
    else:
        ate = min(ate, agora)
        if not de < ate:        # também pega nan
            raise ValueError("o início do período precisa ser antes do fim (e antes de agora)")
    return max(de, ate - MAX_PERIODO), ate


def pontos_do_periodo(c, desde, ate):
    """Pontos do gráfico e o passo (s) de [desde, ate). Até MAX_PONTOS amostras voltam como estão; acima disso
    o SQLite agrupa em MAX_PONTOS baldes de tempo fixo (média; status = pior do balde). Baldes vazios somem,
    então períodos sem medição continuam aparecendo como buraco."""
    n = c.execute("SELECT COUNT(*) FROM checks WHERE epoch >= ? AND epoch < ?", (desde, ate)).fetchone()[0]
    if n <= MAX_PONTOS:
        brutos = ", ".join(f"{col} {nome}" for col, nome in COLUNAS)
        return rows(c, f"SELECT epoch, status, {brutos} FROM checks WHERE epoch >= ? AND epoch < ? ORDER BY epoch",
                    (desde, ate)), INTERVALO
    tam = (ate - desde) / MAX_PONTOS
    medias = ", ".join(f"AVG({col}) {nome}" for col, nome in COLUNAS)
    # Regra do SQLite: numa consulta com um único MAX(), as colunas soltas (status) vêm da linha
    # que deu o máximo, ou seja, o status do pior grau do balde.
    campos = ", ".join(("epoch", "status") + CAMPOS)
    return rows(c, f"""SELECT {campos} FROM (
                           SELECT AVG(epoch) epoch, status, {medias},
                                  MAX(CASE status WHEN 'ok' THEN 0 WHEN 'degradado' THEN 1 ELSE 2 END) grau
                           FROM checks WHERE epoch >= ? AND epoch < ?
                           GROUP BY CAST((epoch - ?) / ? AS INTEGER)) ORDER BY epoch""",
                (desde, ate, desde, tam)), tam


def banco_tamanho(c, agora):
    """Tamanho do banco no disco (arquivo principal + -wal + -shm que existirem) e crescimento por dia.
    por_dia = arquivo principal ÷ dias desde a primeira amostra; None com menos de 1 h de dados."""
    partes = {}
    for sufixo in ("", "-wal", "-shm"):
        try:
            partes[sufixo] = os.path.getsize(DB + sufixo)
        except OSError:
            partes[sufixo] = 0
    primeira = c.execute("SELECT MIN(epoch) FROM checks").fetchone()[0]
    por_dia = None
    if primeira is not None and agora - primeira >= 3600:
        por_dia = partes[""] / ((agora - primeira) / 86400)
    return {"bytes": sum(partes.values()), "por_dia": por_dia}


DIAS = 30
FOLGA_FUSO = 43200      # s: o dia vem do ts (hora local do monitor); o epoch só limita a varredura


def dias_contados(c, primeiro, ultimo):
    """{dia: {dia, n, fora, quedas}} dos dias locais de primeiro a ultimo (date, inclusive), pelo prefixo do ts.
    Só dias com amostra ou queda aparecem."""
    ini = datetime.combine(primeiro, dtime.min).timestamp() - FOLGA_FUSO
    fim = datetime.combine(ultimo + timedelta(days=1), dtime.min).timestamp() + FOLGA_FUSO
    a, b = primeiro.isoformat(), ultimo.isoformat()
    marcas = ",".join("?" * len(CAIU))
    out = {}
    for r in c.execute(f"""SELECT substr(ts, 1, 10) dia, COUNT(*) n, SUM(status IN ({marcas})) fora FROM checks
                           WHERE epoch >= ? AND epoch < ? GROUP BY dia HAVING dia BETWEEN ? AND ?""",
                       CAIU + (ini, fim, a, b)):
        out[r["dia"]] = {"dia": r["dia"], "n": r["n"], "fora": r["fora"], "quedas": 0}
    for r in c.execute("""SELECT substr(start_ts, 1, 10) dia, COUNT(*) n FROM outages
                          WHERE start_epoch >= ? AND start_epoch < ? GROUP BY dia HAVING dia BETWEEN ? AND ?""",
                       (ini, fim, a, b)):
        out.setdefault(r["dia"], {"dia": r["dia"], "n": 0, "fora": 0, "quedas": 0})["quedas"] = r["n"]
    return out


# Dias anteriores a hoje não mudam: ficam na memória do processo e só hoje é recalculado a cada requisição.
# Um dia fechado que ganhar amostras depois fica desatualizado até o painel reiniciar (aceito).
_dias_fechados = {}     # "AAAA-MM-DD" -> item de dias_recentes
_dias_trava = threading.Lock()


def limpar_cache_dias():
    with _dias_trava:
        _dias_fechados.clear()


def dias_recentes(c, agora):
    """Os DIAS dias locais até hoje, em ordem; dias sem amostra vêm com n = 0."""
    hoje = datetime.fromtimestamp(agora).date()
    lista = [(hoje - timedelta(days=i)).isoformat() for i in range(DIAS - 1, -1, -1)]
    vazio = lambda d: {"dia": d, "n": 0, "fora": 0, "quedas": 0}
    with _dias_trava:
        faltam = [d for d in lista[:-1] if d not in _dias_fechados]
        if faltam:
            novos = dias_contados(c, date.fromisoformat(faltam[0]), date.fromisoformat(faltam[-1]))
            for d in faltam:
                _dias_fechados[d] = novos.get(d) or vazio(d)
        for d in [d for d in _dias_fechados if d < lista[0]]:
            del _dias_fechados[d]
        fechados = [_dias_fechados[d] for d in lista[:-1]]
    return fechados + [dias_contados(c, hoje, hoje).get(lista[-1]) or vazio(lista[-1])]


def frase_rota(saltos, ultimo_ok, erro, alvo):
    """Onde o sinal parou, em português simples. O 1º ponto do caminho é o roteador de casa. None se o diagnóstico falhou."""
    if erro:
        return None
    if not ultimo_ok or ultimo_ok <= 1:
        return "O sinal parou no seu roteador: a internet não está saindo de casa."
    if any(s["n"] == ultimo_ok and s["ip"] == alvo for s in saltos):
        return "O sinal chegou até a internet durante o teste: a falha pode ter passado logo depois de começar."
    return f"O sinal passou do roteador e parou na rede da operadora ({ultimo_ok}º ponto do caminho)."


def rotas_das_quedas(c, quedas):
    """Põe em cada queda a `rota` ({frase, saltos}) do diagnóstico gravado pelo monitor, ou None."""
    achadas = {}
    if quedas and tem_tabela(c, "rotas"):
        ids = [q["id"] for q in quedas]
        for r in c.execute(f"SELECT outage_id, alvo, saltos, ultimo_ok, erro FROM rotas "
                           f"WHERE outage_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids):
            saltos = json.loads(r["saltos"] or "[]")
            achadas[r["outage_id"]] = {"frase": frase_rota(saltos, r["ultimo_ok"], r["erro"], r["alvo"]),
                                       "saltos": saltos}
    for q in quedas:
        q["rota"] = achadas.get(q["id"])


TESTE_MAX = 90          # s: duração máxima de um teste de velocidade sem fim gravado (em andamento ou interrompido)
TESTE_FOLGA = 2 * INTERVALO   # s depois do fim em que o pico do teste ainda aparece nas amostras


def amostras_recentes(c):
    """Status das 12 amostras mais recentes, sem as `degradado` que caem dentro de um teste de velocidade:
    o teste satura a conexão e o pico de latência que ele mesmo causa não deve virar "instável"."""
    if not tem_tabela(c, "velocidade"):
        return [r["status"] for r in rows(c, "SELECT status FROM checks ORDER BY epoch DESC LIMIT 12")]
    return [r["status"] for r in rows(c, """
        SELECT status FROM checks k
        WHERE NOT (k.status = 'degradado' AND EXISTS (
            SELECT 1 FROM velocidade v
            WHERE v.epoch BETWEEN k.epoch - ? AND k.epoch
              AND k.epoch <= COALESCE(v.fim_epoch, v.epoch + ?) + ?))
        ORDER BY epoch DESC LIMIT 12""", (TESTE_MAX * 3, TESTE_MAX, TESTE_FOLGA))]


def janelas_teste(c, desde, ate):
    """[[ini, fim]] dos testes de velocidade cuja janela toca [desde, ate), com TESTE_MAX (teste sem fim gravado)
    e TESTE_FOLGA aplicados: a mesma janela que amostras_recentes usa. Inclui teste iniciado antes de `desde`."""
    if not tem_tabela(c, "velocidade"):
        return []
    fim = "COALESCE(fim_epoch, epoch + ?) + ?"
    return [[r["epoch"], r["fim"]] for r in rows(
        c, f"SELECT epoch, {fim} fim FROM velocidade WHERE epoch < ? AND {fim} >= ? ORDER BY epoch",
        (TESTE_MAX, TESTE_FOLGA, ate, TESTE_MAX, TESTE_FOLGA, desde))]


def classificar_acrescimo(ms):
    """Nota da latência sob carga pelo acréscimo (ms) sobre a latência parada; limites de testes públicos de bufferbloat."""
    if ms < 30:
        return "Ótimo", "good"
    if ms < 60:
        return "Bom", "good"
    if ms < 200:
        return "Razoável", "warning"
    return "Ruim", "critical"


def nota_carga(ocioso, down, up):
    """{nome, cat, acrescimo, fase} pela pior fase (baixando/enviando) menos parado, ou None sem dados."""
    fases = [(v, f) for v, f in ((down, "down"), (up, "up")) if v is not None]
    if ocioso is None or not fases:
        return None
    pior, fase = max(fases)
    acrescimo = max(0.0, pior - ocioso)
    nome, cat = classificar_acrescimo(acrescimo)
    return {"nome": nome, "cat": cat, "acrescimo": acrescimo, "fase": fase}


def velocidade(c, desde, ate):
    """(testes do período em ordem, último teste bem-sucedido e último completo bem-sucedido, mesmo fora do
    período). Teste com erro vem sem Mbps."""
    if not tem_tabela(c, "velocidade"):
        return [], None, None
    carga = ("l.ocioso_ms, l.down_ms, l.up_ms, l.velocidade_id tem_carga" if tem_tabela(c, "latencia_carga")
             else "NULL ocioso_ms, NULL down_ms, NULL up_ms, NULL tem_carga")
    junta = "LEFT JOIN latencia_carga l ON l.velocidade_id = v.id" if tem_tabela(c, "latencia_carga") else ""
    if tem_tabela(c, "velocidade_completo"):
        compl, junta = "k.velocidade_id IS NOT NULL", junta + " LEFT JOIN velocidade_completo k ON k.velocidade_id = v.id"
    else:
        compl = "0"
    base = (f"SELECT v.epoch, v.fim_epoch fim, v.down_mbps, v.up_mbps, v.erro, {compl} completo, {carga} "
            f"FROM velocidade v {junta}")

    def item(r):
        return {"epoch": r["epoch"], "fim": r["fim"], "erro": r["erro"], "completo": bool(r["completo"]),
                "down": None if r["erro"] else r["down_mbps"], "up": None if r["erro"] else r["up_mbps"],
                "carga": None if r["tem_carga"] is None else
                {"ocioso": r["ocioso_ms"], "down": r["down_ms"], "up": r["up_ms"],
                 "nota": nota_carga(r["ocioso_ms"], r["down_ms"], r["up_ms"])}}
    testes = [item(r) for r in rows(c, base + " WHERE v.epoch >= ? AND v.epoch < ? ORDER BY v.epoch", (desde, ate))]
    ok = " WHERE v.erro IS NULL AND v.down_mbps IS NOT NULL"
    ultimo = rows(c, base + ok + " ORDER BY v.epoch DESC LIMIT 1")
    ultimo_compl = rows(c, base + ok + f" AND {compl} ORDER BY v.epoch DESC LIMIT 1")
    return testes, item(ultimo[0]) if ultimo else None, item(ultimo_compl[0]) if ultimo_compl else None


def teste_rodando(c, agora):
    """Teste de velocidade em andamento agora, {epoch, completo}, ou None."""
    if not tem_tabela(c, "velocidade"):
        return None
    compl = ("EXISTS (SELECT 1 FROM velocidade_completo k WHERE k.velocidade_id = v.id)"
             if tem_tabela(c, "velocidade_completo") else "0")
    r = rows(c, f"""SELECT v.epoch, {compl} completo FROM velocidade v
                    WHERE v.fim_epoch IS NULL AND v.erro IS NULL AND v.epoch > ? ORDER BY v.epoch DESC LIMIT 1""",
             (agora - TESTE_MAX,))
    return {"epoch": r[0]["epoch"], "completo": bool(r[0]["completo"])} if r else None


def proximo_manual(c, agora):
    """Epoch a partir do qual o botão volta a pedir teste completo, ou None se já pode."""
    if not (tem_tabela(c, "velocidade") and tem_tabela(c, "velocidade_completo")):
        return None
    ult = c.execute("SELECT MAX(v.epoch) FROM velocidade v JOIN velocidade_completo k ON k.velocidade_id = v.id"
                    ).fetchone()[0]
    return ult + MANUAL_INTERVALO if ult is not None and ult + MANUAL_INTERVALO > agora else None


def teste_pedido(agora):
    """Há pedido de teste completo ainda não atendido pelo monitor?"""
    try:
        return agora - os.path.getmtime(PEDIDO) <= PEDIDO_VALIDADE
    except OSError:
        return False


def pedir_teste():
    with open(PEDIDO, "w") as f:
        f.write(f"{time.time():.0f}\n")


def api(minutos=60, de=None, ate=None):
    """Dados do período [de, ate) (ou dos últimos `minutos`); atual/recentes/wifi/banco/dias são sempre de agora."""
    agora = time.time()
    desde, ate = periodo(agora, minutos, de, ate)
    marcas = ",".join("?" * len(CAIU))
    c = conectar()
    try:
        pontos, passo = pontos_do_periodo(c, desde, ate)
        resumo = rows(c, "SELECT status, COUNT(*) n FROM checks WHERE epoch >= ? AND epoch < ? GROUP BY status",
                      (desde, ate))

        atual = rows(c, "SELECT epoch, status FROM checks ORDER BY epoch DESC LIMIT 1")
        atual = atual[0] if atual else None
        parado = not atual or agora - atual["epoch"] > PARADO_APOS
        recentes = amostras_recentes(c)

        # fim de queda sem end_epoch (monitor morto no meio dela) = primeira amostra com outro status
        quedas = rows(c, """SELECT id, status, start_epoch ini,
                                   COALESCE(end_epoch, (SELECT MIN(k.epoch) FROM checks k
                                                        WHERE k.epoch > o.start_epoch AND k.status != o.status)) fim
                            FROM outages o WHERE (end_epoch IS NULL OR end_epoch >= ?) AND start_epoch < ?
                            ORDER BY start_epoch DESC""", (desde, ate))
        for q in quedas:
            if q["fim"] is None and parado:
                q["fim"] = atual["epoch"] if atual else q["ini"]
        quedas = [q for q in quedas if q["fim"] is None or q["fim"] >= desde]
        falhas = {"n": len(quedas),
                  "seg": sum(min(q["fim"] or agora, ate) - max(q["ini"], desde) for q in quedas)}
        quedas = quedas[:30]
        rotas_das_quedas(c, quedas)

        # toda queda abre uma linha em outages; só varre checks a partir da mais recente (sem ela, sem queda)
        ini = c.execute("SELECT MAX(start_epoch) FROM outages").fetchone()[0]
        ultima = [] if ini is None else rows(
            c, f"SELECT epoch FROM checks WHERE epoch >= ? AND status IN ({marcas}) ORDER BY epoch DESC LIMIT 1",
            (ini,) + CAIU)
        inicio_atual = None
        if atual and atual["status"] in CAIU:
            ant = rows(c, "SELECT epoch FROM checks WHERE status != ? ORDER BY epoch DESC LIMIT 1", (atual["status"],))
            inicio_atual = rows(c, "SELECT MIN(epoch) e FROM checks WHERE epoch > ?",
                                (ant[0]["epoch"] if ant else 0,))[0]["e"]
        wifi = rows(c, "SELECT ssid, freq FROM wifi_info ORDER BY id DESC LIMIT 1")
        banco = banco_tamanho(c, agora)
        dias = dias_recentes(c, agora)
        testes, ultimo_teste, ultimo_completo = velocidade(c, desde, ate)
        rodando = teste_rodando(c, agora)
        proximo = proximo_manual(c, agora)
        janelas = janelas_teste(c, desde, ate)
    finally:
        c.close()
    return {"pontos": pontos, "passo": passo, "resumo": resumo, "quedas": quedas, "falhas": falhas,
            "atual": atual, "recentes": recentes, "ultima_queda": ultima[0]["epoch"] if ultima else None,
            "inicio_atual": inicio_atual, "wifi": wifi[0] if wifi else None, "banco": banco, "dias": dias,
            "velocidade": testes, "velocidade_ultimo": ultimo_teste,
            "velocidade_completo": ultimo_completo, "velocidade_rodando": rodando, "teste_manual_apos": proximo,
            "teste_pedido": teste_pedido(agora), "agora": agora, "de": desde, "ate": ate,
            "intervalo": INTERVALO, "parado_apos": PARADO_APOS, "status_queda": list(CAIU),
            "teste_max": TESTE_MAX, "teste_folga": TESTE_FOLGA, "periodo_max": MAX_PERIODO, "n_dias": DIAS,
            "janelas_teste": janelas}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            body, tipo = PAGINA.encode(), "text/html; charset=utf-8"
        elif u.path == "/api":
            q = parse_qs(u.query)
            um = lambda k, tipo, padrao=None: tipo(q[k][0]) if k in q else padrao
            try:
                args = {"minutos": um("min", int, 60), "de": um("de", float), "ate": um("ate", float)}
            except ValueError:
                self.send_error(400, "parametro invalido")
                return
            try:
                body, tipo = json.dumps(api(**args)).encode(), "application/json"
            except ValueError as e:
                self.send_error(400, str(e))
                return
            except Exception as e:
                self.send_error(500, str(e))
                return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/teste-completo":
            self.send_error(404)
            return
        # cabeçalho próprio: outro site aberto no navegador não consegue mandá-lo sem permissão (CORS)
        if self.headers.get("X-Pedido") != "1":
            self.send_error(403)
            return
        try:
            c = conectar()
            try:
                espera = proximo_manual(c, time.time())
            finally:
                c.close()
            if espera is not None:
                self.send_error(429, "teste completo recente")
                return
            pedir_teste()
        except (OSError, sqlite3.Error) as e:
            self.send_error(500, str(e))
            return
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


PAGINA = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minha internet</title>
<style>
:root{color-scheme:light;
--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--nodata:#d6d5cf;
--good-bg:rgba(12,163,12,.08);--warning-bg:rgba(250,178,25,.13);--critical-bg:rgba(208,59,59,.09);--nodata-bg:rgba(137,135,129,.10);
--band:rgba(11,11,11,.07)}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;
--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--nodata:#3a3a37;
--good-bg:rgba(12,163,12,.15);--warning-bg:rgba(250,178,25,.13);--critical-bg:rgba(208,59,59,.18);--nodata-bg:rgba(137,135,129,.12);
--band:rgba(255,255,255,.08)}}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:20px 16px 40px;transition:opacity .2s}
main.carregando{opacity:.6}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:16px}
h1{font-size:20px;margin:0}
.upd{color:var(--muted);font-size:13px}
.seg{display:inline-flex;flex-wrap:wrap;gap:2px;background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:3px}
.seg button{font:inherit;font-size:14px;border:0;background:none;color:var(--ink2);padding:6px 12px;border-radius:7px;cursor:pointer}
.seg button:hover{background:var(--nodata-bg)}
.seg button[aria-pressed=true]{background:var(--ink);color:var(--surface);font-weight:600}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:18px;margin-bottom:14px;position:relative}
.hero{display:flex;gap:16px;align-items:flex-start}
.hero .ic{flex:none;width:52px;height:52px}
.hero h2{font-size:24px;line-height:1.2;margin:2px 0 6px}
.hero p{margin:0;color:var(--ink2);max-width:64ch}
.hero .desde{margin-top:10px;font-size:13px;color:var(--ink2)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:14px}
.tile{margin:0}
.tile .lbl{font-size:13px;color:var(--ink2);font-weight:600}
.tile .val{display:flex;align-items:center;gap:8px;font-size:26px;font-weight:700;margin:6px 0 2px}
.tile .val svg{width:22px;height:22px;flex:none}
.tile .sub{font-size:13px;color:var(--muted)}
h3{font-size:16px;margin:0 0 2px}
.cap{font-size:13px;color:var(--muted);margin:0 0 12px;max-width:72ch}
.leg{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--ink2);margin-top:10px}
.leg span{display:inline-flex;align-items:center;gap:6px}
.leg i{display:inline-block;width:12px;height:12px;border-radius:3px}
.leg i.ln{width:16px;height:2px;border-radius:1px}
canvas{display:block;width:100%;touch-action:pan-y}
#tl{height:62px;cursor:crosshair}.chart{height:220px}
.tip{position:absolute;display:none;z-index:2;pointer-events:none;background:var(--surface);border:1px solid var(--ring);border-radius:8px;
box-shadow:0 4px 14px rgba(0,0,0,.14);padding:8px 10px;font-size:13px;white-space:nowrap}
.tip .t{color:var(--muted);margin-bottom:3px}
.tip .r{display:flex;align-items:center;gap:6px;color:var(--ink2)}
.tip .r b{color:var(--ink);font-size:14px}
.tip .r i{display:inline-block;width:12px;height:2px}
.tip .r i.q{height:12px;width:12px;border-radius:3px}
.list{list-style:none;margin:0;padding:0}
.list li{display:flex;gap:12px;align-items:center;padding:10px 0;border-top:1px solid var(--grid)}
.list li:first-child{border-top:0}
.list svg{width:22px;height:22px;flex:none}
.list .o{flex:1;min-width:0}.list .o b{display:block;font-weight:600}.list .o span{color:var(--muted);font-size:13px}
.list .d{color:var(--ink2);font-size:14px;text-align:right}
.list li{align-items:flex-start}.list li>svg{margin-top:2px}
.list .o .rota{display:block;color:var(--ink2);font-size:13px;margin-top:4px}
.list .o details{margin-top:4px;font-size:13px}.list .o details summary{font-weight:400;color:var(--ink2)}
.list .o table{margin-top:4px}
details summary{cursor:pointer;font-weight:600}
details p{color:var(--ink2);font-size:13px;max-width:80ch}
.tab{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px;font-variant-numeric:tabular-nums}
td,th{text-align:left;padding:5px 8px;border-bottom:1px solid var(--grid)}
th{color:var(--ink2);font-weight:600}td.n,th.n{text-align:right}
code{font-size:13px;background:var(--nodata-bg);padding:1px 5px;border-radius:4px}
.dias{display:grid;gap:3px}
.dias i{display:block;aspect-ratio:1;max-height:34px;border-radius:3px;cursor:default}
.dias i:hover{outline:2px solid var(--ink);outline-offset:1px}
.vazio{color:var(--muted);font-size:14px;margin:6px 0 0}
.carga{display:flex;gap:10px;align-items:flex-start;margin-top:14px;padding-top:12px;border-top:1px solid var(--grid)}
.carga svg{width:22px;height:22px;flex:none;margin-top:1px}
.carga b{display:block}.carga .sub{font-size:13px;color:var(--muted)}.carga p{margin:2px 0;color:var(--ink2);font-size:14px}
.plano{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:flex-end;margin-top:14px;padding-top:12px;border-top:1px solid var(--grid)}
.plano label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--ink2);font-weight:600}
.plano input{font:inherit;font-size:14px;color:var(--ink);background:var(--page);border:1px solid var(--ring);border-radius:7px;padding:5px 8px;width:7em}
.testar{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-top:12px}
.testar button{font:inherit;font-size:14px;font-weight:600;border:0;border-radius:7px;padding:7px 16px;background:var(--ink);color:var(--surface);cursor:pointer}
.testar button:disabled{opacity:.45;cursor:default}
.testar span{font-size:13px;color:var(--muted)}
#plres{margin-top:10px}#plres:empty{display:none}
#plres .carga{margin-top:8px;padding-top:0;border-top:0}
.datas{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end;padding:14px 18px}
.datas label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--ink2);font-weight:600}
.datas input{font:inherit;font-size:14px;color:var(--ink);background:var(--page);border:1px solid var(--ring);border-radius:7px;padding:5px 8px}
.datas .dh{display:flex;gap:6px}.datas input[inputmode]{width:5.5em}
.datas button{font:inherit;font-size:14px;font-weight:600;border:0;border-radius:7px;padding:7px 16px;background:var(--ink);color:var(--surface);cursor:pointer}
.datas .erro{flex-basis:100%;color:var(--critical);font-size:13px}.datas .erro:empty{display:none}
.diasx{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-top:4px}
</style></head><body><main id="m">
<header>
  <div><h1>Minha internet</h1><div class="upd" id="upd">carregando…</div></div>
  <div class="seg" id="per" role="group" aria-label="Período">
    <button data-min="60">Última hora</button><button data-min="360">6 horas</button><button data-min="1440">24 horas</button><button data-min="10080">7 dias</button><button id="bdatas" aria-expanded="false">Escolher datas</button>
  </div>
</header>
<form class="card datas" id="datas" hidden>
  <label>De<span class="dh"><input type="date" id="dde"><input type="text" id="hde" inputmode="numeric" maxlength="5" placeholder="hh:mm" aria-label="Hora de início"></span></label>
  <label>Até<span class="dh"><input type="date" id="date"><input type="text" id="hate" inputmode="numeric" maxlength="5" placeholder="hh:mm" aria-label="Hora de fim"></span></label>
  <button type="submit">Ver</button>
  <span class="erro" id="derro" role="alert"></span>
</form>
<section class="card hero" id="hero"></section>
<div class="tiles" id="tiles"></div>
<section class="card"><h3>Como foi o período</h3>
  <p class="cap">Cada cor mostra como a internet estava naquele momento. Passe o mouse para ver o horário. Clique e arraste para ver um trecho de perto.</p>
  <canvas id="tl"></canvas>
  <div class="leg"><span><i style="background:var(--good)"></i>Funcionando</span><span><i style="background:var(--warning)"></i>Instável ou lenta</span><span><i style="background:var(--critical)"></i>Sem conexão</span><span><i style="background:var(--nodata)"></i>Sem medição (monitor desligado)</span></div>
  <div class="tip"></div></section>
<section class="card"><h3 id="dias-t">Últimos dias</h3>
  <p class="cap">Cada quadrado é um dia, com hoje à direita. A cor mostra quanto do dia a internet funcionou. Este quadro não muda com o período escolhido lá em cima.</p>
  <div class="dias" id="dias"></div><div class="diasx"><span id="dias0"></span><span id="dias1"></span></div>
  <div class="leg"><span><i style="background:var(--good)"></i>Funcionou 99% do tempo ou mais</span><span><i style="background:var(--warning)"></i>De 95% a 99%</span><span><i style="background:var(--critical)"></i>Menos de 95%</span><span><i style="background:var(--nodata)"></i>Sem medição (monitor desligado)</span></div>
  <div class="tip"></div></section>
<section class="card"><h3>Rapidez</h3>
  <p class="cap">Tempo que um sinal leva para ir e voltar, em milissegundos (ms). Quanto <b>menor</b>, melhor: abaixo de 50 ms é ótimo, acima de 150 ms a internet parece lenta.</p>
  <canvas id="c1" class="chart"></canvas>
  <div class="leg"><span><i class="ln" style="background:var(--s1)"></i>Até a internet</span><span><i class="ln" style="background:var(--s2)"></i>Até o roteador (dentro de casa)</span><span><i style="background:var(--critical-bg);box-shadow:inset 0 0 0 1px var(--critical)"></i>Sem conexão</span><span><i style="background:var(--band);box-shadow:inset 0 0 0 1px var(--axis)"></i>Teste de velocidade (a resposta fica mais lenta enquanto ele roda)</span></div>
  <div class="tip"></div></section>
<section class="card"><h3>Velocidade</h3>
  <p class="cap">Quanto a internet consegue baixar e enviar, em megabits por segundo (Mbps). Quanto <b>maior</b>, melhor. O monitor testa sozinho de tempos em tempos (normalmente a cada 30 minutos; cada teste gasta cerca de 35 MB).</p>
  <canvas id="c3" class="chart"></canvas><p class="vazio" id="vvazio" hidden></p>
  <div class="leg"><span><i class="ln" style="background:var(--s1)"></i>Baixar (download)</span><span><i class="ln" style="background:var(--s2)"></i>Enviar (upload)</span></div>
  <div class="carga" id="carga" hidden></div>
  <div class="plano"><label>Plano contratado: baixar (Mbps)<input type="text" id="pdown" inputmode="decimal" placeholder="ex.: 500"></label>
    <label>Enviar (Mbps)<input type="text" id="pup" inputmode="decimal" placeholder="ex.: 250"></label></div>
  <div id="plres"></div>
  <div class="testar"><button type="button" id="btest">Fazer teste completo agora</button><span id="tstat"></span></div>
  <div class="tip"></div></section>
<section class="card"><h3>Força do sinal Wi-Fi</h3>
  <p class="cap">Quanto <b>maior</b>, melhor. Abaixo de 35% a conexão pode ficar lenta ou cair: tente ficar mais perto do roteador.</p>
  <canvas id="c2" class="chart"></canvas>
  <div class="tip"></div></section>
<section class="card"><h3>Quando a conexão falhou</h3><p class="cap" id="qcap"></p><ul class="list" id="q"></ul></section>
<section class="card"><details><summary>Detalhes técnicos</summary><div id="tec"></div></details></section>
</main>
<script>
const $=id=>document.getElementById(id);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(x,d=0)=>x==null?'–':x.toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
const avg=a=>{a=a.filter(x=>x!=null);return a.length?a.reduce((s,x)=>s+x,0)/a.length:null};
const caiu=s=>D.status_queda.includes(s)||!(s in ST);   // lista do servidor; status que a página não conhece também é queda
const cat=s=>s==='ok'?'good':s==='degradado'?'warning':'critical';

const ST={
  ok:{nome:'Funcionando',titulo:'Sua internet está funcionando bem',
      texto:'Tudo certo: o Wi-Fi, o roteador e a internet estão respondendo normalmente.'},
  degradado:{nome:'Instável ou lenta',titulo:'Sua internet está instável',
      texto:'Ela funciona, mas com lentidão ou pequenas falhas. Vídeos e chamadas podem travar.'},
  falha_internet:{nome:'Sem internet',dica:'provável problema na operadora',titulo:'Sem internet',
      texto:'O Wi-Fi e o roteador estão funcionando, mas a internet não chega até eles. Normalmente é um problema da operadora. Se durar mais de alguns minutos, reinicie o modem; se continuar, ligue para o provedor.'},
  falha_lan:{nome:'Roteador não respondeu',dica:'problema no Wi-Fi ou no roteador',titulo:'O roteador não está respondendo',
      texto:'O computador está no Wi-Fi, mas não consegue falar com o roteador. Tente chegar mais perto dele ou reiniciá-lo.'},
  sem_wifi:{nome:'Wi-Fi desconectado',dica:'o computador saiu da rede',titulo:'Wi-Fi desconectado',
      texto:'O computador não está conectado a nenhuma rede. Verifique se o Wi-Fi está ligado.'},
  falha_dns:{nome:'Sites não abriam',dica:'falha no DNS',titulo:'Os sites não estão abrindo',
      texto:'A conexão existe, mas o serviço que traduz o nome dos sites (DNS) não respondeu. Costuma passar sozinho; se continuar, reinicie o roteador.'}};
const stNome=s=>(ST[s]||{nome:s}).nome;

const ICON={good:'<path d="M7 12.5l3.2 3.2L17 9"/>',warning:'<path d="M12 7v6M12 16.6v.1"/>',
  critical:'<path d="M8.5 8.5l7 7M15.5 8.5l-7 7"/>',muted:'<path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.3M12 16.6v.1"/>'};
const icon=k=>`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="var(--${k})"/><g fill="none" stroke="${k==='warning'?'#3a2a00':'#fff'}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${ICON[k]}</g></svg>`;

const hm=e=>new Date(e*1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
function quando(e){const d=new Date(e*1000),h=new Date();h.setHours(0,0,0,0);
  const dia=Math.round((h-new Date(d).setHours(0,0,0,0))/864e5);
  return (dia===0?'hoje':dia===1?'ontem':d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'}))+' às '+hm(e)}
function dur(s){s=Math.max(0,Math.round(s));if(s<60)return s+(s===1?' segundo':' segundos');
  const m=Math.round(s/60);if(m<60)return m+' min';const h=Math.floor(m/60),r=m%60;
  return h<48?h+' h'+(r?' '+r+' min':''):Math.round(h/24)+' dias'}

const rapidez=ms=>ms==null?null:ms<50?['Ótima','good']:ms<100?['Boa','good']:ms<150?['Razoável','warning']:['Lenta','critical'];
const estab=p=>p==null?null:p<0.5?['Estável','good']:p<2?['Algumas falhas','warning']:['Instável','critical'];
const pctSinal=dbm=>dbm==null?null:Math.max(0,Math.min(100,2*(dbm+100)));
const sinal=p=>p==null?null:p>=70?['Excelente','good']:p>=50?['Bom','good']:p>=35?['Razoável','warning']:['Fraco','critical'];
const banda=f=>{const m=parseInt(f);return m>=5900?'6 GHz':m>=4900?'5 GHz':'2,4 GHz'};

const emTeste=(e,J)=>J.some(([a,b])=>e>=a&&e<=b);   // J = D.janelas_teste: o servidor já aplica TESTE_MAX e a folga

let D=null,MIN=60,FAIXA=null;   // FAIXA = {de,ate} (epoch) escolhida em "Escolher datas" ou arrastando; aí MIN não vale
try{MIN=+localStorage.getItem('periodo')||60}catch(e){}
const janela=()=>[D.de,D.ate];   // o servidor devolve o período já ajustado (fim no futuro vira agora)
const dm=e=>new Date(e*1000).toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});
const mesmoDia=(a,b)=>new Date(a*1000).toDateString()===new Date(b*1000).toDateString();
const limite=()=>Math.max(20,D.passo*2.5);   // distância maior que isso entre pontos = monitor desligado

function prep(cv){const dpr=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
  if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr)}
  const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,W,H);g.font='12px system-ui,sans-serif';return{g,W,H}}
// período longo ou que não termina hoje leva a data; acima de 8 dias, só a data
function eixoX(g,x0,x1,L,pw,y){const data=x1-x0>36*3600||!mesmoDia(x1,D.agora),soData=x1-x0>8*86400,n=pw<480?2:4;g.fillStyle=css('--muted');
  for(let i=0;i<=n;i++){const e=x0+(x1-x0)*i/n;
    g.textAlign=i===0?'left':i===n?'right':'center';
    g.fillText(soData?dm(e):(data?dm(e)+' ':'')+hm(e),L+pw*i/n,y)}}
function perto(P,e,lim=limite()){let m=null,dm=Infinity;for(const p of P){const d=Math.abs(p.epoch-e);if(d<dm){dm=d;m=p}}return dm<=lim?m:null}
function nice(v){const s=v/4,p=10**Math.floor(Math.log10(s)),m=s/p;return(m<=1?1:m<=2?2:m<=2.5?2.5:m<=5?5:10)*p*4}

function hero(){
  const a=D.atual;let k,t,x,desde='';
  if(!a||D.agora-a.epoch>D.parado_apos){k='muted';t='O monitor não está medindo';
    x='Nenhuma medição recente'+(a?' (a última foi '+quando(a.epoch)+')':'')+'. Para voltar a monitorar, rode make start no terminal.'}
  else{let s=a.status;
    if(!caiu(s))s=D.recentes.filter(r=>r==='degradado').length>=3?'degradado':'ok';  // 1 amostra ruim isolada não muda o resumo
    const i=ST[s]||{titulo:s,texto:''};k=cat(s);t=i.titulo;x=i.texto;
    if(caiu(s)&&D.inicio_atual)desde='Começou '+quando(D.inicio_atual)+' · já dura '+dur(D.agora-D.inicio_atual);
    else if(D.ultima_queda)desde='Última falha: '+quando(D.ultima_queda)+' (há '+dur(D.agora-D.ultima_queda)+')';
    else desde='Nenhuma falha registrada até agora.'}
  const bg=k==='muted'?'nodata':k;
  $('hero').style.background=`linear-gradient(var(--${bg}-bg),var(--${bg}-bg)),var(--surface)`;
  $('hero').innerHTML=`<div class="ic">${icon(k)}</div><div><h2>${esc(t)}</h2><p>${esc(x)}</p>${desde?`<div class="desde">${esc(desde)}</div>`:''}</div>`}

function tiles(){
  const P=D.pontos,tot=D.resumo.reduce((s,r)=>s+r.n,0),bad=D.resumo.filter(r=>caiu(r.status)).reduce((s,r)=>s+r.n,0);
  const up=tot?100*(tot-bad)/tot:null,f=D.falhas,w=D.wifi,vu=D.velocidade_ultimo;
  const inet=avg(P.map(p=>p.inet)),perda=avg(P.map(p=>p.perda)),sn=avg(P.map(p=>p.sinal));
  const T=[
    ['Conexão funcionando',up==null?null:[num(up,up===100?0:1)+'%',upCat(up)],
      up==null?'sem medições no período':'do tempo · '+(f.n?`fora do ar ${f.n} ${f.n===1?'vez':'vezes'}, ${dur(f.seg)} no total`:'nenhuma queda')],
    ['Rapidez',rapidez(inet),inet==null?'':`resposta média de ${num(inet)} ms`],
    ['Estabilidade',estab(perda),perda==null?'':`${num(perda,1)}% dos dados se perderam no caminho`],
    ['Sinal do Wi-Fi',sinal(sn),sn==null?'':`${num(sn)}%`+(w&&w.ssid?` · rede “${w.ssid}”`+(w.freq?' · '+banda(w.freq):''):'')],
    ['Velocidade',vu?[`${num(vu.down)} / ${num(vu.up)} Mbps`,null]:null,
      vu?`Baixar (download) / Enviar (upload) · medido há ${dur(D.agora-(vu.fim||vu.epoch))}`:'nenhum teste de velocidade ainda']];
  $('tiles').innerHTML=T.map(([l,v,s])=>`<div class="card tile"><div class="lbl">${l}</div><div class="val">${v?(v[1]?icon(v[1]):'')+esc(v[0]):'–'}</div><div class="sub">${esc(s)}</div></div>`).join('')}

function timeline(){
  const cv=$('tl'),P=D.pontos,{g,W,H}=prep(cv),T=2,ph=H-T-22,[x0,x1]=janela(),lim=limite(),xs=e=>(e-x0)/(x1-x0)*W;
  g.save();g.beginPath();g.roundRect(0,T,W,ph,6);g.clip();
  g.fillStyle=css('--nodata');g.fillRect(0,T,W,ph);
  P.forEach((p,i)=>{const n=P[i+1],fim=n&&n.epoch-p.epoch<=lim?n.epoch:p.epoch+Math.min(D.passo,lim);
    const a=xs(p.epoch),b=xs(fim);g.fillStyle=css('--'+cat(p.status));g.fillRect(a,T,Math.max(b-a,p.status==='ok'?.5:2),ph)});
  g.restore();
  eixoX(g,x0,x1,0,W,H-4);
  cv._base=timeline;
  cv._x2e=x=>Math.max(x0,Math.min(x1,x0+x/W*(x1-x0)));cv._faixaY=[T,T+ph];   // escala e altura para o arrasto()
  cv._h=x=>{const e=cv._x2e(x),p=perto(P,e);
    const st=p?`<div class="r"><i class="q" style="background:var(--${cat(p.status)})"></i><b>${esc(stNome(p.status))}</b></div>`
              :`<div class="r"><i class="q" style="background:var(--nodata)"></i><b>Sem medição</b></div>`;
    return{x,html:`<div class="t">${esc(quando(p?p.epoch:e))}</div>${st}`}};
  cv._mark=h=>{g.strokeStyle=css('--ink');g.lineWidth=1.5;g.beginPath();g.moveTo(Math.round(h.x)+.5,0);g.lineTo(Math.round(h.x)+.5,T+ph+2);g.stroke()}}

// o: un, max, faixas (quedas em vermelho), P (pontos; padrão D.pontos), lim (maior distância ligada por linha),
//    marcas (bolinha em cada ponto, para séries esparsas), janelas ([[ini,fim]] desenhadas como faixa --band),
//    esq (margem esquerda para os rótulos do eixo Y)
function lineChart(cv,series,o={}){
  const {un='',max=null,faixas=false,P=D.pontos,lim=limite(),marcas=false,janelas=[],esq=52}=o;
  const {g,W,H}=prep(cv),L=esq,R=10,T=8,B=24,pw=W-L-R,ph=H-T-B,[x0,x1]=janela();
  const xs=e=>L+(e-x0)/(x1-x0)*pw;
  const vals=series.flatMap(s=>P.map(p=>p[s.k])).filter(v=>v!=null).sort((a,b)=>a-b);
  // escala pelo percentil 98: um pico isolado não achata o resto do gráfico (ele sai pelo topo)
  const hi=max??nice(Math.max(1,(vals[Math.floor(.98*(vals.length-1))]||1)*1.15)),ys=v=>T+ph-Math.min(v,hi*1.02)/hi*ph;
  g.lineWidth=1;g.strokeStyle=css('--grid');g.fillStyle=css('--muted');g.textAlign='right';
  for(let i=1;i<=4;i++){const v=hi*i/4,y=Math.round(ys(v))+.5;g.beginPath();g.moveTo(L,y);g.lineTo(W-R,y);g.stroke();g.fillText(num(v)+un,L-8,y+4)}
  g.fillText('0'+un,L-8,T+ph+4);
  if(janelas.length){g.fillStyle=css('--band');
    for(const [a,b] of janelas){const xa=Math.max(L,xs(a)),xb=Math.min(W-R,xs(b));if(xb+2>xa)g.fillRect(xa,T,Math.max(xb-xa,2),ph)}}
  if(faixas){g.fillStyle=css('--critical-bg');
    P.forEach((p,i)=>{if(!caiu(p.status))return;const n=P[i+1],fim=n&&n.epoch-p.epoch<=lim?n.epoch:p.epoch+D.passo;
      const a=xs(p.epoch);g.fillRect(a,T,Math.max(xs(fim)-a,2),ph)})}
  g.strokeStyle=css('--axis');g.beginPath();g.moveTo(L,T+ph+.5);g.lineTo(W-R,T+ph+.5);g.stroke();
  g.save();g.beginPath();g.rect(L,0,pw,T+ph);g.clip();
  g.lineWidth=2;g.lineJoin='round';g.lineCap='round';
  for(const s of [...series].reverse()){g.strokeStyle=css(s.c);g.beginPath();let ant=null;
    for(const p of P){const v=p[s.k];if(v==null){ant=null;continue}const x=xs(p.epoch),y=ys(v);
      ant&&p.epoch-ant.epoch<=lim?g.lineTo(x,y):g.moveTo(x,y);ant=p}g.stroke();
    if(marcas){g.fillStyle=css(s.c);for(const p of P){const v=p[s.k];if(v==null)continue;g.beginPath();g.arc(xs(p.epoch),ys(v),3,0,7);g.fill()}}}
  g.restore();
  eixoX(g,x0,x1,L,pw,H-6);
  cv._base=()=>lineChart(cv,series,o);
  cv._h=x=>{const p=perto(P,x0+(x-L)/pw*(x1-x0),lim);if(!p)return null;
    let html=`<div class="t">${esc(quando(p.epoch))}</div>`;
    for(const s of series)html+=`<div class="r"><i style="background:var(${s.c})"></i><b>${p[s.k]==null?'–':num(p[s.k])+un}</b>${esc(s.n)}</div>`;
    if(caiu(p.status))html+=`<div class="r"><i class="q" style="background:var(--critical)"></i>${esc(stNome(p.status))}</div>`;
    if(emTeste(p.epoch,janelas))html+=`<div class="r"><i class="q" style="background:var(--band);box-shadow:inset 0 0 0 1px var(--axis)"></i>teste de velocidade rodando</div>`;
    return{x:xs(p.epoch),p,html}};
  cv._mark=h=>{g.strokeStyle=css('--axis');g.lineWidth=1;g.beginPath();g.moveTo(Math.round(h.x)+.5,T);g.lineTo(Math.round(h.x)+.5,T+ph);g.stroke();
    for(const s of series){const v=h.p[s.k];if(v==null)continue;g.beginPath();g.arc(h.x,ys(v),5,0,7);g.fillStyle=css(s.c);g.fill();
      g.lineWidth=2;g.strokeStyle=css('--surface');g.stroke()}}}

function fraseCarga(n){
  const quem=n.fase==='up'?'Quando alguém envia algo (fotos, vídeos, backup)':'Quando alguém baixa algo';
  if(n.acrescimo<1)return quem+', a resposta não fica mais lenta: ótimo para chamadas de vídeo e jogos.';
  const fim={Ótimo:'nem dá para perceber.',Bom:'quase não se nota.',Razoável:'chamadas de vídeo podem travar.',
    Ruim:'chamadas de vídeo e jogos ficam bem ruins.'}[n.nome];
  return `${quem}, a resposta fica ${num(n.acrescimo)} ms mais lenta: ${fim}`}

let PLANO={down:null,up:null};
try{PLANO=Object.assign(PLANO,JSON.parse(localStorage.getItem('plano')||'{}'))}catch(e){}
const lerMbps=v=>{const n=parseFloat(String(v).replace(',','.'));return n>0?n:null};
// faixas da Anatel: média >= 80% do contratado é o esperado; instantânea abaixo de 40% é descumprimento
const planoCat=r=>r>=.8?'good':r>=.4?'warning':'critical';
function plano(){
  // só o teste completo serve para conferir o plano: o rápido (25 MB) mede a arrancada e costuma dar bem menos
  const el=$('plres'),C=(D.velocidade||[]).filter(t=>t.completo&&(t.down!=null||t.up!=null)),vc=D.velocidade_completo;
  const lin=(nome,k,cont,aprox)=>{if(!cont)return '';
    const v=C.map(t=>t[k]).filter(x=>x!=null),ult=vc&&vc[k]!=null?vc[k]:null;
    if(!v.length&&ult==null)return '';
    const med=v.length?v.reduce((a,b)=>a+b)/v.length:null,ref=med!=null?med:ult,r=ref/cont,cat=planoCat(r);
    const txt=r>=.8?'dentro do esperado':r>=.4?'abaixo do esperado':'muito abaixo do contratado';
    return `<div class="carga">${icon(cat)}<div><b>${nome}: ${num(100*r)}% do plano (${txt})${aprox?' · aproximado':''}</b>`+
      `<div class="sub">Contratado ${num(cont,cont%1?1:0)} Mbps · `+(med!=null?(v.length===1?`teste completo ${num(med)} Mbps`:
        `média de ${v.length} testes completos no período ${num(med)} Mbps (melhor ${num(Math.max(...v))}, pior ${num(Math.min(...v))})`)
        :`último teste completo ${num(ult)} Mbps, ${esc(quando(vc.fim||vc.epoch))}`)+`</div></div></div>`};
  const h=lin('Baixar (download)','down',PLANO.down,false)+lin('Enviar (upload)','up',PLANO.up,true);
  el.innerHTML=h||((PLANO.down||PLANO.up)?'<p class="vazio">Ainda não há teste completo para comparar com o plano. Ele roda 3 vezes por dia (normalmente às 9h, 15h e 21h).</p>':'');
  if(h)el.insertAdjacentHTML('beforeend','<p class="vazio">Usa só o teste completo (3 vezes por dia, download maior): o teste rápido do gráfico costuma marcar menos que a velocidade real. O envio (upload) ainda é medido com pouco volume, então é aproximado. O esperado é receber pelo menos 80% do contratado, em média (regra da Anatel).</p>')}
let PEDINDO=false;
function botaoTeste(){
  const b=$('btest'),s=$('tstat'),r=D.velocidade_rodando,fora=D.atual&&caiu(D.atual.status);
  const apos=D.teste_manual_apos,T=D.velocidade||[],ult=T[T.length-1],lim=ult&&ult.erro&&ult.erro.includes('429');
  b.disabled=PEDINDO||!!r||D.teste_pedido||!!apos;
  s.textContent=r?`Teste ${r.completo?'completo':'rápido'} rodando (começou há ${dur(D.agora-r.epoch)}). O resultado aparece aqui quando terminar.`
    :D.teste_pedido?(fora?'Pedido feito. O teste espera a internet voltar.':'Pedido feito. O teste começa em alguns segundos.')
    :(lim?'O último teste falhou porque o servidor de teste limitou o uso (muitos testes seguidos). Ele libera em até 1 hora. ':'')+
    (apos?`Para não ser bloqueado pelo servidor de teste, o próximo teste completo pode ser pedido a partir das ${hm(apos)}.`
      :'Leva cerca de 30 segundos e baixa por volta de 1 GB. Dá para pedir 1 por hora.')}
$('btest').onclick=async()=>{PEDINDO=true;$('btest').disabled=true;
  try{const r=await fetch('/teste-completo',{method:'POST',headers:{'X-Pedido':'1'}});if(!r.ok)throw 0;await load()}
  catch(e){$('tstat').textContent='Não foi possível pedir o teste. Tente de novo.'}
  finally{PEDINDO=false;if(D)botaoTeste()}};
$('pdown').value=PLANO.down||'';$('pup').value=PLANO.up||'';
[['pdown','down'],['pup','up']].forEach(([id,k])=>$(id).oninput=e=>{PLANO[k]=lerMbps(e.target.value);
  try{localStorage.setItem('plano',JSON.stringify(PLANO))}catch(x){}if(D)plano()});
function velocidade(){
  const V=(D.velocidade||[]).filter(t=>t.down!=null||t.up!=null).map(t=>({epoch:t.fim||t.epoch,down:t.down,up:t.up,status:'ok'}));
  const dif=V.slice(1).map((p,i)=>p.epoch-V[i].epoch).sort((a,b)=>a-b),med=dif.length?dif[dif.length>>1]:0;
  const vazio=$('vvazio'),vu=D.velocidade_ultimo;
  vazio.hidden=!!V.length;
  vazio.textContent=vu?'Nenhum teste de velocidade neste período. O último foi '+quando(vu.fim||vu.epoch)+'.'
    :'Ainda não há nenhum teste de velocidade. O primeiro roda cerca de 1 minuto depois de o monitor iniciar.';
  // liga só testes consecutivos: lacuna maior que ~2 intervalos fica sem linha
  lineChart($('c3'),[{k:'down',c:'--s1',n:'baixar (download)'},{k:'up',c:'--s2',n:'enviar (upload)'}],
    {un:' Mbps',P:V,lim:med?2.5*med:3600,marcas:true,esq:76});
  const c=vu&&vu.carga,n=c&&c.nota,el=$('carga');
  el.hidden=!n;
  if(n)el.innerHTML=`${icon(n.cat)}<div><b>Quando a internet está em uso: ${esc(n.nome)}</b><p>${esc(fraseCarga(n))}</p>`+
    `<div class="sub">Resposta parada ${num(c.ocioso)} ms · baixando ${num(c.down)} ms · enviando ${num(c.up)} ms · teste ${esc(quando(vu.fim||vu.epoch))}</div></div>`}

const CAMINHO_ABERTO=new Set();   // "ver caminho" abertos sobrevivem à atualização a cada 5 s
function caminho(q){const r=q.rota;if(!r)return '';
  let h=r.frase?`<span class="rota">${esc(r.frase)}</span>`:'';
  if(r.saltos&&r.saltos.length)h+=`<details data-id="${q.id}"${CAMINHO_ABERTO.has(q.id)?' open':''}><summary>ver caminho</summary>`+
    `<div class="tab"><table><tr><th class="n">Ponto</th><th>Endereço (IP)</th><th class="n">Tempo</th></tr>${r.saltos.map(s=>
      `<tr><td class="n">${s.n}${s.n===1?' (roteador)':''}</td><td>${s.ip?`<code>${esc(s.ip)}</code>`:'sem resposta'}</td><td class="n">${s.ms==null?'–':num(s.ms,1)+' ms'}</td></tr>`).join('')}</table></div></details>`;
  return h}
function quedas(){
  const Q=D.quedas,f=D.falhas;
  $('qcap').textContent=f.n?`${f.n} ${f.n===1?'falha':'falhas'} no período, somando ${dur(f.seg)} sem conexão.`+(f.n>Q.length?` Mostrando as ${Q.length} mais recentes.`:''):'';
  $('q').innerHTML=Q.length?Q.map(q=>{const i=ST[q.status]||{nome:q.status},agora=q.fim==null;
      return `<li>${icon('critical')}<div class="o"><b>${esc(i.nome)}</b><span>${esc(quando(q.ini))}${i.dica?' · '+esc(i.dica):''}</span>${caminho(q)}</div>`+
        `<div class="d">${agora?'<b>acontecendo agora</b><br>há '+esc(dur(D.agora-q.ini)):'durou '+esc(dur(q.fim-q.ini))}</div></li>`}).join('')
    :`<li>${icon('good')}<div class="o"><b>Nenhuma falha neste período</b></div></li>`}

const DIA_ST={good:'Funcionou bem',warning:'Algumas falhas',critical:'Muitas falhas',nodata:'Sem medição'};
const upCat=up=>up>=99?'good':up>=95?'warning':'critical';   // mesmas faixas do tile "Conexão funcionando"
function horas(s){return s<3600?Math.round(s/60)+' min':num(s/3600,s<36000?1:0)+' h'}
function diaInfo(d){const [a,m,dd]=d.dia.split('-').map(Number),dt=new Date(a,m-1,dd),hoje=d===D.dias[D.dias.length-1];
  const nome=hoje?'Hoje':dt.toLocaleDateString('pt-BR',{weekday:'long',day:'2-digit',month:'2-digit'});
  if(!d.n)return{k:'nodata',nome,linhas:['Nenhuma medição neste dia']};
  const up=100*(d.n-d.fora)/d.n,k=upCat(up),med=d.n*D.intervalo,
    total=hoje?Math.max(med,D.agora-dt.getTime()/1000):86400;
  return{k,nome,linhas:[`${num(up,up===100?0:1)}% do tempo funcionando`,
    d.quedas?`Caiu ${d.quedas} ${d.quedas===1?'vez':'vezes'} · ${dur(d.fora*D.intervalo)} fora do ar`:(d.fora?`${dur(d.fora*D.intervalo)} fora do ar`:'Nenhuma queda'),
    `Medido ${horas(med)} de ${horas(total)}`+(hoje?' até agora':'')]}}
function dias(){
  const el=$('dias'),X=D.dias.map(diaInfo);
  el.style.gridTemplateColumns=`repeat(${D.n_dias},minmax(0,1fr))`;$('dias-t').textContent=`Últimos ${D.n_dias} dias`;
  el.innerHTML=X.map((x,i)=>`<i data-i="${i}" style="background:var(--${x.k})" aria-label="${esc(x.nome+': '+DIA_ST[x.k]+'. '+x.linhas.join('. '))}"></i>`).join('');
  const f=d=>{const [a,m,dd]=d.split('-');return dd+'/'+m};
  $('dias0').textContent=f(D.dias[0].dia);$('dias1').textContent='hoje';
  const card=el.parentElement,tip=card.querySelector('.tip');
  el.onpointermove=ev=>{const q=ev.target.closest('i[data-i]');if(!q){tip.style.display='none';return}
    const x=X[+q.dataset.i];
    tip.innerHTML=`<div class="t">${esc(x.nome)}</div><div class="r"><i class="q" style="background:var(--${x.k})"></i><b>${esc(DIA_ST[x.k])}</b></div>`+
      x.linhas.map(l=>`<div class="r">${esc(l)}</div>`).join('');
    tip.style.display='block';
    const cr=card.getBoundingClientRect(),r=q.getBoundingClientRect(),tw=tip.offsetWidth;
    let left=r.left-cr.left+r.width/2-tw/2;left=Math.max(8,Math.min(left,card.clientWidth-tw-8));
    tip.style.left=left+'px';tip.style.top=(r.bottom-cr.top+6)+'px'};
  el.onpointerleave=()=>{tip.style.display='none'}}

function tecnico(){
  const P=D.pontos,a=k=>avg(P.map(p=>p[k])),tot=D.resumo.reduce((s,r)=>s+r.n,0)||1;
  const M=[['Resposta do roteador (gateway)',a('gw'),' ms'],['Resposta da Cloudflare (1.1.1.1)',a('cf'),' ms'],['Resposta do Google (8.8.8.8)',a('gg'),' ms'],
    ['Perda de pacotes até o roteador',a('gwl'),' %',2],['Perda de pacotes até a Cloudflare',a('cfl'),' %',2],['Perda de pacotes até o Google',a('ggl'),' %',2],
    ['Tempo de resposta do DNS',a('dns'),' ms'],['Sinal Wi-Fi',a('dbm'),' dBm']];
  const vu=D.velocidade_ultimo,c=vu&&vu.carga;
  if(vu)M.push(['Último teste: baixar (download)',vu.down,' Mbps'],['Último teste: enviar (upload)',vu.up,' Mbps']);
  if(c)M.push(['Último teste: resposta parada (mediana)',c.ocioso,' ms'],['Último teste: resposta baixando (mediana)',c.down,' ms'],
    ['Último teste: resposta enviando (mediana)',c.up,' ms']);
  $('tec').innerHTML=`<p>A cada ${D.intervalo} segundos o monitor envia sinais (ping) para o roteador e para dois servidores na internet (Cloudflare e Google), testa o DNS e lê a força do sinal Wi-Fi.
    Se o roteador não responde, o problema está dentro de casa; se o roteador responde mas a internet não, o problema é da operadora.
    “Instável” significa que algum pacote se perdeu ou que a internet demorou mais de 150 ms nos dois servidores (Cloudflare e Google); se só um deles estiver lento, a internet não é considerada instável.</p>
    <div class="tab"><table><tr><th>Medição (média no período)</th><th class="n">Valor</th></tr>${M.map(([l,v,u,d])=>`<tr><td>${l}</td><td class="n">${num(v,d||1)}${u}</td></tr>`).join('')}</table></div>
    <div class="tab"><table><tr><th>Situação</th><th>Código</th><th class="n">Medições</th><th class="n">% do tempo</th></tr>${[...D.resumo].sort((x,y)=>y.n-x.n).map(r=>
      `<tr><td>${esc(stNome(r.status))}</td><td><code>${esc(r.status)}</code></td><td class="n">${num(r.n)}</td><td class="n">${num(100*r.n/tot,2)}%</td></tr>`).join('')}</table></div>`}

function tamanho(b){const f=(v,d)=>v.toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
  return b<1048576?f(b/1024,0)+' KB':b<1073741824?f(b/1048576,1)+' MB':f(b/1073741824,2)+' GB'}
function textoBanco(b){if(!b)return '';
  return ' · Banco: '+tamanho(b.bytes)+(b.por_dia==null?'':' · cresce ~'+tamanho(b.por_dia)+'/dia')}

function draw(){
  if(!D)return;
  D.pontos.forEach(p=>{const v=[p.cf,p.gg].filter(x=>x!=null);p.inet=v.length?v.reduce((s,x)=>s+x)/v.length:null;
    p.perda=Math.max(p.gwl||0,p.cfl||0,p.ggl||0);p.sinal=pctSinal(p.dbm)});
  document.querySelectorAll('.tip').forEach(t=>t.style.display='none');
  hero();tiles();timeline();dias();
  lineChart($('c1'),[{k:'inet',c:'--s1',n:'até a internet'},{k:'gw',c:'--s2',n:'até o roteador'}],{un:' ms',faixas:true,janelas:D.janelas_teste});
  velocidade();plano();botaoTeste();
  lineChart($('c2'),[{k:'sinal',c:'--s1',n:'sinal'}],{un:'%',max:100});
  quedas();tecnico();
  document.querySelectorAll('canvas').forEach(c=>c._sobre&&c._sobre());   // arrasto em andamento sobrevive à atualização
  $('upd').textContent=(FAIXA?'Mostrando de '+dm(D.de)+' '+hm(D.de)+' até '+(mesmoDia(D.de,D.ate)?'':dm(D.ate)+' ')+hm(D.ate)+' · ':'')+
    'Atualizado às '+new Date().toLocaleTimeString('pt-BR')+' · atualiza sozinho a cada 5 s'+textoBanco(D.banco)}

function hover(cv){const card=cv.parentElement,tip=card.querySelector('.tip');
  cv.onpointermove=ev=>{if(!cv._h||cv._arrastando)return;const r=cv.getBoundingClientRect(),h=cv._h(ev.clientX-r.left);cv._base();
    if(!h){tip.style.display='none';return}cv._mark(h);tip.innerHTML=h.html;tip.style.display='block';
    const cr=card.getBoundingClientRect(),ox=r.left-cr.left,tw=tip.offsetWidth;let left=ox+h.x+14;
    if(left+tw>card.clientWidth-8)left=ox+h.x-14-tw;
    tip.style.left=Math.max(8,left)+'px';tip.style.top=(r.top-cr.top+(cv.id==='tl'?cv.clientHeight+4:8))+'px'};
  cv.onpointerleave=()=>{if(cv._arrastando)return;tip.style.display='none';cv._base&&cv._base()}}

// Clicar, segurar e arrastar seleciona um trecho; ao soltar chama escolhe(de, ate) com o trecho arredondado ao
// minuto. Só usa a escala que o gráfico expõe (cv._x2e: x em px → epoch, já limitado à janela; cv._faixaY:
// [topo, base] da faixa, opcional). Arrasto curto (< 6 px ou < 60 s) é clique e não faz nada; Esc cancela.
// Com o touch-action:pan-y do canvas, no toque o arrasto vertical continua rolando a página (pointercancel).
const ARRASTO_MIN_PX=6,ARRASTO_MIN_S=60;
function arrasto(cv,escolhe){const card=cv.parentElement,tip=card.querySelector('.tip');let a=null;   // a = {id, x0, x}
  const trecho=()=>{const [e0,e1]=[cv._x2e(a.x0),cv._x2e(a.x)].sort((p,q)=>p-q),[j0,j1]=[cv._x2e(0),cv._x2e(cv.clientWidth)];
    return{de:Math.max(j0,Math.floor(e0/60)*60),ate:Math.min(j1,Math.ceil(e1/60)*60),curto:Math.abs(a.x-a.x0)<ARRASTO_MIN_PX||e1-e0<ARRASTO_MIN_S}};
  const pinta=()=>{cv._base();const g=cv.getContext('2d'),[y0,y1]=cv._faixaY||[0,cv.clientHeight];
    const xa=Math.min(a.x0,a.x),xb=Math.max(a.x0,a.x);
    g.fillStyle=css('--band');g.fillRect(xa,y0,xb-xa,y1-y0);
    g.strokeStyle=css('--axis');g.lineWidth=1;g.strokeRect(Math.round(xa)+.5,y0+.5,Math.max(0,Math.round(xb-xa)-1),y1-y0-1);
    const {de,ate}=trecho(),dia=!mesmoDia(de,ate),f=e=>(dia?dm(e)+' ':'')+hm(e);
    tip.innerHTML=`<div class="r"><b>De ${esc(f(de))} até ${esc(f(ate))}</b></div>`;tip.style.display='block';
    const r=cv.getBoundingClientRect(),cr=card.getBoundingClientRect(),tw=tip.offsetWidth;
    tip.style.left=Math.max(8,Math.min(r.left-cr.left+(xa+xb)/2-tw/2,card.clientWidth-tw-8))+'px';
    tip.style.top=(r.top-cr.top+cv.clientHeight+4)+'px'};
  const fim=ev=>{if(!a||(ev&&ev.pointerId!==a.id))return null;const t=trecho();
    try{cv.releasePointerCapture(a.id)}catch(e){}a=null;cv._arrastando=false;cv._sobre=null;tip.style.display='none';cv._base&&cv._base();return t};
  const px=ev=>{const r=cv.getBoundingClientRect();return Math.max(0,Math.min(r.width,ev.clientX-r.left))};
  cv.addEventListener('pointerdown',ev=>{if(!cv._x2e||ev.button!==0||a)return;
    a={id:ev.pointerId,x0:px(ev),x:px(ev)};cv.setPointerCapture(ev.pointerId);if(ev.pointerType==='mouse')ev.preventDefault()});
  cv.addEventListener('pointermove',ev=>{if(!a||ev.pointerId!==a.id)return;a.x=px(ev);
    if(!cv._arrastando&&Math.abs(a.x-a.x0)<ARRASTO_MIN_PX)return;   // ainda pode ser um clique: o hover segue
    cv._arrastando=true;cv._sobre=pinta;pinta()});
  cv.addEventListener('pointerup',ev=>{const t=fim(ev);if(t&&!t.curto)escolhe(t.de,t.ate)});
  cv.addEventListener('pointercancel',fim);
  addEventListener('keydown',ev=>{if(ev.key==='Escape'&&a)fim()})}

function marcaPeriodo(){document.querySelectorAll('#per button[data-min]').forEach(b=>b.setAttribute('aria-pressed',!FAIXA&&+b.dataset.min===MIN));
  $('bdatas').setAttribute('aria-pressed',!!FAIXA)}
async function load(){
  try{const r=await fetch(FAIXA?`/api?de=${FAIXA.de}&ate=${FAIXA.ate}`:'/api?min='+MIN);if(!r.ok)throw 0;D=await r.json();draw()}
  catch(e){$('upd').textContent='Não foi possível carregar os dados. O painel ainda está rodando?'}
  finally{$('m').classList.remove('carregando')}}
function trocaPeriodo(){marcaPeriodo();$('m').classList.add('carregando');load()}
function abreDatas(abrir){$('datas').hidden=!abrir;$('bdatas').setAttribute('aria-expanded',abrir)}
// período escolhido em "Escolher datas" ou arrastando no "Como foi o período"; os botões de período o limpam
function escolheFaixa(de,ate){FAIXA={de,ate};abreDatas(false);trocaPeriodo()}
document.querySelectorAll('#per button[data-min]').forEach(b=>b.onclick=()=>{MIN=+b.dataset.min;FAIXA=null;try{localStorage.setItem('periodo',MIN)}catch(e){}
  abreDatas(false);trocaPeriodo()});
// "Escolher datas": abre já preenchido com o período que está na tela. A escolha não fica salva:
// quem reabre o painel dias depois volta para um período "até agora", não para uma data velha.
// A hora é um campo de texto HH:MM, não datetime-local: esse o navegador desenha no idioma dele,
// e em inglês aparece 2:30 PM. Datas e horas são montadas em hora local (toISOString() daria UTC).
const p2=n=>String(n).padStart(2,'0');
const dataLocal=e=>{const d=new Date(e*1000);return `${d.getFullYear()}-${p2(d.getMonth()+1)}-${p2(d.getDate())}`};
const horaLocal=e=>{const d=new Date(e*1000);return `${p2(d.getHours())}:${p2(d.getMinutes())}`};
const HORA=/^([01]?\d|2[0-3]):([0-5]\d)$/;
// "9:05" → "09:05"; null se não for uma hora válida
function hora24(t){const h=HORA.exec(t.trim());return h&&`${p2(+h[1])}:${h[2]}`}
// "AAAA-MM-DD" + "HH:MM" → epoch (hora local)
function epochLocal(data,hora){const [a,m,d]=data.split('-').map(Number),[h,min]=hora.split(':').map(Number);
  return new Date(a,m-1,d,h,min).getTime()/1000}
$('bdatas').onclick=()=>{const abrir=$('datas').hidden;abreDatas(abrir);if(!abrir)return;
  const agora=Date.now()/1000;$('dde').max=dataLocal(agora);$('derro').textContent='';
  if(D){$('dde').value=dataLocal(D.de);$('hde').value=horaLocal(D.de);$('date').value=dataLocal(D.ate);$('hate').value=horaLocal(D.ate)}
  $('dde').focus()};
$('datas').onsubmit=ev=>{ev.preventDefault();
  const hde=hora24($('hde').value),hate=hora24($('hate').value);
  if(hde)$('hde').value=hde;if(hate)$('hate').value=hate;
  const vazia=!$('dde').value||!$('date').value,de=epochLocal($('dde').value,hde||''),ate=epochLocal($('date').value,hate||''),agora=Date.now()/1000;
  const erro=vazia?'Preencha as duas datas.':!hde||!hate?'Hora inválida: use o formato 14:30.'
    :isNaN(de)||isNaN(ate)?'Preencha as duas datas.':de>=agora?'O início precisa ser antes de agora.'
    :de>=ate?'O início precisa ser antes do fim.':ate-de>D.periodo_max?`Escolha no máximo ${D.periodo_max/86400} dias.`:'';
  $('derro').textContent=erro;if(erro)return;
  escolheFaixa(de,ate)};
['tl','c1','c2','c3'].forEach(id=>hover($(id)));
arrasto($('tl'),escolheFaixa);
$('q').addEventListener('toggle',ev=>{const id=+ev.target.dataset.id;if(!id)return;
  ev.target.open?CAMINHO_ABERTO.add(id):CAMINHO_ABERTO.delete(id)},true);
addEventListener('resize',draw);matchMedia('(prefers-color-scheme:dark)').onchange=draw;
if(![60,360,1440,10080].includes(MIN))MIN=60;
marcaPeriodo();load();setInterval(load,5000);
</script></body></html>"""

if __name__ == "__main__":
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        sys.exit(f"A porta {PORT} já está em uso (o painel do Docker já está rodando?). "
                 f"Pare o container com `make stop` ou use outra porta: PORT=8081 make web")
    print(f"Painel em http://127.0.0.1:{PORT}", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
