param(
    [string]$PackageRoot = $PSScriptRoot
)
$ErrorActionPreference = "Stop"
$manifestPath = Join-Path $PackageRoot "SHA256SUMS.csv"
if (!(Test-Path $manifestPath)) { throw "Missing manifest: $manifestPath" }

$entries = Import-Csv $manifestPath
$failures = 0
foreach ($e in $entries) {
    $fp = Join-Path $PackageRoot $e.relative_path
    if (!(Test-Path $fp)) {
        Write-Host "FAIL (missing): $($e.relative_path)" -ForegroundColor Red
        $failures++
        continue
    }
    $actualHash = (Get-FileHash $fp -Algorithm SHA256).Hash.ToLower()
    $actualSize = (Get-Item $fp).Length
    if ($actualHash -ne $e.sha256.ToLower() -or $actualSize -ne [int64]$e.size_bytes) {
        Write-Host "FAIL (mismatch): $($e.relative_path)" -ForegroundColor Red
        $failures++
    } else {
        Write-Host "PASS: $($e.relative_path)" -ForegroundColor Green
    }
}

$evRows = Import-Csv (Join-Path $PackageRoot "analysis\event_level_evidence_review_v001.csv")
$srRows = Import-Csv (Join-Path $PackageRoot "analysis\source_evidence_register_v001.csv")
$uniqueIds = ($evRows | Select-Object -ExpandProperty event_id -Unique).Count

if ($evRows.Count -ne 16 -or $uniqueIds -ne 16) {
    Write-Host "FAIL: Expected 16 unique Mariana events, found $($evRows.Count) rows / $uniqueIds unique." -ForegroundColor Red
    $failures++
} else {
    Write-Host "PASS: 16 rows / 16 unique event IDs verified." -ForegroundColor Green
}

if ($failures -gt 0) { throw "Verification failed with $failures error(s)." }
Write-Host "ALL CHECKS PASSED ($($entries.Count) manifest files, $($srRows.Count) source records)." -ForegroundColor Cyan
