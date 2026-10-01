# 01: Monitor grava `tracepath` na queda + `make rotas`

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** quando abre uma queda `falha_internet`, o monitor roda `tracepath -n -m 15 1.1.1.1` em segundo plano (sem atrasar o ciclo de 5 s), uma vez por queda, e grava o caminho na tabela nova `rotas` ligada à queda. A thread principal faz a gravação quando o diagnóstico termina. `make rotas` lista os diagnósticos no padrão `$(SQL)`. Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/01 (Monitor testável + `make test`)

**Status:** ready-for-agent

- [x] Tabela `rotas` com `CREATE TABLE IF NOT EXISTS`; um banco existente a ganha ao reiniciar o monitor
- [x] Parser puro do `tracepath` testado com saídas de exemplo: caminho completo, `no reply` no meio, só o gateway, nenhum salto
- [x] Só `falha_internet` dispara; no máximo um diagnóstico por queda
- [ ] Ciclo de 5 s não atrasa enquanto o `tracepath` roda (timeout ~30 s)
- [x] `tracepath` ausente ou com erro → linha com `erro`, queda registrada normalmente
- [x] Dockerfile instala `iputils-tracepath`; funciona sem root no container e no host
- [x] `make rotas` aparece em `make help`
- [x] `make test` passa
