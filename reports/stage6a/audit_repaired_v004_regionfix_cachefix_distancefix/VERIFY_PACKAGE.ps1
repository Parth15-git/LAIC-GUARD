param([string]$PackageRoot = $PSScriptRoot)
$ErrorActionPreference = "Stop"

$manifestPath = Join-Path $PackageRoot "SHA256SUMS.csv"
if (!(Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Missing SHA256SUMS.csv"
}

$expectedPaths = @(
    "STAGE6A_AUDIT_REPAIRED_v004.md",
    "VERIFY_PACKAGE.ps1",
    "analysis/stage6a_v004_benchmark_summary.csv",
    "analysis/stage6a_v004_event_features.csv",
    "analysis/stage6a_unit_and_window_tests_v004.json"
)

$entries = @(Import-Csv -LiteralPath $manifestPath)
if ($entries.Count -ne $expectedPaths.Count) {
    throw "Manifest must contain exactly $($expectedPaths.Count) entries."
}

$rootFull = [System.IO.Path]::GetFullPath($PackageRoot)
$rootFull = $rootFull.TrimEnd([char[]]@(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
))
$rootPrefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar

$seen = New-Object 'System.Collections.Generic.HashSet[string]'

foreach ($required in $expectedPaths) {
    $matchesForPath = @($entries | Where-Object {
        [string]$_.relative_path -eq $required
    })
    if ($matchesForPath.Count -ne 1) {
        throw "Manifest entry missing or duplicated: $required"
    }
}

foreach ($entry in $entries) {
    $relativePath = ([string]$entry.relative_path).Trim()
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        throw "Manifest contains a blank relative path."
    }
    if ($expectedPaths -notcontains $relativePath) {
        throw "Unexpected manifest path: $relativePath"
    }
    if (-not $seen.Add($relativePath)) {
        throw "Duplicate manifest path: $relativePath"
    }

    $fullPath = [System.IO.Path]::GetFullPath(
        (Join-Path $PackageRoot $relativePath)
    )
    if (-not $fullPath.StartsWith(
        $rootPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Path escapes package root: $relativePath"
    }
    if (!(Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "Missing package file: $relativePath"
    }

    $file = Get-Item -LiteralPath $fullPath
    if ($file.Length -le 0) {
        throw "Empty package file: $relativePath"
    }

    $expectedSize = 0L
    if (-not [long]::TryParse([string]$entry.size_bytes, [ref]$expectedSize)) {
        throw "Invalid size_bytes in manifest: $relativePath"
    }
    if ($file.Length -ne $expectedSize) {
        throw "Size mismatch: $relativePath"
    }

    $expectedHash = ([string]$entry.sha256).Trim().ToLowerInvariant()
    if ($expectedHash -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid SHA256 field in manifest: $relativePath"
    }

    $actualHash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "SHA256 mismatch: $relativePath"
    }

    Write-Host "PASS: size and SHA256 - $relativePath" -ForegroundColor Green
}

# Validate event-level CSV identity and completeness.
$eventPath = Join-Path $PackageRoot "analysis\stage6a_v004_event_features.csv"
$eventRows = @(Import-Csv -LiteralPath $eventPath)
if ($eventRows.Count -lt 1) {
    throw "Event-features CSV is empty."
}

$idSet = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($row in $eventRows) {
    $eventId = ([string]$row.event_id).Trim()
    if ([string]::IsNullOrWhiteSpace($eventId)) {
        throw "Blank event_id in event-features CSV."
    }
    if (-not $idSet.Add($eventId)) {
        throw "Duplicate event_id in event-features CSV: $eventId"
    }
}

# Validate summary CSV and its adjusted-p-value columns.
$summaryPath = Join-Path $PackageRoot "analysis\stage6a_v004_benchmark_summary.csv"
$summaryRows = @(Import-Csv -LiteralPath $summaryPath)
if ($summaryRows.Count -lt 1) {
    throw "Benchmark summary CSV is empty."
}

$columns = @($summaryRows[0].PSObject.Properties.Name)
$requiredColumns = @(
    "p_auc_holm_four_primary_models",
    "p_physical_holm_three_distinct_endpoints"
)
foreach ($column in $requiredColumns) {
    if ($columns -notcontains $column) {
        throw "Required adjusted-p-value column missing: $column"
    }
}

$aucAdjustedCount = 0
$physicalAdjustedCount = 0
$physicalAdjustedValues = @{}
$duplicatePhysicalKeys = @()
$culture = [System.Globalization.CultureInfo]::InvariantCulture
$numberStyle = [System.Globalization.NumberStyles]::Float

foreach ($row in $summaryRows) {
    $number = 0.0
    $aucValue = [string]$row.p_auc_holm_four_primary_models
    if ([double]::TryParse($aucValue, $numberStyle, $culture, [ref]$number)) {
        if ($number -lt 0.0 -or $number -gt 1.0) {
            throw "AUC Holm-adjusted p-value outside [0,1]."
        }
        $aucAdjustedCount++
    }

    $physicalValue = ([string]$row.p_physical_holm_three_distinct_endpoints).Trim()
    if (
        $physicalValue -and
        $physicalValue -ne "NOT_IN_PRIMARY_FAMILY"
    ) {
        try {
            $physicalObject = ConvertFrom-Json -InputObject $physicalValue -ErrorAction Stop
        }
        catch {
            throw "Invalid JSON physical Holm field in summary row '$($row.model_or_stratum)': $($_.Exception.Message)"
        }

        foreach ($endpointProperty in $physicalObject.PSObject.Properties) {
            $endpoint = [string]$endpointProperty.Name
            $endpointValue = $endpointProperty.Value

            if ([string]$endpointValue.status -eq "DUPLICATE_NOT_RECOUNTED") {
                $duplicatePhysicalKeys += $endpoint
                continue
            }

            $rawPhysicalP = 0.0
            $adjustedPhysicalP = 0.0

            if (-not [double]::TryParse(
                [string]$endpointValue.raw_p,
                $numberStyle,
                $culture,
                [ref]$rawPhysicalP
            )) {
                throw "Invalid raw physical p-value for endpoint '$endpoint'."
            }

            if (-not [double]::TryParse(
                [string]$endpointValue.holm_adjusted_p,
                $numberStyle,
                $culture,
                [ref]$adjustedPhysicalP
            )) {
                throw "Invalid physical Holm-adjusted p-value for endpoint '$endpoint'."
            }

            if (
                $rawPhysicalP -lt 0.0 -or $rawPhysicalP -gt 1.0 -or
                $adjustedPhysicalP -lt 0.0 -or $adjustedPhysicalP -gt 1.0
            ) {
                throw "Physical raw or Holm-adjusted p-value outside [0,1]: $endpoint"
            }

            if ($physicalAdjustedValues.ContainsKey($endpoint)) {
                throw "Duplicate distinct physical endpoint in summary: $endpoint"
            }

            $physicalAdjustedValues[$endpoint] = $adjustedPhysicalP
            $physicalAdjustedCount++
        }
    }
}

if ($aucAdjustedCount -lt 4) {
    throw "Expected four numeric primary AUC Holm-adjusted values; found $aucAdjustedCount."
}
if ($physicalAdjustedCount -ne 3) {
    throw "Expected exactly three distinct physical Holm-adjusted JSON values; found $physicalAdjustedCount."
}
foreach ($expectedEndpoint in @("ztd", "cal", "vtec")) {
    if (-not $physicalAdjustedValues.ContainsKey($expectedEndpoint)) {
        throw "Missing distinct physical Holm-adjusted endpoint: $expectedEndpoint"
    }
}
foreach ($expectedDuplicate in @("cal", "vtec")) {
    if ($duplicatePhysicalKeys -notcontains $expectedDuplicate) {
        throw "Expected M4 duplicate marker missing for endpoint: $expectedDuplicate"
    }
}

# Validate JSON metadata and ensure cohort counts match the CSV.
$jsonPath = Join-Path $PackageRoot "analysis\stage6a_unit_and_window_tests_v004.json"
$meta = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json

# The four primary classifier models are mandatory and cannot be skipped.
$requiredPrimaryModels = @(
    "M2a: Raw GNSS ZTD-Only (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)",
    "M2c: Baseline-Calibrated ERA5 Residual (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)",
    "M3: Quiet F10.7-Adj. GIM VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)",
    "M4_ERA5: Joint Calibrated ERA5 + Quiet VTEC (Shallow, PRIMARY-DEPENDENCE-COMPONENT-CV)"
)

foreach ($primaryName in $requiredPrimaryModels) {
    $primaryMatches = @(
        $summaryRows | Where-Object {
            ([string]$_.model_or_stratum) -eq $primaryName
        }
    )

    if ($primaryMatches.Count -ne 1) {
        throw "Expected exactly one primary model summary row: $primaryName"
    }

    if ([string]$primaryMatches[0].status -ne "EVALUATED") {
        throw "Primary model was not evaluated: $primaryName"
    }
}

# Reconcile every skipped secondary evaluation between CSV and JSON.
$csvSkippedRows = @(
    $summaryRows | Where-Object {
        ([string]$_.status).StartsWith("SKIPPED_")
    }
)

$csvSkippedNames = @(
    $csvSkippedRows |
    ForEach-Object { [string]$_.model_or_stratum } |
    Sort-Object
)

$jsonSkippedRows = @($meta.skipped_secondary_evaluations)

$jsonSkippedNames = @(
    $jsonSkippedRows |
    ForEach-Object { [string]$_.model_or_stratum } |
    Sort-Object
)

$skipDifferences = @(
    Compare-Object `
        -ReferenceObject $csvSkippedNames `
        -DifferenceObject $jsonSkippedNames
)

if ($skipDifferences.Count -ne 0) {
    throw "CSV and JSON skipped-secondary evaluation records do not match."
}

foreach ($skip in $jsonSkippedRows) {
    $skipName = [string]$skip.model_or_stratum
    $skipStatus = [string]$skip.status

    if (@("SKIPPED_EMPTY_COHORT", "SKIPPED_INSUFFICIENT_VALIDATION_GROUPS") -notcontains $skipStatus) {
        throw "Unexpected skipped-secondary status: $skipStatus"
    }

    if ($requiredPrimaryModels -contains $skipName) {
        throw "A mandatory primary model appears in the skipped list: $skipName"
    }

    if ([string]::IsNullOrWhiteSpace([string]$skip.reason)) {
        throw "Skipped-secondary record has no reason: $skipName"
    }

    $matchingSkipRows = @(
        $summaryRows | Where-Object {
            ([string]$_.model_or_stratum) -eq $skipName
        }
    )

    if ($matchingSkipRows.Count -ne 1) {
        throw "Skipped-secondary CSV row is missing or duplicated: $skipName"
    }

    if ([string]$matchingSkipRows[0].status -ne $skipStatus) {
        throw "Skipped-secondary status differs between CSV and JSON: $skipName"
    }
}

# Verify the authoritative Stage 4B distance field and independent QC.
$distanceValidation = $meta.distance_validation

if ($null -eq $distanceValidation) {
    throw "JSON distance_validation metadata is missing."
}

if ([string]$distanceValidation.source_field -ne "verified_gnss_distance_km") {
    throw "Unexpected or missing verified GNSS distance source field."
}

if ([int]$distanceValidation.events_validated -ne $eventRows.Count) {
    throw "Distance-validation event count does not match event-features CSV."
}

$maximumDistanceDifference = [double]$distanceValidation.maximum_absolute_difference_km
$distanceTolerance = [double]$distanceValidation.acceptance_tolerance_km

if (
    $maximumDistanceDifference -lt 0.0 -or
    $distanceTolerance -le 0.0 -or
    $maximumDistanceDifference -gt $distanceTolerance
) {
    throw "Independent Haversine distance validation failed its tolerance."
}

if ($null -eq $meta.cohort_counts) {
    throw "JSON missing cohort_counts."
}
if ([int]$meta.cohort_counts.n_total_paired -ne $eventRows.Count) {
    throw "JSON event count does not match event-features CSV row count."
}
if ([string]$meta.scientific_scope -notmatch "not prospective earthquake prediction") {
    throw "JSON scientific-scope limitation is missing."
}

$groups = $meta.dependence_group_counts_primary_shallow
if ($null -eq $groups) {
    throw "JSON missing primary dependence-group counts."
}
foreach ($key in @(
    "time_overlap",
    "shared_time_or_station_50d",
    "shared_time_or_station_any"
)) {
    $value = $groups.$key
    if ($null -eq $value -or [int]$value -lt 1) {
        throw "Missing or invalid dependence-group count: $key"
    }
}

$multipleTesting = $meta.multiple_testing
if ($null -eq $multipleTesting) {
    throw "JSON multiple_testing metadata is missing."
}
if ([string]$multipleTesting.method -notmatch "Holm step-down") {
    throw "JSON multiple_testing method is missing or unexpected."
}

$families = $multipleTesting.families
if ($null -eq $families) {
    throw "JSON multiple_testing.families object is missing."
}

$familySpecifications = @(
    @{ Name = "four_primary_model_auc_tests"; ExpectedCount = 4 },
    @{ Name = "three_distinct_physical_endpoint_tests"; ExpectedCount = 3 },
    @{ Name = "two_primary_model_comparisons"; ExpectedCount = 2 }
)

foreach ($spec in $familySpecifications) {
    $familyProperty = $families.PSObject.Properties[$spec.Name]
    if ($null -eq $familyProperty) {
        throw "Missing multiple-testing family: $($spec.Name)"
    }

    $family = $familyProperty.Value
    if ($null -eq $family.raw_p_values -or $null -eq $family.holm_adjusted_p_values) {
        throw "Family lacks raw or Holm-adjusted p-values: $($spec.Name)"
    }

    $rawProperties = @($family.raw_p_values.PSObject.Properties | ForEach-Object { $_ })
    $adjustedProperties = @($family.holm_adjusted_p_values.PSObject.Properties | ForEach-Object { $_ })

    if ($rawProperties.Count -ne $spec.ExpectedCount) {
        throw "Unexpected raw p-value count in family $($spec.Name): $($rawProperties.Count)"
    }
    if ($adjustedProperties.Count -ne $spec.ExpectedCount) {
        throw "Unexpected Holm-adjusted p-value count in family $($spec.Name): $($adjustedProperties.Count)"
    }

    $rawNames = @($rawProperties | ForEach-Object { $_.Name } | Sort-Object)
    $adjustedNames = @($adjustedProperties | ForEach-Object { $_.Name } | Sort-Object)
    $keyDifferences = @(Compare-Object -ReferenceObject $rawNames -DifferenceObject $adjustedNames)

    if ($keyDifferences.Count -ne 0) {
        throw "Raw and adjusted p-value keys differ in family $($spec.Name)."
    }

    foreach ($entry in $rawProperties) {
        $pValue = 0.0
        if (-not [double]::TryParse(
            [string]$entry.Value,
            $numberStyle,
            $culture,
            [ref]$pValue
        )) {
            throw "Nonnumeric raw p-value in family $($spec.Name): $($entry.Name)"
        }
        if ($pValue -lt 0.0 -or $pValue -gt 1.0) {
            throw "Raw p-value outside [0,1] in family $($spec.Name): $($entry.Name)"
        }
    }

    foreach ($entry in $adjustedProperties) {
        $pValue = 0.0
        if (-not [double]::TryParse(
            [string]$entry.Value,
            $numberStyle,
            $culture,
            [ref]$pValue
        )) {
            throw "Nonnumeric Holm-adjusted p-value in family $($spec.Name): $($entry.Name)"
        }
        if ($pValue -lt 0.0 -or $pValue -gt 1.0) {
            throw "Holm-adjusted p-value outside [0,1] in family $($spec.Name): $($entry.Name)"
        }
    }

    Write-Host "PASS: family $($spec.Name) contains $($spec.ExpectedCount) matched raw/adjusted p-values." -ForegroundColor Green
}

if ([string]$multipleTesting.duplicate_policy -notmatch "not recounted") {
    throw "JSON does not document the M4 duplicate physical-endpoint policy."
}
$warning = [string]$multipleTesting.auc_permutation_resolution_warning
if ($warning -notmatch "99" -or $warning -notmatch "pilot") {
    throw "JSON does not document the 99-permutation AUC pilot limitation."
}

# Validate both matched model comparisons and their Holm-adjusted values.
$comparisons = $meta.paired_model_comparisons
foreach ($key in @("M2c_vs_M2a", "M4_vs_M3")) {
    $comparison = $comparisons.$key
    if ($null -eq $comparison) {
        throw "Missing model comparison metadata: $key"
    }
    $adjusted = 0.0
    if (-not [double]::TryParse(
        [string]$comparison.p_value_holm,
        $numberStyle,
        $culture,
        [ref]$adjusted
    )) {
        throw "Missing numeric Holm-adjusted comparison p-value: $key"
    }
    if ($adjusted -lt 0.0 -or $adjusted -gt 1.0) {
        throw "Comparison Holm-adjusted p-value outside [0,1]: $key"
    }
}

# Validate report substance and scope.
$reportPath = Join-Path $PackageRoot "STAGE6A_AUDIT_REPAIRED_v004.md"
$reportText = Get-Content -LiteralPath $reportPath -Raw
if ($reportText.Length -lt 1000) {
    throw "Audit report is unexpectedly short."
}
if ($reportText -notmatch "not prospective earthquake prediction") {
    throw "Audit report does not state the scientific-scope limitation."
}
if ($reportText -notmatch "Multiple-testing correction") {
    throw "Audit report is missing the multiple-testing section."
}
if ($reportText -notmatch "99" -or $reportText -notmatch "pilot") {
    throw "Audit report is missing the AUC permutation pilot warning."
}
if ($reportText -notmatch "verified_gnss_distance_km") {
    throw "Audit report is missing verified GNSS distance provenance."
}
if ($reportText -notmatch "Secondary analyses skipped") {
    throw "Audit report is missing secondary-analysis skip disclosure."
}

Write-Host "PASS: unique, nonblank event IDs ($($eventRows.Count) rows)." -ForegroundColor Green
Write-Host "PASS: four primary AUC Holm values and three distinct physical Holm values." -ForegroundColor Green
Write-Host "PASS: cohort, dependence groups, duplicate policy, and scientific scope." -ForegroundColor Green
Write-Host "PASS: both matched model comparisons have Holm-adjusted p-values." -ForegroundColor Green
Write-Host "PASS: substantive audit report and 99-permutation pilot caveat." -ForegroundColor Green
Write-Host "ALL CHECKS PASSED (Stage 6A v004 package verified)." -ForegroundColor Cyan
