# Glance installer for Windows (PowerShell):
#
#   irm https://sorena-paydar.github.io/Glance/install.ps1 | iex
#
# Installs uv if needed, installs the `glance` command, then starts guided setup.
# Set $env:GLANCE_NO_SETUP = "1" to skip setup.
$ErrorActionPreference = "Stop"

$Source = $env:GLANCE_SOURCE
if (-not $Source) {
    $Source = "glance[tray] @ https://github.com/sorena-paydar/Glance/archive/refs/heads/main.zip"
}

Write-Host "==> Installing Glance"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing uv (Python package manager)"
    powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# uv downloads Python 3.12 by itself if it isn't installed.
uv tool install --force --python 3.12 $Source
if ($LASTEXITCODE -ne 0) { throw "Installing Glance failed." }
uv tool update-shell | Out-Null

$Bin = (uv tool dir --bin).Trim()
if ($env:Path -notlike "*$Bin*") { $env:Path = "$Bin;$env:Path" }

Write-Host "==> Glance installed. Run 'glance' any time to start it."

if (-not $env:GLANCE_NO_SETUP) {
    Write-Host "==> Starting setup"
    glance
}
