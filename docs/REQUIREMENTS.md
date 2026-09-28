# Requirements and delivered scope

- Four Linux screens: business overview, lane history, data quality, operational Settlement Review Desk.
- Snapshot-scoped read-only analysis with one eligibility/aggregation layer and source-linked drill-through.
- Explicit preliminary versus reconciled states, settlement-date basis, cohort counts and raw geography.
- Durable local review decisions with duplicate protection, source revision/value checks, reason/evidence and local reviewer label.
- Controlled, backed-up, versioned category/facility application; rollback/recovery and actual status rather than optimistic success.
- Independent fictional dataset, matching SQLite/CSV/JSON exports, public selection, documentation and evidence.

Implemented and tested in this milestone. The exact test and browser results are in `evidence/validation.json` and `evidence/browser/result.json`.

Pending scope: full historical financial reconciliation, numeric/date proposal application from the UI, economic category aggregation/allocation, bank payout bridge, supported facility-to-route linkage, geocoded distance searches, trip duration, live offers, Power BI Desktop runtime, and the Microsoft cloud workflow. Empty or unsupported features are labeled; no results are fabricated.
