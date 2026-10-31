<#
.SYNOPSIS
  Download the Tailwind CSS standalone CLI (no Node needed) and build app.css.

.USAGE
  .\scripts\tailwind.ps1            # one-off build (minified)
  .\scripts\tailwind.ps1 -Watch     # rebuild on every template change
#>
param(
    [switch]$Watch,
    [string]$Version = "v4.3.3"
)

$ErrorActionPreference = "Stop"
$root  = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $root ".tools"
$exe   = Join-Path $tools "tailwindcss.exe"
$in    = Join-Path $root "app\static\src\input.css"
$out   = Join-Path $root "app\static\css\app.css"

if (-not (Test-Path $exe)) {
    New-Item -ItemType Directory -Force $tools | Out-Null
    $url = "https://github.com/tailwindlabs/tailwindcss/releases/download/$Version/tailwindcss-windows-x64.exe"
    Write-Host "Downloading Tailwind CLI $Version ..."
    Invoke-WebRequest -Uri $url -OutFile $exe
}

$args_ = @("-i", $in, "-o", $out, "--minify")
if ($Watch) { $args_ += "--watch" }
& $exe @args_
