$ErrorActionPreference = "Stop"

$RedisCli = "E:\environment\redis-7.4.9-windows-msys2\redis-cli.exe"

& $RedisCli "-h" "127.0.0.1" "-p" "16380" "shutdown"
if ($LASTEXITCODE -ne 0) {
    throw "Redis shutdown failed with exit code $LASTEXITCODE"
}
