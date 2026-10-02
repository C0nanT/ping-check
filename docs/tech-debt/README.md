# Índice de revisões de dívida técnica

Fonte de verdade da partição de módulos usada nas revisões (`/tech-debt-map`). Relatórios ficam em `.scratch/tech-debt-map/<módulo>/<data>.md`.

| Módulo | Caminhos | Origem | Última revisão | Relatório | Em aberto |
| ------ | -------- | ------ | -------------- | --------- | --------- |
| Painel | `painel.py`, `tests/test_painel_api.py` | proposed | 2026-10-02 | `.scratch/tech-debt-map/painel/2026-10-02.md` | 8 (+1 pergunta) |
| Monitor | `monitor.py`, `tests/test_monitor.py` | proposed | nunca | – | – |

## Guardrails

- Constantes compartilhadas entre `painel.py`, o JS e `monitor.py` (status, intervalos, nome do arquivo de pedido) precisam de um teste que compare os dois lados, ou de um campo no payload da API em vez de uma cópia com comentário "mesmo X do Y".
- Todo valor que o JS precisa e que o servidor já conhece deve vir em `/api`, não ser redeclarado no JS.
