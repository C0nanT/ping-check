# Painel: contratos testados e página em arquivos separados

Status: ready-for-agent

Origem: linhas 1 e 2 do mapa de dívida técnica `.scratch/tech-debt-map/painel/2026-10-02.md`. A linha 8 do mesmo mapa (guarda `__main__` no meio dos testes) entra aqui porque o trabalho mexe no mesmo arquivo de testes.

## Problem Statement

Quem mantém o painel precisa lembrar de mudar à mão valores que existem em mais de um lugar: a lista de status que contam como queda, o nome e a validade do arquivo de pedido de teste, o intervalo entre amostras, a duração máxima de um teste de velocidade, o limite de dias do seletor. Hoje isso é só um comentário do tipo "mesmo X do Y". Se um lado muda e o outro não, nada falha: o botão "Fazer teste completo agora" deixa de funcionar, quedas somem das contagens, ou o gráfico de Rapidez sombreia a janela errada. `make test` continua verde.

A página inteira (HTML, CSS e ~40 funções de JavaScript) vive dentro de uma string Python no meio do arquivo do servidor, e nenhum teste a toca. Mudar um texto ou uma cor exige editar um arquivo de 900 linhas, e um erro de sintaxe no JavaScript deixa a página em branco sem que nenhum teste perceba.

## Solution

1. O servidor passa a enviar na resposta de `/api` os valores que a página precisa (status de queda, intervalo, limite de espera, duração máxima de teste, folga, número de dias), e a página lê esses campos em vez de redeclará-los. Um teste de contrato compara os valores que precisam coincidir com os do monitor, de modo que a divergência quebre o `make test`.
2. O gráfico de Rapidez passa a sombrear as janelas de teste que o servidor calcula (as mesmas que ele usa para ignorar `degradado` no "agora"), não só os testes iniciados dentro do período.
3. A página é separada em arquivos `html`, `css` e `js`, servidos pelo próprio painel, sem biblioteca nem recurso externo. Um teste de fumaça garante que a página carrega e que o JavaScript é sintaticamente válido.

Para quem usa o painel nada muda na tela, exceto a correção do sombreamento na borda do período (item 2).

## User Stories

1. Como mantenedor, quero que `make test` falhe se o nome do arquivo de pedido diferir entre painel e monitor, para que o botão de teste manual nunca pare de funcionar em silêncio.
2. Como mantenedor, quero que `make test` falhe se a validade do pedido diferir entre painel e monitor, para que o painel não mostre "pedido aguardando" quando o monitor já descartou o pedido.
3. Como mantenedor, quero que `make test` falhe se o intervalo entre amostras diferir entre painel e monitor, para que a detecção de lacunas ("sem medição") não fique errada.
4. Como mantenedor, quero que a lista de status de queda do painel seja conferida contra os status que `classify()` produz, para que um status novo do monitor não suma das contagens de quedas e dias.
5. Como mantenedor, quero que a duração máxima de teste (`TESTE_MAX`) exista num só lugar para a página, para que a faixa de teste no gráfico não discorde do servidor.
6. Como mantenedor, quero que a página receba da API o intervalo entre amostras, para que os cartões de dia calculem "horas medidas" e "fora do ar" sem um `5` fixo no JavaScript.
7. Como mantenedor, quero que a página receba da API o limite de "monitor parado" (hoje 60 s), para que a mensagem "monitor não está medindo" use o mesmo valor que o servidor.
8. Como mantenedor, quero que a página receba da API o número de dias e o limite do período, para que o seletor de datas e a grade de 30 dias não repitam o `30`.
9. Como mantenedor, quero que a página receba a lista de status de queda, para que um status desconhecido no futuro conte como queda na tela, como o servidor já conta.
10. Como usuário do painel, quero que o gráfico de Rapidez sombreie o teste de velocidade que começou pouco antes do início do período escolhido, para que o pico de latência dele não pareça uma falha real.
11. Como usuário do painel, quero que o "agora" no topo e o gráfico concordem sobre quais amostras foram afetadas por um teste, para que eu não veja "instável" num lugar e "ok" no outro.
12. Como usuário do painel, quero que a página continue funcionando sem internet e sem CDN, para que ela abra em qualquer situação, mesmo com a conexão caída.
13. Como mantenedor, quero editar o texto e as cores da página em arquivos `css` e `html` próprios, para não mexer numa string `r"""` dentro de Python.
14. Como mantenedor, quero editar o JavaScript num arquivo `.js`, para ter destaque de sintaxe, verificação de sintaxe e menos cuidado com `\` e `"""`.
15. Como mantenedor, quero que um erro de sintaxe no JavaScript faça `make test` falhar, para não descobrir uma página em branco no navegador.
16. Como mantenedor, quero que `make test` falhe se a página referir um id de elemento que não existe no HTML, para pegar renomeações incompletas.
17. Como mantenedor, quero que o `AGENTS.md` descreva a nova estrutura de arquivos da página, para que a próxima sessão não procure o `PAGINA` que não existe mais.
18. Como operador no Docker, quero que o contêiner `painel` sirva a página nova sem rebuild, como hoje, para continuar usando `make restart` depois de editar.
19. Como operador no Docker, quero que a imagem `ping-check` contenha os arquivos da página, para que a imagem funcione mesmo sem o bind mount `.:/app`.
20. Como operador, quero que o healthcheck do painel (`GET /api?min=1`) continue passando, para que a mudança de arquivos não derrube o serviço.
21. Como mantenedor, quero que rodar o arquivo de testes do painel não pule `TesteAgoraTest`, para não ter falso verde nos testes do botão manual e do 429.
22. Como cliente antigo da API (aba aberta de uma versão anterior), quero que os campos novos sejam só acréscimos, para que nada existente quebre durante a atualização.
23. Como mantenedor, quero que o painel continue sem dependências além da biblioteca padrão, para manter o projeto sem build nem instalação.
24. Como mantenedor, quero que o servidor recuse caminhos fora da lista de arquivos da página (sem `..`, sem listar diretório), para que servir arquivos do disco não abra leitura arbitrária.

## Implementation Decisions

Fonte de verdade das decisões: respostas do usuário ao mapa (2026-10-02), decisões 1, 2, 5 e 6.

**Parte A: contratos (sem mudar a tela, exceto B abaixo)**

- A resposta de `/api` ganha campos aditivos: o intervalo entre amostras, o limite de "monitor parado", a lista de status de queda, `TESTE_MAX`, `TESTE_FOLGA`, o limite do período e o número de dias. Os nomes seguem o vocabulário em português já usado na resposta (`passo`, `dias`, `quedas`, …). `passo` já existe e continua sendo o intervalo efetivo dos buckets; o intervalo bruto entre amostras é um campo à parte.
- A lista de status de queda (`CAIU`) passa a ser a fonte única: o JavaScript deixa de ter a própria regra "diferente de `ok` e `degradado`" e usa a lista da API. Um status desconhecido conta como queda, como o servidor já faz (decisão 1 do mapa: o comportamento do JS vira o do Python, pela lista enviada). Os valores permanecem `sem_wifi`, `falha_lan`, `falha_internet`, `falha_dns`, `degradado`, `ok`; o contrato de strings com monitor, `CAIU`, o mapa `ST` do JS e as consultas do Makefile não muda.
- Cartões de dia: o tempo medido e o tempo fora do ar passam a usar o intervalo vindo da API em lugar do `5` fixo. Decisão 2: a aproximação "amostras × intervalo" continua aceita; só deixa de ser um literal.
- A folga de `+10` no JavaScript (`emTeste`) deixa de existir como número solto; ver Parte B.
- O servidor passa a enviar as janelas de teste (início e fim já com `TESTE_MAX` e `TESTE_FOLGA` aplicados), calculadas com a mesma regra de `amostras_recentes`, cobrindo testes iniciados antes do período mas cuja janela toca o período. O JavaScript apenas desenha. É a correção do achado 3 do mapa.
- Teste de contrato (`ContratoMonitorTest` ou nome equivalente): confere que o nome do arquivo de pedido, a validade, o intervalo e os status de queda coincidem com o monitor; os status de queda são derivados do que `classify()` pode devolver, menos `ok`/`degradado`. O painel **não** importa o monitor em produção; só o teste importa os dois.
- Os campos novos são puramente aditivos; nenhum campo existente muda de nome ou de forma.

**Parte B: página em arquivos**

- A página passa a ser três arquivos estáticos (estrutura, estilo e script), ao lado do servidor ou em subpasta dedicada, servidos pelo `H` do painel. Continua sem biblioteca, sem CDN, sem recurso externo; as chamadas de rede da página são só para o próprio painel.
- Rotas: `/` serve o HTML; o CSS e o JS são servidos por rotas fixas e conhecidas (lista fechada, não um servidor de arquivos genérico). Qualquer outro caminho continua em 404. O tipo de conteúdo e a codificação UTF-8 são enviados corretamente.
- A string `PAGINA` deixa de existir. O contrato "HTML/CSS/JS inlined; nenhum asset externo" do `AGENTS.md` é substituído por "arquivos estáticos locais servidos pelo próprio painel; nenhum asset externo/CDN". Essa atualização faz parte da mudança.
- O Dockerfile hoje copia só os dois scripts para a imagem; passa a copiar também os arquivos da página. Em runtime o bind mount `.:/app` já os traz; o `COPY` garante a imagem autossuficiente.
- O healthcheck (`GET /api?min=1`) não depende da página e permanece como está.
- Ordem: primeiro o teste de fumaça sobre a página como ela é hoje (verde antes de mover), depois a separação, para que o teste prove que nada mudou.
- As regras de apresentação (herói "≥3 de 12", plano Anatel 0,8/0,4, cores 99/95, limites de rapidez/estabilidade/sinal) **ficam no JavaScript**. Decisão 6 do mapa: não mover para Python agora.

**Parte C: higiene dos testes**

- A guarda `if __name__ == "__main__": unittest.main()` sai do meio do arquivo de testes (apagada ou movida para o fim); o Makefile já usa `discover`.

## Testing Decisions

- **Um bom teste aqui** exercita o comportamento externo: o JSON de `/api`, a resposta HTTP de `GET /` e dos arquivos estáticos, e o fato de a página carregar e ser válida. Não testa nomes de funções internas nem a ordem de consultas SQL.
- **Seams propostos** (o mais alto possível; preferir os que já existem):
  1. **`GET /api` via o servidor real em thread** (já é o padrão de `HandlerTest`/`ApiBase` no arquivo de testes do painel). Cobre os campos novos, as janelas de teste e a compatibilidade aditiva.
  2. **Constantes dos dois módulos lado a lado** (`painel` × `monitor`, ambos já importados no arquivo de testes). Cobre o contrato.
  3. **`GET /` e as rotas estáticas via o mesmo servidor em thread.** Cobre carregamento, tipos de conteúdo, 404 fora da lista e a presença dos ids que o JavaScript procura.
  4. **`node --check` sobre o arquivo `.js`**, *pulado* se `node` não existir na máquina (o projeto continua só com biblioteca padrão; a verificação é opcional e não vira dependência).
  Os quatro seams ficam em um único arquivo de testes do painel; nenhum seam novo no monitor.
- **Arte prévia:** `ApiBase` (banco temporário com o `SCHEMA` do monitor, relógio fixo `AGORA`), `HandlerTest`/`H.get` para chamadas HTTP, `BancoAntigoTest` para banco sem tabelas novas (os campos novos não podem exigir tabela nova), `NotaCargaTest`/`PeriodoTest`/`DiasTest` para o estilo de teste de regra.
- Testes de regressão obrigatórios: banco antigo continua respondendo; janelas de teste incluem um teste iniciado antes de `de` cuja janela alcança o período; o status de queda desconhecido conta como queda na lista enviada.
- `make test` roda tudo sem rede, Docker nem banco real, como hoje.

## Out of Scope

- Mover as regras de apresentação do JavaScript para Python (decisão 6).
- Achados 4 a 7 do mapa: extrair `api()`, erros 500 sem vazamento e com log, chave estável em `nota_carga`, validação de `Host`. Cada um merece spec ou ticket próprio.
- O custo de polling em janelas largas (pergunta em aberto do mapa; falta medir com 30 dias de dados).
- O módulo Monitor e qualquer mudança em `monitor.py`; o monitor continua sendo só lido pelo teste de contrato.
- Mudança visual além da correção de borda das janelas de teste.
- Bundler, minificação, framework ou qualquer dependência de build.

## Further Notes

- **Seams a confirmar com o usuário** (passo 3 do `/to-spec`): os quatro acima. Meu palpite é que servem; o único que pode incomodar é o `node --check` opcional.
- Risco da Parte B: o servidor passa a ler arquivos do disco. A lista fechada de rotas (história 24) evita virar um servidor de arquivos genérico.
- Raio de impacto da Parte B é Module+ (Dockerfile e `AGENTS.md` mudam junto); a Parte A é contida.
- Ordem sugerida de tickets: (1) teste de contrato e guarda `__main__`; (2) campos novos na API + JS passa a usá-los + janelas de teste; (3) teste de fumaça sobre a página atual; (4) separação em arquivos + Dockerfile + `AGENTS.md`.
