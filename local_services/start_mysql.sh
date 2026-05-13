#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/mnt/e/workspacce/AI/ai_kefu"
MYSQL_HOME="/mnt/e/environment/mysql-8.0.45"
MYSQLD="$MYSQL_HOME/usr/sbin/mysqld"
MYSQL="$MYSQL_HOME/usr/bin/mysql"
MYSQL_LIB="$MYSQL_HOME/usr/lib/x86_64-linux-gnu"
CONF="$PROJECT_DIR/local_services/mysql.cnf"
DATA_DIR="$PROJECT_DIR/.data/mysql/data"
RUN_DIR="$PROJECT_DIR/.data/run"
LOG_DIR="$PROJECT_DIR/.data/logs"
MYSQLD_OPTS=(
  --basedir="$MYSQL_HOME/usr"
  --datadir="$DATA_DIR"
  --plugin-dir="$MYSQL_HOME/usr/lib/mysql/plugin"
  --lc-messages-dir="$MYSQL_HOME/usr/share/mysql"
  --port=3306
  --bind-address=127.0.0.1
  --socket=/tmp/ai_kefu_mysql.sock
  --pid-file=/tmp/ai_kefu_mysql.pid
  --log-error="$LOG_DIR/mysql.err"
  --character-set-server=utf8mb4
  --collation-server=utf8mb4_unicode_ci
  --secure-file-priv=
  --skip-log-bin
  --mysqlx=0
)
MYSQL_OPTS=(--protocol=SOCKET --socket=/tmp/ai_kefu_mysql.sock -uroot -p1234)

mkdir -p "$DATA_DIR" "$RUN_DIR" "$LOG_DIR"
export LD_LIBRARY_PATH="$MYSQL_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

if [ ! -d "$DATA_DIR/mysql" ]; then
  "$MYSQLD" "${MYSQLD_OPTS[@]}" --initialize-insecure
  "$MYSQLD" "${MYSQLD_OPTS[@]}" --init-file="$PROJECT_DIR/local_services/mysql_init.sql" --daemonize
  sleep 5
  "$MYSQL" "${MYSQL_OPTS[@]}" -e "SELECT VERSION();"
  "$MYSQL" "${MYSQL_OPTS[@]}" -e "SHUTDOWN;"
  sleep 3
fi

"$MYSQLD" "${MYSQLD_OPTS[@]}" --daemonize
sleep 3
"$MYSQL" "${MYSQL_OPTS[@]}" -e "CREATE DATABASE IF NOT EXISTS kefu_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
"$MYSQL" "${MYSQL_OPTS[@]}" -e "SELECT VERSION() AS mysql_version;"
