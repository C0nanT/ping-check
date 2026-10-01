UNIT   := ping-check
DIR    := $(CURDIR)
DB     := $(DIR)/conexao.db
PYTHON := /usr/bin/python3
SQL    := $(PYTHON) -c "import sqlite3,sys;c=sqlite3.connect('$(DB)');cur=c.execute(sys.argv[1]);print(' | '.join(d[0] for d in cur.description));[print(' | '.join(str(x) for x in r)) for r in cur]"

.PHONY: help start stop restart status logs run web summary outages last backup clean

help: ## Lista os comandos
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

start: ## Inicia o monitor em background (Docker)
	docker compose up -d --build

stop: ## Para o monitor
	-docker compose down

restart: stop start ## Reinicia o monitor

status: ## Status do container
	-docker compose ps

logs: ## Log ao vivo (quedas)
	docker compose logs -f

run: ## Roda em primeiro plano (Ctrl+C para parar)
	$(PYTHON) -u monitor.py

web: ## Painel web em http://127.0.0.1:8080 (Ctrl+C para parar)
	$(PYTHON) painel.py

summary: ## Resumo por status
	@$(SQL) "select status, count(*) amostras, round(100.0*count(*)/(select count(*) from checks),2) pct, round(avg(gw_avg_ms),1) gw_ms, round(avg(cf_avg_ms),1) cf_ms, round(avg(wifi_dbm),1) dbm from checks group by status order by 2 desc"

outages: ## Lista quedas
	@$(SQL) "select status, start_ts, end_ts, round(duration_s,1) dur_s, samples from outages order by start_epoch"

last: ## Últimas 20 amostras
	@$(SQL) "select ts, status, gw_loss_pct gw_loss, gw_avg_ms gw_ms, cf_loss_pct cf_loss, cf_avg_ms cf_ms, round(dns_ms,1) dns_ms, wifi_dbm dbm from checks order by id desc limit 20"

backup: ## Copia o banco com data/hora
	$(PYTHON) -c "import sqlite3;sqlite3.connect('$(DB)').backup(sqlite3.connect('$(DIR)/conexao-$(shell date +%Y%m%d-%H%M%S).db'))"

clean: stop ## Para o monitor e apaga o banco
	rm -f $(DB) $(DB)-wal $(DB)-shm
