$ErrorActionPreference = "Stop"

$Mysql = "E:\environment\mysql-8.0.46-winx64-bin\bin\mysql.exe"
$RedisCli = "E:\environment\redis-7.4.9-windows-msys2\redis-cli.exe"
$CypherShell = "E:\environment\neo4j-community-5.26.26\bin\cypher-shell.bat"

& $Mysql "--protocol=TCP" "--host=127.0.0.1" "--port=3306" "--user=root" "--password=1234" "-e" "SHOW DATABASES LIKE 'kefu_agent';"
if ($LASTEXITCODE -ne 0) {
    throw "MySQL check failed with exit code $LASTEXITCODE"
}

& $RedisCli "-h" "127.0.0.1" "-p" "16380" "ping"
if ($LASTEXITCODE -ne 0) {
    throw "Redis check failed with exit code $LASTEXITCODE"
}

& $CypherShell "-a" "bolt://127.0.0.1:7687" "-u" "neo4j" "-p" "12345678" "RETURN 1 AS ok;"
if ($LASTEXITCODE -ne 0) {
    throw "Neo4j check failed with exit code $LASTEXITCODE"
}
