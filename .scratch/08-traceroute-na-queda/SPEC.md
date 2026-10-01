# Traceroute automático quando a internet cai

Status: ready-for-agent

## Problem Statement

Quando o status é `falha_internet`, o painel diz que "normalmente é um problema da operadora", mas não mostra onde o sinal parou. Para o usuário (e para o atendente da operadora) faz diferença saber se o sinal nem saiu do roteador/modem ou se entrou na rede da operadora e parou lá dentro.

## Solution

Quando começa uma queda `falha_internet`, o monitor roda em segundo plano um `tracepath` até 1.1.1.1 e guarda o caminho percorrido junto com a queda. No painel, na lista "Quando a conexão falhou", a queda mostra uma frase simples, como "O sinal parou no seu roteador: a internet não está saindo de casa" ou "O sinal passou do roteador e parou na rede da operadora (3º ponto do caminho)". O caminho completo fica dentro de um "ver caminho" recolhido.

## User Stories

1. Como usuário, quero saber onde o sinal parou quando a internet cai, para saber se o problema é em casa ou na operadora.
2. Como usuário, quero uma frase simples em português, não uma tabela de IPs.
3. Como usuário, quero poder abrir o caminho completo, para passar para o suporte técnico da operadora.
4. Como usuário, quero que o diagnóstico fique salvo na queda, para consultar depois que a internet voltar.
5. Como usuário, quero que o diagnóstico rode sozinho, sem eu fazer nada.
6. Como dono, quero que o diagnóstico não atrase as medições de 5 s.
7. Como dono, quero no máximo um diagnóstico por queda, para não gerar tráfego nem processos em excesso.
8. Como dono, quero que o diagnóstico só rode em `falha_internet` (em `falha_lan` o roteador nem responde; em `sem_wifi` não há rede).
9. Como dono, quero que pontos do caminho que não respondem ("sem resposta") sejam tratados direito, porque muitos roteadores de operadora não respondem.
10. Como dono, quero que funcione sem root, no host e no container.
11. Como dono, quero que um banco existente ganhe a tabela nova sozinho, sem migração manual.
12. Como dono, quero que, se o `tracepath` falhar ou não existir, a queda continue sendo registrada normalmente.

## Implementation Decisions

- Ferramenta: `tracepath -n -m 15 1.1.1.1` (iputils; usa UDP, não precisa de root nem de capability). Dockerfile ganha o pacote `iputils-tracepath`. Timeout do subprocesso de ~30 s.
- Execução: quando o laço abre uma queda `falha_internet`, submete o diagnóstico a um executor e **não espera**. A cada ciclo seguinte, o laço verifica se o futuro terminou e, se sim, grava o resultado. Toda escrita no banco continua na thread principal (a conexão SQLite é de uma thread só). Se o monitor parar antes de o diagnóstico terminar, ele é descartado.
- Esquema: nova tabela `rotas` (`CREATE TABLE IF NOT EXISTS`, então um banco existente a ganha sozinho): `id`, `outage_id`, `ts`, `epoch`, `alvo`, `saltos` (JSON: lista de `{n, ip|null, ms|null}`), `ultimo_ok` (número do último salto que respondeu ou NULL), `saida` (texto bruto), `erro` (texto ou NULL).
- Parser puro da saída do `tracepath` → lista de saltos + último salto que respondeu (padrão de parser da spec `01-testes-unitarios`).
- Interpretação (no painel, função pura em Python que devolve a frase): nenhum salto respondeu ou só o gateway → "parou no seu roteador/modem"; respondeu algum salto depois do gateway → "passou do roteador e parou na rede da operadora (Nº ponto)"; erro → sem frase.
- `/api`: cada item de `quedas` passa a incluir `rota` (`{"frase", "saltos"}` ou `null`), buscada pelo `outage_id`. A consulta de quedas passa a trazer o `id` da queda.
- Frontend: frase como linha extra no item da lista; `<details>` "ver caminho" com tabela simples (ponto, IP, tempo).

## Testing Decisions

- Parser do `tracepath`: saídas reais de exemplo guardadas no teste — caminho completo, caminho com `no reply` no meio, só o gateway respondendo, nenhum salto.
- Interpretação: os casos de saltos acima → frase esperada.
- `api()` com banco temporário: queda com linha em `rotas` → `rota` preenchida; sem linha → `null`.
- Não testar a execução real do `tracepath` nem o laço.
- Prior art: parser do `ping` e testes de `api()` da spec `01-testes-unitarios`.

## Out of Scope

- Repetir o diagnóstico durante quedas longas, ou rodar ao voltar.
- Diagnóstico para `falha_dns`, `falha_lan`, `sem_wifi`.
- MTR contínuo, IPv6, geolocalização ou nome do provedor por IP.

## Further Notes

- Depende de `01-testes-unitarios`.
- O texto das frases deve seguir o tom do mapa `ST` (português simples, sem jargão).
