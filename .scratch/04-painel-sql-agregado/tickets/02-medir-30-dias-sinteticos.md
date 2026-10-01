# 02: Medir com 30 dias sintéticos e ajustar consultas lentas

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** prova de que o painel continua rápido com o banco grande. Gerar um banco sintético de 30 dias (amostra a cada 5 s, fora do `conexao.db` real), medir `api(10080)` e `api(43200)` e corrigir só as consultas que estourarem a meta, por exemplo a de `ultima_queda` quando não há quedas (pode usar `outages`). Spec: `../SPEC.md`.

**Blocked by:** 01 (Agrupamento no SQLite)

**Status:** ready-for-agent

- [ ] `api(10080)` e `api(43200)` abaixo de 0,5 s no banco sintético, tempos registrados na entrega
- [x] Banco sintético com e sem quedas medido
- [ ] Consultas ajustadas mantêm `make test` passando
- [x] Gerador e medição não entram em `make test` nem tocam no `conexao.db` real
