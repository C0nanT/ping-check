# 02: Frase e "ver caminho" no painel

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** na lista "Quando a conexão falhou", uma queda `falha_internet` com diagnóstico mostra uma frase simples ("O sinal parou no seu roteador…" / "O sinal passou do roteador e parou na rede da operadora (3º ponto do caminho)") e um "ver caminho" recolhido com ponto, IP e tempo. `/api` inclui `rota` em cada item de `quedas`. Spec: `../SPEC.md`.

**Blocked by:** 01-testes-unitarios/02 (Testes de `api()` com banco temporário), 01 (Monitor grava `tracepath` na queda)

**Status:** ready-for-human

- [x] Função pura de interpretação testada: só gateway/nenhum salto → roteador; salto após o gateway → operadora com número do ponto; erro → sem frase
- [x] `quedas` traz o `id` da queda e `rota` (`{frase, saltos}` ou `null`)
- [x] Queda sem diagnóstico continua aparecendo como hoje
- [x] Frases no tom do mapa `ST`, sem jargão
- [x] `<details>` "ver caminho" funciona no celular (tabela com rolagem própria, como `.tab`)
- [x] Testes via `api()`; `make test` passa
