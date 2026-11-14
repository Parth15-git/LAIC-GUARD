param([string]$PackageRoot = $PSScriptRoot)
$ErrorActionPreference = "Stop"
$entries = Import-Csv (Join-Path $PackageRoot "SHA256SUMS.csv")
$failures = 0
foreach ($e in $entries) {
    $fp = Join-Path $PackageRoot $e.relative_path
    if (!(Test-Path $fp) -or (Get-FileHash $fp -Algorithm SHA256).Hash.ToLower() -ne $e.sha256.ToLower() -or (Get-Item $fp).Length -ne [int64]$e.size_bytes) {
        Write-Host "FAIL: $($e.relative_path)" -ForegroundColor Red; $failures++
    } else { Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green }
}
$evRows = Import-Csv (Join-Path $PackageRoot "analysis\event_level_evidence_review_v001.csv")
$srRows = Import-Csv (Join-Path $PackageRoot "analysis\source_evidence_register_v001.csv")
if ($evRows.Count -ne 14 -or ($evRows | Select-Object -ExpandProperty event_id -Unique).Count -ne 14) { throw "Row count mismatch" }
if ($failures -gt 0) { throw "Verification failed" }
Write-Host "ALL CHECKS PASSED (14 unique Izu-Bonin events, $($entries.Count) manifest files, $($srRows.Count) source records)." -ForegroundColor Cyan
