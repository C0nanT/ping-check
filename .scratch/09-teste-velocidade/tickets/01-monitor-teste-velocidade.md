# 01: Monitor faz o teste de velocidade + `make velocidade`

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** a cada `VELOCIDADE_A_CADA` minutos (padrão 30; `0` desliga), com a internet no ar, o monitor baixa ~25 MB de `speed.cloudflare.com/__down` e envia ~10 MB para `__up` em segundo plano, sem atrasar o ciclo de 5 s, e grava Mbps na tabela nova `velocidade`. Usa o mesmo padrão de executor e gravação na thread principal do `08-traceroute-na-queda/01`. `make velocidade` lista os testes no padrão `$(SQL)`. Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/01 (Monitor testável + `make test`), 08-traceroute-na-queda/01 (mesmo laço e mesmo padrão de executor)

**Status:** ready-for-human

- [x] Tabela `velocidade` com `CREATE TABLE IF NOT EXISTS` (`epoch`, `fim_epoch`, `down_mbps`, `up_mbps`, `bytes_down`, `bytes_up`, `erro`)
- [x] Função pura de agendamento testada: antes do intervalo não; depois sim; status de queda não; intervalo 0 nunca; primeiro teste ~1 min após iniciar
- [x] Cálculo de Mbps testado; tempo medido do primeiro byte/início do envio até o fim
- [x] Nunca dois testes ao mesmo tempo; timeout ~30 s por fase
- [x] Erro (timeout, HTTP) vira linha com `erro`, sem derrubar o monitor
- [x] Só stdlib (`urllib`)
- [x] `make velocidade` aparece em `make help`; `VELOCIDADE_A_CADA` documentado no `AGENTS.md`
- [x] `make test` passa
