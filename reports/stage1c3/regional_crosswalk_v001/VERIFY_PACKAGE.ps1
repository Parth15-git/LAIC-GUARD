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
$rows = Import-Csv (Join-Path $PackageRoot "analysis\event_level_regional_crosswalk_v001.csv")
if ($rows.Count -ne 1186 -or ($rows | Select-Object -ExpandProperty event_id -Unique).Count -ne 1186) { throw "Row count mismatch" }
$blanks = ($rows | Where-Object {
    [string]::IsNullOrWhiteSpace($_.frozen_crosswalk_status_v001) -or
    [string]::IsNullOrWhiteSpace($_.frozen_macro_region_v001) -or
    [string]::IsNullOrWhiteSpace($_.frozen_subregion_v001) -or
    [string]::IsNullOrWhiteSpace($_.frozen_depth_tectonic_stratum_v001) -or
    [string]::IsNullOrWhiteSpace($_.stage1c2_disposition_v001)
}).Count
if ($blanks -gt 0) { throw "Found $blanks rows with blank frozen fields" }
if ($failures -gt 0) { throw "SHA-256 verification failed" }
Write-Host "ALL CHECKS PASSED (1,186 / 1,186 unique events, 0 blank fields, $($entries.Count) manifest files)." -ForegroundColor Cyan
