$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Neo4jHome = "E:\environment\neo4j-community-5.26.26"
$JavaHome = "E:\environment\jdk21"
$Neo4j = Join-Path $Neo4jHome "bin\neo4j.bat"
$Neo4jAdmin = Join-Path $Neo4jHome "bin\neo4j-admin.bat"
$Neo4jData = Join-Path $ProjectDir ".data\neo4j-win\data"

New-Item -ItemType Directory -Force -Path $Neo4jData, (Join-Path $ProjectDir ".data\neo4j-win\plugins"), (Join-Path $ProjectDir ".data\neo4j-win\import"), (Join-Path $ProjectDir ".data\logs\neo4j"), (Join-Path $ProjectDir ".data\run\neo4j") | Out-Null

if (-not (Test-Path $Neo4j)) {
    throw "Neo4j executable not found: $Neo4j"
}
if (-not (Test-Path (Join-Path $JavaHome "bin\java.exe"))) {
    throw "Java executable not found: $JavaHome\bin\java.exe"
}

$env:JAVA_HOME = $JavaHome
$env:NEO4J_HOME = $Neo4jHome
$env:NEO4J_CONF = $PSScriptRoot

if (-not (Test-Path (Join-Path $Neo4jData "dbms\auth.ini"))) {
    & $Neo4jAdmin "dbms" "set-initial-password" "12345678"
    if ($LASTEXITCODE -ne 0) {
        throw "Neo4j initial password setup failed with exit code $LASTEXITCODE"
    }
}

$Connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 7687 -ErrorAction SilentlyContinue
if (-not $Connection) {
    Start-Process -FilePath $Neo4j -ArgumentList "console" -WindowStyle Hidden
}

$Ready = $false
for ($i = 0; $i -lt 120; $i++) {
    $Connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 7687 -ErrorAction SilentlyContinue
    if ($Connection) {
        $Ready = $true
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $Ready) {
    throw "Neo4j did not become ready on 127.0.0.1:7687"
}

Write-Host "Neo4j is listening on bolt://127.0.0.1:7687"
