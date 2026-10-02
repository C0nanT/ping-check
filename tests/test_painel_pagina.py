import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request

import painel


def separa(pagina):
    """(html, js): o HTML sem o <script> e o JavaScript embutido."""
    m = re.search(r"<script>(.*?)</script>", pagina, re.S)
    return pagina[:m.start()] + pagina[m.end():], m.group(1)


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
        r = urllib.request.urlopen(f"http://127.0.0.1:{cls.srv.server_address[1]}/")
        cls.status, cls.tipo, cls.corpo = r.status, r.headers["Content-Type"], r.read().decode("utf-8")

    def test_get_raiz_devolve_a_pagina(self):
        self.assertEqual(self.status, 200)
        self.assertEqual(self.tipo, "text/html; charset=utf-8")
        self.assertTrue(self.corpo.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn("<title>Minha internet</title>", self.corpo)
        self.assertIn("<script>", self.corpo)

    def test_todo_id_usado_pelo_js_existe_no_html(self):
        html, js = separa(self.corpo)
        usados = ids_do_js(js)
        self.assertGreater(len(usados), 10)        # o extrator achou os ids, não ficou cego
        self.assertEqual(usados - ids_do_html(html), set())

    def test_remover_um_id_do_html_e_detectado(self):
        html, js = separa(self.corpo)
        alvo = sorted(ids_do_js(js))[0]
        sem = html.replace(f'id="{alvo}"', "")
        self.assertEqual(ids_usados_faltando(sem, js), {alvo})

    @unittest.skipUnless(shutil.which("node"), "node não instalado")
    def test_javascript_tem_sintaxe_valida(self):
        _, js = separa(self.corpo)
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
