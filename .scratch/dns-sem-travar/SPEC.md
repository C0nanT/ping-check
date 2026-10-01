# Teste de DNS que não trava o monitor

Status: ready-for-agent

## Problem Statement

O teste de DNS chama `getaddrinfo` numa thread do pool de 6 workers e espera no máximo `DNS_TIMEOUT` segundos. Quando o tempo acaba, o monitor registra a falha, mas a chamada continua rodando, ocupando a thread. Numa queda de DNS longa, cada ciclo (5 s) prende mais uma thread. Em poucos ciclos o pool fica cheio e os pings também param de rodar: o monitor congela justo durante a queda, e o painel mostra "sem medição" em vez de "Os sites não estão abrindo". O comentário no código diz que o executor resolve o timeout, mas não resolve.

## Solution

O teste de DNS passa a rodar como um **subprocesso com timeout** (`getent ahosts`), igual aos pings. Quando o tempo acaba, o processo é morto e nada fica preso. A resolução usa o mesmo caminho do sistema (NSS: `/etc/hosts`, systemd-resolved, etc.), então o resultado continua representando o que os programas do computador veem.

## User Stories

1. Como usuário, quero que o monitor continue medindo durante uma queda de DNS longa, para o painel mostrar o problema certo em vez de "sem medição".
2. Como usuário, quero que uma queda de DNS apareça como `falha_dns` do começo ao fim, com duração certa.
3. Como dono do projeto, quero que nenhum teste de rede deixe thread ou processo pendurado, para o monitor rodar meses sem degradar.
4. Como dono do projeto, quero que o DNS continue testando o mesmo nome (`DNS_HOST`) e com o mesmo limite (`DNS_TIMEOUT`).
5. Como dono do projeto, quero que `dns_ms` continue sendo o tempo da resolução, para os gráficos e médias continuarem comparáveis.
6. Como dono do projeto, quero um teste automático provando que um DNS que não responde devolve falha dentro do limite.
7. Como dono do projeto, quero que funcione igual no host (`make run`) e no container (`make start`).

## Implementation Decisions

- `dns_check()` executa `getent ahosts <DNS_HOST>` via `subprocess.run(..., timeout=DNS_TIMEOUT)`. Saída com código 0 e pelo menos um endereço → `(1, ms)`; código ≠ 0, timeout ou exceção → `(0, None)`. `subprocess.run` mata o filho no timeout.
- O comando fica numa constante de módulo (lista de argumentos), para o teste poder trocá-lo.
- O laço principal continua submetendo `dns_check` ao pool, mas não precisa mais do `result(timeout=...)` como proteção: o próprio `dns_check` garante o limite. Manter um timeout de segurança um pouco maior que `DNS_TIMEOUT` é aceitável.
- `getent` vem do `libc-bin`, presente no host e na imagem `python:3.12-slim`; o Dockerfile não muda.
- Corrigir o comentário enganoso sobre o executor.
- `dns_ms` passa a incluir o custo de criar o processo (alguns ms). Aceito; registrar no `CLAUDE.md` se for relevante.

## Testing Decisions

- Teste do comportamento de timeout: trocar o comando da constante por um que dorme mais que `DNS_TIMEOUT` (ex.: `sleep`) e verificar que `dns_check()` devolve `(0, None)` em menos de `DNS_TIMEOUT` + 1 s.
- Teste de sucesso sem rede: trocar o comando por um que imprime uma linha no formato do `getent` e sai com 0 → `(1, ms)` com `ms` ≥ 0.
- Teste de falha: comando que sai com código 2 → `(0, None)`.
- Prior art: estrutura de `testes-unitarios`.

## Out of Scope

- Trocar o servidor DNS usado, testar vários nomes ou consultar 1.1.1.1/8.8.8.8 diretamente.
- Mudar o tamanho do pool.

## Further Notes

- Depende de `testes-unitarios`.
