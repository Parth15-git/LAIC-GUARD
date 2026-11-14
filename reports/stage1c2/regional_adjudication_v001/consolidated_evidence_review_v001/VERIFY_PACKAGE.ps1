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
$rows = Import-Csv (Join-Path $PackageRoot "analysis\event_level_consolidated_evidence_review_v001.csv")
if ($rows.Count -ne 1186 -or ($rows | Select-Object -ExpandProperty event_id -Unique).Count -ne 1186) { throw "Baseline count mismatch" }
$qCount = ($rows | Where-Object { $_.in_adjudication_queue_v001 -eq "True" }).Count
if ($qCount -ne 351) { throw "Queue count mismatch: $qCount" }
if ($failures -gt 0) { throw "Verification failed" }
Write-Host "ALL CHECKS PASSED (1,186 / 1,186 unique catalogue events, 351 / 351 queue events, $($entries.Count) manifest files)." -ForegroundColor Cyan
