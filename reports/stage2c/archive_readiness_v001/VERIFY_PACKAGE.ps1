param([string]$PackageRoot = $PSScriptRoot)
$ErrorActionPreference = "Stop"
$entries = Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv")
foreach ($e in $entries) {
    $fp = Join-Path $PackageRoot $e.relative_path
    if (!(Test-Path $fp) -or (Get-FileHash $fp -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower()) {
        throw "SHA256 mismatch: $($e.relative_path)"
    }
    Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green
}
$rows = Import-Csv (Join-Path $PackageRoot "analysis\stage2c_verified_benchmark_cohort_v001.csv")
if ($rows.Count -ne 363) { throw "Expected 363 rows, got $($rows.Count)" }
Write-Host "ALL CHECKS PASSED (363 near-regional events audited and SHA-256 verified)." -ForegroundColor Cyan

