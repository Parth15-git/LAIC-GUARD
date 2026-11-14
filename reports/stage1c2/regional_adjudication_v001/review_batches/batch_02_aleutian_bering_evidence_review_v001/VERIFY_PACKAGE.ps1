param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ZipPath
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
    throw "ZIP file not found: $ZipPath"
}

$zipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "ZIP SHA-256: $zipHash"

$stageRoot = Join-Path $env:TEMP ("LAIC-GUARD_AB_Batch02_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stageRoot | Out-Null
Expand-Archive -LiteralPath $ZipPath -DestinationPath $stageRoot

$manifestFiles = @(Get-ChildItem -LiteralPath $stageRoot -Filter 'SHA256SUMS.csv' -File -Recurse)
if ($manifestFiles.Count -ne 1) {
    throw "Expected exactly one SHA256SUMS.csv; found $($manifestFiles.Count). Extraction: $stageRoot"
}

$packageRoot = Split-Path -Parent $manifestFiles[0].FullName
$manifestRows = @(Import-Csv -LiteralPath $manifestFiles[0].FullName)
if ($manifestRows.Count -ne 5) {
    throw "Expected five manifest entries; found $($manifestRows.Count)."
}

$seenPaths = @{}
$manifestResults = foreach ($entry in $manifestRows) {
    if ([string]::IsNullOrWhiteSpace($entry.relative_path)) {
        throw 'Manifest contains an empty relative_path.'
    }
    if ($seenPaths.ContainsKey($entry.relative_path)) {
        throw "Duplicate manifest path: $($entry.relative_path)"
    }
    $seenPaths[$entry.relative_path] = $true

    $normalizedRelativePath = $entry.relative_path.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    $filePath = Join-Path $packageRoot $normalizedRelativePath
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
        throw "Manifest file missing: $($entry.relative_path)"
    }

    $fileInfo = Get-Item -LiteralPath $filePath
    $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $sizeMatch = ($fileInfo.Length -eq [long]$entry.size_bytes)
    $hashMatch = ($actualHash -eq $entry.sha256.ToLowerInvariant())
    if (-not $sizeMatch -or -not $hashMatch) {
        throw "Manifest verification failed: $($entry.relative_path)"
    }

    [PSCustomObject]@{
        File = $entry.relative_path
        SizeMatch = $sizeMatch
        HashMatch = $hashMatch
    }
}

Write-Host "`n=== MANIFEST VERIFICATION ==="
$manifestResults | Format-Table -AutoSize

$eventCsv = Join-Path $packageRoot 'analysis\event_level_evidence_review_v001.csv'
$sourceCsv = Join-Path $packageRoot 'analysis\source_evidence_register_v001.csv'
$packageEvents = @(Import-Csv -LiteralPath $eventCsv)
$packageSources = @(Import-Csv -LiteralPath $sourceCsv)

$eventIds = @($packageEvents | ForEach-Object { $_.event_id })
$uniqueEventIds = @($eventIds | Sort-Object -Unique)
if ($packageEvents.Count -ne 37 -or $uniqueEventIds.Count -ne 37) {
    throw "Event validation failed: rows=$($packageEvents.Count), unique IDs=$($uniqueEventIds.Count)."
}

$sourceIds = @($packageSources | ForEach-Object { $_.source_id })
$uniqueSourceIds = @($sourceIds | Sort-Object -Unique)
if ($packageSources.Count -ne 21 -or $uniqueSourceIds.Count -ne 21) {
    throw "Source register validation failed: rows=$($packageSources.Count), unique IDs=$($uniqueSourceIds.Count)."
}

$usedReferences = @(
    foreach ($eventRow in $packageEvents) {
        foreach ($reference in ([string]$eventRow.source_reference_ids -split ';')) {
            $trimmedReference = $reference.Trim()
            if (-not [string]::IsNullOrWhiteSpace($trimmedReference)) {
                $trimmedReference
            }
        }
    }
)

$missingReferences = @(
    $usedReferences | Sort-Object -Unique | Where-Object { $_ -notin $uniqueSourceIds }
)
$unusedReferences = @(
    $uniqueSourceIds | Where-Object { $_ -notin $usedReferences }
)
if ($missingReferences.Count -gt 0 -or $unusedReferences.Count -gt 0) {
    throw "Reference validation failed. Missing: $($missingReferences -join ', '); unused: $($unusedReferences -join ', ')"
}

Write-Host "`n=== DATA VALIDATION ==="
Write-Host "Event rows: $($packageEvents.Count)"
Write-Host "Unique event IDs: $($uniqueEventIds.Count)"
Write-Host "Source rows: $($packageSources.Count)"
Write-Host "Unique source IDs: $($uniqueSourceIds.Count)"
Write-Host "Missing source references: $($missingReferences.Count)"
Write-Host "Unused source references: $($unusedReferences.Count)"
Write-Host "Extracted package folder: $packageRoot"
Write-Host "`nALL PACKAGE CHECKS PASSED"
