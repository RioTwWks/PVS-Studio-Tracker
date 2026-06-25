#!/usr/bin/env bash
# Wrapper: docker compose (v2 plugin) or docker-compose (v1 binary).
set -euo pipefail

if docker compose version >/dev/null 2>&1; then
  exec docker compose "$@"
fi

if command -v docker-compose >/dev/null 2>&1; then
  exec docker-compose "$@"
fi

echo "Docker Compose not found." >&2
echo "" >&2
echo "Install one of:" >&2
echo "  - Docker Compose plugin (v2): docker compose version" >&2
echo "  - Standalone: docker-compose --version" >&2
echo "" >&2
echo "Ubuntu/Debian example:" >&2
echo "  sudo apt-get update && sudo apt-get install -y docker-compose-plugin" >&2
echo "  # or: sudo apt-get install -y docker-compose" >&2
exit 1
