param(
  [int[]]$Ports = @(8001, 8002)
)

$ErrorActionPreference = "Continue"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeRoot = Join-Path $Root ".runtime\dm-two-node"
$PidFile = Join-Path $RuntimeRoot "pids.json"

if (Test-Path $PidFile) {
  try {
    $payload = Get-Content $PidFile -Raw | ConvertFrom-Json
    foreach ($node in @($payload.nodes)) {
      if ($node.pid) {
        Stop-Process -Id ([int]$node.pid) -Force -ErrorAction SilentlyContinue
      }
      if ($node.port) {
        $Ports += [int]$node.port
      }
    }
  } catch {
    Write-Host "Could not parse $PidFile; falling back to port cleanup."
  }
}

foreach ($port in ($Ports | Select-Object -Unique)) {
  $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($listener in $listeners) {
    if ($listener.OwningProcess) {
      Write-Host "Stopping PID $($listener.OwningProcess) on port $port"
      Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
  }
}

Write-Host "DM test nodes stopped."
