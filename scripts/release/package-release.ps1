# Package release bundle into VT_RELEASE_DIR (called from build-all).
param(
    [switch]$SkipDockerExport
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"
Import-ReleaseEnv

$repo = Get-RepoRoot
$out = Get-ReleaseOutputDir
$tag = Get-ReleaseTag
$dockerDir = Join-Path $repo "docker"

Write-ReleaseStep "Release output: $out"
if (Test-Path $out) {
    Remove-Item -Recurse -Force $out
}
New-Item -ItemType Directory -Path $out | Out-Null

$deployRoot = Join-Path $out "deploy"
New-Item -ItemType Directory -Path $deployRoot | Out-Null

Write-ReleaseStep "Copy deploy/docker, configs, scripts/release"
Copy-Item -Recurse (Join-Path $repo "docker") (Join-Path $deployRoot "docker")
$bundledDotenv = Join-Path $deployRoot "docker\.env"
if (Test-Path $bundledDotenv) {
    Remove-Item -Force $bundledDotenv
}
Copy-Item -Recurse (Join-Path $repo "configs") (Join-Path $deployRoot "configs")
New-Item -ItemType Directory -Path (Join-Path $out "scripts\release") -Force | Out-Null
$releaseSrc = Join-Path $repo "scripts\release"
$releaseDst = Join-Path $out "scripts\release"
$winReserved = '(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$'
Get-ChildItem -LiteralPath $releaseSrc -Force |
    Where-Object { $_.Name -notmatch $winReserved } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $releaseDst $_.Name) -Recurse -Force }

Write-ReleaseStep "Public URLs for server (public-urls.env)"
Write-PublicUrlsEnvFile (Join-Path $deployRoot "docker\public-urls.env")

$artifacts = Join-Path $out "artifacts"
New-Item -ItemType Directory -Path (Join-Path $artifacts "cli") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $artifacts "browser-extension") -Force | Out-Null

$cliDist = Join-Path $repo "cli\dist"
if (Test-Path $cliDist) {
    Copy-Item (Join-Path $cliDist "*") (Join-Path $artifacts "cli") -Recurse
}

$extDist = Join-Path $repo "browser-extension\dist"
if (Test-Path $extDist) {
    $extOut = Join-Path $artifacts "browser-extension\dist"
    Copy-Item -Recurse $extDist $extOut
    $zipPath = Join-Path $artifacts ("voice-transcriber-extension-{0}.zip" -f $tag)
    Compress-Archive -Path (Join-Path $extDist "*") -DestinationPath $zipPath -Force
}

if (-not $SkipDockerExport) {
    Assert-CommandExists "docker" ""
    $imgDir = Join-Path $out "docker-images"
    New-Item -ItemType Directory -Path $imgDir | Out-Null

    Write-ReleaseStep "Export app images (docker save, including compose profiles)"
    $prevDir = Get-Location
    Set-Location $dockerDir
    try {
        $allImages = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $base = docker compose config --images 2>$null
        if ($LASTEXITCODE -ne 0) { throw "docker compose config --images failed" }
        foreach ($i in $base) { if ($i) { [void]$allImages.Add($i.Trim()) } }
        $profCsv = @()
        if ($env:VT_DOCKER_COMPOSE_PROFILES) { $profCsv += $env:VT_DOCKER_COMPOSE_PROFILES }
        if ($env:VT_COMPOSE_PROFILES) { $profCsv += $env:VT_COMPOSE_PROFILES }
        $profileNames = ($profCsv -join ',') -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        if ($profileNames.Count -gt 0) {
            foreach ($p in $profileNames) {
                $svcs = @(Get-ComposeProfileBuildServices $p)
                if ($svcs.Count -eq 0) {
                    $profImgs = docker compose --profile $p config --images 2>$null
                    if ($LASTEXITCODE -ne 0) { throw "docker compose config --images (profile $p) failed" }
                    foreach ($i in $profImgs) { if ($i) { [void]$allImages.Add($i.Trim()) } }
                    continue
                }
                foreach ($s in $svcs) {
                    $profImgs = docker compose --profile $p config --images $s 2>$null
                    if ($LASTEXITCODE -ne 0) { throw "docker compose config --images ($s) failed" }
                    foreach ($i in $profImgs) { if ($i) { [void]$allImages.Add($i.Trim()) } }
                }
            }
        }
        # Infra images (postgres/redis/minio) — отдельно при VT_EXPORT_INFRA_IMAGES (см. bash package-release.sh).
        $unique = $allImages | Where-Object {
            $_ -and
            $_ -notmatch '^(postgres|redis):' -and
            $_ -notmatch '^minio/' -and
            $_ -notmatch '^voice-transcriber-tests'
        } | Sort-Object
        foreach ($img in $unique) {
            if (-not (Test-DockerImageExists $img)) {
                throw "Local image not found: $img. Run build-docker / docker compose build first."
            }
            $safeName = ($img -replace '[/:]', '_')
            $tar = Join-Path $imgDir "$safeName.tar"
            Write-Host "  save $img -> $tar"
            docker save -o $tar $img
            if ($LASTEXITCODE -ne 0) { throw "docker save failed for $img" }
        }
    }
    finally {
        Set-Location $prevDir
    }

    if ($env:VT_EXPORT_INFRA_IMAGES -eq "1") {
        Write-ReleaseStep "Export infra images (postgres, redis, minio)"
        $infra = @("postgres:16-alpine", "redis:7-alpine", "minio/minio:latest")
        foreach ($img in $infra) {
            if (-not (Test-DockerImageExists $img)) {
                Write-Host "  pull $img"
                docker pull $img
                if ($LASTEXITCODE -ne 0) { throw "docker pull failed for $img" }
            }
            $safeName = ($img -replace '[/:]', '_')
            $tar = Join-Path $imgDir "infra_$safeName.tar"
            Write-Host "  save $img -> $tar"
            docker save -o $tar $img
            if ($LASTEXITCODE -ne 0) { throw "docker save failed for $img" }
        }
    }
}

$manifest = @{
    product  = "voice-transcriber"
    tag      = $tag
    built_at = (Get-Date).ToUniversalTime().ToString("o")
    contents = @(
        "deploy/docker"
        "deploy/configs"
        "docker-images/*.tar"
        "artifacts/cli"
        "artifacts/browser-extension"
        "scripts/release/install-or-update.sh"
    )
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $out "RELEASE_MANIFEST.json") -Encoding UTF8

$readme = @"
Voice Transcriber release $tag

1. Copy this folder to the server (scp, rsync, or zip).
2. On Linux: edit /etc/voice-transcriber/voice-transcriber.env
   Copy URL lines from deploy/docker/public-urls.env (VT_ADMIN_WEBUI_ORIGIN required for admin OAuth).
3. Run: bash scripts/release/install-or-update.sh <path-to-this-folder>

See docs/RELEASE_BUILD_AND_DEPLOY.md
"@
Set-Content -Path (Join-Path $out "README-DISTRIBUTION.txt") -Value $readme -Encoding UTF8

Write-Host ""
Write-Host "Release bundle ready: $out" -ForegroundColor Green
