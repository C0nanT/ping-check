# 03: Teste de fumaça da página atual

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** `make test` passa a provar que a página abre e que o JavaScript é válido, antes de qualquer separação de arquivos. Via o servidor real em thread: `GET /` responde 200 com HTML UTF-8, contém o script, e todo id de elemento que o JS procura existe no HTML. Um teste com `node --check` sobre o JavaScript embutido, pulado quando `node` não existe (o projeto segue só com a biblioteca padrão). Este ticket não mexe na página: é a rede de segurança do 04.

**Blocked by:** 02 (a página já terá os campos novos; o teste descreve a versão que vai ser separada).

**Status:** ready-for-human

- [x] `GET /` devolve 200, `text/html; charset=utf-8` e o conteúdo da página
- [x] Todo id usado pelo JS (`getElementById`/seletores por id) existe no HTML; remover um id no HTML faz o teste falhar
- [x] Um erro de sintaxe introduzido no JS faz o teste falhar quando `node` está instalado; o teste é pulado (skip) sem `node`
- [x] Nenhuma dependência nova; `make test` passa sem rede, Docker nem banco real
