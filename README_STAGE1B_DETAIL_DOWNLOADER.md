# LAIC-GUARD Stage 1B — ComCat event detail downloader

## Why this tool exists

The uploaded Stage 1A manifest contains 15 columns and 55 rows. This downloader preserves that exact schema and appends two manifest records for each successful event detail retrieval:
1. Original USGS ComCat GeoJSON Detail response bytes.
2. A retrieval sidecar documenting the request, retrieval time, response identity, SHA-256, and available product-type counts.

It reads the Stage 1B priority list and the Stage 1A v002 catalogue. It verifies the 26 annual summary GeoJSON files against the current manifest before using their `properties.detail` URLs.

USGS GeoJSON Detail is a single-event feature including a `properties.products` object for products contributed by multiple sources. The tool downloads the detail JSON only; it does NOT download product-content attachments.

## Install

Copy `scripts/06_download_comcat_event_details.py` into the existing project's `scripts/` directory.

## First: compile and dry-run

From the LAIC-GUARD project root:

```powershell
python -m py_compile .\scripts\06_download_comcat_event_details.py
python .\scripts\06_download_comcat_event_details.py
```

Dry-run is the default. It makes no network requests and changes no files. It checks:
- `reports/stage1b/detail_review_priority_v001.csv`
- `metadata/event_catalogue_v002.csv`
- `metadata/data_manifest.csv`
- all 26 raw annual USGS summary GeoJSON files and their manifest hashes
- priority IDs against the v002 event IDs
- the manifest's exact 15-column schema

If the event-ID column in the priority CSV cannot be detected automatically, rerun with `--id-column COLUMN_NAME`.

## Second: three-event live test

Only after dry-run validation succeeds:

```powershell
python .\scripts\06_download_comcat_event_details.py --execute --limit 3
```

Check the three saved detail files, sidecars, manifest rows, status report and product index before continuing.

## Third: retrieve all priority details

```powershell
python .\scripts\06_download_comcat_event_details.py --execute
```

Default request pacing is one second between events. The process is resumable: files already present are skipped only when both their SHA-256/size match the existing manifest rows. Partial or unregistered files cause a safe stop rather than overwrite.

## Outputs

Raw ignored-by-Git files:
- `data/raw/usgs_event_details/<event_id>.detail.geojson`
- `data/raw/usgs_event_details/<event_id>.detail.metadata.json`

Tracked review outputs:
- `reports/stage1b/comcat_detail_retrieval_status_v001.csv`
- `reports/stage1b/comcat_detail_product_index_v001.csv`

`metadata/data_manifest.csv` is appended incrementally after each successful event.

## Important limits

- No event is removed, merged, or reclassified.
- No sequence ID is assigned.
- No product attachments are downloaded.
- No event catalogue CSV is modified.
- Failed events are recorded in the retrieval status report; successes remain preserved and registered.
- The downloader uses a conservative one-request-per-second pacing default. This is a courtesy setting, not a claim about a published USGS quota.
- A later manifest/artifact audit and Git review are required before committing any Stage 1B outputs.

## Provenance

The request uses each summary feature's USGS `properties.detail` URL when it is a valid HTTPS URL on `earthquake.usgs.gov`. If unavailable, it uses the FDSN Event Web Service `eventid` query as a fallback. Each saved detail response must be a single GeoJSON Feature, and its returned event ID must equal the requested ID or list the requested ID among its associated IDs.
