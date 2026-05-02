param(
  [switch]$Clean
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$frontendDir = Join-Path $repoRoot "frontend"
$frontendOut = Join-Path $frontendDir "out"
$srcTauriDir = Join-Path $scriptDir "src-tauri"
$companionDir = Join-Path $srcTauriDir "companion-www"
$backendRuntimeDir = Join-Path $srcTauriDir "backend-runtime"
$iconsScript = Join-Path $scriptDir "scripts\generate-icons.cjs"
$exportScript = Join-Path $scriptDir "scripts\build-frontend-export.cjs"
$backendRuntimeScript = Join-Path $scriptDir "scripts\build-backend-runtime.cjs"
$manifestScript = Join-Path $scriptDir "scripts\write-release-manifest.cjs"
$localUpdaterKey = Join-Path $repoRoot "release-secrets\shadowbroker-updater.key"
$localUpdaterKeyPassword = Join-Path $repoRoot "release-secrets\shadowbroker-updater.key.pass"

function Invoke-External {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Command,
    [string]$WorkingDirectory = $scriptDir
  )

  $exe = $Command[0]
  $args = @()
  if ($Command.Length -gt 1) {
    $args = $Command[1..($Command.Length - 1)]
  }

  Push-Location $WorkingDirectory
  try {
    & $exe @args
    if ($LASTEXITCODE -ne 0) {
      throw "Command failed: $($Command -join ' ')"
    }
  }
  finally {
    Pop-Location
  }
}

foreach ($tool in @("cargo", "npm", "node")) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "$tool is required for desktop packaging."
  }
}

Push-Location $scriptDir
try {
  & cargo tauri -V *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "The Tauri CLI is required for desktop packaging. Install it with: cargo install tauri-cli@^2"
  }
}
finally {
  Pop-Location
}

if ($Clean) {
  Write-Host "=== Cleaning previous desktop release artifacts ==="
  foreach ($path in @(
    $frontendOut,
    $companionDir,
    $backendRuntimeDir,
    (Join-Path $srcTauriDir "icons"),
    (Join-Path $srcTauriDir "target\\release\\bundle"),
    (Join-Path $srcTauriDir "target\\release\\wix"),
    (Join-Path $srcTauriDir "target\\release\\nsis")
  )) {
    if (Test-Path $path) {
      Remove-Item -LiteralPath $path -Recurse -Force
    }
  }
  Write-Host ""
}

Write-Host "=== Generating branded desktop icons ==="
Invoke-External -Command @("node", $iconsScript)
Write-Host ""

Write-Host "=== Building frontend static export for desktop packaging ==="
Invoke-External -Command @("node", $exportScript)
Write-Host ""

Write-Host "=== Staging managed backend runtime for desktop packaging ==="
Invoke-External -Command @("node", $backendRuntimeScript)
Write-Host ""

if (-not (Test-Path $frontendOut)) {
  throw "frontend/out was not produced by NEXT_OUTPUT=export npm run build"
}
if (-not (Test-Path $backendRuntimeDir)) {
  throw "src-tauri/backend-runtime was not produced by build-backend-runtime.cjs"
}

Write-Host "Copying frontend export to companion-www..."
if (Test-Path $companionDir) {
  Remove-Item -LiteralPath $companionDir -Recurse -Force
}
Copy-Item -LiteralPath $frontendOut -Destination $companionDir -Recurse
$fileCount = (Get-ChildItem -LiteralPath $companionDir -Recurse -File | Measure-Object).Count
Write-Host "  -> $fileCount files"
Write-Host ""

Push-Location $srcTauriDir
try {
  if (-not $env:SHADOWBROKER_BACKEND_URL) {
    $env:SHADOWBROKER_BACKEND_URL = "http://127.0.0.1:8000"
  }
  if (
    -not $env:TAURI_SIGNING_PRIVATE_KEY -and
    -not $env:TAURI_SIGNING_PRIVATE_KEY_PATH -and
    (Test-Path $localUpdaterKey)
  ) {
    $env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -LiteralPath $localUpdaterKey -Raw
    if (($null -eq $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) -and (Test-Path $localUpdaterKeyPassword)) {
      $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = Get-Content -LiteralPath $localUpdaterKeyPassword -Raw
    }
  }

  Write-Host "=== ShadowBroker Tauri Build ==="
  Write-Host "Frontend dist:    $frontendOut"
  Write-Host "Companion www:    $companionDir"
  Write-Host "Backend runtime:  $backendRuntimeDir"
  Write-Host "Backend URL:      $env:SHADOWBROKER_BACKEND_URL"
  if ($env:TAURI_SIGNING_PRIVATE_KEY -or $env:TAURI_SIGNING_PRIVATE_KEY_PATH) {
    Write-Host "Updater signing:  enabled"
  } else {
    Write-Host "Updater signing:  disabled (set TAURI_SIGNING_PRIVATE_KEY_PATH to emit update signatures)"
  }
  Write-Host ""

  cargo tauri build
  if ($LASTEXITCODE -ne 0) {
    throw "cargo tauri build failed."
  }

  $bundleDir = Join-Path $srcTauriDir "target\release\bundle"
  if (Test-Path $bundleDir) {
    Write-Host ""
    Write-Host "=== Writing release manifest ==="
    Invoke-External -Command @("node", $manifestScript, $bundleDir)
  }
}
finally {
  Pop-Location
}
