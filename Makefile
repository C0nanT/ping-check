UNIT   := ping-check
DIR    := $(CURDIR)
DB     := $(DIR)/conexao.db
PYTHON := /usr/bin/python3
SQL    := $(PYTHON) -c "import sqlite3,sys;c=sqlite3.connect('$(DB)');cur=c.execute(sys.argv[1]);print(' | '.join(d[0] for d in cur.description));[print(' | '.join(str(x) for x in r)) for r in cur]"

.PHONY: help start stop restart status logs run web test hooks summary outages last rotas velocidade backup clean

help: ## Lista os comandos
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

start: ## Inicia monitor e painel em background (Docker)
	docker compose up -d --build

stop: ## Para monitor e painel
	-docker compose down

restart: stop start ## Reinicia monitor e painel

status: ## Status dos containers (monitor e painel)
	-docker compose ps

logs: ## Log ao vivo dos dois serviços (quedas)
	docker compose logs -f

run: ## Roda em primeiro plano (Ctrl+C para parar)
	$(PYTHON) -u monitor.py

web: ## Painel em primeiro plano, para desenvolver (Ctrl+C; PORT=8081 se o container já usa a 8080)
	$(PYTHON) painel.py

test: ## Roda os testes unitários (sem rede, sem tocar no banco)
	$(PYTHON) -m unittest discover -s tests -t . -v

hooks: ## Ativa os git hooks versionados (pre-push roda os testes)
	git config core.hooksPath .githooks

summary: ## Resumo por status
	@$(SQL) "select status, count(*) amostras, round(100.0*count(*)/(select count(*) from checks),2) pct, round(avg(gw_avg_ms),1) gw_ms, round(avg(cf_avg_ms),1) cf_ms, round(avg(wifi_dbm),1) dbm from checks group by status order by 2 desc"

outages: ## Lista quedas
	@$(SQL) "select status, start_ts, end_ts, round(duration_s,1) dur_s, samples from outages order by start_epoch"

last: ## Últimas 20 amostras
	@$(SQL) "select ts, status, gw_loss_pct gw_loss, gw_avg_ms gw_ms, cf_loss_pct cf_loss, cf_avg_ms cf_ms, round(dns_ms,1) dns_ms, wifi_dbm dbm from checks order by id desc limit 20"

rotas: ## Diagnósticos de caminho (tracepath) das quedas falha_internet
	@$(SQL) "select r.ts, o.status, round(o.duration_s,1) dur_s, r.alvo, json_array_length(r.saltos) saltos, r.ultimo_ok, (select json_extract(j.value,'$$.ip') from json_each(r.saltos) j where json_extract(j.value,'$$.n')=r.ultimo_ok) ultimo_ip, r.erro from rotas r left join outages o on o.id=r.outage_id order by r.epoch desc limit 30"

velocidade: ## Testes de velocidade (Mbps) e latência parado/baixando/enviando
	@$(SQL) "select v.ts, round(v.down_mbps,1) baixar, round(v.up_mbps,1) enviar, round(v.fim_epoch-v.epoch) dur_s, round(l.ocioso_ms,1) parado_ms, round(l.down_ms,1) baixando_ms, round(l.up_ms,1) enviando_ms, round(l.down_perda,1) perda_b, round(l.up_perda,1) perda_e, v.erro from velocidade v left join latencia_carga l on l.velocidade_id=v.id order by v.epoch desc limit 30"

backup: ## Copia o banco com data/hora
	$(PYTHON) -c "import sqlite3;sqlite3.connect('$(DB)').backup(sqlite3.connect('$(DIR)/conexao-$(shell date +%Y%m%d-%H%M%S).db'))"

clean: stop ## Para monitor e painel e apaga o banco
	rm -f $(DB) $(DB)-wal $(DB)-shm
