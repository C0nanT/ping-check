# Painel agrega os pontos no SQL

Status: ready-for-agent

## Problem Statement

Em cada atualização (a cada 5 s), `/api` busca **todas** as amostras do período e só depois agrupa em até 600 pontos no Python. Em 7 dias são ~120 mil linhas; a API aceita até 30 dias (~520 mil). Como o banco cresce sem limite (decisão do dono), o painel vai ficar lento e pesado com o tempo, justo nos períodos longos.

## Solution

O agrupamento em baldes de tempo fixo passa a ser feito **dentro do SQLite**, que devolve no máximo 600 linhas já agrupadas. O resultado para o usuário é o mesmo de hoje: média dos valores por balde, pior status do balde, baldes vazios somem (o buraco de "sem medição" continua aparecendo).

## User Stories

1. Como usuário, quero que o painel de 7 dias abra e atualize tão rápido quanto o de 1 hora.
2. Como usuário, quero que os gráficos fiquem iguais aos de hoje depois da mudança.
3. Como usuário, quero que períodos com o monitor desligado continuem aparecendo como "sem medição".
4. Como usuário, quero que um momento sem conexão dentro de um balde continue pintando o balde de vermelho (pior status vence).
5. Como dono do projeto, quero que o painel continue rápido daqui a meses, com o banco grande.
6. Como dono do projeto, quero que o painel não use muita memória nem CPU mesmo deixado aberto o dia todo.
7. Como dono do projeto, quero que o contrato do `/api` (`pontos`, `passo` e os outros campos) não mude, para o JavaScript continuar igual.
8. Como dono do projeto, quero uma medida de desempenho com um banco sintético de 30 dias, para saber que a meta foi atingida.

## Implementation Decisions

- Antes de buscar os pontos, `api()` conta as amostras do período (barato, há índice em `epoch`). Até `MAX_PONTOS` → busca as linhas brutas como hoje, `passo` = `INTERVALO`.
- Acima disso → uma consulta com `GROUP BY` do índice do balde (`(epoch - desde) / tam`, truncado), `AVG` de cada campo de `CAMPOS` (o `AVG` do SQLite ignora NULL, igual à média atual) e `AVG(epoch)`, ordenada pelo balde. `passo` = `tam`.
- Pior status do balde: grau calculado com `CASE` (`ok` 0, `degradado` 1, outros 2, igual ao `GRAU`) e `MAX(grau)` com o `status` como coluna solta. O SQLite garante que, numa consulta com um único agregado `MAX()`, as colunas soltas vêm da linha que deu o máximo. Usar isso de propósito e deixar um comentário curto explicando.
- Remover `reduz()` (o agrupamento em Python), já que nada mais a usa.
- Conferir as outras consultas de `api()` no banco grande e corrigir só o que estiver lento: a busca de `ultima_queda` (`status IN (...)` ordenado por `epoch`) pode varrer o histórico inteiro se não houver quedas. Se precisar, ela pode usar a tabela `outages` em vez de `checks`.
- Sem mudança de esquema.

## Testing Decisions

- Os testes de agrupamento da spec `testes-unitarios` (feitos via `api()`) precisam continuar passando sem alteração: essa é a prova de que o comportamento não mudou.
- Acrescentar um caso com vários status de queda no mesmo balde para garantir que o status devolvido é de grau 2.
- Medida de desempenho (manual, não entra em `make test`): gerar um banco sintético de 30 dias com amostras a cada 5 s e medir `api(43200)` e `api(10080)`. Meta: menos de 0,5 s em cada.
- Prior art: testes de `api()` da spec `testes-unitarios`.

## Out of Scope

- Apagar ou resumir dados antigos (o dono quer deixar crescer).
- Cache das respostas.
- Mudar `MAX_PONTOS` ou o visual dos gráficos.

## Further Notes

- Depende de `testes-unitarios`.
- `uptime-por-dia` também consulta 30 dias a cada atualização; ela tem estratégia própria (cache dos dias fechados).
