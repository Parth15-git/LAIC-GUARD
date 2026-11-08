# Reproducibility and Verification Checklist

## Before download
- [ ] Source and product identified.
- [ ] Official product documentation read.
- [ ] Access terms/licence checked.
- [ ] Product version and time resolution recorded.
- [ ] Expected spatial/temporal coverage stated.

## After download
- [ ] File opens and format is valid.
- [ ] Source URL and download timestamp (UTC) recorded.
- [ ] File size recorded.
- [ ] SHA-256 recorded.
- [ ] Date range and station/product IDs verified.
- [ ] Original file retained unchanged.

## Before processing
- [ ] Script version and configuration saved.
- [ ] Units, coordinates and time zones checked.
- [ ] QA flags interpreted using product-specific documentation.
- [ ] Missingness not silently filled.
- [ ] Duplicate records and out-of-range values checked.

## Before analysis
- [ ] Event selection rule frozen.
- [ ] Sequence grouping defined.
- [ ] Feature calculations tested on a small sample.
- [ ] No future data enters historical forecasts.
- [ ] Test events/periods remain untouched.
- [ ] Control selection and multiple-testing plan documented.

## Before GitHub push
- [ ] No credentials, tokens, personal data or restricted raw data.
- [ ] No oversized raw data files.
- [ ] README and source registry updated.
- [ ] Code formatted and tests pass.
- [ ] Manifest and checksums included where permissible.
- [ ] Commit message describes the change.
