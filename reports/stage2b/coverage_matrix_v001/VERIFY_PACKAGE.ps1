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
$anc = Import-Csv (Join-Path $PackageRoot "analysis\event_primary_gnss_anchors_v001.csv")
$cov = Import-Csv (Join-Path $PackageRoot "analysis\coverage_matrix_v001.csv")
if ($anc.Count -ne 563 -or $cov.Count -ne (563 * 4)) { throw "Row count mismatch" }
Write-Host "ALL CHECKS PASSED (563 anchor assignments, 2,252 multi-domain coverage rows verified)." -ForegroundColor Cyan
