# Build CLI wheel/sdist (docs/RELEASE_BUILD_AND_DEPLOY.md section 4).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"
Import-ReleaseEnv

Assert-CommandExists "python" "Python 3.12+ required (python in PATH)."
$repo = Get-RepoRoot
$cliDir = Join-Path $repo "cli"

Write-ReleaseStep "CLI: python -m build (output: cli/dist/)"
$prevDir = Get-Location
Set-Location $cliDir
try {
    python -m pip install --upgrade pip build
    if ($LASTEXITCODE -ne 0) { throw "pip install build failed" }
    python -m build
    if ($LASTEXITCODE -ne 0) { throw "python -m build failed" }
}
finally {
    Set-Location $prevDir
}

Write-Host "Artifacts: $cliDir\dist\" -ForegroundColor Green
