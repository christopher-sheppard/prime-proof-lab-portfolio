# Reporting contract 1.1

All tables in a batch come from the same consistent `source.sqlite` backup. `reporting.sqlite`, CSVs and JSON rows have matching keys and values. The manifest includes table counts, SHA-256 hashes, parser/schema versions, source-through date, quality counts and dataset type. `data_dictionary.json` is generated from the actual SQLite field/type definitions, not copied from the proposed design.

| Table | Grain and primary key | Notes |
|---|---|---|
| FactStatement | One current owner/payroll statement document, statement_id | Same-date units are retained; net due is cash due, not profit |
| FactLoadLeg | One current source leg, leg_id | Key is document/page/physical line; no stop/invoice joins into the fact |
| FactPosting | One source posting line, posting_id | Signed integer cents; service date stays null unless supported |
| FactReviewIssue | One current source issue/party review, issue_id | Maps to SourceRecord; standalone support-document issues have null statement_id |
| DimDate | One continuous calendar date, date | ISO week/year included; used as settlement/posting date basis |
| DimOperatingPeriod | One evidenced period, period_id | Explicit unknown member; no year-based guesses |
| DimOrigin / DimDestination | One raw city/jurisdiction tuple per role, place_id | Unverified OCR places; not automatically facilities |
| SourceRecord | One review subject, record_id | Exact source locator, original JSON, expected revision and value fingerprint; local drill-through |

The manifest is `ExportManifest` as a JSON document, rather than an extra relational table. Historical duplicate parser runs are excluded by the existing latest-run boundary, not by settlement date. Possible semantic duplicate legs remain excluded; complete semantic deduplication of statement cash is pending.

The initial amount field is **candidate_dispatch_owner_cents**, not verified freight earnings. Preliminary eligibility requires a known owner amount, known loaded/empty/total miles, positive loaded and total miles, nonnegative empty miles, matching mileage and statement-revenue arithmetic, a single supported dispatch allocation, no possible duplicate identity, a settlement date and no disputed route approval annotation. No private rows are certified reconciled in this release.

For eligible rows only, weighted total-mile RPM is `sum(candidate_dispatch_owner_cents) / 100 / sum(total_miles)`. The same rows supply loaded-mile RPM and empty-mile share. No eligible rows produces null/Unavailable, not a fabricated zero. Individual-rate median/range are separately labeled. Zero-mile and uncertain allocation records stay in detail and review.

CSV empty cells are SQL NULL. IDs and codes are text, preserving leading zeros; cents/miles/flags are integers. Do not convert monetary cents to floating-point currency before summing. JSON preserves nulls and integer values exactly. Source evidence, source revisions, invoice detail, and local journals belong with private exports. Public releases generate these tables independently from fictional fixtures.

Record-level category/facility decisions are versioned in the ledger and visible in the Review Desk history. The reporting adapter deliberately does not treat them as global code rules, allocate costs, or bind route cities to invoice facilities. Those business semantics are still pending.
