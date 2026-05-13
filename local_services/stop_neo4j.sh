#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/mnt/e/workspacce/AI/ai_kefu"
NEO4J_DIST="/mnt/e/environment/neo4j-5.26.26/usr/share/neo4j"
JAVA_HOME="/mnt/e/environment/openjdk-21/usr/lib/jvm/java-21-openjdk-amd64"
NEO4J_CONF="$PROJECT_DIR/local_services"

JAVA_HOME="$JAVA_HOME" NEO4J_CONF="$NEO4J_CONF" "$NEO4J_DIST/bin/neo4j" stop
