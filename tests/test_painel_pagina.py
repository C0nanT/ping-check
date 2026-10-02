import http.client
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request

import painel


def ids_do_html(html):
    return set(re.findall(r'\bid="([^"]+)"', html))


def ids_do_js(js):
    """Ids que o JS procura: $('x'), getElementById('x'), '#x' em seletores e listas ['a','b'].forEach(id=>...)."""
    ids = set(re.findall(r"\$\('([\w-]+)'\)", js))
    ids |= set(re.findall(r"getElementById\('([\w-]+)'\)", js))
    for sel in re.findall(r"querySelector(?:All)?\('([^']*)'\)", js):
        ids |= set(re.findall(r"#([\w-]+)", sel))
    for lista in re.findall(r"\[((?:'[\w-]+',?)+)\]\.forEach\(id=>", js):
        ids |= set(re.findall(r"'([\w-]+)'", lista))
    return ids


def ids_usados_faltando(html, js):
    return ids_do_js(js) - ids_do_html(html)


class PaginaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = painel.ThreadingHTTPServer(("127.0.0.1", 0), painel.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.porta = cls.srv.server_address[1]
        cls.html = cls.pega("/")
        cls.css = cls.pega("/pagina.css")
        cls.js = cls.pega("/pagina.js")

    @classmethod
    def pega(cls, caminho):
        """(status, Content-Type, corpo) sem normalizar o caminho (urllib deixaria passar `..` como veio, http.client também)."""
        c = http.client.HTTPConnection("127.0.0.1", cls.porta, timeout=5)
        try:
            c.request("GET", caminho)
            r = c.getresponse()
            return r.status, r.getheader("Content-Type"), r.read().decode("utf-8", "replace")
        finally:
            c.close()

    def test_get_raiz_devolve_a_pagina(self):
        status, tipo, corpo = self.html
        self.assertEqual(status, 200)
        self.assertEqual(tipo, "text/html; charset=utf-8")
        self.assertTrue(corpo.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn("<title>Minha internet</title>", corpo)
        self.assertIn('href="/pagina.css"', corpo)
        self.assertIn('src="/pagina.js"', corpo)

    def test_css_e_js_tem_tipo_e_utf8(self):
        self.assertEqual(self.css[:2], (200, "text/css; charset=utf-8"))
        self.assertEqual(self.js[:2], (200, "text/javascript; charset=utf-8"))
        self.assertIn(":root", self.css[2])
        self.assertIn("Não", self.js[2] + self.html[2])   # acentos chegam íntegros

    def test_so_a_lista_fechada_e_servida(self):
        for caminho in ("/pagina.html", "/painel.py", "/monitor.py", "/conexao.db", "/Makefile", "/AGENTS.md",
                        "/tests/", "/..", "/../painel.py", "/%2e%2e/painel.py", "/pagina.css/../painel.py",
                        "/static/pagina.js", "/pagina.js/"):
            with self.subTest(caminho=caminho):
                self.assertEqual(self.pega(caminho)[0], 404)

    def test_nenhum_recurso_externo(self):
        for nome, (_, _, corpo) in (("html", self.html), ("css", self.css), ("js", self.js)):
            with self.subTest(arquivo=nome):
                self.assertEqual(re.findall(r"(?:src|href)\s*=\s*[\"']?(?:https?:)?//", corpo), [])
                self.assertEqual(re.findall(r"url\(\s*[\"']?(?:https?:)?//|@import|fetch\(\s*[\"']https?:|https?://", corpo), [])

    def test_todo_id_usado_pelo_js_existe_no_html(self):
        usados = ids_do_js(self.js[2])
        self.assertGreater(len(usados), 10)        # o extrator achou os ids, não ficou cego
        self.assertEqual(usados - ids_do_html(self.html[2]), set())

    def test_remover_um_id_do_html_e_detectado(self):
        alvo = sorted(ids_do_js(self.js[2]))[0]
        sem = self.html[2].replace(f'id="{alvo}"', "")
        self.assertEqual(ids_usados_faltando(sem, self.js[2]), {alvo})

    @unittest.skipUnless(shutil.which("node"), "node não instalado")
    def test_javascript_tem_sintaxe_valida(self):
        js = self.js[2]
        self.checa_sintaxe(js)
        with self.assertRaises(AssertionError):
            self.checa_sintaxe(js + "\nconst = ;")  # erro introduzido: o teste tem que pegar

    def checa_sintaxe(self, js):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "pagina.js")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(js)
            r = subprocess.run(["node", "--check", f], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
