# 01: Pragmas de WAL enxuto no monitor

> **Difficulty:** Easy: **suggested model:** Haiku/Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** o monitor abre o banco por uma função `abrir_banco(caminho)` (`connect` + `SCHEMA` + `journal_mode=WAL` + `wal_autocheckpoint=100` + `journal_size_limit=0`), usada por `main()`. Os valores ficam em constantes no topo de `monitor.py`. O WAL deixa de ficar em ~4 MB e o tamanho no painel passa a refletir os dados. Spec: `../SPEC.md`.

**Blocked by:** nada

**Status:** ready-for-agent

- [ ] `abrir_banco()` extraída de `main()`, que passa a usá-la
- [ ] Constantes nomeadas para `wal_autocheckpoint` (100) e `journal_size_limit` (0)
- [ ] Teste: as três pragmas têm os valores esperados numa conexão de `abrir_banco()`
- [ ] Teste: muitos inserts com commit → `-wal` nunca passa de ~0,5 MB
- [ ] Teste: banco antigo com WAL grande, reaberto por `abrir_banco()` → WAL encolhe depois de gravar
- [ ] `CLAUDE.md` atualizado (uma linha sobre as pragmas e o motivo)
- [ ] `make test` passa
