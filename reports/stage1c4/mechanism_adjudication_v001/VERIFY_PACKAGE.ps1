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
$rows = Import-Csv (Join-Path $PackageRoot "analysis\event_level_mechanism_adjudication_v001.csv")
if ($rows.Count -ne 1186 -or ($rows | Select-Object -ExpandProperty event_id -Unique).Count -ne 1186) { throw "Row count mismatch" }
Write-Host "ALL CHECKS PASSED (1,186 / 1,186 unique events verified)." -ForegroundColor Cyan
