param(
  [string]$Python = "python"
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPath = Join-Path $repoRoot "venv"
& $Python -m venv $venvPath

$pip = Join-Path $venvPath "Scripts\pip.exe"
& $pip install -r (Join-Path $repoRoot "requirements-dev.txt")
