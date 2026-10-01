import importlib
import os
import unittest

import monitor

NORMAL = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.

--- 1.1.1.1 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 603ms
rtt min/avg/max/mdev = 10.100/12.500/15.250/2.100 ms
"""
TOTAL_LOSS = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.

--- 1.1.1.1 ping statistics ---
4 packets transmitted, 0 received, 100% packet loss, time 3070ms
"""
PARTIAL = """--- 8.8.8.8 ping statistics ---
4 packets transmitted, 3 received, 25% packet loss, time 600ms
rtt min/avg/max/mdev = 9.000/10.000/11.000/1.000 ms
"""


def p(loss=0.0, avg=10.0):
    return {"loss": loss, "avg": avg, "max": avg, "jitter": 1.0}


class ParsePingTest(unittest.TestCase):
    def test_saida_normal(self):
        self.assertEqual(monitor.parse_ping(NORMAL),
                         {"loss": 0.0, "avg": 12.5, "max": 15.25, "jitter": 2.1})

    def test_perda_parcial(self):
        r = monitor.parse_ping(PARTIAL)
        self.assertEqual((r["loss"], r["avg"]), (25.0, 10.0))

    def test_perda_total_sem_rtt(self):
        self.assertEqual(monitor.parse_ping(TOTAL_LOSS),
                         {"loss": 100.0, "avg": None, "max": None, "jitter": None})

    def test_texto_vazio(self):
        self.assertEqual(monitor.parse_ping(""),
                         {"loss": 100.0, "avg": None, "max": None, "jitter": None})


class ClassifyTest(unittest.TestCase):
    def c(self, iface="wlan0", gw=None, cf=None, gg=None, dns=1):
        return monitor.classify(iface, gw or p(), cf or p(), gg or p(), dns)

    def test_ok(self):
        self.assertEqual(self.c(), "ok")

    def test_sem_wifi(self):
        self.assertEqual(self.c(iface=None), "sem_wifi")

    def test_falha_lan(self):
        self.assertEqual(self.c(gw=p(100, None)), "falha_lan")

    def test_falha_internet_exige_os_dois_alvos(self):
        self.assertEqual(self.c(cf=p(100, None), gg=p(100, None)), "falha_internet")

    def test_um_alvo_com_100_de_perda_e_ok_hoje(self):
        # Caracterização do comportamento atual (min das perdas = 0); a spec
        # 02-degradado-dois-alvos deve mudar isto.
        self.assertEqual(self.c(cf=p(100, None)), "ok")

    def test_falha_dns(self):
        self.assertEqual(self.c(dns=0), "falha_dns")

    def test_degradado_perda_gateway(self):
        self.assertEqual(self.c(gw=p(25)), "degradado")

    def test_degradado_perda_internet(self):
        self.assertEqual(self.c(cf=p(25), gg=p(50)), "degradado")

    def test_degradado_latencia_alta(self):
        self.assertEqual(self.c(cf=p(0, 151)), "degradado")

    def test_latencia_no_limite_e_ok(self):
        self.assertEqual(self.c(cf=p(0, 150)), "ok")

    def test_prioridade_sem_wifi_sobre_tudo(self):
        self.assertEqual(self.c(iface=None, gw=p(100, None), dns=0), "sem_wifi")

    def test_prioridade_lan_sobre_internet_e_dns(self):
        self.assertEqual(self.c(gw=p(100, None), cf=p(100, None), gg=p(100, None), dns=0),
                         "falha_lan")

    def test_prioridade_internet_sobre_dns(self):
        self.assertEqual(self.c(cf=p(100, None), gg=p(100, None), dns=0), "falha_internet")

    def test_prioridade_dns_sobre_degradado(self):
        self.assertEqual(self.c(gw=p(25), dns=0), "falha_dns")


class ImportTest(unittest.TestCase):
    def test_importar_nao_toca_no_banco(self):
        def snap():
            try:
                st = os.stat(monitor.DB_PATH)
                return st.st_mtime_ns, st.st_size
            except FileNotFoundError:
                return None
        antes = snap()
        importlib.reload(monitor)
        self.assertEqual(snap(), antes)


if __name__ == "__main__":
    unittest.main()
