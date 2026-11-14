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
$res = Import-Csv (Join-Path $PackageRoot "analysis\stage3b_multilayer_falsification_results_v001.csv")
Write-Host "ALL CHECKS PASSED ($($res.Count) multi-layer benchmark events verified)." -ForegroundColor Cyan
