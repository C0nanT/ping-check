# `degradado` considera os dois servidores

Status: ready-for-agent

## Problem Statement

Uma amostra vira `degradado` por latência só quando a Cloudflare passa de 150 ms; o Google é ignorado. Se a Cloudflare estiver lenta e o Google rápido, o painel diz "instável" com a internet funcionando bem. Se a Cloudflare falhar toda (sem média) e o Google estiver lento, a lentidão não aparece. Isso é incoerente com a regra de perda, que já usa o melhor dos dois (`min`).

## Solution

A latência para `degradado` passa a ser a **melhor média entre Cloudflare e Google**: a internet só é considerada lenta quando **os dois** passam de 150 ms. Quando só um respondeu, vale a média desse.

## User Stories

1. Como usuário do painel, quero que a internet só apareça como "instável" por lentidão quando ela estiver lenta de verdade, para não me preocupar à toa.
2. Como usuário, quero que um servidor lento sozinho (problema dele, não meu) não marque minha conexão como instável.
3. Como usuário, quero que, se só o Google responder e estiver lento, a lentidão apareça, para não esconder um problema real.
4. Como dono do projeto, quero que perda e latência sigam o mesmo critério ("melhor dos dois"), para a regra ser fácil de explicar.
5. Como dono do projeto, quero que a ordem de prioridade dos status não mude, para não quebrar o contrato com o painel e o Makefile.
6. Como dono do projeto, quero testes cobrindo os casos de um alvo lento, os dois lentos e um alvo sem resposta.
7. Como usuário, quero que o texto do painel ("demorou mais de 150 ms") continue verdadeiro depois da mudança.

## Implementation Decisions

- Só muda o critério de latência dentro de `classify()`: em vez da média da Cloudflare, usa o menor valor entre as médias disponíveis de Cloudflare e Google. Sem média disponível em nenhum dos dois → a latência não marca `degradado` (esse caso já é `falha_internet` pela perda de 100%).
- Limite continua 150 ms; perda continua `min` dos dois; ordem e nomes dos status não mudam (contrato com `CAIU`, `ST` e Makefile intacto).
- Dados antigos em `checks` **não** são reclassificados.
- Revisar o texto em "Detalhes técnicos" do painel: deixar claro que "demorou mais de 150 ms" vale para os dois servidores.

## Testing Decisions

- Testes de `classify()` (base da spec `01-testes-unitarios`): Cloudflare 200 ms + Google 40 ms → `ok`; os dois > 150 → `degradado`; Cloudflare sem média + Google 200 ms → `degradado`; Cloudflare sem média + Google 40 ms → `ok`; perda > 0 em qualquer alvo continua igual ao comportamento atual.
- Prior art: testes de `classify()` da spec `01-testes-unitarios`.

## Out of Scope

- Mudar o limite de 150 ms, os limites de perda ou a regra de `falha_*`.
- Reclassificar histórico.

## Further Notes

- Depende de `01-testes-unitarios`.
- Nota de SOLID (OCP): esta mudança mexe no `if` encadeado de `classify()` sem criar um status novo; não acrescenta ramo.
