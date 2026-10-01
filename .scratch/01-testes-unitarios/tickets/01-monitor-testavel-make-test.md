# 01: Monitor testável + `make test`

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** `make test` roda uma suíte `unittest` da stdlib, sem rede, sem Docker e sem tocar no `conexao.db`, cobrindo `classify()` e a leitura da saída do `ping`. Para isso, a leitura da saída do `ping` vira uma função pura que `ping()` chama; o comportamento do monitor não muda. Spec: `../SPEC.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `make test` existe, aparece em `make help` e usa o `$(PYTHON)` do Makefile
- [ ] Testes para cada status de `classify()` e para a prioridade quando dois problemas ocorrem juntos
- [ ] Parser do `ping` extraído como função pura; testes com saída normal, 100% de perda e sem linha de RTT
- [ ] Importar `monitor` nos testes não tem efeito colateral
- [ ] `make run` continua gravando amostras iguais às de antes
- [ ] `CLAUDE.md` deixa de dizer "no tests" e cita `make test`
