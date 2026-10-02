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


# lista fechada de arquivos da página: caminho -> (arquivo ao lado de painel.py, tipo de conteúdo)
ARQUIVOS = {
    "/": ("pagina.html", "text/html; charset=utf-8"),
    "/pagina.css": ("pagina.css", "text/css; charset=utf-8"),
    "/pagina.js": ("pagina.js", "text/javascript; charset=utf-8"),
}


def ler_arquivo(nome):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), nome), "rb") as f:
        return f.read()


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ARQUIVOS:
            nome, tipo = ARQUIVOS[u.path]
            try:
                body = ler_arquivo(nome)
            except OSError as e:
                self.send_error(500, str(e))
                return
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
