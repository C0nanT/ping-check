# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Home connection monitor (Linux, Portuguese UI/comments/identifiers). Two standalone Python 3 scripts, stdlib only — no dependencies, no build, no linter, tests via `make test` (stdlib `unittest`). Not a git repo.

- `monitor.py` — collector loop; writes samples to `conexao.db` (SQLite, WAL).
- `painel.py` — read-only web dashboard on `http://127.0.0.1:8080` (`PORT` env overrides). HTML/CSS/JS is inlined in the `PAGINA` string; no external assets. Exits with a Portuguese message if the port is taken.

## Commands

All via `make` (run `make help` for the list). Python is pinned to `/usr/bin/python3`.

- `make test` — runs the `unittest` suite in `tests/` (no network, Docker or real DB).
- `make hooks` — once per clone: sets `core.hooksPath=.githooks`, so the versioned `pre-push` hook runs `make test` and blocks the push on failure (`--no-verify` skips).
- `make run` — monitor in foreground. `make web` — dashboard in foreground, for development (fails with "porta em uso" while the `painel` container holds the port: `make stop` or `PORT=8081 make web`).
- `make start` / `stop` / `restart` / `status` / `logs` — both services in Docker (`docker compose`, containers `ping-check` (monitor) and `ping-check-painel`, both `restart: unless-stopped`).
- `make summary` / `outages` / `last` / `rotas` / `velocidade` — ad-hoc SQL reports via the `$(SQL)` one-liner in the Makefile (no `sqlite3` CLI needed). Add new reports the same way.
- `make backup` — online copy to `conexao-YYYYMMDD-HHMMSS.db`.
- `make clean` — stops both services and **deletes the database** (incl. `-wal`/`-shm`).

## Docker

Two services on the same `ping-check` image (built by `monitor`; `painel` has `pull_policy: never` and no build of its own). They don't depend on each other: one failing doesn't stop the other.

`monitor` settings that matter (the monitor breaks without them):
- `network_mode: host` — the monitor must see the host's default route, gateway and `/proc/net/wireless`.
- `.:/app` bind mount — `conexao.db` lives on the host, so `make summary`/`web` keep working. Code changes take effect after `make restart`; no rebuild needed.
- Sleep inhibit — the Dockerfile `CMD` runs `systemd-inhibit --what=sleep:idle:handle-lid-switch` (talking to the host's logind over D-Bus) in the background as **root**, because the host polkit denies uid 1000 from outside a session. `setpriv` drops the monitor to 1000:1000 so DB files stay owned by the host user. The monitor is `exec`'d as the main process under `init: true` (tini) so it receives SIGTERM directly and closes open `outages`/`runs` rows. Don't add `user:` to the `monitor` service, and don't make `systemd-inhibit` the parent of the monitor (it doesn't forward signals). Check with `systemd-inhibit --list`.
- Non-root `ping` works because the Dockerfile `setcap`s it (the host's `ping_group_range` is disabled).
- `/etc/localtime` mount — `ts` columns use local time.
- Healthcheck — healthy if the newest `checks.epoch` is under 30s old (read-only query on the DB).
- D-Bus socket mount plus `apparmor=unconfined` — `nmcli` (the `wifi_info` table) talks to the host NetworkManager, and Docker's AppArmor profile blocks that otherwise.

`painel` service: `network_mode: host` (binds 127.0.0.1 on the host, so it is reachable only from this machine), `user: "1000:1000"` (needs no root — the "no `user:`" rule is for `monitor` only), same `.:/app` mount **read-write** (a WAL reader writes `-shm`; it still can't write the DB because it opens `mode=ro`) plus `/etc/localtime`, no D-Bus and no `apparmor=unconfined`. `PORT` is passed through (default 8080). Healthcheck: HTTP GET `/api?min=1` with stdlib, every 30s. Code changes take effect after `make restart`, like the monitor.

## Architecture

**Monitor cycle** (every `INTERVAL`=5s): resolve default route (`ip route`) → in parallel ping gateway, 1.1.1.1 (`cf`), 8.8.8.8 (`google`/`gg`) via `ping` subprocess, plus DNS lookup with timeout → read signal from `/proc/net/wireless` → `classify()` → insert into `checks`. Every `WIFI_INFO_EVERY`=60s also logs BSSID/channel/rate from `nmcli` into `wifi_info`. Each process run is recorded in `runs`.

**Background tasks** (`Fundo` in `monitor.py`): slow jobs run in daemon threads, at most one per name, so they never delay the 5s cycle; the main thread calls `fundo.colher(db)` each cycle and does the DB write itself (the SQLite connection is single-threaded). A task still running at shutdown is discarded. Add new slow jobs as another `fundo.iniciar(nome, fn, gravar)`, not as code in the cycle.

**Route diagnosis**: when a `falha_internet` outage opens (and no diagnosis is running), `tracepath -n -m 15 1.1.1.1` runs via `Fundo` (under `stdbuf -oL`, 60s timeout — each silent hop costs ~3s; partial output survives a timeout) and is stored in `rotas` (`outage_id`, `saltos` JSON `[{n, ip|null, ms|null}]`, `ultimo_ok`, raw `saida`, `erro`). Never for other statuses. `make rotas` lists them.

**Speed test**: every `VELOCIDADE_A_CADA` minutes (env, default 30, `0` disables; passed through in `compose.yaml`), first one ~60s after start, never while the current status is down (`hora_de_testar()`), one at a time via `Fundo`. Downloads 25 MB from `speed.cloudflare.com/__down` and POSTs 10 MB to `__up` with `urllib` (custom `User-Agent`: the default one gets 403), timing from the first response byte / first body read (excludes DNS/TLS), 30s cap per phase. ~35 MB per test, ~1.7 GB/day at the default. The `velocidade` row is inserted when the test **starts** (`fim_epoch` NULL = running) and filled when it ends; rows left open by a stop/crash get `erro='interrompido'`. Errors become `erro`, never an exception. Latency under load (bufferbloat): `ping -n -i 0.2` to 1.1.1.1 for 5s idle, then continuously during each phase (stopped with SIGINT), parsed by `parse_ping_respostas()` (median + loss) into `latencia_carga` (keyed by `velocidade_id`; separate table because there are no migrations). A latency failure never blocks the speed result. `make velocidade` lists both.

**Status values** (from `classify()`, in priority order): `sem_wifi`, `falha_lan`, `falha_internet`, `falha_dns`, `degradado`, `ok`. These strings are shared contract between `monitor.py`, `CAIU` and the JS `ST` map in `painel.py`, and Makefile queries — change all together.

**Outages**: anything other than `ok`/`degradado` is "down". Monitor keeps one open `outages` row in memory; a status change or recovery closes it (sets `end_*`, `duration_s`) and a different down status opens a new row. Open outage is closed on SIGTERM/SIGINT shutdown; after a crash it stays with `end_ts` NULL (dashboard shows "em andamento").

**Schema** lives in `SCHEMA` in `monitor.py` using `CREATE TABLE IF NOT EXISTS` only — no migrations. Adding columns won't affect an existing `conexao.db`; requires manual `ALTER TABLE` or a fresh DB. New tables do appear on monitor restart, so new data goes in new tables, never new columns. The dashboard opens the DB read-only and can't create them: guard every query on a newer table with `tem_tabela()` (covered by `BancoAntigoTest`).

**Dashboard**: written for non-technical users in plain Portuguese, with raw numbers tucked into a "Detalhes técnicos" `<details>`. `/api?min=N` (last N minutes) or `/api?de=E&ate=E` (epoch range, from the "Escolher datas" picker) returns the points of the half-open window `[de, ate)` (`periodo()`: future `ate` → now, span capped at `MAX_PERIODO`=30 days by moving `de`, invalid → 400) plus precomputed summary fields (`de`/`ate` = effective window, which the client draws from; `pontos`, `resumo`, `quedas`/`falhas` (`seg` clipped to the window) and `velocidade` follow the window, everything else is always "now"; the custom range is not saved in `localStorage`; `atual`, `recentes` = statuses of the last 12 samples, newest first, **excluding `degradado` samples inside a speed-test window** `[epoch, COALESCE(fim_epoch, epoch+TESTE_MAX) + TESTE_FOLGA]` so the test's own latency spike doesn't make the hero say "instável" — real outages still count, and `resumo`/`pontos`/uptime are untouched; `velocidade` = speed tests started in the period, oldest first, `{epoch, fim, down, up, erro, carga}` (`down`/`up` null when `erro`; `carga` = `{ocioso, down, up, nota}` or null, `nota` = `{nome, cat, acrescimo, fase}` from `nota_carga()`: worst phase minus idle, <30 Ótimo, <60 Bom, <200 Razoável, else Ruim); `velocidade_ultimo` = last successful test even outside the period, or null; `inicio_atual`, `ultima_queda`, `falhas`, `quedas`, `wifi`, `passo`, `banco` = `{bytes, por_dia}`: disk size of db + `-wal` + `-shm`, and main-file growth per day, null under 1h of data; `dias` = the 30 local days up to today, oldest first, each `{dia, n, fora, quedas}` — samples, samples with a `CAIU` status, outages started that day; the day is the `ts` date prefix, not derived from `epoch`, and is independent of `min`). Closed days (before today) are cached in process memory (`_dias_fechados`, lock-protected for `ThreadingHTTPServer`); only today is recounted per request, and the cache resets on restart. Points are downsampled into ≤ `MAX_PONTOS`=600 **fixed-time** buckets (mean values, worst status). Empty buckets are dropped, so gaps when the monitor was off survive, and the client treats a gap > `max(20s, 2.5×passo)` as "sem medição". An outage with NULL `end_epoch` (monitor crashed) ends at the first later sample with a different status. Each `quedas` item carries its `id` and `rota` (`{frase, saltos}` from `rotas`, or null; `frase_rota()` turns the hops into plain Portuguese — hop 1 is the home router — with `frase` null when the diagnosis failed). Frontend: hand-drawn canvas charts (no library), shared hover tooltip, status → plain-language text in the JS `ST` map, polls every 5s. Colors follow the dataviz reference palette (series `--s1`/`--s2`, status `--good`/`--warning`/`--critical`; `--band` = speed-test window in the Rapidez chart). `lineChart()` takes its points via options (`P`, `lim`, `marcas`, `janelas`, `esq`), so non-`checks` series (speed) reuse it. Opens DB with `mode=ro` so it is safe to run alongside the monitor.

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
