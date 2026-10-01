# 01: DNS via `getent` com timeout

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** durante uma queda de DNS longa, o monitor continua medindo a cada 5 s e registra `falha_dns` do começo ao fim, em vez de congelar com o pool cheio de threads presas. O teste de DNS vira um subprocesso `getent ahosts <DNS_HOST>` com `timeout=DNS_TIMEOUT`; o comando fica numa constante que o teste pode trocar. Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/01 (Monitor testável + `make test`)

**Status:** ready-for-human

- [x] Comando que dorme além do limite → `(0, None)` em menos de `DNS_TIMEOUT` + 1 s, sem processo pendurado
- [x] Comando que imprime um endereço e sai com 0 → `(1, ms)` com `ms` ≥ 0
- [x] Comando que sai com código ≠ 0 → `(0, None)`
- [x] Comentário enganoso sobre o executor corrigido
- [x] Funciona com `make run` e `make start` (Dockerfile sem mudanças)
- [x] `make test` passa
