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
$ev = Import-Csv (Join-Path $PackageRoot "analysis\event_gnss_coverage_summary_v001.csv")
if ($ev.Count -ne 563) { throw "Expected 563 Stage 1D events, got $($ev.Count)" }
Write-Host "ALL CHECKS PASSED (563 Stage 1D events paired and SHA-256 verified)." -ForegroundColor Cyan
