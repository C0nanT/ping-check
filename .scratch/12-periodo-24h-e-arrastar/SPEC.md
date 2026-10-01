# Período: horário 24 h e arrastar para filtrar

Status: ready-for-agent

## Problem Statement

O seletor "Escolher datas" (já feito: `/api?de=&ate=`, formulário De/Até) usa `<input type="datetime-local">`. O navegador desenha esse campo no idioma **dele**, não no da página (`lang="pt-BR"` não muda isso). Num navegador em inglês, a hora aparece como 12 h com AM/PM, o que confunde. O resto do painel já usa 24 h (`toLocaleTimeString('pt-BR', …)`).

Para olhar de perto um trecho que chamou atenção no gráfico "Como foi o período", hoje o usuário precisa ler os horários no tooltip e digitar no formulário. Seria mais natural clicar, segurar e arrastar sobre o trecho.

## Solution

1. **Horário sempre em 24 h:** o formulário passa a ter, para De e Até, um campo de data (`type="date"`, que não tem AM/PM) e um campo de hora próprio no formato `HH:MM` (00:00–23:59), em vez do `datetime-local`.
2. **Arrastar para filtrar:** no gráfico "Como foi o período" (canvas `#tl`), clicar, segurar e arrastar desenha uma faixa de seleção. Ao soltar, o painel passa a mostrar exatamente aquele trecho, como se tivesse sido escolhido em "Escolher datas".

## User Stories

1. Como usuário, quero ver e digitar horas como 14:30, nunca como 2:30 PM, em qualquer navegador.
2. Como usuário, quero arrastar sobre um trecho vermelho ou amarelo da linha do tempo e ver só aquele trecho.
3. Como usuário, enquanto arrasto, quero ver de que horário até que horário estou selecionando.
4. Como usuário, quero poder desistir no meio do arrasto (soltar sem mover, ou apertar Esc).
5. Como usuário, depois de dar zoom, quero voltar facilmente para "Última hora", "24 horas" etc.
6. Como usuário, quero poder arrastar de novo dentro do trecho já filtrado, para chegar mais perto.

## Implementation Decisions

Só frontend (`PAGINA` em `painel.py`). Backend e `/api` não mudam: o arrasto produz um `FAIXA = {de, ate}` igual ao do formulário.

**Hora 24 h**
- De e Até viram, cada um, `<input type="date">` + `<input type="text" inputmode="numeric" maxlength="5" placeholder="hh:mm">`, rotulados juntos ("De" / "Até").
- Validação da hora por regex `^([01]?\d|2[0-3]):[0-5]\d$`. Aceitar `9:05` e normalizar para `09:05`. Erro em português no `#derro` existente ("Hora inválida: use o formato 14:30.").
- Montar o epoch com `new Date(ano, mes-1, dia, h, m)` (hora local), nunca com string ISO sem fuso.
- Preenchimento ao abrir: a partir de `D.de`/`D.ate`, com os campos da data local (a função `local()` atual vira duas: data `AAAA-MM-DD` e hora `HH:MM`).
- `max` de data no campo De continua sendo hoje. As validações atuais continuam: início antes do fim, início antes de agora e no máximo 30 dias.
- Conferir que todo texto de hora no painel continua em 24 h (`hm()`, `quando()`, `upd`, eixos). Todos usam `'pt-BR'`, que já é 24 h. Se algum `toLocale*` estiver sem locale, passar `'pt-BR'` (e `hourCycle:'h23'` onde houver hora).

**Arrastar no "Como foi o período"**
- Pointer events no `#tl` (`pointerdown` → `setPointerCapture` → `pointermove` → `pointerup`). Isso funciona com mouse e toque. O `touch-action:pan-y` atual mantém a rolagem vertical no celular, e o arrasto horizontal vira seleção.
- Converter x → epoch com a mesma escala do `timeline()` (`x0 + x/W*(x1-x0)`, com `[x0, x1] = janela()`). Limitar a `[x0, x1]`.
- Durante o arrasto:
  - desenhar a faixa sobre o gráfico (redesenha a base e põe um retângulo semitransparente com `--band` e borda `--axis`);
  - o tooltip mostra "De 14:05 até 15:20", com a data quando o período não é de um dia só (reaproveitar `dm`/`hm`/`mesmoDia`);
  - o hover normal fica suspenso.
- Ao soltar:
  - Se o arrasto for menor que 6 px **ou** menor que 60 s, é um clique: não faz nada.
  - Se não, arredondar `de` para baixo e `ate` para cima, ao minuto. Depois `FAIXA = {de, ate}`, fechar o formulário se estiver aberto e chamar `trocaPeriodo()`. Isso já marca "Escolher datas" como ativo e mostra "Mostrando de … até …" no topo.
- Esc durante o arrasto cancela (some a faixa, volta o hover).
- Cursor `crosshair` no `#tl`.
- Legenda do cartão: acrescentar "Clique e arraste para ver um trecho de perto." ao `.cap` atual.
- Voltar: os botões de período existentes já limpam `FAIXA`. Não criar um botão extra.
- Escopo: só o `#tl`. Os outros gráficos continuam só com hover.
- Organização: o arrasto vai numa função própria (`arrasto(cv)`, ao lado de `hover(cv)`), que só conhece a escala do canvas e um callback `(de, ate)`. O `timeline()` expõe a escala (por exemplo `cv._x2e`), como já faz com `_h`/`_mark`. Assim dá para ligar o arrasto em outro gráfico depois sem mexer nele.

## Testing Decisions

- Não há teste de JS no repositório (só `unittest` do stdlib). O backend não muda, então `make test` deve continuar passando sem testes novos.
- Checar a sintaxe: extrair o `<script>` de `PAGINA` e rodar `node --check` (se houver node).
- Checagem manual com `PORT=8081 make web`:
  - navegador em inglês: o formulário mostra 24 h;
  - `9:5`, `24:00` e `ab` dão erro; `9:05` é aceito;
  - arrastar seleciona e filtra, e o topo mostra o período;
  - um clique simples não filtra;
  - Esc cancela;
  - arrastar de novo dá mais zoom;
  - um preset volta ao normal;
  - no celular (ou nas devtools em modo touch), arrastar na horizontal seleciona e na vertical rola a página.

## Out of Scope

- Arrastar nos gráficos Rapidez / Velocidade / Sinal.
- Clicar num dia do quadro "Últimos 30 dias" para filtrar aquele dia (boa ideia para depois).
- Histórico de zoom ("voltar ao período anterior").
- Seletor de data próprio (o `type="date"` nativo continua, mesmo que mostre a data no formato do navegador; ele não tem AM/PM).

## Further Notes

- Depende do filtro por intervalo de datas já implementado (`periodo()`, `/api?de=&ate=`, `FAIXA`, `trocaPeriodo()`).
- O intervalo escolhido por arrasto também não é salvo no `localStorage`, como o do formulário.
