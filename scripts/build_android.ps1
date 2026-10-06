param(
    [Parameter(Mandatory = $true)]
    [string]$JavaHome,
    [Parameter(Mandatory = $true)]
    [string]$AndroidSdkRoot,
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AndroidRoot = Join-Path $ProjectRoot "android"
$Version = (Get-Content -Raw (Join-Path $ProjectRoot "VERSION")).Trim()
$DistRoot = if ($OutputDirectory) { [System.IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $ProjectRoot "dist" }
New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
$JavaExecutable = Join-Path $JavaHome "bin\java.exe"
$AndroidJar = Join-Path $AndroidSdkRoot "platforms\android-36\android.jar"

if (-not (Test-Path -LiteralPath $JavaExecutable)) {
    throw "JDK 17을 찾을 수 없습니다: $JavaExecutable"
}
if (-not (Test-Path -LiteralPath $AndroidJar)) {
    throw "Android SDK Platform 36을 찾을 수 없습니다: $AndroidJar"
}

& (Join-Path $ProjectRoot "scripts\sync_fonts.ps1")

$escapedSdkPath = $AndroidSdkRoot.Replace("\", "\\").Replace(":", "\:")
[System.IO.File]::WriteAllText(
    (Join-Path $AndroidRoot "local.properties"),
    "sdk.dir=$escapedSdkPath`r`n",
    [System.Text.UTF8Encoding]::new($false)
)

$previousJavaHome = $env:JAVA_HOME
$previousSdkRoot = $env:ANDROID_SDK_ROOT
$env:JAVA_HOME = $JavaHome
$env:ANDROID_SDK_ROOT = $AndroidSdkRoot

Push-Location $AndroidRoot
try {
    & ".\gradlew.bat" testDebugUnitTest lintSideload assembleSideload
    if ($LASTEXITCODE -ne 0) {
        throw "Android build failed."
    }
} finally {
    Pop-Location
    $env:JAVA_HOME = $previousJavaHome
    $env:ANDROID_SDK_ROOT = $previousSdkRoot
}

$sourceApk = Join-Path $AndroidRoot "app\build\outputs\apk\sideload\app-sideload.apk"
$destinationApk = Join-Path $DistRoot "NovelAI-LAN-Studio-Android-v$Version.apk"
Copy-Item -LiteralPath $sourceApk -Destination $destinationApk -Force
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $destinationApk
Write-Host "완료: $destinationApk"
Write-Host "SHA-256: $($hash.Hash)"
