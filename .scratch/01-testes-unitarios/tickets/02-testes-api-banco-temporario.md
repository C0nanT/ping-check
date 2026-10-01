# 02: Testes de `api()` com banco temporário

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** testes do painel pela costura `api(minutos)`, usando um SQLite temporário criado com o `SCHEMA` do monitor (o caminho do banco do painel é trocado no teste). Eles prendem o comportamento atual que as próximas specs não podem quebrar. Spec: `../SPEC.md`.

**Blocked by:** 01 (Monitor testável + `make test`)

**Status:** ready-for-human

- [x] Poucas amostras → `pontos` sem agrupar e `passo` = intervalo do monitor
- [x] Mais que `MAX_PONTOS` → média dos valores e pior status por balde
- [x] Baldes vazios somem (buraco de "sem medição" preservado)
- [x] Queda com `end_epoch` NULL termina na primeira amostra seguinte com outro status
- [x] Queda aberta com monitor parado termina na última amostra
- [x] `falhas` (número e segundos) recortado ao período
- [x] `atual`, `recentes`, `inicio_atual` e `ultima_queda` cobertos
- [x] Agrupamento testado só via `api()`, nunca chamando `reduz()` direto
- [x] Nenhum teste toca no `conexao.db` real
