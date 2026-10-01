# 01: Agrupamento no SQLite

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** os gráficos do painel ficam iguais aos de hoje, mas `/api` deixa de carregar todas as amostras do período no Python. Acima de `MAX_PONTOS`, o SQLite devolve os baldes já agrupados (média por campo, pior status pelo `MAX()` com coluna solta, baldes vazios somem). `reduz()` sai. Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/02 (Testes de `api()` com banco temporário)

**Status:** ready-for-agent

- [x] Testes de agrupamento de `01-testes-unitarios/02` passam sem alteração
- [x] Novo teste: vários status de queda no mesmo balde → status de grau 2
- [x] Até `MAX_PONTOS` amostras, as linhas brutas voltam como hoje
- [x] Contrato do `/api` (`pontos`, `passo`, demais campos) inalterado; JS sem mudanças
- [x] Comentário curto explica a regra de coluna solta com `MAX()` do SQLite
