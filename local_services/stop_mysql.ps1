$ErrorActionPreference = "Stop"

$MysqlAdmin = "E:\environment\mysql-8.0.46-winx64-bin\bin\mysqladmin.exe"

& $MysqlAdmin "--protocol=TCP" "--host=127.0.0.1" "--port=3306" "--user=root" "--password=1234" "shutdown"
if ($LASTEXITCODE -ne 0) {
    throw "MySQL shutdown failed with exit code $LASTEXITCODE"
}
