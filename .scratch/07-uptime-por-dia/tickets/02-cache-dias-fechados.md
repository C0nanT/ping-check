# 02: Cache dos dias fechados

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** o cartão "Últimos 30 dias" deixa de reprocessar 30 dias a cada 5 s. O painel guarda em memória os dias anteriores a hoje e recalcula só hoje. Na virada do dia, ontem entra no cache. Reiniciar o painel limpa o cache. Spec: `../SPEC.md`.

**Blocked by:** 01 (Cartão "Últimos 30 dias")

**Status:** ready-for-human

- [x] Segunda chamada a `api()` devolve os mesmos dias fechados sem consultá-los de novo
- [x] Amostras novas de hoje mudam só o item de hoje
- [x] Virada do dia: o dia que fechou passa para o cache e a janela anda um dia
- [x] Tempo de `api()` com banco sintético de 30 dias registrado antes/depois na entrega
- [x] Cache seguro com o `ThreadingHTTPServer` (requisições simultâneas)
- [x] `make test` passa
