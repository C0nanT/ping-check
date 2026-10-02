# 04: Separar a página em arquivos html, css e js

> **Difficulty:** Heavy: **suggested model:** Opus (Claude Code) / Opus or the strongest reasoning model available (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** a página deixa de ser uma string dentro do servidor e passa a ser três arquivos estáticos (estrutura, estilo, script) servidos pelo próprio painel, sem biblioteca, sem CDN, sem recurso externo. `/` serve o HTML; o CSS e o JS saem de rotas fixas e conhecidas, numa lista fechada (não é um servidor de arquivos genérico: qualquer outro caminho, incluindo `..`, continua em 404), com tipo de conteúdo e UTF-8 corretos. As regras de apresentação ficam no JS. A mudança inclui atualizar o `AGENTS.md` (o contrato "HTML/CSS/JS inlined; no external assets" vira "arquivos estáticos locais servidos pelo painel; nenhum asset externo") e o `COPY` do Dockerfile, para a imagem conter os arquivos da página mesmo sem o bind mount. O comportamento visível da página não muda.

**Blocked by:** 03 (o teste de fumaça precisa estar verde antes de mover; depois passa a ler os arquivos novos).

**Status:** ready-for-agent

- [ ] A página renderiza e funciona igual a antes (conferir no navegador via `make web` e no contêiner `painel`)
- [ ] O teste de fumaça do 03, adaptado aos arquivos novos, continua passando; ids, sintaxe do JS e tipos de conteúdo são verificados
- [ ] Caminhos fora da lista fechada (incluindo tentativas com `..`) respondem 404; não há listagem de diretório
- [ ] Nenhum recurso externo ou CDN é carregado; a página abre sem internet
- [ ] A string `PAGINA` não existe mais; `AGENTS.md` descreve a nova estrutura
- [ ] O Dockerfile copia os arquivos da página; o healthcheck do painel (`GET /api?min=1`) continua passando
- [ ] `make restart` após editar um arquivo da página basta para ver a mudança (sem rebuild), como hoje
- [ ] `make test` passa
