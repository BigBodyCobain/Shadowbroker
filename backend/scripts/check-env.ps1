param(
  [string]$Python = "python"
)

& $Python -c "from services.env_check import validate_env; validate_env(strict=False)"
