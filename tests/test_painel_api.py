import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import monitor
import painel

AGORA = 1_000_000.0


class ApiBase(unittest.TestCase):
    """Banco SQLite temporário com o SCHEMA do monitor; o DB do painel e o relógio são trocados."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = os.path.join(self.dir, "teste.db")
        con = sqlite3.connect(self.db)
        con.executescript(monitor.SCHEMA)
        con.close()
        for alvo in (mock.patch.object(painel, "DB", self.db),
                     mock.patch.object(painel.time, "time", return_value=AGORA)):
            alvo.start()
            self.addCleanup(alvo.stop)

    def sql(self, q, args=()):
        con = sqlite3.connect(self.db)
        with con:
            con.execute(q, args)
        con.close()

    def amostra(self, epoch, status="ok", gw=None, dbm=None):
        self.sql("INSERT INTO checks (ts, epoch, status, gw_avg_ms, wifi_dbm) VALUES ('t', ?, ?, ?, ?)",
                 (epoch, status, gw, dbm))

    def queda(self, ini, fim, status="falha_lan"):
        self.sql("INSERT INTO outages (status, start_ts, start_epoch, end_ts, end_epoch) VALUES (?, 't', ?, 't', ?)",
                 (status, ini, fim))


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


if __name__ == "__main__":
    unittest.main()
