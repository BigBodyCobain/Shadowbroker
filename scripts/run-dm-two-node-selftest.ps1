param(
  [string]$NodeA = "http://127.0.0.1:8001",
  [string]$NodeB = "http://127.0.0.1:8002",
  [string]$AdminKey = "dm-test-node-local-admin-key-00000001"
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeRoot = Join-Path $Root ".runtime\dm-two-node"
$ReportPath = Join-Path $RuntimeRoot "two-node-selftest.json"
$Headers = @{ "X-Admin-Key" = $AdminKey }

function Invoke-Json(
  [string]$Method,
  [string]$Uri,
  [object]$Body = $null,
  [switch]$Admin
) {
  $args = @{
    Method = $Method
    Uri = $Uri
    TimeoutSec = 30
  }
  if ($Admin) {
    $args.Headers = $Headers
  }
  if ($null -ne $Body) {
    $args.Body = ($Body | ConvertTo-Json -Depth 100)
    $args.ContentType = "application/json"
  }
  return Invoke-RestMethod @args
}

function Assert-Ok([object]$Result, [string]$Step) {
  if (-not $Result -or -not [bool]$Result.ok) {
    $detail = if ($Result -and $Result.detail) { [string]$Result.detail } else { "no detail" }
    throw "$Step failed: $detail"
  }
}

function Register-DmNode([string]$BaseUrl, [string]$Label) {
  $registered = Invoke-Json "Post" "$BaseUrl/api/wormhole/dm/register-key" -Admin
  Assert-Ok $registered "$Label key registration"
  if (-not [bool]$registered.prekeys_ok -or -not $registered.prekey_detail -or -not $registered.prekey_detail.bundle) {
    throw "$Label prekey registration failed"
  }
  return [pscustomobject]@{
    label = $Label
    base = $BaseUrl
    node_id = [string]$registered.node_id
    dh_pub_key = [string]$registered.dh_pub_key
    prekey_bundle = $registered.prekey_detail.bundle
    registered = $registered
  }
}

function Try-Compose(
  [object]$Sender,
  [object]$Receiver,
  [string]$Plaintext
) {
  $body = @{
    peer_id = $Receiver.node_id
    peer_dh_pub = $Receiver.dh_pub_key
    plaintext = $Plaintext
    local_alias = $Sender.label
    remote_alias = $Receiver.label
  }
  return Invoke-Json "Post" "$($Sender.base)/api/wormhole/dm/compose" $body
}

function Decrypt-OnReceiver(
  [object]$Receiver,
  [object]$Sender,
  [object]$Envelope
) {
  $body = @{
    peer_id = $Sender.node_id
    ciphertext = $Envelope.ciphertext
    nonce = $Envelope.nonce
    format = $Envelope.format
    local_alias = $Receiver.label
    remote_alias = $Sender.label
    session_welcome = $Envelope.session_welcome
  }
  return Invoke-Json "Post" "$($Receiver.base)/api/wormhole/dm/decrypt" $body -Admin
}

function Search-PlaintextInNodeData([string]$Needle) {
  $hits = @()
  foreach ($nodeName in @("node-a", "node-b")) {
    $dataPath = Join-Path $RuntimeRoot "$nodeName\backend\data"
    if (-not (Test-Path $dataPath)) {
      continue
    }
    $matches = Get-ChildItem -Path $dataPath -Recurse -File -ErrorAction SilentlyContinue |
      Select-String -Pattern ([regex]::Escape($Needle)) -SimpleMatch -ErrorAction SilentlyContinue
    foreach ($match in @($matches)) {
      $hits += [pscustomobject]@{
        node = $nodeName
        path = $match.Path
        line = $match.LineNumber
      }
    }
  }
  return @($hits)
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

$healthA = Invoke-Json "Get" "$NodeA/api/health"
$healthB = Invoke-Json "Get" "$NodeB/api/health"

$nodeAState = Register-DmNode $NodeA "node-a"
$nodeBState = Register-DmNode $NodeB "node-b"

Invoke-Json "Post" "$NodeA/api/wormhole/dm/reset" @{ peer_id = $nodeBState.node_id } -Admin | Out-Null
Invoke-Json "Post" "$NodeB/api/wormhole/dm/reset" @{ peer_id = $nodeAState.node_id } -Admin | Out-Null

$inviteA = Invoke-Json "Get" "$NodeA/api/wormhole/dm/invite"
$inviteB = Invoke-Json "Get" "$NodeB/api/wormhole/dm/invite"
$inviteImportBIntoA = Invoke-Json "Post" "$NodeA/api/wormhole/dm/invite/import" @{
  invite = $inviteB.invite
  alias = "node-b"
} -Admin
Assert-Ok $inviteImportBIntoA "node-a import node-b signed invite"
$inviteImportAIntoB = Invoke-Json "Post" "$NodeB/api/wormhole/dm/invite/import" @{
  invite = $inviteA.invite
  alias = "node-a"
} -Admin
Assert-Ok $inviteImportAIntoB "node-b import node-a signed invite"

$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$messageAB = "dm-two-node-a-to-b-$timestamp"
$messageBA = "dm-two-node-b-to-a-$timestamp"

# Keep the actual round-trip below a clean first session so the receiver gets a
# fresh welcome every time.
Invoke-Json "Post" "$NodeA/api/wormhole/dm/reset" @{ peer_id = $nodeBState.node_id } -Admin | Out-Null
Invoke-Json "Post" "$NodeB/api/wormhole/dm/reset" @{ peer_id = $nodeAState.node_id } -Admin | Out-Null

$composeAB = Try-Compose $nodeAState $nodeBState $messageAB
Assert-Ok $composeAB "node-a compose to node-b"
$decryptAB = Decrypt-OnReceiver $nodeBState $nodeAState $composeAB
Assert-Ok $decryptAB "node-b decrypt from node-a"
if ([string]$decryptAB.plaintext -ne $messageAB) {
  throw "node-b decrypted unexpected plaintext"
}

$composeBA = Try-Compose $nodeBState $nodeAState $messageBA
Assert-Ok $composeBA "node-b compose to node-a"
$decryptBA = Decrypt-OnReceiver $nodeAState $nodeBState $composeBA
Assert-Ok $decryptBA "node-a decrypt from node-b"
if ([string]$decryptBA.plaintext -ne $messageBA) {
  throw "node-a decrypted unexpected plaintext"
}

$plaintextHits = @()
$plaintextHits += Search-PlaintextInNodeData $messageAB
$plaintextHits += Search-PlaintextInNodeData $messageBA

$report = [pscustomobject]@{
  ok = $true
  checked_at = $timestamp
  nodes = @{
    node_a = @{
      url = $NodeA
      id = $nodeAState.node_id
      health_status = $healthA.status
    }
    node_b = @{
      url = $NodeB
      id = $nodeBState.node_id
      health_status = $healthB.status
    }
  }
  first_contact = @{
    node_a_to_node_b = @{
      local = "node-a"
      remote = "node-b"
      trust_level = [string]$inviteImportBIntoA.trust_level
      invite_attested = [bool]$inviteImportBIntoA.invite_attested
    }
    node_b_to_node_a = @{
      local = "node-b"
      remote = "node-a"
      trust_level = [string]$inviteImportAIntoB.trust_level
      invite_attested = [bool]$inviteImportAIntoB.invite_attested
    }
    invite_export_ok = ([bool]$inviteA.ok -and [bool]$inviteB.ok)
    invite_import_node_b_into_node_a = @{
      ok = [bool]$inviteImportBIntoA.ok
      detail = [string]$inviteImportBIntoA.detail
    }
    invite_import_node_a_into_node_b = @{
      ok = [bool]$inviteImportAIntoB.ok
      detail = [string]$inviteImportAIntoB.detail
    }
  }
  message_round_trip = @{
    node_a_to_node_b = @{
      compose_ok = [bool]$composeAB.ok
      decrypt_ok = [bool]$decryptAB.ok
      format = [string]$composeAB.format
      has_session_welcome = [bool]$composeAB.session_welcome
      ciphertext_contains_plaintext = ([string]$composeAB.ciphertext).Contains($messageAB)
    }
    node_b_to_node_a = @{
      compose_ok = [bool]$composeBA.ok
      decrypt_ok = [bool]$decryptBA.ok
      format = [string]$composeBA.format
      has_session_welcome = [bool]$composeBA.session_welcome
      ciphertext_contains_plaintext = ([string]$composeBA.ciphertext).Contains($messageBA)
    }
  }
  privacy_storage_check = @{
    plaintext_found_in_node_data = ($plaintextHits.Count -gt 0)
    hits = @($plaintextHits)
  }
  limits = @(
    "This proves two separate localhost backend processes can perform MLS DM compose/decrypt both ways.",
    "It proves signed invite import can resolve invite-scoped prekeys over the peer-authenticated local test lane.",
    "It does not prove RNS/Tor/relay delivery because this local runtime intentionally disables those transports."
  )
}

$report | ConvertTo-Json -Depth 100 | Set-Content -Path $ReportPath -Encoding UTF8

Write-Host ""
Write-Host "DM two-node selftest passed."
Write-Host "A -> B: $($composeAB.format), decrypted by node-b."
Write-Host "B -> A: $($composeBA.format), decrypted by node-a."
Write-Host "Plaintext in node data: $($report.privacy_storage_check.plaintext_found_in_node_data)"
Write-Host "Invite import A<-B: $($report.first_contact.invite_import_node_b_into_node_a.ok) $($report.first_contact.invite_import_node_b_into_node_a.detail)"
Write-Host "Invite import B<-A: $($report.first_contact.invite_import_node_a_into_node_b.ok) $($report.first_contact.invite_import_node_a_into_node_b.detail)"
Write-Host "Report: $ReportPath"
