$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourceRoot = Join-Path $ProjectRoot "assets\fonts"
$Targets = @(
    (Join-Path $ProjectRoot "frontend\public\fonts")
)

$FontFiles = Get-ChildItem -LiteralPath $SourceRoot -Filter "*.woff2" -File
$LicenseFiles = Get-ChildItem -LiteralPath (Join-Path $SourceRoot "licenses") -Filter "*.txt" -File
if ($FontFiles.Count -ne 8 -or $LicenseFiles.Count -ne 8) {
    throw "내장 글꼴 또는 라이선스 파일이 8개가 아닙니다."
}

foreach ($Target in $Targets) {
    $LicenseTarget = Join-Path $Target "licenses"
    New-Item -ItemType Directory -Force -Path $Target, $LicenseTarget | Out-Null
    foreach ($Font in $FontFiles) {
        Copy-Item -LiteralPath $Font.FullName -Destination (Join-Path $Target $Font.Name) -Force
    }
    foreach ($License in $LicenseFiles) {
        Copy-Item -LiteralPath $License.FullName -Destination (Join-Path $LicenseTarget $License.Name) -Force
    }
}
