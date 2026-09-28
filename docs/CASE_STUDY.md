# Case study: making trucking settlement figures usable

[README](../README.md) · [Visual tour](VISUAL_TOUR.md) · [Architecture](ARCHITECTURE.md) · [Evidence map](EVIDENCE_MAP.md)

## Problem and intended user

An owner-operator needs to compare freight by revenue per mile and lane, while understanding the limitations of the underlying records. Weekly settlements combine load activity with expenses, cash transfers, payroll and adjustments. Reading each document manually makes it difficult to compare periods consistently or revisit the assumptions behind a number.

Chris Sheppard brought the operating context: partial loads handed to another driver, multiple facilities under the same customer brand, trainer payroll, lease transitions, reserve payouts and charges that appear long after the service date. Those details shaped the requirements and exception cases.

The intended decision is: **what does my historical freight experience support, and what still needs review before I rely on it?** Current dispatch availability and route-level profit estimates require additional data and are outside this milestone.

## Contribution and approach

Chris supplied the domain requirements and business acceptance rules. Codex assisted with implementation and validation. The prototype uses Python, SQLite and Streamlit to connect a reporting model to a local review desk. A separate fictional dataset lets a reviewer reproduce the demonstration without the private settlement archive.

The deliverable connects a source ledger that retains provenance, reporting snapshots for consistent analysis, and a decision journal that preserves review history. The [architecture](ARCHITECTURE.md) describes those boundaries.

## Business rules translated into the build

| Operating reality | Implementation choice | Why it matters |
|---|---|---|
| Loads cover different distances | Divide eligible revenue by the same legs' total miles | Prevents short loads from receiving disproportionate weight |
| Mileage or repower allocation may be uncertain | Keep the leg visible and exclude it from rate calculations | Avoids making an unsupported rate look precise |
| A load can have several stops and repeated invoice pages | Keep one reporting row per source load leg | Prevents duplicated revenue from joins |
| Settlement cash includes reserve movements and adjustments | Keep cash due separate from the freight-rate calculation | Avoids presenting payout as profit |
| A trainee's gross pay may include Prime-funded amounts | Distinguish evidenced owner charges from trainee gross | Avoids assigning the entire wage to the owner |
| A source can be reparsed after review starts | Check source revision and value before applying a mapping | Protects newer evidence from stale decisions |
| Processing can stop after a database write | Retain a unique applied-decision key and recovery history | Allows a retry to find the existing effect |

## A calculation you can explain in an interview

The synthetic fixture has two eligible legs:

| Leg | Candidate owner revenue | Loaded miles | Empty miles | Total miles | Individual RPM |
|---|---:|---:|---:|---:|---:|
| A | $100 | 80 | 20 | 100 | $1.00 |
| B | $300 | 180 | 20 | 200 | $1.50 |
| Combined | **$400** | **260** | **40** | **300** | **$1.333 weighted** |

`($100 + $300) / (100 + 200) = $1.333 per total mile`.

The simple average of $1.00 and $1.50 would be $1.25 and would give the two different-distance legs equal weight. Five other fixture legs remain visible but are excluded for unknown mileage, unresolved repower allocation, zero mileage or a disputed annotation. These are test values, not claimed earnings.

## Demonstrated result

The release provides four functioning dashboard pages, nine SQL reporting tables with matching CSV/JSON exports, original source-page inspection and a persistent local decision journal. Supported category/facility mappings have validation, backup, rollback and recovery paths. Numeric/date corrections remain proposals.

An independent rerun on September 28, 2026 passed **65 automated tests** on the supplied synthetic release, including Streamlit AppTest checks. The screenshots and browser smoke record are supplied-release evidence. See the [evidence map](EVIDENCE_MAP.md) for exact implementation and verification links.

The small fixture proves behavior under selected cases. It does not establish complete ingestion or reconciliation of eight years of statements. The demo seeds extraction and structured records directly; historical OCR and financial completeness are separate work.

## Next business milestones

Complete historical reconciliation, support city/state-only facility confirmation, establish economic cost classification, and validate richer lane comparisons against the private archive. Any claimed improvement in revenue, cost or review time will require a measured baseline and subsequent results. This release makes no such outcome claim.
