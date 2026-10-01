# 01: Latência sob carga gravada + relatório

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** cada teste de velocidade também mede a latência até 1.1.1.1 parado (~5 s antes), durante o download e durante o upload (`ping -n -i 0.2` sem `-q`), e grava mediana e perda na tabela nova `latencia_carga`, ligada ao teste. A tabela é separada porque não há migração em `velocidade`. `make velocidade` passa a mostrar esses números. Spec: `../SPEC.md`.

**Blocked by:** 09-teste-velocidade/01 (Monitor faz o teste de velocidade)

**Status:** ready-for-human

- [x] Tabela `latencia_carga` com `CREATE TABLE IF NOT EXISTS` (`velocidade_id`, `ocioso_ms`, `down_ms`, `up_ms`, `down_perda`, `up_perda`)
- [x] Parser puro do `ping` sem `-q` testado: várias respostas → mediana; respostas faltando → perda; nenhuma → mediana `None` e perda 100%
- [x] Falha na medida de latência não impede gravar a velocidade
- [x] Sem tráfego extra além do próprio teste e dos pings; funciona sem root
- [x] `make velocidade` mostra parado/baixando/enviando
- [x] `make test` passa
