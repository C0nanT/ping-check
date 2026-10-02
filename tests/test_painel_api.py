import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from unittest import mock

import monitor
import painel

AGORA = 1_000_000.0
HOJE = datetime.fromtimestamp(AGORA).date()


def iso(epoch):
    return datetime.fromtimestamp(epoch).isoformat(timespec="seconds")


def meia_noite(d):
    """epoch da meia-noite local do dia d."""
    return datetime(d.year, d.month, d.day).timestamp()


class ApiBase(unittest.TestCase):
    """Banco SQLite temporário com o SCHEMA do monitor; o DB do painel e o relógio são trocados."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = os.path.join(self.dir, "teste.db")
        con = sqlite3.connect(self.db)
        con.executescript(monitor.SCHEMA)
        con.close()
        painel.limpar_cache_dias()
        self.addCleanup(painel.limpar_cache_dias)
        self.pedido = os.path.join(self.dir, "pedido_teste_completo")
        for alvo in (mock.patch.object(painel, "DB", self.db), mock.patch.object(painel, "PEDIDO", self.pedido),
                     mock.patch.object(painel.time, "time", return_value=AGORA)):
            alvo.start()
            self.addCleanup(alvo.stop)

    def sql(self, q, args=()):
        con = sqlite3.connect(self.db)
        with con:
            con.execute(q, args)
        con.close()

    def amostra(self, epoch, status="ok", gw=None, dbm=None):
        self.sql("INSERT INTO checks (ts, epoch, status, gw_avg_ms, wifi_dbm) VALUES (?, ?, ?, ?, ?)",
                 (iso(epoch), epoch, status, gw, dbm))

    def queda(self, ini, fim, status="falha_lan"):
        return self.sql_id("INSERT INTO outages (status, start_ts, start_epoch, end_ts, end_epoch) VALUES (?, ?, ?, ?, ?)",
                           (status, iso(ini), ini, iso(fim), fim))

    def sql_id(self, q, args=()):
        con = sqlite3.connect(self.db)
        with con:
            i = con.execute(q, args).lastrowid
        con.close()
        return i


class AgrupamentoTest(ApiBase):
    def test_poucas_amostras_sem_agrupar(self):
        for i in range(10):
            self.amostra(AGORA - 100 + i * 5, gw=float(i))
        r = painel.api(60)
        self.assertEqual(len(r["pontos"]), 10)
        self.assertEqual([p["gw"] for p in r["pontos"]], [float(i) for i in range(10)])
        self.assertEqual(r["passo"], monitor.INTERVAL)

    def test_exatamente_max_pontos_nao_agrupa(self):
        for i in range(painel.MAX_PONTOS):
            self.amostra(AGORA - 3500 + i, gw=1.0)
        r = painel.api(60)
        self.assertEqual(len(r["pontos"]), painel.MAX_PONTOS)
        self.assertEqual(r["passo"], monitor.INTERVAL)

    def test_muitas_amostras_media_e_pior_status_por_balde(self):
        # 1200 amostras a cada 3 s em 60 min -> baldes de 6 s com 2 amostras cada
        desde = AGORA - 3600
        for i in range(1200):
            status = "ok"
            if i == 1:
                status = "falha_lan"      # balde 0: ok + falha_lan
            elif i == 2:
                status = "degradado"      # balde 1: degradado + ok
            self.amostra(desde + 3 * i + 1, status=status, gw=float(i))
        r = painel.api(60)
        self.assertEqual(len(r["pontos"]), 600)
        self.assertAlmostEqual(r["passo"], 6.0)
        p0, p1, p2 = r["pontos"][:3]
        self.assertAlmostEqual(p0["gw"], 0.5)
        self.assertEqual(p0["status"], "falha_lan")
        self.assertAlmostEqual(p1["gw"], 2.5)
        self.assertEqual(p1["status"], "degradado")
        self.assertEqual(p2["status"], "ok")
        self.assertAlmostEqual(p0["epoch"], desde + 2.5)

    def test_varios_status_de_queda_no_balde_devolve_grau_2(self):
        desde = AGORA - 3600
        for i in range(1200):
            status = {0: "degradado", 1: "falha_dns", 2: "ok"}.get(i, "ok")
            self.amostra(desde + 3 * i + 1, status=status)
        r = painel.api(60)
        self.assertEqual(r["pontos"][0]["status"], "falha_dns")
        self.assertEqual(set(r["pontos"][0]), {"epoch", "status", *painel.CAMPOS})

    def test_media_ignora_valores_nulos(self):
        desde = AGORA - 3600
        for i in range(1200):
            self.amostra(desde + 3 * i + 1, gw=10.0 if i % 2 == 0 else None)
        r = painel.api(60)
        self.assertEqual({p["gw"] for p in r["pontos"]}, {10.0})

    def test_baldes_vazios_somem_e_deixam_buraco(self):
        desde = AGORA - 3600
        for i in range(350):                       # primeiros 15 min
            self.amostra(desde + 2 * i + 1)
        for i in range(350):                       # últimos 15 min
            self.amostra(AGORA - 900 + 2 * i + 1)
        r = painel.api(60)
        self.assertGreater(r["passo"], painel.INTERVALO)
        ep = [p["epoch"] for p in r["pontos"]]
        self.assertLess(len(ep), 600)
        maior_vão = max(b - a for a, b in zip(ep, ep[1:]))
        self.assertGreater(maior_vão, 1500)
        self.assertGreater(maior_vão, 2.5 * r["passo"])


class QuedasTest(ApiBase):
    def test_queda_sem_fim_termina_na_primeira_amostra_com_outro_status(self):
        for e in (AGORA - 100, AGORA - 95):
            self.amostra(e)
        for e in (AGORA - 90, AGORA - 85, AGORA - 80):
            self.amostra(e, status="falha_lan")
        self.amostra(AGORA - 75, status="falha_internet")   # outro status ainda "down"
        self.amostra(AGORA - 70)
        self.amostra(AGORA - 2)
        self.sql("INSERT INTO outages (status, start_ts, start_epoch) VALUES ('falha_lan', 't', ?)",
                 (AGORA - 90,))
        r = painel.api(60)
        self.assertEqual(len(r["quedas"]), 1)
        self.assertEqual(r["quedas"][0]["ini"], AGORA - 90)
        self.assertEqual(r["quedas"][0]["fim"], AGORA - 75)
        self.assertEqual(r["falhas"], {"n": 1, "seg": 15})

    def test_queda_aberta_com_monitor_parado_termina_na_ultima_amostra(self):
        self.amostra(AGORA - 500)
        for e in (AGORA - 400, AGORA - 395, AGORA - 390):
            self.amostra(e, status="falha_lan")
        self.sql("INSERT INTO outages (status, start_ts, start_epoch) VALUES ('falha_lan', 't', ?)",
                 (AGORA - 400,))
        r = painel.api(60)
        self.assertEqual(r["quedas"][0]["fim"], AGORA - 390)
        self.assertEqual(r["falhas"], {"n": 1, "seg": 10})

    def test_queda_em_andamento_conta_ate_agora(self):
        self.amostra(AGORA - 200)
        for e in (AGORA - 100, AGORA - 50, AGORA - 1):
            self.amostra(e, status="falha_lan")
        self.sql("INSERT INTO outages (status, start_ts, start_epoch) VALUES ('falha_lan', 't', ?)",
                 (AGORA - 100,))
        r = painel.api(60)
        self.assertIsNone(r["quedas"][0]["fim"])
        self.assertEqual(r["falhas"], {"n": 1, "seg": 100})

    def test_falhas_recortadas_ao_periodo(self):
        self.amostra(AGORA - 1)
        self.queda(AGORA - 5000, AGORA - 4000)      # fora do período
        self.queda(AGORA - 1000, AGORA - 300)       # começa antes de desde (10 min = 600 s)
        self.queda(AGORA - 200, AGORA - 150)        # inteira dentro
        r = painel.api(10)
        self.assertEqual(r["falhas"], {"n": 2, "seg": 300 + 50})
        self.assertEqual(len(r["quedas"]), 2)


class ResumoTest(ApiBase):
    def test_banco_vazio(self):
        r = painel.api(60)
        self.assertEqual(r["pontos"], [])
        self.assertIsNone(r["atual"])
        self.assertEqual(r["recentes"], [])
        self.assertIsNone(r["inicio_atual"])
        self.assertIsNone(r["ultima_queda"])
        self.assertEqual(r["falhas"], {"n": 0, "seg": 0})

    def test_atual_e_recentes_mais_novo_primeiro_limitados_a_12(self):
        for i in range(15):
            self.amostra(AGORA - 150 + i * 5, status="degradado" if i == 14 else "ok")
        r = painel.api(60)
        self.assertEqual(r["atual"], {"epoch": AGORA - 80, "status": "degradado"})
        self.assertEqual(len(r["recentes"]), 12)
        self.assertEqual(r["recentes"][0], "degradado")
        self.assertEqual(set(r["recentes"][1:]), {"ok"})

    def test_ok_sem_inicio_atual_e_com_ultima_queda(self):
        self.amostra(AGORA - 30, status="falha_dns")
        self.amostra(AGORA - 20)
        self.amostra(AGORA - 10)
        self.queda(AGORA - 30, AGORA - 20, status="falha_dns")
        r = painel.api(60)
        self.assertIsNone(r["inicio_atual"])
        self.assertEqual(r["ultima_queda"], AGORA - 30)

    def test_degradado_nao_conta_como_queda(self):
        self.amostra(AGORA - 10, status="degradado")
        self.assertIsNone(painel.api(60)["ultima_queda"])

    def test_inicio_atual_e_primeira_amostra_da_sequencia_em_queda(self):
        self.amostra(AGORA - 50)
        self.amostra(AGORA - 40, status="falha_lan")
        self.amostra(AGORA - 30, status="falha_lan")
        self.amostra(AGORA - 20, status="falha_lan")
        self.sql("INSERT INTO outages (status, start_ts, start_epoch) VALUES ('falha_lan', 't', ?)", (AGORA - 40,))
        r = painel.api(60)
        self.assertEqual(r["atual"]["status"], "falha_lan")
        self.assertEqual(r["inicio_atual"], AGORA - 40)
        self.assertEqual(r["ultima_queda"], AGORA - 20)

    def test_inicio_atual_sem_amostra_anterior_diferente(self):
        self.amostra(AGORA - 20, status="falha_lan")
        self.amostra(AGORA - 10, status="falha_lan")
        self.assertEqual(painel.api(60)["inicio_atual"], AGORA - 20)

    def test_resumo_so_conta_o_periodo(self):
        self.amostra(AGORA - 5000)
        self.amostra(AGORA - 10)
        self.assertEqual(painel.api(10)["resumo"], [{"status": "ok", "n": 1}])


class IsolamentoTest(ApiBase):
    def test_api_usa_o_banco_temporario(self):
        self.assertEqual(painel.DB, self.db)
        self.assertNotEqual(os.path.abspath(painel.DB), os.path.abspath(monitor.DB_PATH))


class BancoTest(ApiBase):
    def test_bytes_soma_principal_wal_e_shm(self):
        for sufixo, n in (("-wal", 1000), ("-shm", 500)):
            with open(self.db + sufixo, "wb") as f:
                f.write(b"x" * n)
        r = painel.api(60)
        esperado = sum(os.path.getsize(self.db + s) for s in ("", "-wal", "-shm") if os.path.exists(self.db + s))
        self.assertEqual(r["banco"]["bytes"], esperado)
        self.assertGreaterEqual(r["banco"]["bytes"], os.path.getsize(self.db) + 1500)

    def test_sem_wal_nao_quebra(self):
        for s in ("-wal", "-shm"):
            if os.path.exists(self.db + s):
                os.remove(self.db + s)
        self.assertEqual(painel.api(60)["banco"]["bytes"], os.path.getsize(self.db))

    def test_por_dia_nulo_com_menos_de_1h(self):
        self.amostra(AGORA - 1800)
        self.assertIsNone(painel.api(60)["banco"]["por_dia"])

    def test_por_dia_nulo_sem_amostras(self):
        self.assertIsNone(painel.api(60)["banco"]["por_dia"])

    def test_por_dia_usa_so_arquivo_principal(self):
        self.amostra(AGORA - 2 * 86400)
        with open(self.db + "-wal", "wb") as f:
            f.write(b"x" * 100000)
        b = painel.api(60)["banco"]
        self.assertAlmostEqual(b["por_dia"], os.path.getsize(self.db) / 2)


class DiasTest(ApiBase):
    def dia(self, r, d):
        return next(x for x in r["dias"] if x["dia"] == d.isoformat())

    def test_sempre_30_dias_em_ordem_terminando_hoje(self):
        dias = painel.api(60)["dias"]
        self.assertEqual(len(dias), 30)
        self.assertEqual([x["dia"] for x in dias],
                         [(HOJE - timedelta(days=i)).isoformat() for i in range(29, -1, -1)])
        self.assertEqual({(x["n"], x["fora"], x["quedas"]) for x in dias}, {(0, 0, 0)})

    def test_conta_amostras_e_fora_por_dia_local(self):
        ontem, antes = HOJE - timedelta(days=1), HOJE - timedelta(days=10)
        for s in ("ok", "degradado", "falha_internet"):
            self.amostra(meia_noite(HOJE) + 60, status=s)
        self.amostra(meia_noite(ontem) + 1, status="falha_lan")
        self.amostra(meia_noite(ontem) + 86399, status="sem_wifi")
        self.amostra(meia_noite(antes) + 3600, status="degradado")
        r = painel.api(60)
        self.assertEqual(self.dia(r, HOJE), {"dia": HOJE.isoformat(), "n": 3, "fora": 1, "quedas": 0})
        self.assertEqual((self.dia(r, ontem)["n"], self.dia(r, ontem)["fora"]), (2, 2))
        self.assertEqual((self.dia(r, antes)["n"], self.dia(r, antes)["fora"]), (1, 0))
        self.assertEqual(sum(x["n"] for x in r["dias"]), 6)

    def test_dia_vem_do_ts_e_nao_do_epoch(self):
        # ts gravado num fuso diferente do painel: vale o prefixo do ts
        ontem = HOJE - timedelta(days=1)
        self.sql("INSERT INTO checks (ts, epoch, status) VALUES (?, ?, 'ok')",
                 (ontem.isoformat() + "T23:59:00", meia_noite(HOJE) + 1800))
        r = painel.api(60)
        self.assertEqual(self.dia(r, ontem)["n"], 1)
        self.assertEqual(self.dia(r, HOJE)["n"], 0)

    def test_amostras_com_mais_de_30_dias_ficam_fora(self):
        self.amostra(meia_noite(HOJE - timedelta(days=30)) + 10)
        self.assertEqual(sum(x["n"] for x in painel.api(60)["dias"]), 0)

    def test_quedas_contam_pelo_dia_de_inicio(self):
        ontem = HOJE - timedelta(days=1)
        self.queda(meia_noite(HOJE) - 60, meia_noite(HOJE) + 600)   # começa ontem, termina hoje
        self.queda(meia_noite(HOJE) + 900, meia_noite(HOJE) + 960)
        self.queda(meia_noite(HOJE) + 1900, meia_noite(HOJE) + 1960, status="falha_dns")
        r = painel.api(60)
        self.assertEqual(self.dia(r, ontem)["quedas"], 1)
        self.assertEqual(self.dia(r, HOJE)["quedas"], 2)

    def test_nao_depende_do_periodo(self):
        self.amostra(meia_noite(HOJE - timedelta(days=5)) + 10)
        self.assertEqual(painel.api(60)["dias"], painel.api(10080)["dias"])


class CacheDiasTest(ApiBase):
    def espiar(self):
        espia = mock.patch.object(painel, "dias_contados", wraps=painel.dias_contados).start()
        self.addCleanup(mock.patch.stopall)
        return espia

    def test_segunda_chamada_so_consulta_hoje(self):
        self.amostra(meia_noite(HOJE - timedelta(days=3)) + 10)
        primeira = painel.api(60)["dias"]
        espia = self.espiar()
        self.assertEqual(painel.api(60)["dias"], primeira)
        self.assertEqual([c.args[1:] for c in espia.call_args_list], [(HOJE, HOJE)])

    def test_dia_fechado_nao_e_reconsultado(self):
        d = HOJE - timedelta(days=3)
        self.amostra(meia_noite(d) + 10)
        painel.api(60)
        self.amostra(meia_noite(d) + 20)       # amostra atrasada num dia fechado: fica desatualizado (aceito)
        r = painel.api(60)["dias"]
        self.assertEqual(next(x for x in r if x["dia"] == d.isoformat())["n"], 1)

    def test_amostras_novas_de_hoje_mudam_so_hoje(self):
        self.amostra(meia_noite(HOJE - timedelta(days=1)) + 10)
        antes = painel.api(60)["dias"]
        self.amostra(meia_noite(HOJE) + 10, status="falha_lan")
        depois = painel.api(60)["dias"]
        self.assertEqual(antes[:-1], depois[:-1])
        self.assertEqual((depois[-1]["n"], depois[-1]["fora"]), (1, 1))

    def test_virada_do_dia_anda_a_janela_e_guarda_o_dia_que_fechou(self):
        self.amostra(meia_noite(HOJE) + 10)
        antes = painel.api(60)["dias"]
        amanha = AGORA + 86400
        espia = self.espiar()
        with mock.patch.object(painel.time, "time", return_value=amanha):
            depois = painel.api(60)["dias"]
            self.assertEqual(depois[:-2], antes[1:-1])
            self.assertEqual(depois[-2], {"dia": HOJE.isoformat(), "n": 1, "fora": 0, "quedas": 0})
            self.assertEqual(depois[-1]["dia"], (HOJE + timedelta(days=1)).isoformat())
            self.assertEqual([c.args[1:] for c in espia.call_args_list],
                             [(HOJE, HOJE), (HOJE + timedelta(days=1),) * 2])
            espia.reset_mock()
            painel.api(60)
            self.assertEqual(len(espia.call_args_list), 1)
        self.assertNotIn((HOJE - timedelta(days=29)).isoformat(), painel._dias_fechados)

    def test_chamadas_simultaneas(self):
        for i in range(5):
            self.amostra(meia_noite(HOJE - timedelta(days=i + 1)) + 10)
        res, erros = [], []

        def chama():
            try:
                res.append(painel.api(60)["dias"])
            except Exception as e:      # pragma: no cover
                erros.append(e)
        ts = [threading.Thread(target=chama) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(erros, [])
        self.assertEqual(len(res), 8)
        self.assertTrue(all(r == res[0] for r in res))
        self.assertEqual(sum(x["n"] for x in res[0]), 5)


def salto(n, ip=None, ms=None):
    return {"n": n, "ip": ip, "ms": ms}


class FraseRotaTest(unittest.TestCase):
    def f(self, saltos, ultimo, erro=None):
        return painel.frase_rota(saltos, ultimo, erro, "1.1.1.1")

    def test_nenhum_salto_respondeu(self):
        self.assertIn("parou no seu roteador", self.f([salto(1), salto(2)], None))

    def test_sem_saltos(self):
        self.assertIn("parou no seu roteador", self.f([], None))

    def test_so_o_gateway(self):
        self.assertIn("parou no seu roteador", self.f([salto(1, "192.168.0.1", 2.0), salto(2)], 1))

    def test_salto_depois_do_gateway_e_operadora_com_numero_do_ponto(self):
        saltos = [salto(1, "192.168.0.1", 2.0), salto(2), salto(3, "189.4.103.41", 14.0), salto(4)]
        frase = self.f(saltos, 3)
        self.assertIn("rede da operadora", frase)
        self.assertIn("3º ponto", frase)

    def test_chegou_ao_destino(self):
        frase = self.f([salto(1, "192.168.0.1", 2.0), salto(2, "1.1.1.1", 9.0)], 2)
        self.assertNotIn("operadora", frase)
        self.assertIn("chegou", frase)

    def test_erro_sem_frase(self):
        self.assertIsNone(self.f([], None, "tempo esgotado"))


class RotaApiTest(ApiBase):
    def rota(self, oid, saltos, ultimo, erro=None):
        self.sql("INSERT INTO rotas (outage_id, ts, epoch, alvo, saltos, ultimo_ok, saida, erro) "
                 "VALUES (?, 't', ?, '1.1.1.1', ?, ?, 'x', ?)", (oid, AGORA - 100, json.dumps(saltos), ultimo, erro))

    def test_queda_com_rota(self):
        self.amostra(AGORA - 1)
        oid = self.queda(AGORA - 200, AGORA - 100, status="falha_internet")
        saltos = [salto(1, "192.168.0.1", 2.0), salto(2, "10.0.0.1", 9.0), salto(3)]
        self.rota(oid, saltos, 2)
        q = painel.api(60)["quedas"][0]
        self.assertEqual(q["id"], oid)
        self.assertEqual(q["rota"]["saltos"], saltos)
        self.assertIn("2º ponto", q["rota"]["frase"])

    def test_queda_sem_rota_vem_null(self):
        self.amostra(AGORA - 1)
        oid = self.queda(AGORA - 200, AGORA - 100)
        q = painel.api(60)["quedas"][0]
        self.assertEqual(q["id"], oid)
        self.assertIsNone(q["rota"])

    def test_rota_com_erro_sem_frase(self):
        self.amostra(AGORA - 1)
        oid = self.queda(AGORA - 200, AGORA - 100, status="falha_internet")
        self.rota(oid, [], None, erro="tempo esgotado")
        self.assertIsNone(painel.api(60)["quedas"][0]["rota"]["frase"])


class BancoAntigoTest(ApiBase):
    """Banco criado antes das tabelas novas: o painel (somente leitura) não pode criá-las e não pode quebrar."""

    def setUp(self):
        super().setUp()
        con = sqlite3.connect(self.db)
        novas = [n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                 if n not in ("checks", "wifi_info", "outages", "runs")]
        for n in novas:
            con.execute(f"DROP TABLE {n}")
        con.commit()
        con.close()

    def test_api_funciona_sem_as_tabelas_novas(self):
        self.amostra(AGORA - 10, status="degradado")
        self.queda(AGORA - 200, AGORA - 100, status="falha_internet")
        r = painel.api(60)
        self.assertIsNone(r["quedas"][0]["rota"])
        self.assertEqual(r["recentes"], ["degradado"])
        self.assertEqual(r["velocidade"], [])
        self.assertIsNone(r["velocidade_ultimo"])
        self.assertIsNone(r["velocidade_completo"])

    def test_velocidade_sem_a_tabela_de_completos(self):
        con = sqlite3.connect(self.db)
        con.executescript(monitor.SCHEMA)
        con.execute("DROP TABLE velocidade_completo")
        con.execute("INSERT INTO velocidade (ts, epoch, fim_epoch, down_mbps, up_mbps) VALUES (?, ?, ?, 300, 90)",
                    (iso(AGORA - 600), AGORA - 600, AGORA - 580))
        con.commit()
        con.close()
        r = painel.api(60)
        self.assertFalse(r["velocidade"][0]["completo"])
        self.assertIsNone(r["velocidade_completo"])


class VelocidadeBase(ApiBase):
    def velo(self, epoch, fim=None, down=None, up=None, erro=None):
        if fim is None and down is not None:
            fim = epoch + 40
        return self.sql_id("INSERT INTO velocidade (ts, epoch, fim_epoch, down_mbps, up_mbps, erro) VALUES (?, ?, ?, ?, ?, ?)",
                           (iso(epoch), epoch, fim, down, up, erro))

    def carga(self, vid, ocioso, down, up):
        self.sql("INSERT INTO latencia_carga (velocidade_id, ocioso_ms, down_ms, up_ms, down_perda, up_perda) "
                 "VALUES (?, ?, ?, ?, 0, 0)", (vid, ocioso, down, up))


class VelocidadeApiTest(VelocidadeBase):
    def test_testes_do_periodo_em_ordem(self):
        self.velo(AGORA - 5000, down=50.0, up=10.0)          # fora do período de 60 min
        self.velo(AGORA - 1800, down=300.0, up=95.0)
        self.velo(AGORA - 600, down=280.0, up=90.0)
        v = painel.api(60)["velocidade"]
        self.assertEqual([(t["epoch"], t["fim"], t["down"], t["up"], t["erro"]) for t in v],
                         [(AGORA - 1800, AGORA - 1760, 300.0, 95.0, None), (AGORA - 600, AGORA - 560, 280.0, 90.0, None)])

    def test_ultimo_bem_sucedido_mesmo_fora_do_periodo(self):
        self.velo(AGORA - 9000, down=40.0, up=8.0)
        self.velo(AGORA - 7200, down=50.0, up=10.0)
        self.velo(AGORA - 600, fim=AGORA - 590, erro="HTTP 403")
        r = painel.api(60)
        self.assertEqual((r["velocidade_ultimo"]["epoch"], r["velocidade_ultimo"]["down"]), (AGORA - 7200, 50.0))
        self.assertEqual(len(r["velocidade"]), 1)

    def test_marca_teste_completo_e_traz_o_ultimo_mesmo_fora_do_periodo(self):
        antigo = self.velo(AGORA - 9000, down=590.0, up=95.0)
        self.velo(AGORA - 7200, down=200.0, up=90.0)                  # rápido, mais recente
        agora = self.velo(AGORA - 600, down=300.0, up=95.0)
        falhou = self.velo(AGORA - 300, fim=AGORA - 280, erro="HTTP 403")
        for vid in (antigo, agora, falhou):
            self.sql("INSERT INTO velocidade_completo (velocidade_id, fluxos, segundos) VALUES (?, 4, 10)", (vid,))
        self.sql("DELETE FROM velocidade_completo WHERE velocidade_id = ?", (agora,))
        r = painel.api(60)
        self.assertEqual([(t["epoch"], t["completo"]) for t in r["velocidade"]],
                         [(AGORA - 600, False), (AGORA - 300, True)])
        self.assertEqual((r["velocidade_completo"]["epoch"], r["velocidade_completo"]["down"]), (AGORA - 9000, 590.0))
        self.assertTrue(r["velocidade_completo"]["completo"])

    def test_teste_com_erro_vem_com_erro_e_sem_mbps(self):
        self.velo(AGORA - 600, fim=AGORA - 570, down=280.0, erro="upload passou de 30 s")
        r = painel.api(60)
        t = r["velocidade"][0]
        self.assertEqual((t["erro"], t["down"], t["up"]), ("upload passou de 30 s", None, None))
        self.assertIsNone(r["velocidade_ultimo"])

    def test_teste_em_andamento_aparece_sem_fim(self):
        self.velo(AGORA - 20)
        t = painel.api(60)["velocidade"][0]
        self.assertEqual((t["fim"], t["down"], t["erro"]), (None, None, None))

    def test_sem_testes(self):
        r = painel.api(60)
        self.assertEqual((r["velocidade"], r["velocidade_ultimo"]), ([], None))

    def test_carga_preenchida_ou_nula(self):
        com = self.velo(AGORA - 1800, down=300.0, up=95.0)
        self.velo(AGORA - 600, down=280.0, up=90.0)
        self.carga(com, 20.0, 140.0, 60.0)
        v = painel.api(60)["velocidade"]
        self.assertEqual(v[0]["carga"], {"ocioso": 20.0, "down": 140.0, "up": 60.0,
                                         "nota": {"nome": "Razoável", "cat": "warning", "acrescimo": 120.0, "fase": "down"}})
        self.assertIsNone(v[1]["carga"])

    def test_ultimo_traz_carga(self):
        vid = self.velo(AGORA - 7200, down=50.0, up=10.0)
        self.carga(vid, 20.0, 30.0, 45.0)
        nota = painel.api(60)["velocidade_ultimo"]["carga"]["nota"]
        self.assertEqual((nota["nome"], nota["fase"], nota["acrescimo"]), ("Ótimo", "up", 25.0))


class NotaCargaTest(unittest.TestCase):
    def test_limites(self):
        casos = {0: "Ótimo", 29: "Ótimo", 30: "Bom", 59: "Bom", 60: "Razoável", 199: "Razoável", 200: "Ruim", 500: "Ruim"}
        for ms, nome in casos.items():
            self.assertEqual(painel.classificar_acrescimo(ms)[0], nome, ms)

    def test_cores_pelos_tokens_de_status(self):
        self.assertEqual([painel.classificar_acrescimo(ms)[1] for ms in (10, 40, 100, 300)],
                         ["good", "good", "warning", "critical"])

    def test_pior_fase_menos_parado(self):
        self.assertEqual(painel.nota_carga(20.0, 50.0, 230.0),
                         {"nome": "Ruim", "cat": "critical", "acrescimo": 210.0, "fase": "up"})

    def test_fase_faltando_usa_a_outra(self):
        self.assertEqual(painel.nota_carga(20.0, None, 60.0)["fase"], "up")

    def test_sem_parado_ou_sem_fases_nao_tem_nota(self):
        self.assertIsNone(painel.nota_carga(None, 50.0, 60.0))
        self.assertIsNone(painel.nota_carga(20.0, None, None))

    def test_mais_rapido_em_uso_conta_como_zero(self):
        self.assertEqual(painel.nota_carga(40.0, 30.0, 35.0)["acrescimo"], 0.0)


class JanelaTesteTest(VelocidadeBase):
    """O pico de latência do próprio teste de velocidade não faz o resumo dizer "instável"."""

    def test_degradado_dentro_da_janela_nao_entra_em_recentes(self):
        for i in range(12):
            self.amostra(AGORA - 120 + i * 5)                       # ok antes do teste
        self.velo(AGORA - 50, fim=AGORA - 10, down=100.0, up=10.0)
        for e in range(int(AGORA - 50), int(AGORA - 5), 5):
            self.amostra(e, status="degradado")
        r = painel.api(60)
        self.assertNotIn("degradado", r["recentes"])
        self.assertEqual(len(r["recentes"]), 12)

    def test_teste_em_andamento_tambem_conta(self):
        self.amostra(AGORA - 60)
        self.velo(AGORA - 30)
        for e in (AGORA - 25, AGORA - 20, AGORA - 15, AGORA - 10):
            self.amostra(e, status="degradado")
        self.assertEqual(painel.api(60)["recentes"], ["ok"])

    def test_degradado_fora_da_janela_continua(self):
        self.velo(AGORA - 600, fim=AGORA - 560, down=100.0, up=10.0)
        for e in (AGORA - 20, AGORA - 15, AGORA - 10):
            self.amostra(e, status="degradado")
        self.assertEqual(painel.api(60)["recentes"], ["degradado"] * 3)

    def test_queda_dentro_da_janela_continua(self):
        self.velo(AGORA - 30)
        self.amostra(AGORA - 20, status="degradado")
        self.amostra(AGORA - 10, status="falha_internet")
        r = painel.api(60)
        self.assertEqual(r["recentes"], ["falha_internet"])
        self.assertEqual(r["atual"]["status"], "falha_internet")

    def test_resumo_e_pontos_nao_mudam(self):
        self.velo(AGORA - 30)
        self.amostra(AGORA - 20, status="degradado")
        r = painel.api(60)
        self.assertEqual(r["resumo"], [{"status": "degradado", "n": 1}])
        self.assertEqual([p["status"] for p in r["pontos"]], ["degradado"])
        self.assertEqual(r["atual"]["status"], "degradado")


class PeriodoTest(unittest.TestCase):
    def test_ultimos_minutos(self):
        self.assertEqual(painel.periodo(AGORA, 60), (AGORA - 3600, AGORA))

    def test_minutos_no_minimo_1(self):
        self.assertEqual(painel.periodo(AGORA, 0), (AGORA - 60, AGORA))

    def test_intervalo_de_datas(self):
        self.assertEqual(painel.periodo(AGORA, de=AGORA - 900, ate=AGORA - 300), (AGORA - 900, AGORA - 300))

    def test_fim_no_futuro_vira_agora(self):
        self.assertEqual(painel.periodo(AGORA, de=AGORA - 900, ate=AGORA + 999), (AGORA - 900, AGORA))

    def test_periodo_longo_e_cortado_no_comeco(self):
        ate = AGORA - 100
        self.assertEqual(painel.periodo(AGORA, de=ate - painel.MAX_PERIODO - 500, ate=ate), (ate - painel.MAX_PERIODO, ate))
        self.assertEqual(painel.periodo(AGORA, 10 ** 9)[0], AGORA - painel.MAX_PERIODO)

    def test_invalidos(self):
        for de, ate in ((AGORA - 100, AGORA - 200), (AGORA - 100, AGORA - 100), (AGORA + 10, AGORA + 20),
                        (AGORA - 100, None), (None, AGORA), (float("nan"), AGORA), (AGORA - 100, float("nan"))):
            with self.subTest(de=de, ate=ate), self.assertRaises(ValueError):
                painel.periodo(AGORA, de=de, ate=ate)


class IntervaloApiTest(VelocidadeBase):
    """Período [de, ate) no passado: só o que está dentro dele entra; o estado atual continua sendo de agora."""
    DE, ATE = AGORA - 3000, AGORA - 2000

    def test_pontos_resumo_e_velocidade_so_do_intervalo(self):
        for e in (self.DE - 5, self.DE, self.ATE - 5, self.ATE, AGORA - 10):
            self.amostra(e, gw=1.0)
        self.velo(self.DE - 100, down=1.0, up=1.0)
        dentro = self.velo(self.DE + 100, down=50.0, up=10.0)
        self.velo(self.ATE + 100, down=2.0, up=2.0)
        r = painel.api(de=self.DE, ate=self.ATE)
        self.assertEqual([p["epoch"] for p in r["pontos"]], [self.DE, self.ATE - 5])
        self.assertEqual(r["resumo"], [{"status": "ok", "n": 2}])
        self.assertEqual([t["epoch"] for t in r["velocidade"]], [self.DE + 100])
        self.assertEqual(r["velocidade_ultimo"]["down"], 2.0)        # o último continua sendo o mais recente
        self.assertEqual(r["atual"]["epoch"], AGORA - 10)            # estado atual não segue o período
        self.assertEqual((r["de"], r["ate"]), (self.DE, self.ATE))
        self.assertTrue(dentro)

    def test_resposta_traz_periodo_tambem_em_minutos(self):
        r = painel.api(10)
        self.assertEqual((r["de"], r["ate"]), (AGORA - 600, AGORA))

    def test_queda_depois_do_fim_fica_fora(self):
        self.queda(self.ATE + 100, self.ATE + 200)
        self.sql("INSERT INTO outages (status, start_ts, start_epoch) VALUES (?, ?, ?)",
                 ("falha_lan", iso(self.ATE + 300), self.ATE + 300))   # aberta, sem fim
        r = painel.api(de=self.DE, ate=self.ATE)
        self.assertEqual(r["quedas"], [])
        self.assertEqual(r["falhas"], {"n": 0, "seg": 0})

    def test_queda_que_atravessa_o_fim_e_recortada(self):
        self.queda(self.ATE - 100, self.ATE + 500)
        r = painel.api(de=self.DE, ate=self.ATE)
        self.assertEqual(r["falhas"], {"n": 1, "seg": 100})
        self.assertEqual(r["quedas"][0]["fim"], self.ATE + 500)    # a lista mostra a duração real

    def test_queda_que_cobre_o_intervalo_todo(self):
        self.queda(self.DE - 100, self.ATE + 100)
        self.assertEqual(painel.api(de=self.DE, ate=self.ATE)["falhas"]["seg"], 1000)

    def test_baldes_pelo_tamanho_do_intervalo(self):
        for i in range(painel.MAX_PONTOS + 1):
            self.amostra(self.DE + i, gw=1.0)
        r = painel.api(de=self.DE, ate=self.ATE)
        self.assertEqual(r["passo"], 1000 / painel.MAX_PONTOS)


class HandlerTest(ApiBase):
    """Parâmetros da /api pela URL: inválido dá 400, não 500."""

    def get(self, caminho):
        h = painel.H.__new__(painel.H)
        h.path, h.wfile = caminho, io.BytesIO()
        enviado = {}
        h.send_error = lambda cod, msg=None: enviado.update(cod=cod, msg=msg)
        h.send_response = lambda cod: enviado.update(cod=cod)
        h.send_header = h.end_headers = lambda *a: None
        h.do_GET()
        return enviado["cod"], h.wfile.getvalue()

    def test_min_continua_funcionando(self):
        cod, corpo = self.get("/api?min=1")
        self.assertEqual(cod, 200)
        self.assertEqual(json.loads(corpo)["de"], AGORA - 60)

    def test_de_e_ate(self):
        cod, corpo = self.get(f"/api?de={AGORA - 900}&ate={AGORA - 300}")
        self.assertEqual(cod, 200)
        self.assertEqual(json.loads(corpo)["ate"], AGORA - 300)

    def test_invalidos_dao_400(self):
        for q in ("min=abc", "de=x&ate=1", f"de={AGORA}", f"de={AGORA - 10}&ate={AGORA - 20}"):
            with self.subTest(q=q):
                self.assertEqual(self.get("/api?" + q)[0], 400)


if __name__ == "__main__":
    unittest.main()


class TesteAgoraTest(VelocidadeBase):
    """Botão "Fazer teste completo agora": pedido por arquivo e estado do teste em andamento."""

    def test_rodando_traz_o_teste_aberto_recente(self):
        self.velo(AGORA - 3000)                                    # aberto há muito tempo: interrompido
        vid = self.velo(AGORA - 20)
        self.sql("INSERT INTO velocidade_completo (velocidade_id, fluxos, segundos) VALUES (?, 4, 10)", (vid,))
        self.assertEqual(painel.api(60)["velocidade_rodando"], {"epoch": AGORA - 20, "completo": True})

    def test_nada_rodando(self):
        self.velo(AGORA - 60, down=500.0, up=90.0)
        self.velo(AGORA - 30, fim=AGORA - 25, erro="HTTP 403")
        self.assertIsNone(painel.api(60)["velocidade_rodando"])

    def test_pedido_aparece_e_expira(self):
        self.assertFalse(painel.api(60)["teste_pedido"])
        painel.pedir_teste()
        os.utime(self.pedido, (AGORA - 10, AGORA - 10))
        self.assertTrue(painel.api(60)["teste_pedido"])
        os.utime(self.pedido, (AGORA - 700, AGORA - 700))
        self.assertFalse(painel.api(60)["teste_pedido"])

    def test_post_exige_cabecalho_e_cria_o_pedido(self):
        srv = painel.ThreadingHTTPServer(("127.0.0.1", 0), painel.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_address[1]}/teste-completo"
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"))
        self.assertEqual(e.exception.code, 403)
        self.assertFalse(os.path.exists(self.pedido))
        r = urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST", headers={"X-Pedido": "1"}))
        self.assertEqual(r.status, 202)
        self.assertTrue(os.path.exists(self.pedido))

    def test_um_teste_completo_manual_por_hora(self):
        self.assertIsNone(painel.api(60)["teste_manual_apos"])
        vid = self.velo(AGORA - 600, fim=AGORA - 570, erro="HTTP Error 429: Too Many Requests")   # falho também conta
        self.sql("INSERT INTO velocidade_completo (velocidade_id, fluxos, segundos) VALUES (?, 4, 10)", (vid,))
        self.assertEqual(painel.api(60)["teste_manual_apos"], AGORA - 600 + painel.MANUAL_INTERVALO)
        self.sql("UPDATE velocidade SET epoch = ? WHERE id = ?", (AGORA - painel.MANUAL_INTERVALO - 1, vid))
        self.assertIsNone(painel.api(60)["teste_manual_apos"])

    def test_post_recusado_logo_depois_de_um_completo(self):
        vid = self.velo(AGORA - 600, down=590.0, up=90.0)
        self.sql("INSERT INTO velocidade_completo (velocidade_id, fluxos, segundos) VALUES (?, 4, 10)", (vid,))
        srv = painel.ThreadingHTTPServer(("127.0.0.1", 0), painel.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/teste-completo", data=b"",
                                     method="POST", headers={"X-Pedido": "1"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 429)
        self.assertFalse(os.path.exists(self.pedido))
