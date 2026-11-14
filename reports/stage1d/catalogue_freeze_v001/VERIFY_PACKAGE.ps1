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
$cat = Import-Csv (Join-Path $PackageRoot "analysis\event_catalogue_frozen_v001.csv")
$exc = Import-Csv (Join-Path $PackageRoot "analysis\event_exclusions_v001.csv")
$incCount = ($cat | Where-Object { $_.stage1d_included_in_pilot_v001 -eq "True" }).Count
if ($cat.Count -ne 1186 -or ($incCount + $exc.Count) -ne 1186) { throw "Partition mismatch" }
Write-Host "ALL CHECKS PASSED (1,186 total = $incCount included + $($exc.Count) excluded)." -ForegroundColor Cyan
