# Painel rodando no Docker

Status: ready-for-agent

## Problem Statement

Só o monitor roda no container. Para ver o painel é preciso deixar um terminal aberto com `make web`; fechar o terminal, reiniciar o computador ou sair da sessão derruba o painel, enquanto o monitor continua gravando sozinho.

## Solution

O painel vira um segundo serviço no `compose.yaml`, com a mesma imagem, iniciado e parado junto com o monitor (`make start` / `make stop`) e religado sozinho (`restart: unless-stopped`). Continua em `http://127.0.0.1:8080`, acessível só do próprio computador. `make web` continua existindo para rodar em primeiro plano durante o desenvolvimento.

## User Stories

1. Como usuário, quero abrir `http://127.0.0.1:8080` a qualquer hora sem ter rodado nada no terminal.
2. Como usuário, quero que o painel volte sozinho depois de reiniciar o computador, como o monitor.
3. Como dono, quero que `make start`, `make stop`, `make restart`, `make status` e `make logs` cuidem dos dois serviços.
4. Como dono, quero que o painel continue acessível só desta máquina (127.0.0.1), não da rede.
5. Como dono, quero que mudanças no código do painel valham depois de `make restart`, sem rebuild, como no monitor.
6. Como dono, quero um healthcheck no painel, para `make status` mostrar se ele está respondendo.
7. Como dono, quero que o painel no container rode sem root e não consiga escrever no banco.
8. Como dono, quero continuar podendo usar `make web` para desenvolver, com uma mensagem clara se a porta já estiver ocupada pelo container.
9. Como dono, quero poder mudar a porta pela variável `PORT`, como hoje.
10. Como dono, quero que o painel não impeça o monitor de subir se ele falhar (e vice-versa).

## Implementation Decisions

- Novo serviço `painel` no compose, `image: ping-check` (a mesma do monitor, sem build próprio), `command` rodando o painel com Python sem buffer, `restart: unless-stopped`, `init: true`.
- `network_mode: host`: o painel continua fazendo bind em 127.0.0.1 do host, sem publicar porta na rede.
- Usuário: `user: "1000:1000"` **neste serviço** — ele não precisa de root nem de `systemd-inhibit`. A regra do `AGENTS.md` "Don't add `user:` to compose" vale para o serviço `monitor`; deixar isso explícito no texto do `AGENTS.md`.
- Volumes: o mesmo bind mount do projeto (precisa ser leitura e escrita: um leitor SQLite em WAL usa o `-shm`) e `/etc/localtime` somente leitura. Sem socket D-Bus, sem `apparmor=unconfined`.
- `PORT` repassado por `environment` com padrão 8080.
- Healthcheck: requisição HTTP para `/api?min=1` com Python stdlib, intervalo de 30 s.
- Makefile: `start`/`stop`/`restart`/`status`/`logs` já atuam no projeto compose inteiro; conferir que `logs` mostra os dois. `make web` mantém o comportamento; se a porta estiver em uso, o painel sai com uma mensagem em português sugerindo `make stop` ou outra `PORT`.
- Atualizar a seção Docker e Commands do `AGENTS.md` (hoje diz que só o monitor roda no container).

## Testing Decisions

- Sem teste automático (é configuração de infraestrutura). Verificação manual descrita na entrega: `make start` → `make status` mostra os dois serviços `healthy`; abrir o painel no navegador; `make restart` depois de editar o painel aplica a mudança; o painel não abre de outro computador da rede; `make web` com o container rodando mostra a mensagem de porta ocupada.

## Out of Scope

- Expor o painel na rede local ou com HTTPS/senha.
- Proxy reverso, domínio.
- Imagem separada para o painel.

## Further Notes

- Independente das outras specs.
