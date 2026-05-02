param(
  [string]$Python = "py"
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPath = Join-Path $repoRoot "venv"
$venvMarker = Join-Path $repoRoot ".venv-dir"
& $Python -3.11 -m venv $venvPath

$pip = Join-Path $venvPath "Scripts\pip.exe"
& $pip install --upgrade pip
Push-Location $repoRoot
& (Join-Path $venvPath "Scripts\python.exe") -m pip install -e .
& $pip install pytest pytest-asyncio ruff black
"venv" | Set-Content -LiteralPath $venvMarker -NoNewline
Pop-Location
