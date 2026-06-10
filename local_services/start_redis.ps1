$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RedisHome = "E:\environment\redis-7.4.9-windows-msys2"
$RedisServer = Join-Path $RedisHome "redis-server.exe"
$RedisCli = Join-Path $RedisHome "redis-cli.exe"
$ConfigFile = Join-Path $PSScriptRoot "redis.conf"
$ConfigDrive = $ConfigFile.Substring(0, 1).ToLower()
$ConfigCygwinPath = "/cygdrive/$ConfigDrive$($ConfigFile.Substring(2) -replace '\\', '/')"

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir ".data\redis"), (Join-Path $ProjectDir ".data\run"), (Join-Path $ProjectDir ".data\logs") | Out-Null

if (-not (Test-Path $RedisServer)) {
    throw "Redis executable not found: $RedisServer"
}

$RedisPort = "16380"

$Connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $RedisPort -ErrorAction SilentlyContinue
if (-not $Connection) {
    Start-Process -FilePath $RedisServer -ArgumentList $ConfigCygwinPath -WorkingDirectory $RedisHome -WindowStyle Hidden
}

$Ready = $false
$SavedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
for ($i = 0; $i -lt 30; $i++) {
    & $RedisCli "-h" "127.0.0.1" "-p" $RedisPort "ping" 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        $Ready = $true
        break
    }
    Start-Sleep -Seconds 1
}
$ErrorActionPreference = $SavedErrorActionPreference

if (-not $Ready) {
    throw "Redis did not become ready on 127.0.0.1:$RedisPort"
}

& $RedisCli "-h" "127.0.0.1" "-p" $RedisPort "ping"
