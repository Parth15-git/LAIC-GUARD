# Import instructions — Batch 02 Aleutian–Bering (v001)

This package is generated outside the user's repository. It has **not** been copied into or modified inside the Windows repository.

Recommended target folder:

`reports\stage1c2\regional_adjudication_v001\review_batches\batch_02_aleutian_bering_evidence_review_v001`

## Download and verify

1. Download `LAIC-GUARD_Stage1C2_Aleutian_Bering_Evidence_Review_v001.zip` to a location outside the repository. The browser's actual download location may differ from `$HOME\Downloads`; use the browser's Downloads page and **Show in folder** to identify the exact path.
2. Open PowerShell and run the verifier included in the package after extracting the ZIP, or invoke the standalone verifier file supplied alongside the package if available. The verifier searches recursively for the manifest, so it correctly handles the ZIP's top-level folder.

Example after downloading to `Downloads`:

```powershell
$zip = Join-Path $HOME 'Downloads\LAIC-GUARD_Stage1C2_Aleutian_Bering_Evidence_Review_v001.zip'
$extract = Join-Path $env:TEMP 'LAIC-GUARD_AB_Batch02_manual'
if (!(Test-Path -LiteralPath $zip -PathType Leaf)) { throw "ZIP not found: $zip" }
Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive -LiteralPath $zip -DestinationPath $extract
$verifier = Get-ChildItem -LiteralPath $extract -Filter 'VERIFY_PACKAGE.ps1' -File -Recurse | Select-Object -First 1
if ($null -eq $verifier) { throw 'VERIFY_PACKAGE.ps1 not found in extracted ZIP.' }
& $verifier.FullName -ZipPath $zip
```

The verifier locates `SHA256SUMS.csv` recursively, derives the package root from the manifest location, checks every manifest entry, and validates the 37 event rows, 37 unique event IDs, 21 source-register rows, and source-reference completeness. It stops on the first failure.

## Import only after local comparison

1. Compare all 37 event IDs and the catalogue fields in `analysis\event_level_evidence_review_v001.csv` against the current local crosswalk and frozen catalogue.
2. Inspect the review report and source register. The package itself records that event facts were transcribed from user-supplied PowerShell output, not independently recalculated from the Windows repository.
3. Only after the comparison passes, copy the extracted package folder into the recommended target folder. Do not overwrite `batch_01` or any historical v001 files.
4. Do not stage or commit the package yet. Ask for approval before staging an explicit file list.

## Scope limitations

The review is provisional. Event-level proposed fields are not approved regional assignments. No supporting-event download or protocol amendment is included. The manifest verifies the generated package, not local repository inputs.
