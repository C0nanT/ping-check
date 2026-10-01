# 01: Hora em 24 h no "Escolher datas"

> **Difficulty:** Easy: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** trocar os dois `datetime-local` do formulário por data (`type="date"`) + hora em texto `HH:MM` (00:00–23:59), com validação e mensagens em português, para que nenhum navegador mostre AM/PM. Spec: `../SPEC.md` (seção "Hora 24 h").

**Blocked by:** nada

**Status:** ready-for-agent

- [ ] De/Até = data + hora `HH:MM`; `9:05` vira `09:05`; hora inválida mostra erro no `#derro`
- [ ] Epoch montado com `new Date(a, m-1, d, h, min)` (hora local)
- [ ] Ao abrir, os campos vêm com o período da tela (`D.de`/`D.ate`)
- [ ] As validações atuais continuam (início < fim, início < agora, ≤ 30 dias)
- [ ] Todo texto de hora do painel continua em 24 h
- [ ] `node --check` no script; `make test` passa
