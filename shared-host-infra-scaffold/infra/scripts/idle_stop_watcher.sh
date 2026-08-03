#!/usr/bin/env bash
#
# Systemd socket activation starts hexa-backend.service on the
# first connection, but does NOT stop it again automatically. This
# script is run periodically (via hexa-backend-idle.timer) to
# check for active connections and stop the service if it's been
# idle for longer than IDLE_MINUTES.
#
# This, combined with socket activation, is what lets multiple
# projects share 1 GiB RAM: only the projects actually receiving
# traffic hold memory at any given moment.

set -euo pipefail

SERVICE="hexa-backend.service"
PORT=8001
IDLE_MINUTES=10

if ! systemctl is-active --quiet "$SERVICE"; then
    exit 0   # already stopped, nothing to do
fi

# Count established connections to the backend port right now.
ACTIVE_CONNECTIONS=$(ss -tn state established "( dport = :$PORT or sport = :$PORT )" | tail -n +2 | wc -l)

if [ "$ACTIVE_CONNECTIONS" -gt 0 ]; then
    exit 0   # traffic is flowing, leave it running
fi

# No active connections. Check how long the service has been running
# with zero connections by using its last-active timestamp as a proxy.
LAST_STATE_CHANGE=$(systemctl show "$SERVICE" -p ActiveEnterTimestamp --value)
LAST_EPOCH=$(date -d "$LAST_STATE_CHANGE" +%s 2>/dev/null || echo 0)
NOW_EPOCH=$(date +%s)
IDLE_SECONDS=$(( NOW_EPOCH - LAST_EPOCH ))

if [ "$IDLE_SECONDS" -ge $(( IDLE_MINUTES * 60 )) ]; then
    logger -t idle_stop_watcher "Stopping $SERVICE after ${IDLE_MINUTES}m idle"
    systemctl stop "$SERVICE"
fi
