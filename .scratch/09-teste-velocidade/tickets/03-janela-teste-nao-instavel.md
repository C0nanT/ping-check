# 03: Janela de teste não marca "instável"

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** o pico de latência causado pelo próprio teste de velocidade não faz o cartão principal dizer "Sua internet está instável", e o usuário entende o pico no gráfico de rapidez. O cartão principal ignora amostras `degradado` dentro de uma janela de teste; o gráfico de rapidez desenha a janela como uma faixa discreta com legenda "teste de velocidade". As amostras em `checks` continuam gravadas como medidas. Spec: `../SPEC.md`.

**Blocked by:** 02 (Tile e gráfico de velocidade)

**Status:** ready-for-agent

- [ ] Durante e logo após um teste, o cartão principal não muda para "instável" só por amostras `degradado` dentro da janela
- [ ] Quedas reais (status de `CAIU`) dentro da janela continuam aparecendo normalmente
- [ ] Faixa da janela visível no gráfico de rapidez, com legenda, nos dois temas
- [ ] Uptime e lista de quedas não mudam
- [ ] Nenhuma amostra é alterada no banco
- [ ] `make test` passa
