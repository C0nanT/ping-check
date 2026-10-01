# 01: Contador do banco no cabeçalho

> **Difficulty:** Light: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** o cabeçalho do painel mostra sempre, na linha de "Atualizado às…", o tamanho do banco no disco e o crescimento por dia (ex.: "Banco: 48,2 MB · cresce ~3,1 MB/dia"), atualizando a cada 5 s, inclusive com o monitor parado. `/api` ganha `banco: {bytes, por_dia}`. Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/02 (Testes de `api()` com banco temporário)

**Status:** ready-for-human

- [x] `banco.bytes` = soma do arquivo principal, `-wal` e `-shm` existentes; ausência do `-wal` não quebra
- [x] `por_dia` = tamanho do arquivo principal ÷ dias desde a primeira amostra; `null` com menos de 1 hora de dados
- [x] Formato pt-BR: KB abaixo de 1 MB, MB com 1 casa, GB com 2 casas; `por_dia` nulo mostra só o tamanho
- [x] Texto discreto (`--muted`), sem quebrar o layout no celular
- [x] Testes via `api()`; `make test` passa
- [x] Lista de campos do `/api` no `CLAUDE.md` atualizada
