# Sync root VERSION into pyproject.toml and package.json files.
$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$versionFile = Join-Path $repoRoot "VERSION"
if (-not (Test-Path $versionFile)) {
    throw "VERSION file not found: $versionFile"
}
$version = (Get-Content -LiteralPath $versionFile -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$') {
    throw "VERSION must be SemVer (e.g. 0.2.0): got '$version'"
}

function Set-PyProjectVersion {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $newText = $text -replace '(?m)^version = ".*"', "version = `"$version`""
    if ($newText -eq $text) {
        Write-Warning "version= not updated in $Path"
    } else {
        Set-Content -LiteralPath $Path -Value $newText -Encoding UTF8 -NoNewline
        Write-Host "Updated $Path -> $version"
    }
}

function Set-PackageJsonVersion {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $newText = $text -replace '(?m)^(\s*"version"\s*:\s*")[^"]*(")', "`${1}$version`${2}"
    if ($newText -eq $text) {
        Write-Warning "version not updated in $Path"
    } else {
        Set-Content -LiteralPath $Path -Value $newText -Encoding UTF8 -NoNewline
        Write-Host "Updated $Path -> $version"
    }
}

Set-PyProjectVersion (Join-Path $repoRoot "server\pyproject.toml")
Set-PyProjectVersion (Join-Path $repoRoot "cli\pyproject.toml")
Set-PackageJsonVersion (Join-Path $repoRoot "webui\package.json")
Set-PackageJsonVersion (Join-Path $repoRoot "admin-webui\package.json")
Set-PackageJsonVersion (Join-Path $repoRoot "browser-extension\package.json")

Write-Host "VERSION $version synced."
