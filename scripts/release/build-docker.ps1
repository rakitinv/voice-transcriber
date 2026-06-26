# Build Docker images (docs/RELEASE_BUILD_AND_DEPLOY.md section 3).
param(
    [switch]$SkipProfiles,
    [string[]]$Services
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_lib.ps1"
Import-ReleaseEnv

function Expand-ComposeServiceNames {
    param([string[]]$Raw)
    if (-not $Raw -or $Raw.Count -eq 0) { return @() }
  # ``@($Raw)`` — never iterate a bare string (PowerShell would walk characters).
    $names = [System.Collections.Generic.List[string]]::new()
    foreach ($item in @($Raw)) {
        if ([string]::IsNullOrWhiteSpace($item)) { continue }
        foreach ($part in ($item -split '[,\s]+')) {
            $t = $part.Trim()
            if ($t) { $names.Add($t) }
        }
    }
    return [string[]]$names.ToArray()
}

Assert-CommandExists "docker" "Install Docker Desktop or Docker Engine."
$repo = Get-RepoRoot
$dockerDir = Join-Path $repo "docker"

Write-ReleaseStep "docker compose build (directory: docker/)"
$prevDir = Get-Location
Set-Location $dockerDir
try {
    Set-ComposeBuildKitEnv

    # Compose build-args for frontends (from scripts/release/release.env via Import-ReleaseEnv).
    $env:VITE_API_BASE_URL = if ($env:VITE_API_BASE_URL) { $env:VITE_API_BASE_URL } else { "" }
    $env:VITE_ADMIN_API_BASE_URL = if ($env:VITE_ADMIN_API_BASE_URL) { $env:VITE_ADMIN_API_BASE_URL } else { "" }
    $env:VITE_PUBLIC_API_BASE_URL = if ($env:VITE_PUBLIC_API_BASE_URL) { $env:VITE_PUBLIC_API_BASE_URL } else { "" }
    $env:VITE_ADMIN_WEBUI_SELF_URL = if ($env:VITE_ADMIN_WEBUI_SELF_URL) { $env:VITE_ADMIN_WEBUI_SELF_URL } else { "" }
    $env:VITE_ADMIN_WEBUI_BASE_PATH = if ($env:VITE_ADMIN_WEBUI_BASE_PATH) { $env:VITE_ADMIN_WEBUI_BASE_PATH } else { "" }
    $env:VT_PUBLIC_API_URL = if ($env:VT_PUBLIC_API_URL) { $env:VT_PUBLIC_API_URL } else { "" }
    $env:VT_WEBUI_ORIGIN = if ($env:VT_WEBUI_ORIGIN) { $env:VT_WEBUI_ORIGIN } else { "" }
    $env:VT_ADMIN_WEBUI_ORIGIN = if ($env:VT_ADMIN_WEBUI_ORIGIN) { $env:VT_ADMIN_WEBUI_ORIGIN } else { "" }

    $serviceList = @(Expand-ComposeServiceNames $Services)
    foreach ($s in @($serviceList)) {
        if ($s -isnot [string] -or $s.Length -le 1) {
            throw @"
Invalid compose service name '$s'. Hyphenated names must be quoted in PowerShell, e.g.:
  -Services "admin-webui"
  -Services webui,"admin-webui"
"@
        }
    }
    if ($serviceList.Count -gt 0) {
        Invoke-ComposeBuildServices $serviceList
    } else {
        $defaultServices = @(Get-ComposeDefaultBuildServices)
        Write-ReleaseStep ("Build default compose services: " + ($defaultServices -join ", "))
        Invoke-ComposeBuildServices $defaultServices
    }

    if (-not $SkipProfiles -and $serviceList.Count -eq 0) {
        $optional = @(Get-ComposeOptionalBuildServices $env:VT_DOCKER_EXTRA_SERVICES $env:VT_DOCKER_COMPOSE_PROFILES)
        if ($optional.Count -gt 0) {
            Write-ReleaseStep "Optional compose services: $($optional -join ', ')"
            Invoke-ComposeBuildServices $optional
        }
    }
}
finally {
    Set-Location $prevDir
}

Write-Host "Done. List images: docker images --filter reference=voice-transcriber*" -ForegroundColor Green
