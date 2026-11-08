LAIC-GUARD — Stage 1B.2 Associate/Disassociate Review

PACKAGE CONTENTS
- scripts/07_audit_disassociate_adjudication.py
- reports/stage1b/adjudication/identity_link_adjudication_v001.csv
- reports/stage1b/adjudication/disassociate_pair_groups_v001.csv
- reports/stage1b/adjudication/associate_counterevidence_v001.csv
- reports/stage1b/adjudication/identity_link_review_summary_v001.json
- reports/stage1b/adjudication/STAGE1B2_IDENTITY_LINK_REVIEW_v001.md

INSTALL
Extract this ZIP into the LAIC-GUARD repository root. It adds one script and the Stage 1B.2 review outputs. It does not contain or overwrite raw data.

REPRODUCE
From the repository root:
  python .\scripts\07_audit_disassociate_adjudication.py

The script reads:
  data\raw\usgs_event_details\*.detail.geojson
  metadata\event_catalogue_v002.csv

It writes the review outputs to:
  reports\stage1b\adjudication\

IMPORTANT
All 25 disassociate records remain PENDING_MANUAL_ADJUDICATION. No events have been merged, split, deleted, or assigned sequence IDs. Do not commit a final event-identity decision until counterpart preferred IDs and ComCat history have been checked.
