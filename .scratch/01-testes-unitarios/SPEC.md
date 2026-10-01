# Testes unitários (stdlib)

Status: ready-for-agent

## Problem Statement

O projeto não tem nenhum teste. As regras que decidem o que o usuário vê — a classificação de cada amostra (`classify()`), a leitura da saída do `ping`, o agrupamento de pontos do painel e o fechamento de quedas sem `end_epoch` — só são verificadas olhando o painel rodando. Qualquer mudança nas próximas specs (DNS, SQL agregado, `degradado`, uptime por dia, traceroute, velocidade) pode quebrar essas regras sem ninguém perceber.

## Solution

Uma suíte de testes com `unittest` da stdlib (sem dependências, como o resto do projeto), rodada por `make test`. Ela testa o comportamento nas duas costuras mais altas que já existem:

- **Monitor**: `classify()` e os parsers puros de saída de comandos (começando pelo do `ping`).
- **Painel**: `api(minutos)` contra um banco SQLite temporário criado com o `SCHEMA` do monitor.

Nenhum teste roda `ping`, `ip`, `nmcli` ou acessa a rede.

## User Stories

1. Como dono do projeto, quero rodar `make test` e ver em segundos se tudo passou, para mudar o código sem medo.
2. Como dono do projeto, quero que os testes não precisem de internet, Docker, Wi-Fi nem root, para rodar em qualquer lugar.
3. Como dono do projeto, quero que os testes não instalem nada, para manter o projeto só com stdlib.
4. Como dono do projeto, quero que os testes nunca toquem no `conexao.db` real, para não sujar nem apagar meu histórico.
5. Como dono do projeto, quero um teste para cada status de `classify()` (`sem_wifi`, `falha_lan`, `falha_internet`, `falha_dns`, `degradado`, `ok`), para garantir a ordem de prioridade.
6. Como dono do projeto, quero testes de quando dois problemas acontecem juntos (ex.: sem gateway e sem DNS), para garantir que vence o de maior prioridade.
7. Como dono do projeto, quero testes do parser do `ping` com saída normal, 100% de perda e saída sem linha de RTT, para que mudanças no formato não virem números errados.
8. Como dono do projeto, quero testes de `api()` com poucas amostras, para garantir que os pontos voltam sem agrupar e com `passo` = intervalo do monitor.
9. Como dono do projeto, quero testes de `api()` com mais amostras que `MAX_PONTOS`, para garantir que o agrupamento usa média dos valores e o pior status do balde.
10. Como dono do projeto, quero um teste de que baldes vazios somem, para que períodos com o monitor desligado continuem aparecendo como buraco.
11. Como dono do projeto, quero um teste de queda com `end_epoch` NULL, para garantir que ela termina na primeira amostra seguinte com outro status.
12. Como dono do projeto, quero um teste de que uma queda ainda aberta com o monitor parado termina na última amostra, para o painel não mostrar "acontecendo agora" errado.
13. Como dono do projeto, quero um teste de `falhas` (número e segundos somados) recortado ao período, para que quedas que começaram antes da janela não contem tempo extra.
14. Como dono do projeto, quero testes de `atual`, `recentes`, `inicio_atual` e `ultima_queda`, para que o cartão principal do painel diga a coisa certa.
15. Como agente implementando as próximas specs, quero esses testes já prontos, para provar que a mudança não quebrou o comportamento atual.

## Implementation Decisions

- Framework: `unittest` da stdlib, descoberto por `python3 -m unittest`. Nova meta `make test` usando o `$(PYTHON)` fixado no Makefile, listada em `make help`.
- Os testes ficam num diretório próprio na raiz do repositório, um arquivo por script (monitor, painel).
- **Extração no monitor**: a leitura da saída do `ping` sai de dentro de `ping()` para uma função pura que recebe o texto e devolve o dict `loss/avg/max/jitter`. `ping()` passa a chamar essa função. O comportamento não muda. Esse é o padrão para os parsers das próximas specs (tracepath, velocidade, latência sob carga).
- **Banco de teste**: cada teste cria um SQLite temporário com o `SCHEMA` do monitor e insere linhas em `checks`/`outages` com `epoch` relativo a `time.time()`. O painel lê o caminho do banco de uma constante de módulo; o teste troca essa constante para o arquivo temporário. O painel continua abrindo com `mode=ro`.
- Importar `monitor` ou `painel` não pode ter efeito colateral (os dois já protegem o `main` com `if __name__ == "__main__"`); manter assim.
- Atualizar o `CLAUDE.md`: tirar "no tests" e citar `make test`.

## Testing Decisions

- Bom teste = testa comportamento externo: entrada de `classify()`/parser → valor devolvido; linhas no banco → JSON de `api()`. Não testa funções internas como `reduz()` diretamente, nem nomes de variáveis ou SQL.
- Agrupamento de pontos é testado **via `api()`**, não via `reduz()`, porque a spec `04-painel-sql-agregado` substitui `reduz()` por SQL e os testes precisam continuar valendo.
- Módulos testados: `classify()`, parser do `ping`, `api()`.
- Não há prior art no repo; esta spec cria o padrão.

## Out of Scope

- Testar `main()` do monitor (laço, rastreio de quedas, sinais), `default_route()`, `wifi_signal()`, `wifi_info()`, `dns_check()` com comandos reais.
- Testar o JavaScript do painel ou o HTML.
- CI, cobertura, linter.

## Further Notes

- Fazer esta spec **primeiro**: as outras (`02-degradado-dois-alvos`, `03-dns-sem-travar`, `04-painel-sql-agregado`, `05-tamanho-banco`, `07-uptime-por-dia`, `08-traceroute-na-queda`, `09-teste-velocidade`, `10-bufferbloat`) acrescentam testes em cima desta base.
