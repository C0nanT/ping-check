# Latência sob carga (bufferbloat)

Status: ready-for-agent

## Problem Statement

Muitas conexões têm boa velocidade, mas ficam muito mais lentas para responder quando alguém está baixando ou enviando algo: chamadas de vídeo travam e jogos ficam com atraso. Isso se chama bufferbloat, e o painel hoje não mostra.

## Solution

Durante cada teste de velocidade (spec `teste-velocidade`), o monitor mede a latência até 1.1.1.1 em três momentos: parado (antes do teste), enquanto baixa e enquanto envia. O painel mostra quanto a internet "fica mais lenta quando está em uso", com uma nota simples (Ótimo / Bom / Razoável / Ruim) e uma frase do tipo "Quando alguém baixa algo, a resposta fica 120 ms mais lenta: chamadas de vídeo podem travar".

## User Stories

1. Como usuário, quero saber se minha internet trava quando alguém está baixando ou enviando algo.
2. Como usuário, quero uma nota simples e uma frase explicando o que ela significa no dia a dia.
3. Como usuário, quero ver separadamente o efeito de baixar e de enviar.
4. Como usuário, quero ver se isso piora em certos horários.
5. Como dono, quero que a medida aconteça junto com o teste de velocidade, sem tráfego extra.
6. Como dono, quero usar a mediana dos pings, para um pico isolado não estragar a nota.
7. Como dono, quero que funcione sem root, no host e no container.
8. Como dono, quero que um banco existente ganhe a tabela nova sozinho.
9. Como dono, quero que, se a medida de latência falhar, o resultado de velocidade continue sendo gravado.

## Implementation Decisions

- Dentro do teste de velocidade: ~5 s de ping parado antes do download; depois ping contínuo durante a fase de download e durante a de upload. `ping -n -i 0.2` até 1.1.1.1 com prazo igual à duração da fase (0,2 s é o menor intervalo permitido sem root).
- Parser puro da saída do `ping` **sem `-q`**: extrai o tempo de cada resposta (`time=X ms`) e conta perdidos → mediana e perda %. Fica junto do parser de `ping` existente.
- Esquema: nova tabela `latencia_carga` (`CREATE TABLE IF NOT EXISTS`) ligada ao teste: `velocidade_id`, `ocioso_ms`, `down_ms`, `up_ms`, `down_perda`, `up_perda`. Tabela separada, e não colunas novas em `velocidade`, porque o esquema não tem migração (`ALTER TABLE`) e `velocidade` pode já existir num banco.
- Nota pelo **acréscimo** (pior fase − parado): < 30 ms Ótimo (`good`), < 60 ms Bom (`good`), < 200 ms Razoável (`warning`), acima Ruim (`critical`). Função pura de classificação no painel.
- `/api`: cada item de `velocidade` ganha `carga` (`{ocioso, down, up, nota}` ou `null`).
- Frontend: no cartão "Velocidade", uma linha "Quando a internet está em uso" com ícone da nota, a frase e os números (parado / baixando / enviando) no estilo dos tiles. Os números brutos também em "Detalhes técnicos".

## Testing Decisions

- Parser de ping sem `-q`: saída com várias respostas → mediana certa; com respostas faltando → perda certa; sem nenhuma resposta → mediana `None`, perda 100%.
- Classificação da nota: os limites (29, 30, 59, 60, 199, 200 ms) → nota esperada.
- `api()` com banco temporário: teste com linha em `latencia_carga` → `carga` preenchida; sem linha → `null`.
- Prior art: testes de parser e de `api()` das specs `testes-unitarios` e `teste-velocidade`.

## Out of Scope

- Medir bufferbloat fora do teste de velocidade.
- Recomendar configurações do roteador (SQM/QoS).
- Outros alvos de ping durante o teste.

## Further Notes

- Depende de `teste-velocidade` (e, por ela, de `testes-unitarios`).
- Os limites da nota seguem os usados por testes públicos de bufferbloat; ajustáveis depois.
