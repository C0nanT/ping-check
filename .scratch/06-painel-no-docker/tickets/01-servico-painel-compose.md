# 01: Serviço `painel` no compose

> **Difficulty:** Heavy: **suggested model:** Opus (Claude Code) / Opus or the strongest reasoning model available (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** `http://127.0.0.1:8080` fica disponível sempre, sem terminal aberto, e volta sozinho depois de reiniciar o computador. Um segundo serviço `painel` no compose usa a mesma imagem, `network_mode: host`, `user: "1000:1000"` (só neste serviço), o mesmo bind mount (leitura e escrita, por causa do `-shm` do WAL), `/etc/localtime`, `PORT` e healthcheck HTTP. `make start/stop/restart/status/logs` cuidam dos dois; `make web` continua para desenvolvimento. Spec: `../SPEC.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `make start` → `make status` mostra `monitor` e `painel` como `healthy`
- [x] Painel acessível em 127.0.0.1 e inacessível de outra máquina da rede
- [ ] Editar o painel + `make restart` aplica a mudança sem rebuild
- [x] Painel roda como 1000:1000, sem D-Bus e sem `apparmor=unconfined`
- [x] `make logs` mostra os dois serviços
- [x] `make web` com o container rodando sai com mensagem em português (porta ocupada → `make stop` ou outra `PORT`)
- [x] Falha de um serviço não impede o outro de subir
- [x] `AGENTS.md` (Commands e Docker) atualizado; regra de não usar `user:` explicitada como regra do serviço `monitor`
