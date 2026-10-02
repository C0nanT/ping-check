# 02: API envia constantes e janelas de teste; a página deixa de redeclará-las

> **Difficulty:** Standard: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** a resposta de `/api` ganha campos aditivos com os valores que a página precisa: intervalo entre amostras, limite de "monitor parado", lista de status de queda, `TESTE_MAX`, `TESTE_FOLGA`, limite do período e número de dias. A página lê esses campos e para de declarar `5`, `60`, `30`, `TESTE_MAX=90`, a folga `+10` e a regra "diferente de `ok`/`degradado`"; um status desconhecido continua contando como queda, agora pela lista enviada. O servidor também envia as janelas de teste (início e fim com `TESTE_MAX` e `TESTE_FOLGA` aplicados, mesma regra de `amostras_recentes`), inclusive de teste iniciado antes do início do período cuja janela alcança o período, e o gráfico de Rapidez sombreia essas janelas. Nada existente muda de nome ou forma; para o usuário a tela fica igual, exceto a correção de borda do sombreamento.

**Blocked by:** 01 (o teste de contrato já protege a lista de status e as constantes que este ticket passa a enviar).

**Status:** ready-for-agent

- [ ] `/api` devolve os campos novos, sem remover nem renomear nenhum campo existente
- [ ] O JS não contém mais os literais `5` (intervalo), `60` (parado), `30` (dias/período), `TESTE_MAX=90` nem `+10`; usa os campos da API
- [ ] Um status desconhecido conta como queda na UI (via lista enviada), igual ao servidor
- [ ] Um teste de velocidade iniciado antes de `de`, com janela que alcança o período, aparece nas janelas enviadas e fica sombreado no gráfico de Rapidez
- [ ] Banco antigo (sem tabelas novas) continua respondendo, com os campos novos presentes (`BancoAntigoTest`)
- [ ] Teste de regressão para as janelas e para o campo de status de queda; `make test` passa
- [ ] Conferido no navegador (`make web`): cartões de dia, "monitor não está medindo", seletor de datas e gráfico de Rapidez se comportam como antes
