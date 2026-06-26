# Full release build: Docker + CLI + extension + package.
param(
    [switch]$SkipDocker,
    [switch]$SkipCli,
    [switch]$SkipExtension,
    [switch]$SkipPackage,
    [switch]$SkipProfiles
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"
Import-ReleaseEnv

$tag = Get-ReleaseTag
$out = Get-ReleaseOutputDir
Write-Host "Release tag: $tag"
Write-Host "Output directory: $out"

if (-not $SkipDocker) {
    if ($SkipProfiles) {
        & "$PSScriptRoot\build-docker.ps1" -SkipProfiles
    } else {
        & "$PSScriptRoot\build-docker.ps1"
    }
}
if (-not $SkipCli) {
    & "$PSScriptRoot\build-cli.ps1"
}
if (-not $SkipExtension) {
    & "$PSScriptRoot\build-extension.ps1"
}
if (-not $SkipPackage) {
    & "$PSScriptRoot\package-release.ps1"
}

Write-Host ""
Write-Host "Build finished. Copy this folder to the server:" -ForegroundColor Green
Write-Host "  $out"
