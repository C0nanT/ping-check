# Teste de velocidade periódico

Status: ready-for-agent

## Problem Statement

O monitor mede se a internet funciona e quão rápido ela responde (latência), mas não a velocidade de download e upload. O usuário não consegue saber se está recebendo a velocidade contratada, nem se ela cai em certos horários.

## Solution

A cada 30 minutos o monitor faz um teste de velocidade em segundo plano usando os servidores da Cloudflare: baixa ~25 MB e envia ~10 MB, e grava o resultado em Mbps. O painel mostra um cartão "Velocidade" com o último resultado e um gráfico de download/upload no período escolhido. Os momentos de teste aparecem marcados no gráfico de rapidez, para o usuário entender o pico de latência que o teste causa.

## User Stories

1. Como usuário, quero ver a velocidade de download e upload da minha internet, para comparar com o plano contratado.
2. Como usuário, quero que o teste rode sozinho a cada 30 minutos.
3. Como usuário, quero ver como a velocidade variou ao longo do dia e da semana.
4. Como usuário, quero ver o último resultado e quando ele foi medido.
5. Como usuário, quero os termos em português simples ("Baixar (download)", "Enviar (upload)", "Mbps").
6. Como usuário, quero que o teste não faça o painel dizer que a internet está instável só por causa dele.
7. Como usuário, quero ver no gráfico de rapidez quando um teste estava rodando.
8. Como dono, quero que o teste não pule nem atrase as medições de 5 s.
9. Como dono, quero que o teste não rode quando a internet está fora do ar, porque é inútil.
10. Como dono, quero poder mudar o intervalo ou desligar o teste por variável de ambiente (ex.: em rede com franquia).
11. Como dono, quero saber o tráfego gasto (~35 MB por teste, ~1,7 GB por dia).
12. Como dono, quero que um teste que falhe (timeout, erro HTTP) fique registrado com o erro, sem derrubar o monitor.
13. Como dono, quero que um banco existente ganhe a tabela nova sozinho.
14. Como dono, quero que o teste use só stdlib.

## Implementation Decisions

- Alvos: download por GET em `speed.cloudflare.com/__down?bytes=25000000`; upload por POST de 10 MB em `speed.cloudflare.com/__up`. Cliente `urllib` da stdlib.
- Medida: Mbps = bytes × 8 ÷ segundos, contando do primeiro byte recebido (download) / do início do envio (upload) até o fim, para excluir DNS/TLS. Timeout por fase de ~30 s.
- Agendamento: função pura que, dada a hora atual, a hora do último teste e o status atual, decide se é hora de testar. Testa se passou o intervalo **e** o status atual não é de queda. Primeiro teste ~1 minuto depois de o monitor iniciar.
- Configuração: variável `VELOCIDADE_A_CADA` em minutos, padrão 30; `0` desliga.
- Execução: mesmo padrão da spec `08-traceroute-na-queda` — o teste roda num executor sem bloquear o ciclo, e a thread principal grava o resultado quando o futuro termina. Nunca dois testes ao mesmo tempo.
- Esquema: nova tabela `velocidade` (`CREATE TABLE IF NOT EXISTS`): `id`, `ts`, `epoch` (início), `fim_epoch`, `down_mbps`, `up_mbps`, `bytes_down`, `bytes_up`, `erro`.
- Amostras de `checks` durante um teste são gravadas normalmente (os dados continuam honestos). No painel: o cartão principal (que olha as amostras recentes) ignora amostras `degradado` que caem dentro de uma janela de teste; o gráfico de rapidez desenha a janela como faixa discreta com legenda "teste de velocidade". O uptime não é afetado (só status de queda contam como fora do ar).
- `/api` ganha `velocidade`: lista de testes do período (`epoch`, `fim`, `down`, `up`, `erro`) e o último teste bem-sucedido, mesmo que fora do período.
- Frontend: quinto tile "Velocidade" (último download/upload e "medido há X"); cartão com gráfico de linhas usando o `lineChart` existente (download `--s1`, upload `--s2`), pontos ligados só entre testes consecutivos.

## Testing Decisions

- Agendamento (função pura): antes do intervalo → não; depois → sim; status de queda → não; intervalo 0 → nunca.
- Cálculo de Mbps: bytes/tempo conhecidos → valor esperado.
- `api()` com banco temporário: testes no período aparecem; o último teste bem-sucedido vem mesmo fora do período; testes com erro aparecem com `erro` e sem Mbps.
- Não testar a rede real.
- Prior art: testes de `api()` e parsers da spec `01-testes-unitarios`.

## Out of Scope

- Escolher servidor, várias conexões em paralelo, teste multi-thread.
- Comparar com a velocidade contratada (o usuário não informa o plano ainda).
- Alertas de velocidade baixa.

## Further Notes

- Depende de `01-testes-unitarios`. A spec `10-bufferbloat` estende esta.
- `speed.cloudflare.com/__down` e `__up` são endpoints públicos sem contrato formal; se mudarem, o teste passa a registrar `erro`.
- Decisão tomada pelo agente, para confirmar na revisão: o cartão principal ignora `degradado` dentro da janela de teste, em vez de pausar as medições durante o teste (pausar criaria buracos de "sem medição" e esconderia quedas reais).
