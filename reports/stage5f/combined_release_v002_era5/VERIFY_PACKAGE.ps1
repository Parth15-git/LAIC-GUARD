param([string]$PackageRoot = $PSScriptRoot)
$ErrorActionPreference = "Stop"
foreach ($e in (Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv"))) {
  if ((Get-FileHash (Join-Path $PackageRoot $e.relative_path) -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) { throw "Mismatch: $($e.relative_path)" }
  Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green
}
Write-Host "ALL CHECKS PASSED (Stage 5F combined v002 + v002_era5 release verified)." -ForegroundColor Cyan
