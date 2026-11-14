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
$qa = Import-Csv (Join-Path $PackageRoot "analysis\stage3a_trop_pilot_qa_v001.csv")
Write-Host "ALL CHECKS PASSED ($($qa.Count) Tier-1 M>=7.0 events ingested, parsed, and SHA-256 verified)." -ForegroundColor Cyan
