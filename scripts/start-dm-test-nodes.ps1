param(
  [int]$NodeAPort = 8001,
  [int]$NodeBPort = 8002,
  [switch]$NoSync
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$SourceBackend = Join-Path $Root "backend"
$RuntimeRoot = Join-Path $Root ".runtime\dm-two-node"
$PidFile = Join-Path $RuntimeRoot "pids.json"

function Resolve-SharedPython {
  $marker = Join-Path $SourceBackend ".venv-dir"
  $candidates = @()
  if (Test-Path $marker) {
    $raw = (Get-Content $marker -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($raw) {
      $venvDir = if ([System.IO.Path]::IsPathRooted($raw)) { $raw } else { Join-Path $SourceBackend $raw }
      $candidates += Join-Path $venvDir "Scripts\python.exe"
    }
  }
  $candidates += @(
    (Join-Path $SourceBackend "venv\Scripts\python.exe"),
    (Join-Path $SourceBackend "venv-repair\Scripts\python.exe")
  )
  $candidates += Get-ChildItem -Path $SourceBackend -Directory -Filter "venv-repair*" -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "Scripts\python.exe" }

  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path $candidate)) {
      return (Resolve-Path $candidate).Path
    }
  }
  throw "Could not find an existing backend Python venv. Start the normal backend once first, then rerun this script."
}

function Stop-PortIfListening([int]$Port) {
  $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($listener in $listeners) {
    if ($listener.OwningProcess) {
      Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
  }
}

function Sync-RuntimeBackend([string]$NodeName) {
  $nodeRoot = Join-Path $RuntimeRoot $NodeName
  $destBackend = Join-Path $nodeRoot "backend"
  New-Item -ItemType Directory -Force -Path $nodeRoot | Out-Null

  if (-not $NoSync) {
    New-Item -ItemType Directory -Force -Path $destBackend | Out-Null
    $excludeDirs = @(
      "data",
      "node_modules",
      "venv",
      ".venv",
      "venv-repair",
      "venv-repair-*",
      ".venv-repair",
      ".pytest_cache",
      ".ruff_cache",
      "__pycache__",
      "build",
      "backend.egg-info",
      "tests",
      "timemachine",
      "sb-custody-verify-*"
    )
    $excludeFiles = @(".env", "*.pyc", "*.pyo", "*.log", "test_*.py")
    $args = @(
      $SourceBackend,
      $destBackend,
      "/MIR",
      "/R:1",
      "/W:1",
      "/NFL",
      "/NDL",
      "/NJH",
      "/NJS",
      "/NP",
      "/XD"
    ) + $excludeDirs + @("/XF") + $excludeFiles
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -gt 7) {
      throw "robocopy failed for $NodeName with exit code $LASTEXITCODE"
    }
    foreach ($runtimeOnlyDir in @("tests", "timemachine", ".pytest_cache", ".ruff_cache", "__pycache__")) {
      $path = Join-Path $destBackend $runtimeOnlyDir
      if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
      }
    }
    Get-ChildItem -Path $destBackend -Filter "test_*.py" -File -ErrorAction SilentlyContinue |
      Remove-Item -Force -ErrorAction SilentlyContinue
  }

  $dataDir = Join-Path $destBackend "data"
  New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
  '{"enabled":true,"updated_at":0}' | Set-Content -Path (Join-Path $dataDir "node.json") -Encoding ASCII
  return $destBackend
}

function Write-NodeRunner(
  [string]$NodeName,
  [string]$BackendDir,
  [string]$Python,
  [int]$Port,
  [int]$PeerPort
) {
  $nodeRoot = Split-Path $BackendDir -Parent
  $logPath = Join-Path $nodeRoot "backend-$Port.log"
  $runner = Join-Path $nodeRoot "run-$Port.cmd"
  $peer = "http://127.0.0.1:$PeerPort"
  $privacyCore = Join-Path $Root "privacy-core\target\release\privacy_core.dll"
  if (-not (Test-Path $privacyCore)) {
    $privacyCore = Join-Path $Root "privacy-core\debug\privacy_core.dll"
  }
  if (-not (Test-Path $privacyCore)) {
    throw "Could not find privacy-core DLL under privacy-core\target\release or privacy-core\debug."
  }
  $content = @"
@echo off
set SB_TEST_NODE_NAME=$NodeName
set SB_TEST_NODE_URL=http://127.0.0.1:$Port
set ADMIN_KEY=dm-test-node-local-admin-key-00000001
set MESH_SELF_PEER_URL=http://127.0.0.1:$Port
set MESH_PEER_PUSH_SECRET=dm-test-two-node-peer-push-secret-00000001
set MESH_ONLY=true
set MESH_NODE_MODE=participant
set MESH_BOOTSTRAP_DISABLED=true
set MESH_MQTT_ENABLED=false
set MESH_RNS_ENABLED=false
set MESH_ARTI_ENABLED=false
set MESH_DM_SECURE_MODE=true
set MESH_PRIVATE_RELEASE_APPROVAL_ENABLE=true
set MESH_DM_RELAY_AUTO_RELOAD=true
set MESH_RELAY_PEERS=$peer
set PRIVACY_CORE_LIB=$privacyCore
set PYTHONPATH=$BackendDir
cd /d "$BackendDir"
"$Python" -m uvicorn main:app --host 127.0.0.1 --port $Port --timeout-keep-alive 120
"@
  $content | Set-Content -Path $runner -Encoding ASCII
  return @{ Runner = $runner; Log = $logPath }
}

function Start-TestNode([string]$NodeName, [int]$Port, [int]$PeerPort, [string]$Python) {
  Stop-PortIfListening $Port
  $backendDir = Sync-RuntimeBackend $NodeName
  $runnerInfo = Write-NodeRunner $NodeName $backendDir $Python $Port $PeerPort
  $cmd = "/c `"`"$($runnerInfo.Runner)`" > `"$($runnerInfo.Log)`" 2>&1`""
  $process = Start-Process -FilePath "cmd.exe" -ArgumentList $cmd -PassThru -WindowStyle Minimized
  return @{
    node = $NodeName
    port = $Port
    pid = $process.Id
    backend = $backendDir
    data = Join-Path $backendDir "data"
    log = $runnerInfo.Log
    peer = "http://127.0.0.1:$PeerPort"
  }
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
$python = Resolve-SharedPython

$nodes = @(
  Start-TestNode "node-a" $NodeAPort $NodeBPort $python
  Start-TestNode "node-b" $NodeBPort $NodeAPort $python
)

$payload = @{
  started_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  shared_python = $python
  nodes = $nodes
}
$payload | ConvertTo-Json -Depth 5 | Set-Content -Path $PidFile -Encoding UTF8

Write-Host ""
Write-Host "DM two-node test runtime started without copying dependencies."
Write-Host "Shared Python: $python"
foreach ($node in $nodes) {
  Write-Host "$($node.node): http://127.0.0.1:$($node.port)"
  Write-Host "  data: $($node.data)"
  Write-Host "  log:  $($node.log)"
}
Write-Host ""
Write-Host "Stop with: powershell -ExecutionPolicy Bypass -File scripts\stop-dm-test-nodes.ps1"
