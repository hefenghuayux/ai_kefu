#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/mnt/e/workspacce/AI/ai_kefu"
NEO4J_DIST="/mnt/e/environment/neo4j-5.26.26/usr/share/neo4j"
JAVA_HOME="/mnt/e/environment/openjdk-21/usr/lib/jvm/java-21-openjdk-amd64"
NEO4J_CONF="$PROJECT_DIR/local_services"
NEO4J_DATA="$PROJECT_DIR/.data/neo4j/data"

mkdir -p "$PROJECT_DIR/.data/neo4j/data" "$PROJECT_DIR/.data/neo4j/plugins" "$PROJECT_DIR/.data/neo4j/import" "$PROJECT_DIR/.data/logs/neo4j" "$PROJECT_DIR/.data/run"

if [ ! -f "$NEO4J_DATA/dbms/auth" ]; then
  JAVA_HOME="$JAVA_HOME" NEO4J_CONF="$NEO4J_CONF" "$NEO4J_DIST/bin/neo4j-admin" dbms set-initial-password 12345678
fi

JAVA_HOME="$JAVA_HOME" NEO4J_CONF="$NEO4J_CONF" "$NEO4J_DIST/bin/neo4j" start
JAVA_HOME="$JAVA_HOME" NEO4J_CONF="$NEO4J_CONF" "$NEO4J_DIST/bin/neo4j" status
