#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/mnt/e/workspacce/AI/ai_kefu"
REDIS_HOME="/mnt/e/environment/redis-7.0.15"
REDIS_LIB="$REDIS_HOME/usr/lib/x86_64-linux-gnu"

mkdir -p "$PROJECT_DIR/.data/redis" "$PROJECT_DIR/.data/run" "$PROJECT_DIR/.data/logs"
export LD_LIBRARY_PATH="$REDIS_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$REDIS_HOME/usr/bin/redis-server" "$PROJECT_DIR/local_services/redis.conf"
sleep 1
"$REDIS_HOME/usr/bin/redis-cli" -h 127.0.0.1 -p 6379 ping
