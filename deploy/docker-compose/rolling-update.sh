#!/usr/bin/env bash
# Rolling update app-1 и app-2 по очереди (без простоя nginx).
set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"
SERVICES=(app-1 app-2)

for svc in "${SERVICES[@]}"; do
  echo "==> Rebuild and restart $svc"
  docker compose -f "$COMPOSE_FILE" up -d --no-deps --build "$svc"
  echo "==> Wait until $svc is healthy"
  for _ in $(seq 1 60); do
    cid=$(docker compose -f "$COMPOSE_FILE" ps -q "$svc")
    status=$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "starting")
    if [ "$status" = "healthy" ]; then
      echo "$svc is healthy"
      break
    fi
    sleep 2
  done
done

echo "Rolling update finished. Public URL: http://localhost:8080/webhook/inbound"
