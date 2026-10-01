# WAL enxuto (tamanho do banco honesto)

Status: ready-for-agent

## Problem Statement

O topo do painel mostra "Banco: 4,3 MB · cresce ~3,1 MB/dia" com poucas horas de dados, o que parece contraditório. Os dados reais (`conexao.db`) têm ~0,3 MB; quase todo o resto é o `conexao.db-wal`. Com os padrões do SQLite, o WAL cresce até ~1000 páginas (≈4 MB) antes do checkpoint automático e **nunca encolhe**: o arquivo é reaproveitado e fica em ~4 MB para sempre. O total mostrado leva um custo fixo de ~4 MB que não é dado acumulado.

## Solution

O monitor, que é quem escreve no banco, configura a conexão para manter o WAL pequeno:

- `PRAGMA wal_autocheckpoint=100`: checkpoint a cada ~100 páginas (≈400 KB) em vez de 1000.
- `PRAGMA journal_size_limit=0`: quando o WAL é reiniciado depois de um checkpoint, o arquivo é truncado em vez de ficar do tamanho máximo que já teve.

Assim o total no painel fica perto do tamanho real dos dados (WAL entre ~0 e ~0,4 MB), sem mudar nada no painel.

Medido num banco de teste (3000 inserts com commit, linhas de ~150 bytes):

| journal_size_limit | wal_autocheckpoint | WAL máx | WAL final |
|---|---|---|---|
| (padrão) | 1000 | 4,1 MB | 4,1 MB |
| 0 | 1000 | 4,1 MB | 0,98 MB |
| 0 | 100 | 0,42 MB | 0,13 MB |

Só `journal_size_limit` não resolve: o WAL ainda chega a 4 MB antes de cada checkpoint. Por isso as duas configurações vão juntas.

## User Stories

1. Como usuário, quero que o tamanho do banco mostrado no painel corresponda aos dados guardados, sem um "peso morto" de ~4 MB.
2. Como usuário, quero que o tamanho e o crescimento por dia mostrados no topo não pareçam se contradizer.
3. Como dono, quero que a mudança valha também para um `conexao.db` que já existe, sem migração nem perda de dados.
4. Como dono, quero que o ciclo de 5 s do monitor não fique mais lento.

## Implementation Decisions

- As duas pragmas são **por conexão** (não ficam gravadas no arquivo): precisam rodar toda vez que o monitor abre o banco, logo depois de `PRAGMA journal_mode=WAL`.
- Tirar a abertura do banco de `main()` para uma função pequena (por exemplo `abrir_banco(caminho)`: `connect` + `SCHEMA` + pragmas), que dá para testar sem rodar o loop. É uma mudança local no caminho que esta spec já toca (boy scout).
- Valores como constantes nomeadas no topo de `monitor.py`, junto de `INTERVAL` e das outras.
- O painel não muda: continua abrindo `mode=ro` e somando `-wal`/`-shm` em `banco.bytes`. Como o checkpoint fica mais frequente, `por_dia` (só o arquivo principal) também fica mais em dia.
- Custo: o checkpoint passa de ~1 a cada 30 min para ~1 a cada 3 min, copiando ~400 KB por vez. É desprezível para um ciclo de 5 s.
- Leitores do painel podem adiar um checkpoint enquanto leem. Como as consultas são curtas, o WAL só passa um pouco de 100 páginas de vez em quando. Aceitável.
- Atualizar `AGENTS.md` (seção Monitor/Schema) com uma linha sobre as pragmas e o motivo.

## Testing Decisions

- `abrir_banco()` num arquivo temporário: `PRAGMA journal_mode` = `wal`, `PRAGMA wal_autocheckpoint` = 100, `PRAGMA journal_size_limit` = 0.
- Teste de comportamento: muitos inserts com commit (como no ciclo) numa conexão de `abrir_banco()` → o `-wal` nunca passa de ~0,5 MB (margem acima de 100 páginas × 4 KB).
- Banco já existente (criado sem as pragmas e com WAL grande): reabrir com `abrir_banco()` e gravar → depois do próximo checkpoint, o WAL fica pequeno.
- Sem rede, sem Docker, sem o banco real, como o resto de `make test`.

## Out of Scope

- Mudar o texto ou a conta do tamanho no painel (por exemplo, mostrar o WAL à parte).
- `VACUUM`, retenção ou apagar dados antigos.
- Mexer no modo de abertura do painel (`mode=ro`).

## Further Notes

- Sem relação com outras specs; pode ser feita a qualquer momento.
- Depois de `make restart`, o WAL de ~4 MB de hoje só encolhe no primeiro checkpoint que reiniciar o arquivo (alguns minutos de uso). Não precisa de passo manual.
