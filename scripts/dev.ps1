param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Start-Process -FilePath $Python -ArgumentList "-m", "backend.app.launcher", "--no-tray" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
Push-Location (Join-Path $ProjectRoot "frontend")
try {
    npm run dev
} finally {
    Pop-Location
}
