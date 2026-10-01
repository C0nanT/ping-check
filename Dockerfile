FROM python:3.12-slim

# ping, tracepath (diagnóstico nas quedas; UDP, sem root), ip (iproute2), nmcli (info do Wi-Fi via D-Bus do host)
# e systemd-inhibit (pacote systemd), que segura a suspensão via logind do host
RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping iputils-tracepath iproute2 network-manager libcap2-bin systemd \
 && setcap cap_net_raw+ep /usr/bin/ping \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY monitor.py painel.py ./

# Bloqueia suspensão (inclusive ao fechar a tampa) enquanto o container roda.
# O polkit do host só deixa root bloquear suspensão de fora de uma sessão,
# então systemd-inhibit roda como root em background e o monitor vira o
# processo principal como 1000:1000 (mesmo dono do conexao.db no host),
# recebendo o SIGTERM direto para fechar queda/run abertas.
CMD ["sh", "-c", "systemd-inhibit --what=sleep:idle:handle-lid-switch --who=ping-check --why='Monitor de conexão' --mode=block sleep infinity & exec setpriv --reuid=1000 --regid=1000 --clear-groups python3 -u monitor.py"]
