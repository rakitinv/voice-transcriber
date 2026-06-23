# Shared helpers for release build scripts (Windows PowerShell).

function Get-ReleaseScriptDir { $PSScriptRoot }

function Get-RepoRoot {
    Resolve-Path (Join-Path (Get-ReleaseScriptDir) "..\..")
}

function Import-ReleaseEnv {
    param([string]$ScriptDir = (Get-ReleaseScriptDir))
    $envFile = Join-Path $ScriptDir "release.env"
    if (-not (Test-Path $envFile)) { return }
    Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $name = $Matches[1]
            $value = $Matches[2].Trim()
            if (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            ) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

function Get-ReleaseTag {
    if ($env:VT_RELEASE_TAG) { return $env:VT_RELEASE_TAG.Trim() }
    $versionFile = Join-Path (Get-RepoRoot) "VERSION"
    if (Test-Path $versionFile) {
        $v = (Get-Content -LiteralPath $versionFile -Raw).Trim()
        if ($v) { return "v$v" }
    }
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $prevDir = Get-Location
        Set-Location (Get-RepoRoot)
        try {
            $tag = & git describe --tags --always 2>$null
            if ($LASTEXITCODE -eq 0 -and $tag) { return $tag.Trim() }
        }
        finally {
            Set-Location $prevDir
        }
    }
    Get-Date -Format "yyyy.MM.dd"
}

function Get-ReleaseOutputDir {
    $repo = Get-RepoRoot
    $base = if ($env:VT_RELEASE_DIR) { $env:VT_RELEASE_DIR.Trim() } else { "dist/release" }
    if (-not [System.IO.Path]::IsPathRooted($base)) {
        $base = Join-Path $repo $base
    }
    Join-Path $base ("voice-transcriber-" + (Get-ReleaseTag))
}

function Assert-CommandExists {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Command not found in PATH: $Name. $Hint"
    }
}

function Test-DockerImageExists {
    param([string]$ImageRef)
    # docker image inspect пишет в stderr при отсутствии образа; при $ErrorActionPreference=Stop PowerShell обрывает скрипт.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & docker image inspect $ImageRef *> $null
        return ($LASTEXITCODE -eq 0)
    }
    finally {
        $ErrorActionPreference = $prevEap
    }
}

function Write-ReleaseStep {
    param([string]$Message)
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Get-ComposeDefaultBuildServices {
    # Compose v2.20+ / v5 `docker compose build` без аргументов собирает и profile-only сервисы
    # (например diarization-worker). Явный список — только то, что нужно для базового стека.
    return @(
        "migrate",
        "api",
        "admin-api",
        "worker",
        "worker-final",
        "webui",
        "admin-webui"
    )
}

function Get-ComposeProfileBuildServices {
    param([string]$ProfileName)
    switch ($ProfileName.Trim()) {
        "gpu" { return @("worker-final-gpu", "diarization-worker-gpu") }
        "diarization" { return @("diarization-worker") }
        "scale_llm" { return @("worker-llm") }
        "test" { return @("tests") }
        default { return @() }
    }
}

function Get-ComposeServiceRequiredProfiles {
    param([string]$ServiceName)
    switch ($ServiceName.Trim()) {
        { $_ -in @("worker-final-gpu", "diarization-worker-gpu") } { return @("gpu") }
        "diarization-worker" { return @("diarization") }
        "worker-llm" { return @("scale_llm") }
        "tests" { return @("test") }
        default { return @() }
    }
}

function Set-ComposeBuildKitEnv {
    if (-not $env:DOCKER_BUILDKIT) { $env:DOCKER_BUILDKIT = "1" }
    if (-not $env:COMPOSE_DOCKER_CLI_BUILD) { $env:COMPOSE_DOCKER_CLI_BUILD = "1" }
    if (-not $env:BUILDX_NO_DEFAULT_ATTESTATIONS) { $env:BUILDX_NO_DEFAULT_ATTESTATIONS = "1" }
    if (-not $env:BUILDKIT_PROGRESS) { $env:BUILDKIT_PROGRESS = "plain" }
}

function Invoke-ComposeBuildServices {
    param([string[]]$ServiceNames)

    $unique = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($s in @($ServiceNames)) {
        if (-not [string]::IsNullOrWhiteSpace($s)) { [void]$unique.Add($s.Trim()) }
    }
    if ($unique.Count -eq 0) { return }

    $defaultBatch = [System.Collections.Generic.List[string]]::new()
    $profiled = [System.Collections.Generic.List[string]]::new()
    foreach ($s in @($unique)) {
        if ((Get-ComposeServiceRequiredProfiles $s).Count -gt 0) { $profiled.Add($s) } else { $defaultBatch.Add($s) }
    }

    if ($defaultBatch.Count -gt 0) {
        Write-ReleaseStep ("Build services: " + ($defaultBatch -join ", "))
        & docker compose build @($defaultBatch.ToArray())
        if ($LASTEXITCODE -ne 0) { throw "docker compose build failed with exit code $LASTEXITCODE" }
    }

    foreach ($s in $profiled) {
        $profileArgs = @()
        $profNames = @(Get-ComposeServiceRequiredProfiles $s)
        foreach ($p in $profNames) { $profileArgs += @("--profile", $p) }
        Write-ReleaseStep ("Build service: " + $s + " (profile: " + ($profNames -join ", ") + ")")
        & docker compose @profileArgs build $s
        if ($LASTEXITCODE -ne 0) { throw "docker compose build failed for '$s' with exit code $LASTEXITCODE" }
    }
}

function Get-ComposeOptionalBuildServices {
    param([string]$ExtraServices, [string]$ProfilesCsv)

    $names = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

    if ($ExtraServices) {
        foreach ($part in ($ExtraServices -split "[,\\s]+")) {
            $t = $part.Trim()
            if ($t) { [void]$names.Add($t) }
        }
    }

    if ($ProfilesCsv) {
        foreach ($p in ($ProfilesCsv -split ",")) {
            $t = $p.Trim()
            if (-not $t) { continue }
            $svcs = @(Get-ComposeProfileBuildServices $t)
            if ($svcs.Count -eq 0) {
                Write-Warning ("Unknown compose profile '" + $t + "' (VT_DOCKER_COMPOSE_PROFILES)")
                continue
            }
            foreach ($s in $svcs) { [void]$names.Add($s) }
        }
    }

    return [string[]]@($names | Sort-Object)
}

function Write-PublicUrlsEnvFile {
    param([string]$DestPath)
    $serverEnv = if ($env:VT_SERVER_ENV_FILE) { $env:VT_SERVER_ENV_FILE } else { "/etc/voice-transcriber/voice-transcriber.env" }
    $lines = @()
    if ($env:VT_PUBLIC_API_URL) { $lines += ("VT_PUBLIC_API_URL=" + $env:VT_PUBLIC_API_URL) }
    if ($env:VT_WEBUI_ORIGIN) { $lines += ("VT_WEBUI_ORIGIN=" + $env:VT_WEBUI_ORIGIN) }
    if ($env:VT_ADMIN_WEBUI_ORIGIN) { $lines += ("VT_ADMIN_WEBUI_ORIGIN=" + $env:VT_ADMIN_WEBUI_ORIGIN) }
    if ($env:VT_ADMIN_WEBUI_ORIGINS) { $lines += ("VT_ADMIN_WEBUI_ORIGINS=" + $env:VT_ADMIN_WEBUI_ORIGINS) }
    if ($lines.Count -eq 0) { return }
    @(
        "# Generated from scripts/release/release.env at bundle build time."
        ("# Copy into " + $serverEnv + " on the server (api service reads these at compose up).")
        ""
    ) + $lines | Set-Content -LiteralPath $DestPath -Encoding UTF8
    Write-Host ("  public-urls.env -> " + $DestPath)
}
