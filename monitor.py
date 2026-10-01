#!/usr/bin/env python3
"""Monitor de conexão: grava amostras periódicas em SQLite.

Cada ciclo (INTERVAL s) mede, em paralelo:
  - ping ao gateway (modem)      -> problema local/WiFi
  - ping a 1.1.1.1 e 8.8.8.8     -> problema do provedor/internet
  - resolução DNS                -> problema de DNS
  - sinal WiFi (/proc/net/wireless)
A cada WIFI_INFO_EVERY s grava também BSSID/canal/taxa via nmcli.
Quedas (status != ok) viram linhas na tabela `outages` com início/fim.
"""
import concurrent.futures as cf
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conexao.db")
INTERVAL = 5            # segundos entre ciclos
PING_COUNT = 4          # pacotes por alvo por ciclo
PING_SPACING = 0.2      # s entre pacotes
PING_TIMEOUT = 1        # s de espera por resposta
DNS_HOST = "google.com"
DNS_TIMEOUT = 3
WIFI_INFO_EVERY = 60
INTERNET_TARGETS = {"cf": "1.1.1.1", "google": "8.8.8.8"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,          -- ISO local
    epoch         REAL NOT NULL,
    iface         TEXT,
    gateway       TEXT,
    gw_loss_pct   REAL, gw_avg_ms REAL, gw_max_ms REAL, gw_jitter_ms REAL,
    cf_loss_pct   REAL, cf_avg_ms REAL, cf_max_ms REAL, cf_jitter_ms REAL,
    gg_loss_pct   REAL, gg_avg_ms REAL, gg_max_ms REAL, gg_jitter_ms REAL,
    dns_ok        INTEGER, dns_ms REAL,
    wifi_quality  REAL,                   -- link quality (0-70)
    wifi_dbm      REAL,                   -- nível do sinal em dBm
    status        TEXT NOT NULL           -- ok | degradado | sem_wifi | falha_lan | falha_internet | falha_dns
);
CREATE INDEX IF NOT EXISTS idx_checks_epoch ON checks(epoch);

CREATE TABLE IF NOT EXISTS wifi_info (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, epoch REAL NOT NULL,
    ssid TEXT, bssid TEXT, chan INTEGER, freq TEXT, rate TEXT, signal_pct INTEGER
);

CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    start_ts TEXT NOT NULL, start_epoch REAL NOT NULL,
    end_ts TEXT, end_epoch REAL,
    duration_s REAL,
    samples INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, start_ts TEXT NOT NULL, end_ts TEXT, note TEXT
);
"""

RTT_RE = re.compile(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")
LOSS_RE = re.compile(r"([\d.]+)% packet loss")


def now():
    t = time.time()
    return t, datetime.fromtimestamp(t).isoformat(timespec="seconds")


def default_route():
    """Retorna (gateway, iface) da rota padrão, ou (None, None)."""
    try:
        out = subprocess.run(["ip", "route", "show", "default"],
                             capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"default via (\S+) dev (\S+)", out)
        if m:
            return m.group(1), m.group(2)
    except Exception:
        pass
    return None, None


def parse_ping(out):
    """Lê a saída do `ping -q` e retorna dict loss/avg/max/jitter.

    Sem linha de perda, loss fica 100; sem linha de RTT, avg/max/jitter ficam None.
    """
    res = {"loss": 100.0, "avg": None, "max": None, "jitter": None}
    m = LOSS_RE.search(out)
    if m:
        res["loss"] = float(m.group(1))
    m = RTT_RE.search(out)
    if m:
        res["avg"], res["max"], res["jitter"] = float(m.group(2)), float(m.group(3)), float(m.group(4))
    return res


def ping(host):
    """Retorna dict loss/avg/max/jitter. Loss 100 se tudo falhou."""
    res = {"loss": 100.0, "avg": None, "max": None, "jitter": None}
    if not host:
        return res
    try:
        out = subprocess.run(
            ["ping", "-n", "-q", "-c", str(PING_COUNT), "-i", str(PING_SPACING),
             "-W", str(PING_TIMEOUT), host],
            capture_output=True, text=True,
            timeout=PING_COUNT * PING_SPACING + PING_TIMEOUT + 3).stdout
    except Exception:
        return res
    return parse_ping(out)


def dns_check():
    t0 = time.monotonic()
    try:
        # getaddrinfo não tem timeout próprio; rodamos via executor com timeout
        socket.getaddrinfo(DNS_HOST, 443, proto=socket.IPPROTO_TCP)
        return 1, (time.monotonic() - t0) * 1000
    except Exception:
        return 0, None


def wifi_signal(iface):
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                if iface and line.strip().startswith(iface + ":"):
                    parts = line.split()
                    return float(parts[2].rstrip(".")), float(parts[3].rstrip("."))
    except Exception:
        pass
    return None, None


def wifi_info():
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "IN-USE,SSID,BSSID,CHAN,FREQ,RATE,SIGNAL",
             "dev", "wifi", "list", "--rescan", "no"],
            capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.startswith("*"):
            # campos separados por ':' com ':' escapado como '\:' no BSSID
            fields = re.split(r"(?<!\\):", line)
            fields = [x.replace("\\:", ":") for x in fields]
            if len(fields) >= 7:
                _, ssid, bssid, chan, freq, rate, sig = fields[:7]
                return ssid, bssid, int(chan or 0), freq, rate, int(sig or 0)
    return None


def classify(iface, gw, cf_, gg, dns_ok):
    inet_loss = min(cf_["loss"], gg["loss"])
    if not iface:
        return "sem_wifi"
    if gw["loss"] == 100:
        return "falha_lan"
    if inet_loss == 100:
        return "falha_internet"
    if not dns_ok:
        return "falha_dns"
    avgs = [t["avg"] for t in (cf_, gg) if t["avg"] is not None]
    lento = bool(avgs) and min(avgs) > 150
    if gw["loss"] > 0 or inet_loss > 0 or lento:
        return "degradado"
    return "ok"


def main():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.execute("PRAGMA journal_mode=WAL")
    _, start_ts = now()
    run_id = db.execute("INSERT INTO runs(start_ts, note) VALUES(?, ?)",
                        (start_ts, " ".join(sys.argv[1:]) or None)).lastrowid
    db.commit()

    stop = {"flag": False}

    def handle(sig, _frm):
        stop["flag"] = True
    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    pool = cf.ThreadPoolExecutor(max_workers=6)
    open_outage = None  # (id, status)
    last_wifi_info = 0.0
    print(f"[{start_ts}] monitor iniciado -> {DB_PATH}", flush=True)

    while not stop["flag"]:
        cycle_start = time.monotonic()
        epoch, ts = now()
        gateway, iface = default_route()

        f_gw = pool.submit(ping, gateway)
        f_cf = pool.submit(ping, INTERNET_TARGETS["cf"])
        f_gg = pool.submit(ping, INTERNET_TARGETS["google"])
        f_dns = pool.submit(dns_check)
        gw, cf_, gg = f_gw.result(), f_cf.result(), f_gg.result()
        try:
            dns_ok, dns_ms = f_dns.result(timeout=DNS_TIMEOUT)
        except Exception:
            dns_ok, dns_ms = 0, None
        q, dbm = wifi_signal(iface)
        status = classify(iface, gw, cf_, gg, dns_ok)

        try:
            db.execute(
                """INSERT INTO checks(ts, epoch, iface, gateway,
                   gw_loss_pct, gw_avg_ms, gw_max_ms, gw_jitter_ms,
                   cf_loss_pct, cf_avg_ms, cf_max_ms, cf_jitter_ms,
                   gg_loss_pct, gg_avg_ms, gg_max_ms, gg_jitter_ms,
                   dns_ok, dns_ms, wifi_quality, wifi_dbm, status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ts, epoch, iface, gateway,
                 gw["loss"], gw["avg"], gw["max"], gw["jitter"],
                 cf_["loss"], cf_["avg"], cf_["max"], cf_["jitter"],
                 gg["loss"], gg["avg"], gg["max"], gg["jitter"],
                 dns_ok, dns_ms, q, dbm, status))

            # rastreia quedas (qualquer status != ok/degradado)
            is_down = status not in ("ok", "degradado")
            if open_outage and (not is_down or open_outage[1] != status):
                db.execute(
                    "UPDATE outages SET end_ts=?, end_epoch=?, duration_s=?-start_epoch WHERE id=?",
                    (ts, epoch, epoch, open_outage[0]))
                print(f"[{ts}] fim de {open_outage[1]}", flush=True)
                open_outage = None
            if is_down:
                if open_outage:
                    db.execute("UPDATE outages SET samples=samples+1 WHERE id=?", (open_outage[0],))
                else:
                    oid = db.execute(
                        "INSERT INTO outages(status, start_ts, start_epoch) VALUES(?,?,?)",
                        (status, ts, epoch)).lastrowid
                    open_outage = (oid, status)
                    print(f"[{ts}] QUEDA: {status}", flush=True)

            if epoch - last_wifi_info >= WIFI_INFO_EVERY:
                info = wifi_info()
                if info:
                    db.execute(
                        "INSERT INTO wifi_info(ts, epoch, ssid, bssid, chan, freq, rate, signal_pct) "
                        "VALUES(?,?,?,?,?,?,?,?)", (ts, epoch, *info))
                last_wifi_info = epoch
            db.commit()
        except sqlite3.Error as e:
            print(f"[{ts}] erro sqlite: {e}", flush=True)

        elapsed = time.monotonic() - cycle_start
        end = time.monotonic() + max(0.0, INTERVAL - elapsed)
        while not stop["flag"] and time.monotonic() < end:
            time.sleep(0.2)

    epoch, ts = now()
    if open_outage:
        db.execute("UPDATE outages SET end_ts=?, end_epoch=?, duration_s=?-start_epoch WHERE id=?",
                   (ts, epoch, epoch, open_outage[0]))
    db.execute("UPDATE runs SET end_ts=? WHERE id=?", (ts, run_id))
    db.commit()
    db.close()
    pool.shutdown(wait=False, cancel_futures=True)
    print(f"[{ts}] monitor parado", flush=True)


if __name__ == "__main__":
    main()
