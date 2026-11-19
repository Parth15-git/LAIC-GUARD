# Stage 6A.1 Protocol Addendum 001
## Open-Meteo elevation parameter and response interpretation

Protocol: stage6a1_strict_tcwv_v001.md
Date: 2026-11-18
Status: Clarification to frozen protocol v001

### 1. Required request configuration

The Stage 6A.1 extraction request must explicitly include:

- models=era5
- cell_selection=land
- latitude and longitude from the verified station registry
- elevation equal to registered station elevation in metres
- timezone=UTC

### 2. Interpretation of returned elevation

The five-event pilot compared default elevation handling against explicit station elevation.

When the elevation parameter was explicitly supplied, the returned response elevation equalled the supplied station elevation.

Therefore:

- Record requested station elevation separately.
- Record response-reported elevation separately.
- Do not label response-reported elevation as an independently measured grid-cell DEM elevation.
- Do not calculate station-to-grid elevation difference from that response field.
- Use returned latitude and longitude to calculate horizontal station-to-grid offset.
- An independent DEM elevation comparison requires a separate request without explicit elevation or another independently documented elevation source.

### 3. Pilot findings

Five representative event-station caches were tested.

Changing from default elevation handling to explicit station elevation:

- Did not change the returned grid coordinates in the five pilot cases.
- Changed returned response elevation to the requested station height.
- Changed surface pressure by approximately 2.6–4.0 hPa between the two configurations.
- Changed temperature and dew point by approximately 0.15–0.30 degrees Celsius.
- Did not change TCWV values or missing-value masks in the five pilot cases.

These observations are specific to the five tested cases. They must not be assumed to hold across all 111 event-station caches.

### 4. TCWV availability

The five-event pilot confirmed that explicitly selecting ERA5 did not remove the previously observed missing-TCWV periods in the tested events.

No dew-point-derived replacement is permitted.

Full-cohort missingness must be recalculated from the new pinned caches.

### 5. Comparison limitation

Differences between the previous caches and new pinned ERA5 data cannot be attributed exclusively to model selection.

The old requests did not explicitly select a model and did not pass station elevation. The new requests do both.

Thus, differences may reflect both source-selection and elevation-handling changes.

### 6. Superseding interpretation

This addendum supersedes the returned-grid-elevation interpretation in Section 3 and Section 4 of protocol v001.

The original protocol remains unchanged and retains its original SHA256 hash.

No full-cohort retrieval or benchmark execution is authorised by this addendum alone.

---

End of Addendum 001.
