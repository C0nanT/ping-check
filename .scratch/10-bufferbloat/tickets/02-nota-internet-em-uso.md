# 02: Nota "quando a internet está em uso" no painel

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** no cartão "Velocidade", uma linha "Quando a internet está em uso" mostra ícone, nota (Ótimo / Bom / Razoável / Ruim), uma frase do dia a dia ("Quando alguém baixa algo, a resposta fica 120 ms mais lenta: chamadas de vídeo podem travar") e os números parado/baixando/enviando. Os números brutos também aparecem em "Detalhes técnicos". `/api` inclui `carga` em cada item de `velocidade`. Spec: `../SPEC.md`.

**Blocked by:** 09-teste-velocidade/02 (Tile e gráfico de velocidade), 01 (Latência sob carga gravada)

**Status:** ready-for-agent

- [ ] Função pura da nota pelo acréscimo (pior fase − parado), testada nos limites 29/30, 59/60, 199/200 ms
- [ ] `carga` = `{ocioso, down, up, nota}` ou `null`; teste sem medida de latência não quebra o cartão
- [ ] Cores da nota pelos tokens de status (`good`/`warning`/`critical`)
- [ ] Frase em português simples, no tom do mapa `ST`
- [ ] Testes via `api()`; `make test` passa
