# 02: Tile e gráfico de velocidade

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** o painel mostra um quinto tile "Velocidade" (último download/upload e "medido há X") e um cartão com gráfico de download (`--s1`) e upload (`--s2`) no período escolhido, usando o `lineChart` existente. `/api` ganha `velocidade` (testes do período + último teste bem-sucedido, mesmo fora do período). Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/02 (Testes de `api()` com banco temporário), 01 (Monitor faz o teste de velocidade)

**Status:** ready-for-agent

- [ ] Testes do período no `/api`; último teste bem-sucedido aparece mesmo fora do período; testes com erro trazem `erro` e sem Mbps
- [ ] Tile com termos simples ("Baixar (download)", "Enviar (upload)", Mbps)
- [ ] Sem nenhum teste ainda → tile e cartão explicam isso, sem quebrar
- [ ] Linhas ligadas só entre testes consecutivos (lacuna maior que ~2 intervalos não liga)
- [ ] Tooltip compartilhado funciona no gráfico novo
- [ ] Testes via `api()`; `make test` passa
