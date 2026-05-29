$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$MysqlHome = "E:\environment\mysql-8.0.46-winx64-bin"
$Mysqld = Join-Path $MysqlHome "bin\mysqld.exe"
$Mysql = Join-Path $MysqlHome "bin\mysql.exe"
$ConfigFile = Join-Path $PSScriptRoot "mysql.cnf"
$DataDir = Join-Path $ProjectDir ".data\mysql-win\data"
$LogDir = Join-Path $ProjectDir ".data\logs"
$RunDir = Join-Path $ProjectDir ".data\run"

New-Item -ItemType Directory -Force -Path $DataDir, $LogDir, $RunDir | Out-Null

if (-not (Test-Path $Mysqld)) {
    throw "MySQL executable not found: $Mysqld"
}

$NeedsInit = -not (Test-Path (Join-Path $DataDir "mysql"))

if ($NeedsInit) {
    & $Mysqld "--defaults-file=$ConfigFile" --initialize-insecure
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL initialization failed with exit code $LASTEXITCODE"
    }
}

$Connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 3306 -ErrorAction SilentlyContinue
if (-not $Connection) {
    Start-Process -FilePath $Mysqld -ArgumentList "--defaults-file=$ConfigFile" -WindowStyle Hidden
}

$Ready = $false
$NeedsPasswordSetup = $false
$SavedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
for ($i = 0; $i -lt 30; $i++) {
    & $Mysql "--protocol=TCP" "--host=127.0.0.1" "--port=3306" "--user=root" "-e" "SELECT 1;" 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        $Ready = $true
        $NeedsPasswordSetup = $true
        break
    }

    & $Mysql "--protocol=TCP" "--host=127.0.0.1" "--port=3306" "--user=root" "--password=1234" "-e" "SELECT 1;" 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        $Ready = $true
        break
    }

    Start-Sleep -Seconds 1
}
$ErrorActionPreference = $SavedErrorActionPreference

if (-not $Ready) {
    throw "MySQL did not become ready on 127.0.0.1:3306"
}

if ($NeedsPasswordSetup) {
    & $Mysql "--protocol=TCP" "--host=127.0.0.1" "--port=3306" "--user=root" "-e" "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '1234'; CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY '1234'; GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION; FLUSH PRIVILEGES;"
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL root password setup failed with exit code $LASTEXITCODE"
    }
}

& $Mysql "--protocol=TCP" "--host=127.0.0.1" "--port=3306" "--user=root" "--password=1234" "-e" "CREATE DATABASE IF NOT EXISTS kefu_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; SELECT VERSION() AS mysql_version;"
if ($LASTEXITCODE -ne 0) {
    throw "MySQL database check failed with exit code $LASTEXITCODE"
}
