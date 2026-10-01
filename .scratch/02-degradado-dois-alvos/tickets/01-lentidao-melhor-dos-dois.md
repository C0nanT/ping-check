# 01: Lentidão usa o melhor dos dois servidores

> **Difficulty:** Light: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** uma amostra só vira `degradado` por latência quando Cloudflare **e** Google passam de 150 ms (o menor valor entre as médias disponíveis). Se só um respondeu, vale a média dele. Ordem e nomes dos status não mudam; o histórico não é reclassificado. Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/01 (Monitor testável + `make test`)

**Status:** ready-for-agent

- [ ] Cloudflare 200 ms + Google 40 ms → `ok`
- [ ] Os dois > 150 ms → `degradado`
- [ ] Cloudflare sem média + Google 200 ms → `degradado`; + Google 40 ms → `ok`
- [ ] Casos de perda continuam iguais
- [ ] Texto de "Detalhes técnicos" do painel deixa claro que o limite de 150 ms vale para os dois servidores
- [ ] `make test` passa
