import importlib
import io
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

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

    def test_degradado_latencia_alta_nos_dois(self):
        self.assertEqual(self.c(cf=p(0, 151), gg=p(0, 200)), "degradado")

    def test_um_alvo_lento_sozinho_e_ok(self):
        self.assertEqual(self.c(cf=p(0, 200), gg=p(0, 40)), "ok")
        self.assertEqual(self.c(cf=p(0, 40), gg=p(0, 200)), "ok")

    def test_cf_sem_media_e_google_lento_e_degradado(self):
        self.assertEqual(self.c(cf=p(100, None), gg=p(0, 200)), "degradado")

    def test_cf_sem_media_e_google_rapido_e_ok(self):
        self.assertEqual(self.c(cf=p(100, None), gg=p(0, 40)), "ok")

    def test_latencia_no_limite_e_ok(self):
        self.assertEqual(self.c(cf=p(0, 150), gg=p(0, 150)), "ok")

    def test_prioridade_sem_wifi_sobre_tudo(self):
        self.assertEqual(self.c(iface=None, gw=p(100, None), dns=0), "sem_wifi")

    def test_prioridade_lan_sobre_internet_e_dns(self):
        self.assertEqual(self.c(gw=p(100, None), cf=p(100, None), gg=p(100, None), dns=0),
                         "falha_lan")

    def test_prioridade_internet_sobre_dns(self):
        self.assertEqual(self.c(cf=p(100, None), gg=p(100, None), dns=0), "falha_internet")

    def test_prioridade_dns_sobre_degradado(self):
        self.assertEqual(self.c(gw=p(25), dns=0), "falha_dns")


class DnsCheckTest(unittest.TestCase):
    def usa(self, *cmd):
        # DNS_HOST é anexado ao final do comando; "sh -c 'script' _" o recebe como $1
        antigo = monitor.DNS_CMD
        monitor.DNS_CMD = list(cmd)
        self.addCleanup(setattr, monitor, "DNS_CMD", antigo)

    def test_timeout_devolve_falha_dentro_do_limite(self):
        self.usa("sh", "-c", "exec sleep 30", "_")
        monitor_timeout = monitor.DNS_TIMEOUT
        self.addCleanup(setattr, monitor, "DNS_TIMEOUT", monitor_timeout)
        monitor.DNS_TIMEOUT = 1
        t0 = time.monotonic()
        self.assertEqual(monitor.dns_check(), (0, None))
        self.assertLess(time.monotonic() - t0, monitor.DNS_TIMEOUT + 1)

    def test_sucesso(self):
        self.usa("sh", "-c", "echo '142.250.0.1 STREAM google.com'", "_")
        ok, ms = monitor.dns_check()
        self.assertEqual(ok, 1)
        self.assertGreaterEqual(ms, 0)

    def test_codigo_de_saida_diferente_de_zero(self):
        self.usa("sh", "-c", "exit 2", "_")
        self.assertEqual(monitor.dns_check(), (0, None))

    def test_saida_vazia_com_codigo_zero_e_falha(self):
        self.usa("true")
        self.assertEqual(monitor.dns_check(), (0, None))

    def test_comando_inexistente(self):
        self.usa("/nao/existe")
        self.assertEqual(monitor.dns_check(), (0, None))


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


# saídas reais do `tracepath -n -m 15 1.1.1.1` (iputils)
TP_COMPLETO = """ 1?: [LOCALHOST]                      pmtu 1500
 1:  192.168.0.1                                           3.118ms
 1:  192.168.0.1                                           2.905ms
 2:  10.45.0.1                                            12.104ms
 3:  189.4.103.41                                         14.320ms asymm  4
 4:  1.1.1.1                                              15.002ms reached
     Resume: pmtu 1500 hops 4 back 4
"""
TP_NO_REPLY_NO_MEIO = """ 1?: [LOCALHOST]                      pmtu 1500
 1:  192.168.0.1                                          51.046ms
 1:  192.168.0.1                                           8.972ms
 2:  no reply
 3:  189.4.103.41                                        103.868ms
 4:  no reply
 5:  no reply
     Too many hops: pmtu 1500
     Resume: pmtu 1500
"""
TP_SO_GATEWAY = """ 1?: [LOCALHOST]                      pmtu 1500
 1:  192.168.0.1                                           2.512ms
 1:  192.168.0.1                                           2.300ms
 2:  no reply
 3:  no reply
     Too many hops: pmtu 1500
     Resume: pmtu 1500
"""
TP_NENHUM = """ 1?: [LOCALHOST]                      pmtu 1500
 1:  no reply
 2:  no reply
 3:  no reply
     Too many hops: pmtu 1500
     Resume: pmtu 1500
"""


class ParseTracepathTest(unittest.TestCase):
    def test_caminho_completo(self):
        saltos, ultimo = monitor.parse_tracepath(TP_COMPLETO)
        self.assertEqual(saltos, [{"n": 1, "ip": "192.168.0.1", "ms": 3.118},
                                  {"n": 2, "ip": "10.45.0.1", "ms": 12.104},
                                  {"n": 3, "ip": "189.4.103.41", "ms": 14.32},
                                  {"n": 4, "ip": "1.1.1.1", "ms": 15.002}])
        self.assertEqual(ultimo, 4)

    def test_no_reply_no_meio(self):
        saltos, ultimo = monitor.parse_tracepath(TP_NO_REPLY_NO_MEIO)
        self.assertEqual([s["n"] for s in saltos], [1, 2, 3, 4, 5])
        self.assertEqual(saltos[1], {"n": 2, "ip": None, "ms": None})
        self.assertEqual(saltos[2]["ip"], "189.4.103.41")
        self.assertEqual(ultimo, 3)

    def test_so_o_gateway(self):
        saltos, ultimo = monitor.parse_tracepath(TP_SO_GATEWAY)
        self.assertEqual(len(saltos), 3)
        self.assertEqual(ultimo, 1)

    def test_nenhum_salto(self):
        saltos, ultimo = monitor.parse_tracepath(TP_NENHUM)
        self.assertEqual([s["ip"] for s in saltos], [None, None, None])
        self.assertIsNone(ultimo)

    def test_texto_vazio(self):
        self.assertEqual(monitor.parse_tracepath(""), ([], None))


class TracepathTest(unittest.TestCase):
    def usa(self, *cmd):
        antigo = monitor.TRACEPATH_CMD
        monitor.TRACEPATH_CMD = list(cmd)
        self.addCleanup(setattr, monitor, "TRACEPATH_CMD", antigo)

    def test_sucesso(self):
        self.usa("printf", TP_SO_GATEWAY.replace("%", "%%"))
        r = monitor.tracepath("1.1.1.1")
        self.assertEqual((r["ultimo_ok"], r["erro"], len(r["saltos"])), (1, None, 3))
        self.assertIn("LOCALHOST", r["saida"])

    def test_comando_inexistente_vira_erro(self):
        self.usa("/nao/existe")
        r = monitor.tracepath("1.1.1.1")
        self.assertIsNotNone(r["erro"])
        self.assertEqual((r["saltos"], r["ultimo_ok"]), ([], None))

    def test_codigo_de_erro_sem_saltos_vira_erro(self):
        self.usa("sh", "-c", "echo 'tracepath: socket: Operation not permitted' >&2; exit 1", "_")
        r = monitor.tracepath("1.1.1.1")
        self.assertIn("Operation not permitted", r["erro"])

    def test_timeout_vira_erro(self):
        self.usa("sh", "-c", "exec sleep 30", "_")
        antigo = monitor.TRACEPATH_TIMEOUT
        monitor.TRACEPATH_TIMEOUT = 0.5
        self.addCleanup(setattr, monitor, "TRACEPATH_TIMEOUT", antigo)
        r = monitor.tracepath("1.1.1.1")
        self.assertIn("tempo", r["erro"])


class FundoTest(unittest.TestCase):
    def esperar(self, fundo, db=None, limite=2.0):
        fim = time.monotonic() + limite
        while fundo.ocupado("x") and time.monotonic() < fim:
            fundo.colher(db)
            time.sleep(0.01)

    def test_grava_na_thread_que_colhe_quando_termina(self):
        f, gravados, libera = monitor.Fundo(), [], threading.Event()
        f.iniciar("x", lambda: (libera.wait(2), 42)[1], lambda db, r: gravados.append((db, r, threading.get_ident())))
        f.colher("db")
        self.assertTrue(f.ocupado("x"))
        self.assertEqual(gravados, [])
        libera.set()
        self.esperar(f, "db")
        self.assertFalse(f.ocupado("x"))
        self.assertEqual(gravados, [("db", 42, threading.get_ident())])

    def test_iniciar_nao_espera_a_tarefa(self):
        f, libera = monitor.Fundo(), threading.Event()
        t0 = time.monotonic()
        f.iniciar("x", lambda: libera.wait(5), lambda db, r: None)
        self.assertLess(time.monotonic() - t0, 0.5)
        libera.set()
        self.esperar(f)

    def test_excecao_na_tarefa_nao_chama_gravar(self):
        f, gravados = monitor.Fundo(), []
        f.iniciar("x", lambda: 1 / 0, lambda db, r: gravados.append(r))
        self.esperar(f)
        self.assertFalse(f.ocupado("x"))
        self.assertEqual(gravados, [])


class GravarRotaTest(unittest.TestCase):
    def test_grava_linha_ligada_a_queda(self):
        db = sqlite3.connect(":memory:")
        db.executescript(monitor.SCHEMA)
        res = {"saltos": [{"n": 1, "ip": "192.168.0.1", "ms": 2.5}], "ultimo_ok": 1, "saida": "x", "erro": None}
        monitor.gravar_rota(db, 7, 100.0, "2026-01-01T00:00:00", "1.1.1.1", res)
        r = db.execute("SELECT outage_id, epoch, ts, alvo, saltos, ultimo_ok, saida, erro FROM rotas").fetchone()
        self.assertEqual(r, (7, 100.0, "2026-01-01T00:00:00", "1.1.1.1",
                             '[{"n": 1, "ip": "192.168.0.1", "ms": 2.5}]', 1, "x", None))


class HoraDeTestarTest(unittest.TestCase):
    INI = 1000.0

    def h(self, agora, ultimo=None, status="ok", a_cada=30):
        return monitor.hora_de_testar(agora, self.INI, ultimo, status, a_cada)

    def test_primeiro_teste_um_minuto_depois_de_iniciar(self):
        self.assertFalse(self.h(self.INI + 59))
        self.assertTrue(self.h(self.INI + 60))

    def test_antes_do_intervalo_nao(self):
        self.assertFalse(self.h(self.INI + 5000, ultimo=self.INI + 5000 - 30 * 60 + 1))

    def test_depois_do_intervalo_sim(self):
        self.assertTrue(self.h(self.INI + 5000, ultimo=self.INI + 5000 - 30 * 60))

    def test_status_de_queda_nao(self):
        for st in ("sem_wifi", "falha_lan", "falha_internet", "falha_dns"):
            self.assertFalse(self.h(self.INI + 9999, status=st), st)

    def test_degradado_pode_testar(self):
        self.assertTrue(self.h(self.INI + 9999, status="degradado"))

    def test_intervalo_zero_nunca(self):
        self.assertFalse(self.h(self.INI + 10 ** 7, a_cada=0))
        self.assertFalse(self.h(self.INI + 10 ** 7, ultimo=self.INI, a_cada=0))


class MbpsTest(unittest.TestCase):
    def test_bytes_por_segundo_em_megabits(self):
        self.assertAlmostEqual(monitor.mbps(25_000_000, 2.0), 100.0)
        self.assertAlmostEqual(monitor.mbps(10_000_000, 8.0), 10.0)

    def test_tempo_zero_ou_negativo(self):
        self.assertIsNone(monitor.mbps(1000, 0))


PING_RESPOSTAS = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=60 time=26.4 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=60 time=25.0 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=60 time=130 ms
64 bytes from 1.1.1.1: icmp_seq=4 ttl=60 time=33.1 ms
64 bytes from 1.1.1.1: icmp_seq=5 ttl=60 time=37.9 ms

--- 1.1.1.1 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 806ms
rtt min/avg/max/mdev = 25.000/50.480/130.000/40.000 ms
"""
PING_FALTANDO = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=60 time=20.0 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=60 time=40.0 ms
64 bytes from 1.1.1.1: icmp_seq=4 ttl=60 time=30.0 ms

--- 1.1.1.1 ping statistics ---
5 packets transmitted, 3 received, 40% packet loss, time 806ms
"""
PING_NENHUMA = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.

--- 1.1.1.1 ping statistics ---
10 packets transmitted, 0 received, 100% packet loss, time 1806ms
"""
# ping morto antes de imprimir o resumo
PING_SEM_RESUMO = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=60 time=20.0 ms
64 bytes from 1.1.1.1: icmp_seq=4 ttl=60 time=30.0 ms
"""


class ParsePingRespostasTest(unittest.TestCase):
    def test_varias_respostas_mediana(self):
        self.assertEqual(monitor.parse_ping_respostas(PING_RESPOSTAS), {"mediana": 33.1, "perda": 0.0})

    def test_respostas_faltando_perda(self):
        self.assertEqual(monitor.parse_ping_respostas(PING_FALTANDO), {"mediana": 30.0, "perda": 40.0})

    def test_nenhuma_resposta(self):
        self.assertEqual(monitor.parse_ping_respostas(PING_NENHUMA), {"mediana": None, "perda": 100.0})

    def test_sem_resumo_usa_maior_icmp_seq(self):
        self.assertEqual(monitor.parse_ping_respostas(PING_SEM_RESUMO), {"mediana": 25.0, "perda": 50.0})

    def test_texto_vazio(self):
        self.assertEqual(monitor.parse_ping_respostas(""), {"mediana": None, "perda": 100.0})


class TesteVelocidadeTest(unittest.TestCase):
    """Sem rede: as fases e os pings são trocados por dublês."""

    def troca(self, **fns):
        for nome, fn in fns.items():
            p = mock.patch.object(monitor, nome, fn)
            p.start()
            self.addCleanup(p.stop)

    def test_mede_velocidade_e_latencia_em_cada_fase(self):
        fases = iter([{"mediana": 80.0, "perda": 0.0}, {"mediana": 150.0, "perda": 5.0}])
        self.troca(baixar=lambda: (25_000_000, 2.0), enviar=lambda: (10_000_000, 4.0),
                   ping_parado=lambda: {"mediana": 20.0, "perda": 0.0},
                   ping_continuo=lambda: "proc", parar_ping=lambda p: next(fases))
        r = monitor.teste_velocidade()
        self.assertEqual((r["down_mbps"], r["up_mbps"], r["bytes_down"], r["bytes_up"], r["erro"]),
                         (100.0, 20.0, 25_000_000, 10_000_000, None))
        self.assertEqual(r["carga"], {"ocioso_ms": 20.0, "down_ms": 80.0, "up_ms": 150.0,
                                      "down_perda": 0.0, "up_perda": 5.0})
        self.assertIsNotNone(r["fim_epoch"])

    def test_falha_na_latencia_nao_impede_a_velocidade(self):
        def quebra(*a):
            raise FileNotFoundError("ping")
        self.troca(baixar=lambda: (25_000_000, 2.0), enviar=lambda: (10_000_000, 4.0),
                   ping_parado=quebra, ping_continuo=quebra, parar_ping=quebra)
        r = monitor.teste_velocidade()
        self.assertEqual((r["down_mbps"], r["up_mbps"], r["erro"], r["carga"]), (100.0, 20.0, None, None))

    def test_usa_a_fase_de_download_recebida(self):
        self.troca(baixar=lambda: (1, 1.0), enviar=lambda: (10_000_000, 4.0), ping_parado=lambda: None,
                   ping_continuo=lambda: None, parar_ping=lambda p: None)
        r = monitor.teste_velocidade(lambda: (75_000_000, 1.0))
        self.assertEqual(r["down_mbps"], 600.0)

    def test_erro_na_fase_vira_erro_sem_levantar(self):
        def quebra():
            raise TimeoutError("download passou de 30 s")
        self.troca(baixar=quebra, enviar=lambda: (10_000_000, 4.0),
                   ping_parado=lambda: {"mediana": 20.0, "perda": 0.0},
                   ping_continuo=lambda: "proc", parar_ping=lambda p: {"mediana": 90.0, "perda": 0.0})
        r = monitor.teste_velocidade()
        self.assertIn("30 s", r["erro"])
        self.assertIsNone(r["down_mbps"])
        self.assertIsNone(r["up_mbps"])


class HoraDoCompletoTest(unittest.TestCase):
    H = [9, 15, 21]

    @staticmethod
    def em(hora, minuto=0, dia=2):
        return time.mktime((2026, 10, dia, hora, minuto, 0, 0, 0, -1))   # hora local, como o monitor usa

    def test_so_nas_horas_configuradas(self):
        self.assertTrue(monitor.hora_do_completo(self.em(15, 10), None, "ok", self.H))
        self.assertFalse(monitor.hora_do_completo(self.em(14, 59), None, "ok", self.H))

    def test_uma_vez_por_hora_inclusive_apos_reinicio(self):
        self.assertFalse(monitor.hora_do_completo(self.em(15, 50), self.em(15, 2), "ok", self.H))
        self.assertTrue(monitor.hora_do_completo(self.em(21, 0), self.em(15, 2), "ok", self.H))
        self.assertTrue(monitor.hora_do_completo(self.em(9, 0, dia=3), self.em(9, 0), "ok", self.H))

    def test_nunca_fora_do_ar_e_lista_vazia_desliga(self):
        self.assertTrue(monitor.hora_do_completo(self.em(9), None, "degradado", self.H))
        for st in ("sem_wifi", "falha_lan", "falha_internet", "falha_dns"):
            self.assertFalse(monitor.hora_do_completo(self.em(9), None, st, self.H), st)
        self.assertFalse(monitor.hora_do_completo(self.em(9), None, "ok", []))


class BaixarCompletoTest(unittest.TestCase):
    """Sem rede: cada conexão é um fluxo falso que entrega 10 kB a cada ~1 ms."""

    class Fluxo:
        def __init__(self, abertos):
            self.abertos = abertos

        def __enter__(self):
            self.abertos.append(self)
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            time.sleep(0.001)
            return b"x" * 10_000

    def test_soma_as_conexoes_e_mede_so_depois_do_aquecimento(self):
        abertos, antes = [], threading.active_count()
        n, seg = monitor.baixar_completo(fluxos=3, aquecer=0.05, duracao=0.2, abrir=lambda: self.Fluxo(abertos))
        self.assertEqual(len(abertos), 3)
        self.assertAlmostEqual(seg, 0.2, delta=0.05)
        self.assertGreater(n, 0)
        self.assertEqual(n % 10_000, 0)
        self.assertEqual(threading.active_count(), antes)   # as conexões param no fim da medida

    def test_refaz_o_pedido_quando_o_arquivo_acaba(self):
        pedidos = []

        def abrir():
            pedidos.append(1)
            return io.BytesIO(b"x" * 1000)
        n, _ = monitor.baixar_completo(fluxos=1, aquecer=0, duracao=0.05, abrir=abrir)
        self.assertGreater(len(pedidos), 1)

    def test_todas_as_conexoes_falhando_levanta(self):
        def abrir():
            raise OSError("HTTP 403")
        with self.assertRaises(OSError):
            monitor.baixar_completo(fluxos=2, aquecer=0, duracao=0.05, abrir=abrir)


class PedidoCompletoTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        self.arq = os.path.join(d, "pedido_teste_completo")

    def test_sem_arquivo_nao_ha_pedido(self):
        self.assertFalse(monitor.pedido_completo(1000.0, self.arq))

    def test_pedido_recente_vale_e_some_ao_apagar(self):
        open(self.arq, "w").close()
        os.utime(self.arq, (900, 900))
        self.assertTrue(monitor.pedido_completo(1000.0, self.arq))
        monitor.apagar_pedido(self.arq)
        self.assertFalse(os.path.exists(self.arq))
        monitor.apagar_pedido(self.arq)                            # já apagado: sem erro

    def test_pedido_velho_e_descartado(self):
        open(self.arq, "w").close()
        os.utime(self.arq, (100, 100))
        self.assertFalse(monitor.pedido_completo(100 + monitor.PEDIDO_VALIDADE + 1, self.arq))
        self.assertFalse(os.path.exists(self.arq))


class IniciarVelocidadeTest(unittest.TestCase):
    def test_completo_marca_e_sobrevive_a_reinicio(self):
        db = sqlite3.connect(":memory:")
        db.executescript(monitor.SCHEMA)
        self.assertIsNone(monitor.ultimo_completo(db))
        monitor.iniciar_velocidade(db, 100.0, "t1", completo=True)
        monitor.iniciar_velocidade(db, 200.0, "t2")
        self.assertEqual(monitor.ultimo_completo(db), 100.0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM velocidade_completo").fetchone()[0], 1)


class CorpoUploadTest(unittest.TestCase):
    def test_marca_o_inicio_na_primeira_leitura_e_entrega_n_bytes(self):
        c = monitor.CorpoUpload(100_000, prazo=30)
        self.assertIsNone(c.inicio)
        total = 0
        while True:
            b = c.read(8192)
            if not b:
                break
            total += len(b)
        self.assertEqual(total, 100_000)
        self.assertIsNotNone(c.inicio)

    def test_prazo_estourado_levanta_timeout(self):
        c = monitor.CorpoUpload(10_000_000, prazo=0)
        c.read(10)
        with self.assertRaises(TimeoutError):
            c.read(10)


class GravarVelocidadeTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(monitor.SCHEMA)
        self.vid = monitor.iniciar_velocidade(self.db, 100.0, "2026-01-01T00:00:00")

    def res(self, **kw):
        r = {"fim_epoch": 140.0, "down_mbps": 100.0, "up_mbps": 20.0, "bytes_down": 25_000_000,
             "bytes_up": 10_000_000, "erro": None, "carga": None}
        r.update(kw)
        return r

    def test_linha_aberta_no_inicio(self):
        self.assertEqual(self.db.execute("SELECT epoch, fim_epoch, erro FROM velocidade").fetchone(), (100.0, None, None))

    def test_grava_resultado_e_carga(self):
        carga = {"ocioso_ms": 20.0, "down_ms": 80.0, "up_ms": 150.0, "down_perda": 0.0, "up_perda": 5.0}
        monitor.gravar_velocidade(self.db, self.vid, self.res(carga=carga))
        self.assertEqual(self.db.execute("SELECT fim_epoch, down_mbps, up_mbps, bytes_down, bytes_up, erro FROM velocidade").fetchone(),
                         (140.0, 100.0, 20.0, 25_000_000, 10_000_000, None))
        self.assertEqual(self.db.execute("SELECT velocidade_id, ocioso_ms, down_ms, up_ms, down_perda, up_perda FROM latencia_carga").fetchone(),
                         (self.vid, 20.0, 80.0, 150.0, 0.0, 5.0))

    def test_sem_carga_nao_grava_latencia(self):
        monitor.gravar_velocidade(self.db, self.vid, self.res(erro="HTTP 403", down_mbps=None, up_mbps=None))
        self.assertEqual(self.db.execute("SELECT erro, down_mbps FROM velocidade").fetchone(), ("HTTP 403", None))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM latencia_carga").fetchone(), (0,))

    def test_interrompidos_ficam_com_erro(self):
        monitor.marcar_interrompidos(self.db)
        self.assertEqual(self.db.execute("SELECT erro FROM velocidade").fetchone(), ("interrompido",))


if __name__ == "__main__":
    unittest.main()
