$ErrorActionPreference = "Stop"

$Neo4jHome = "E:\environment\neo4j-community-5.26.26"
$JavaHome = "E:\environment\jdk21"
$env:JAVA_HOME = $JavaHome
$env:NEO4J_HOME = $Neo4jHome
$env:NEO4J_CONF = $PSScriptRoot

$Processes = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*neo4j-community-5.26.26*" -and (
        $_.CommandLine -like "*org.neo4j*" -or $_.CommandLine -like "*neo4j.ps1*"
    )
}

if (-not $Processes) {
    throw "Neo4j process was not found"
}

foreach ($Process in $Processes) {
    Stop-Process -Id $Process.ProcessId -Force
}
