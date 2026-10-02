# 01: Teste de contrato painel × monitor e guarda `__main__`

> **Difficulty:** Light: **suggested model:** Sonnet (Claude Code) / Sonnet (Cursor). Suggestion only, use whatever model you have to hand.

**What to build:** `make test` passa a falhar quando painel e monitor discordam num valor que precisa ser igual: nome do arquivo de pedido de teste completo, validade do pedido, intervalo entre amostras e a lista de status de queda (conferida contra os status que `classify()` pode produzir, menos `ok`/`degradado`). Só o teste importa os dois módulos; o painel continua sem importar o monitor. Aproveitar para tirar a guarda `if __name__ == "__main__"` do meio do arquivo de testes do painel (apagar ou mover para o fim), de modo que nenhuma classe de teste fique depois dela.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Alterar o nome do arquivo de pedido, a validade, o intervalo ou um status de queda em só um dos lados faz `make test` falhar (verificar mudando temporariamente cada valor)
- [ ] Um status novo possível em `classify()` que não esteja na lista de queda do painel nem seja `ok`/`degradado` é pego pelo teste
- [ ] Nenhuma classe de teste fica depois de uma guarda `__main__`; `TesteAgoraTest` continua rodando em `make test`
- [ ] O painel não importa o monitor em produção
- [ ] `make test` passa sem rede, Docker nem banco real
