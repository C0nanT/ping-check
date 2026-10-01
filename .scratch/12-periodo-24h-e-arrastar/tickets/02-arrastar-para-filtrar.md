# 02: Arrastar no "Como foi o período" para filtrar

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** no canvas `#tl`, clicar, segurar e arrastar desenha uma faixa de seleção com tooltip "De … até …". Ao soltar, o painel filtra por aquele trecho (`FAIXA` + `trocaPeriodo()`). Clique sem arrasto e Esc não filtram. Spec: `../SPEC.md` (seção "Arrastar no 'Como foi o período'").

**Blocked by:** nada (independente do 01)

**Status:** ready-for-human

- [x] Função `arrasto(cv)` separada do `hover(cv)`; o `timeline()` expõe a escala x → epoch
- [x] Pointer events + `setPointerCapture`; funciona com mouse e toque; a rolagem vertical continua no celular
- [x] Faixa com `--band`/`--axis` durante o arrasto; tooltip "De 14:05 até 15:20" (com data quando passa de um dia)
- [x] < 6 px ou < 60 s = clique (não faz nada); Esc cancela
- [x] `de` arredondado ao minuto para baixo e `ate` para cima, limitados à janela atual
- [x] Zoom repetido funciona; os presets voltam ao normal; o topo mostra "Mostrando de … até …"
- [x] Cursor `crosshair`; legenda do cartão ganha "Clique e arraste para ver um trecho de perto."
- [x] `node --check` no script; `make test` passa
