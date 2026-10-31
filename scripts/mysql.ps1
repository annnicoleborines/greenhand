# Start or stop XAMPP's MySQL (MariaDB) from the terminal, no Control Panel needed.
#
#   .\scripts\mysql.ps1          # start (does nothing if already running)
#   .\scripts\mysql.ps1 stop     # stop cleanly
#   .\scripts\mysql.ps1 status
#
# XAMPP_HOME can point somewhere other than C:\xampp.

param(
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "start"
)

$xampp = if ($env:XAMPP_HOME) { $env:XAMPP_HOME } else { "C:\xampp" }
$mysqld = Join-Path $xampp "mysql\bin\mysqld.exe"
$mysqladmin = Join-Path $xampp "mysql\bin\mysqladmin.exe"
$ini = Join-Path $xampp "mysql\bin\my.ini"

function Get-MysqlProcess { Get-Process mysqld -ErrorAction SilentlyContinue }

switch ($Action) {
    "status" {
        if (Get-MysqlProcess) { Write-Host "MySQL is running (port 3306)." } else { Write-Host "MySQL is not running." }
    }
    "start" {
        if (Get-MysqlProcess) { Write-Host "MySQL is already running."; break }
        if (-not (Test-Path $mysqld)) { throw "mysqld.exe not found at $mysqld (set XAMPP_HOME)" }
        # Detached so it keeps running after this terminal closes.
        Start-Process -FilePath $mysqld -ArgumentList "--defaults-file=`"$ini`"", "--standalone" -WindowStyle Hidden
        $deadline = (Get-Date).AddSeconds(15)
        while ((Get-Date) -lt $deadline) {
            if ((Test-NetConnection 127.0.0.1 -Port 3306 -WarningAction SilentlyContinue).TcpTestSucceeded) {
                Write-Host "MySQL started."; break
            }
            Start-Sleep -Milliseconds 500
        }
        if (-not (Get-MysqlProcess)) { throw "MySQL did not start. See $xampp\mysql\data\mysql_error.log" }
    }
    "stop" {
        if (-not (Get-MysqlProcess)) { Write-Host "MySQL is not running."; break }
        & $mysqladmin -u root shutdown
        Write-Host "MySQL stopped."
    }
}
