<#
.SYNOPSIS  Run the same checks as CI: lint, format, typecheck, tests.
.USAGE     .\scripts\check.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
ruff check .          ; if ($LASTEXITCODE) { exit $LASTEXITCODE }
ruff format --check . ; if ($LASTEXITCODE) { exit $LASTEXITCODE }
mypy .                ; if ($LASTEXITCODE) { exit $LASTEXITCODE }
pytest                ; if ($LASTEXITCODE) { exit $LASTEXITCODE }
Write-Host "All checks passed." -ForegroundColor Green
