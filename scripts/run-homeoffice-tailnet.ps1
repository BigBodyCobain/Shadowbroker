param(
    [switch]$Serve,
    [switch]$SkipBuild,
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvPath = Join-Path $RepoRoot ".env"

function New-Base64Secret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    [Convert]::ToBase64String($bytes)
}

function Ensure-EnvLine {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    if (!(Test-Path $EnvPath)) {
        New-Item -ItemType File -Path $EnvPath | Out-Null
    }

    $escapedKey = [regex]::Escape($Key)
    $content = Get-Content -LiteralPath $EnvPath -ErrorAction SilentlyContinue
    if ($content | Where-Object { $_ -match "^$escapedKey=" }) {
        return
    }
    Add-Content -LiteralPath $EnvPath -Value "$Key=$Value"
}

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (!(Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

Push-Location $RepoRoot
try {
    Require-Command docker

    Ensure-EnvLine "BIND" "127.0.0.1"
    Ensure-EnvLine "FRONTEND_PORT" "$FrontendPort"
    Ensure-EnvLine "BACKEND_PORT" "$BackendPort"
    Ensure-EnvLine "BACKEND_MEMORY_LIMIT" "4G"
    Ensure-EnvLine "ADMIN_KEY" (New-Base64Secret)
    Ensure-EnvLine "MESH_SECURE_STORAGE_SECRET" (New-Base64Secret)
    Ensure-EnvLine "MESH_DM_TOKEN_PEPPER" (New-Base64Secret)
    Ensure-EnvLine "MESH_INFONET_FLEET_JOIN" "false"
    Ensure-EnvLine "MESH_INFONET_ALLOW_CLEARNET_SYNC" "false"
    Ensure-EnvLine "MESH_MQTT_ENABLED" "false"
    Ensure-EnvLine "MESH_ARTI_ENABLED" "false"
    Ensure-EnvLine "MESH_NODE_MODE" "perimeter"
    Ensure-EnvLine "OPENSKY_CLIENT_ID" ""
    Ensure-EnvLine "OPENSKY_CLIENT_SECRET" ""
    Ensure-EnvLine "AIS_API_KEY" ""
    Ensure-EnvLine "GFW_API_TOKEN" ""
    Ensure-EnvLine "WINDY_API_KEY" ""
    Ensure-EnvLine "SHODAN_API_KEY" ""

    $composeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.homeoffice.yml")
    if ($SkipBuild) {
        & docker compose @composeArgs up -d
    } else {
        & docker compose @composeArgs up -d --build
    }
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "ShadowBroker is running for the TV at: http://127.0.0.1:$FrontendPort"

    if ($Serve) {
        Require-Command tailscale
        & tailscale serve --bg $FrontendPort
        if ($LASTEXITCODE -ne 0) {
            throw "tailscale serve failed with exit code $LASTEXITCODE"
        }

        $tailnetUrl = ""
        try {
            $status = & tailscale status --json | ConvertFrom-Json
            $dnsName = [string]$status.Self.DNSName
            if ($dnsName) {
                $tailnetUrl = "https://$($dnsName.TrimEnd('.'))"
            }
        } catch {
            $tailnetUrl = ""
        }

        if ($tailnetUrl) {
            Write-Host "Tailnet URL: $tailnetUrl"
        } else {
            Write-Host "Tailnet URL: run 'tailscale serve status' to view the HTTPS URL."
        }
    }

    Write-Host ""
    & docker compose @composeArgs ps
} finally {
    Pop-Location
}
