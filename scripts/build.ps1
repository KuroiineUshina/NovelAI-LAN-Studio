param(
    [string]$Python = "python",
    [switch]$SkipTests,
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Version = (Get-Content -Raw (Join-Path $ProjectRoot "VERSION")).Trim()
$DistRoot = if ($OutputDirectory) { [System.IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $ProjectRoot "dist" }
New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null

if (-not $SkipTests) {
    Push-Location $ProjectRoot
    try {
        & $Python -m pytest "backend\tests" -q
        if ($LASTEXITCODE -ne 0) { throw "backend tests failed." }
    } finally {
        Pop-Location
    }
}

& (Join-Path $ProjectRoot "scripts\sync_fonts.ps1")

Push-Location (Join-Path $ProjectRoot "frontend")
try {
    if (Test-Path "package-lock.json") {
        npm ci
    } else {
        npm install
    }
    if ($LASTEXITCODE -ne 0) { throw "npm dependency installation failed." }
    if (-not $SkipTests) {
        npm test
        if ($LASTEXITCODE -ne 0) { throw "frontend tests failed." }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "frontend build failed." }
} finally {
    Pop-Location
}

& $Python (Join-Path $ProjectRoot "scripts\make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "icon build failed." }

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath $DistRoot "NovelAI-LAN-Studio.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
} finally {
    Pop-Location
}

Copy-Item -LiteralPath (Join-Path $ProjectRoot "THIRD_PARTY_NOTICES.txt") -Destination (Join-Path $DistRoot "THIRD_PARTY_NOTICES.txt") -Force

$ExePath = Join-Path $DistRoot "NovelAI-LAN-Studio.exe"
$NoticePath = Join-Path $DistRoot "THIRD_PARTY_NOTICES.txt"
$ZipPath = Join-Path $DistRoot "NovelAI-LAN-Studio-v$Version.zip"
$ApkPath = Join-Path $DistRoot "NovelAI-LAN-Studio-Android-v$Version.apk"
$ChecksumPath = Join-Path $DistRoot "SHA256SUMS.txt"

Compress-Archive -LiteralPath $ExePath, $NoticePath -DestinationPath $ZipPath -CompressionLevel Optimal -Force
$ReleaseFiles = @($ExePath, $ZipPath, $NoticePath, $ApkPath) | Where-Object { Test-Path -LiteralPath $_ }
$ChecksumLines = $ReleaseFiles | ForEach-Object {
    $Hash = Get-FileHash -LiteralPath $_ -Algorithm SHA256
    "$($Hash.Hash)  $(Split-Path $_ -Leaf)"
}
[System.IO.File]::WriteAllLines($ChecksumPath, $ChecksumLines, [System.Text.UTF8Encoding]::new($false))

Write-Host "완료: $ExePath"
