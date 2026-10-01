# Uptime por dia (últimos 30 dias)

Status: ready-for-agent

## Problem Statement

O painel mostra como foi a conexão no período escolhido (no máximo 7 dias), mas não dá para ver de relance quais dias foram ruins no último mês. Isso é o que o usuário precisa para perceber padrões ("toda segunda cai") e para reclamar com a operadora.

## Solution

Um cartão novo, "Últimos 30 dias", com uma faixa de 30 quadrados, um por dia (hoje à direita). Cada quadrado tem a cor de como foi o dia: verde (funcionou quase o tempo todo), amarelo, vermelho, ou cinza (sem medição). Passar o mouse mostra a data, a % do tempo funcionando, quantas vezes caiu, quanto tempo ficou fora do ar e quanto do dia foi medido. O cartão é fixo: não muda com o período selecionado no topo.

## User Stories

1. Como usuário, quero ver os últimos 30 dias de uma vez, para saber quais dias a internet foi ruim.
2. Como usuário, quero que as cores sigam as mesmas regras do cartão "Conexão funcionando" (≥ 99% verde, ≥ 95% amarelo, abaixo disso vermelho), para não ter que aprender outro critério.
3. Como usuário, quero que dias sem medição apareçam em cinza, para não confundir "monitor desligado" com "internet funcionando".
4. Como usuário, quero ver, ao passar o mouse, a data, a % funcionando, o número de quedas e o tempo fora do ar.
5. Como usuário, quero saber quanto do dia foi medido (ex.: "medido 6 h de 24 h"), para confiar mais ou menos no número.
6. Como usuário, quero que o dia de hoje apareça e vá sendo atualizado ao longo do dia.
7. Como usuário, quero que os dias sigam o horário local (meia-noite daqui), não UTC.
8. Como usuário, quero que o cartão funcione no celular (quadrados encolhem, sem rolagem horizontal).
9. Como usuário com daltonismo, quero que o tooltip diga o estado em texto, não só a cor.
10. Como dono, quero que o cartão não deixe o painel lento, mesmo consultando 30 dias a cada 5 s.
11. Como dono, quero que o cartão use o mesmo tooltip e as mesmas cores do resto do painel.

## Implementation Decisions

- `/api` ganha o campo `dias`: lista com os 30 dias locais até hoje, em ordem, cada um `{"dia": "AAAA-MM-DD", "n": <amostras>, "fora": <amostras com status de queda>, "quedas": <outages que começaram no dia>}`. Dias sem amostras vêm com `n: 0`. O frontend calcula `% = (n - fora) / n`, tempo fora ≈ `fora × INTERVALO` e cobertura ≈ `n × INTERVALO / 86400`.
- "Queda" = os status de `CAIU`, igual ao cartão "Conexão funcionando"; `degradado` conta como funcionando.
- O dia vem do prefixo de data da coluna `ts` (que já está em hora local), não de conversão de `epoch`. Assim o resultado é o mesmo no host e no container.
- Desempenho: os dias já fechados não mudam. O painel guarda em memória do processo o resultado dos dias anteriores a hoje e só recalcula o dia de hoje em cada requisição. O cache recomeça quando o painel reinicia. Um dia fechado que ganhar amostras depois (improvável) fica desatualizado até reiniciar: aceito.
- Frontend: cartão entre "Como foi o período" e "Rapidez", título "Últimos 30 dias", legenda igual à da linha do tempo. Quadrados desenhados em grade CSS com 30 colunas (sem canvas), cores `--good`/`--warning`/`--critical`/`--nodata`. Tooltip no mesmo estilo `.tip`. Rótulos de data só no primeiro e no último quadrado.

## Testing Decisions

- Teste via `api()` com banco temporário: amostras em 3 dias diferentes → `dias` tem 30 itens, os dias certos com `n`/`fora` certos e o resto com `n: 0`; `quedas` conta outages pelo dia de início; status `degradado` não conta em `fora`.
- Teste do cache: segunda chamada a `api()` devolve os mesmos dias fechados; amostras novas de hoje mudam só o item de hoje.
- Prior art: testes de `api()` da spec `01-testes-unitarios`.

## Out of Scope

- Mais de 30 dias, calendário mensal, navegação entre meses.
- Exportar relatório (é outro item, ainda não especificado).
- Clicar no dia para mudar o período dos gráficos.

## Further Notes

- Depende de `01-testes-unitarios`. Combina com `04-painel-sql-agregado`, mas não depende dela.
