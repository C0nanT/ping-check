# Tamanho do banco sempre visível no painel

Status: ready-for-agent

## Problem Statement

O dono decidiu deixar o `conexao.db` crescer sem apagar dados antigos (~17 mil amostras por dia), e quer acompanhar o tamanho de perto. Hoje não há como ver isso sem abrir o terminal e somar o arquivo principal com o `-wal` e o `-shm`.

## Solution

O topo do painel mostra sempre o tamanho atual do banco no disco e quanto ele cresce por dia, atualizando junto com o resto (a cada 5 s). Ex.: "Banco: 48,2 MB · cresce ~3,1 MB/dia".

## User Stories

1. Como dono, quero ver o tamanho do banco em qualquer tela do painel, sem abrir nada, para ficar de olho.
2. Como dono, quero que o tamanho inclua os arquivos `-wal` e `-shm`, porque é o espaço real ocupado no disco.
3. Como dono, quero o tamanho em unidade fácil de ler (KB, MB, GB, formato brasileiro), para não fazer conta.
4. Como dono, quero ver quanto o banco cresce por dia, para prever quando ele vai ficar grande demais.
5. Como dono, quero que o número atualize sozinho, junto com o resto do painel.
6. Como dono, quero que o contador apareça mesmo quando o monitor estiver parado, para conferir o banco a qualquer hora.
7. Como dono, quero que o contador não pese no painel, para continuar rápido.
8. Como usuário não técnico, quero que o contador seja discreto e não roube atenção do estado da internet.
9. Como dono, quero que funcione igual com o painel no host (`make web`) ou no container (`painel-no-docker`).

## Implementation Decisions

- `api()` ganha um campo `banco` no JSON: `{"bytes": <soma dos tamanhos do arquivo principal, -wal e -shm que existirem>, "por_dia": <bytes por dia estimados ou null>}`. O tamanho vem de `os.path.getsize` (não abre o banco para escrita; compatível com `mode=ro`).
- `por_dia` = tamanho do arquivo principal ÷ dias desde a primeira amostra em `checks` (`MIN(epoch)`, barato pelo índice). Menos de 1 hora de dados → `null` (estimativa sem sentido). O `-wal` fica fora dessa conta porque varia com os checkpoints.
- Frontend: texto curto na linha de "Atualizado às…" do cabeçalho, com cor `--muted` como o resto da linha. Formatação com `toLocaleString('pt-BR')`: < 1 MB em KB, < 1 GB em MB com 1 casa, depois GB com 2 casas. `por_dia` nulo → mostra só o tamanho.
- Atualizar a lista de campos do `/api` no `CLAUDE.md`.

## Testing Decisions

- Teste via `api()` com banco temporário: `banco.bytes` igual à soma dos arquivos existentes; sem `-wal` não quebra; `por_dia` é `null` com menos de 1 hora de dados e positivo com amostras de dias atrás.
- Prior art: testes de `api()` da spec `testes-unitarios`.

## Out of Scope

- Alertas de tamanho, limites ou limpeza automática.
- Uma meta `make` para ver o tamanho (pode vir depois, no mesmo padrão `$(SQL)`).
- Tamanho por tabela.

## Further Notes

- Depende de `testes-unitarios`.
