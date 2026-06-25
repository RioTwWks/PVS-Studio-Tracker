#!/bin/sh
# Sync DB init before uvicorn; workers skip (command without uvicorn).
set -e

run_init=false
for arg in "$@"; do
  case "$arg" in
    uvicorn|*uvicorn*) run_init=true ;;
  esac
done

if [ "$run_init" = true ]; then
  echo "Running database startup init (python -m pvs_tracker.startup_init) ..."
  python -m pvs_tracker.startup_init
  export PVS_STARTUP_ALREADY_DONE=1
  echo "PVS_STARTUP_ALREADY_DONE=1"
fi

exec "$@"
