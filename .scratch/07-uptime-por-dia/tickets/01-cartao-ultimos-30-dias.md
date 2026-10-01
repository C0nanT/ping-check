# 01: Cartão "Últimos 30 dias"

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** um cartão fixo, "Últimos 30 dias", entre "Como foi o período" e "Rapidez": 30 quadrados (hoje à direita) coloridos por % funcionando (≥ 99 verde, ≥ 95 amarelo, abaixo vermelho, cinza sem medição), com tooltip mostrando data, %, quedas, tempo fora e cobertura do dia. `/api` ganha `dias` (`dia`, `n`, `fora`, `quedas`), com o dia tirado do `ts` local. Nesta fatia tudo é calculado a cada requisição; o cache vem no ticket 02. Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/02 (Testes de `api()` com banco temporário)

**Status:** ready-for-agent

- [ ] `dias` sempre com 30 itens em ordem; dias sem amostra com `n: 0`
- [ ] `fora` conta só status de `CAIU` (`degradado` conta como funcionando); `quedas` conta outages pelo dia de início
- [ ] Cartão não muda com o período selecionado
- [ ] Tooltip em texto (não só cor), no estilo `.tip` existente
- [ ] Grade CSS sem rolagem horizontal no celular; cores dos tokens existentes nos dois temas
- [ ] Testes via `api()`; `make test` passa
