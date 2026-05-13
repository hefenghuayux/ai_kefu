#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/mnt/e/workspacce/AI/ai_kefu"
MYSQL_HOME="/mnt/e/environment/mysql-8.0.45"
MYSQL="$MYSQL_HOME/usr/bin/mysql"
MYSQL_LIB="$MYSQL_HOME/usr/lib/x86_64-linux-gnu"

export LD_LIBRARY_PATH="$MYSQL_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$MYSQL" --protocol=SOCKET --socket=/tmp/ai_kefu_mysql.sock -uroot -p1234 -e "SHUTDOWN;"
