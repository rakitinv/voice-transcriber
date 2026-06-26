# Build browser extension (docs/RELEASE_BUILD_AND_DEPLOY.md section 5).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"
Import-ReleaseEnv

Assert-CommandExists "npm" "Node.js 22 required (npm in PATH)."
$repo = Get-RepoRoot
$extDir = Join-Path $repo "browser-extension"

# Compile-time default for fresh installs (see browser-extension/src/settings/storage.ts).
if (-not $env:VITE_DEFAULT_SERVER_URL -and $env:VT_PUBLIC_API_URL) {
    $env:VITE_DEFAULT_SERVER_URL = $env:VT_PUBLIC_API_URL.Trim()
}
if ($env:VITE_DEFAULT_SERVER_URL) {
    Write-Host "VITE_DEFAULT_SERVER_URL=$($env:VITE_DEFAULT_SERVER_URL)" -ForegroundColor DarkGray
}

Write-ReleaseStep "Browser extension: npm ci && npm run build"
$prevDir = Get-Location
Set-Location $extDir
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
}
finally {
    Set-Location $prevDir
}

Write-Host "Artifacts: $extDir\dist\" -ForegroundColor Green
