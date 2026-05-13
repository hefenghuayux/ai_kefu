#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/mnt/e/workspacce/AI/ai_kefu"
MYSQL_HOME="/mnt/e/environment/mysql-8.0.45"
MYSQL_LIB="$MYSQL_HOME/usr/lib/x86_64-linux-gnu"
REDIS_HOME="/mnt/e/environment/redis-7.0.15"
REDIS_LIB="$REDIS_HOME/usr/lib/x86_64-linux-gnu"

LD_LIBRARY_PATH="$MYSQL_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$MYSQL_HOME/usr/bin/mysql" --protocol=SOCKET --socket=/tmp/ai_kefu_mysql.sock -uroot -p1234 -e "SHOW DATABASES LIKE 'kefu_agent';"
LD_LIBRARY_PATH="$REDIS_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$REDIS_HOME/usr/bin/redis-cli" -h 127.0.0.1 -p 6379 ping
JAVA_HOME="/mnt/e/environment/openjdk-21/usr/lib/jvm/java-21-openjdk-amd64" NEO4J_CONF="$PROJECT_DIR/local_services" /mnt/e/environment/neo4j-5.26.26/usr/share/neo4j/bin/neo4j status
