# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Home connection monitor (Linux, Portuguese UI/comments/identifiers). Two standalone Python 3 scripts, stdlib only — no dependencies, no build, no linter, tests via `make test` (stdlib `unittest`). Not a git repo.

- `monitor.py` — collector loop; writes samples to `conexao.db` (SQLite, WAL).
- `painel.py` — read-only web dashboard on `http://127.0.0.1:8080` (`PORT` env overrides). HTML/CSS/JS is inlined in the `PAGINA` string; no external assets.

## Commands

All via `make` (run `make help` for the list). Python is pinned to `/usr/bin/python3`.

- `make test` — runs the `unittest` suite in `tests/` (no network, Docker or real DB).
- `make run` — monitor in foreground. `make web` — dashboard in foreground.
- `make start` / `stop` / `restart` / `status` / `logs` — monitor in Docker (`docker compose`, container `ping-check`, `restart: unless-stopped`). Only the monitor runs in the container; the dashboard still runs on the host via `make web`.
- `make summary` / `outages` / `last` — ad-hoc SQL reports via the `$(SQL)` one-liner in the Makefile (no `sqlite3` CLI needed). Add new reports the same way.
- `make backup` — online copy to `conexao-YYYYMMDD-HHMMSS.db`.
- `make clean` — stops the monitor and **deletes the database** (incl. `-wal`/`-shm`).

## Docker

`compose.yaml` settings that matter (the monitor breaks without them):
- `network_mode: host` — the monitor must see the host's default route, gateway and `/proc/net/wireless`.
- `.:/app` bind mount — `conexao.db` lives on the host, so `make summary`/`web` keep working. Code changes take effect after `make restart`; no rebuild needed.
- Sleep inhibit — the Dockerfile `CMD` runs `systemd-inhibit --what=sleep:idle:handle-lid-switch` (talking to the host's logind over D-Bus) in the background as **root**, because the host polkit denies uid 1000 from outside a session. `setpriv` drops the monitor to 1000:1000 so DB files stay owned by the host user. The monitor is `exec`'d as the main process under `init: true` (tini) so it receives SIGTERM directly and closes open `outages`/`runs` rows. Don't add `user:` to compose, and don't make `systemd-inhibit` the parent of the monitor (it doesn't forward signals). Check with `systemd-inhibit --list`.
- Non-root `ping` works because the Dockerfile `setcap`s it (the host's `ping_group_range` is disabled).
- `/etc/localtime` mount — `ts` columns use local time.
- Healthcheck — healthy if the newest `checks.epoch` is under 30s old (read-only query on the DB).
- D-Bus socket mount plus `apparmor=unconfined` — `nmcli` (the `wifi_info` table) talks to the host NetworkManager, and Docker's AppArmor profile blocks that otherwise.

## Architecture

**Monitor cycle** (every `INTERVAL`=5s): resolve default route (`ip route`) → in parallel ping gateway, 1.1.1.1 (`cf`), 8.8.8.8 (`google`/`gg`) via `ping` subprocess, plus DNS lookup with timeout → read signal from `/proc/net/wireless` → `classify()` → insert into `checks`. Every `WIFI_INFO_EVERY`=60s also logs BSSID/channel/rate from `nmcli` into `wifi_info`. Each process run is recorded in `runs`.

**Status values** (from `classify()`, in priority order): `sem_wifi`, `falha_lan`, `falha_internet`, `falha_dns`, `degradado`, `ok`. These strings are shared contract between `monitor.py`, `CAIU` and the JS `ST` map in `painel.py`, and Makefile queries — change all together.

**Outages**: anything other than `ok`/`degradado` is "down". Monitor keeps one open `outages` row in memory; a status change or recovery closes it (sets `end_*`, `duration_s`) and a different down status opens a new row. Open outage is closed on SIGTERM/SIGINT shutdown; after a crash it stays with `end_ts` NULL (dashboard shows "em andamento").

**Schema** lives in `SCHEMA` in `monitor.py` using `CREATE TABLE IF NOT EXISTS` only — no migrations. Adding columns won't affect an existing `conexao.db`; requires manual `ALTER TABLE` or a fresh DB.

**Dashboard**: written for non-technical users in plain Portuguese, with raw numbers tucked into a "Detalhes técnicos" `<details>`. `/api?min=N` returns the points plus precomputed summary fields (`atual`, `recentes`, `inicio_atual`, `ultima_queda`, `falhas`, `quedas`, `wifi`, `passo`). Points are downsampled into ≤ `MAX_PONTOS`=600 **fixed-time** buckets (mean values, worst status). Empty buckets are dropped, so gaps when the monitor was off survive, and the client treats a gap > `max(20s, 2.5×passo)` as "sem medição". An outage with NULL `end_epoch` (monitor crashed) ends at the first later sample with a different status. Frontend: hand-drawn canvas charts (no library), shared hover tooltip, status → plain-language text in the JS `ST` map, polls every 5s. Colors follow the dataviz reference palette (series `--s1`/`--s2`, status `--good`/`--warning`/`--critical`). Opens DB with `mode=ro` so it is safe to run alongside the monitor.

## SOLID

Apply SOLID at the **architecture** level: module boundaries, dependency direction, and the interfaces between them. It is a way to shape seams, not a naming ritual. "Module" means whatever this codebase groups behaviour into: here, a function or a script.

### Scope: boy scout rule

SOLID applies to:

- code written new in the current change, and
- the existing code the current flow already passes through, when a small local edit clears friction that change is hitting.

The rest of the codebase stays as it is. Keep a change's blast radius on the flow being built or fixed: a repo-wide SOLID refactor is its own piece of work, and happens only when explicitly asked for. The codebase converges one change at a time.

When applying a principle would require reshaping modules outside the current flow, leave them alone and say so in the summary of the change.

### The principles, as architecture rules

- **SRP**: a module has one reason to change. When one flow forces edits in a module that other flows also own for unrelated reasons, that module is holding two responsibilities.
- **OCP**: new behaviour arrives as a new implementation behind an existing interface, rather than another branch in a growing conditional over kinds of thing.

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/` (created lazily). See `docs/agents/domain.md`.

### Git guardrails

Destructive git (`commit`, `push`, `reset`, …) is denied via `permissions.deny` in `.claude/settings.json`. See `docs/agents/git-guardrails.md`.
