#!/usr/bin/env bash
set -euo pipefail

REDIS_HOME="/mnt/e/environment/redis-7.0.15"
REDIS_LIB="$REDIS_HOME/usr/lib/x86_64-linux-gnu"

export LD_LIBRARY_PATH="$REDIS_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$REDIS_HOME/usr/bin/redis-cli" -h 127.0.0.1 -p 6379 shutdown
