# Known limitations and next work

This list describes the uploaded revision 1.1 baseline; the PC checkout may already contain later work.

1. **City/state-only facility review.** The writer and UI currently require a street address. The intended v1 requirement is that customer code, city and state can suffice. Implement optional address fields with provenance and a regression check; keep individual facilities distinct even under the same company.
2. **Historical reconciliation.** Parsing and arithmetic checks are incomplete for parts of the private archive. A passing synthetic suite does not establish historical completeness or resolve missing weeks.
3. **Financial changes.** Numeric/date proposals are retained for review but not applied by this UI. Facility/category decisions do not certify a statement or change financial amounts automatically.
4. **Lane decisions.** Historical rates do not establish current availability, reload probability, exact route fuel use, state-tax liability or per-load profit. Exact-radius search needs separately sourced location data.
5. **Power BI.** Query and measure files are present. An actual Desktop report and its verification are pending.
6. **Microsoft workflow.** The separate prime-power-platform-lab reports a published Canvas app checkpoint but is blocked at Power Automate Save with `FlowNotOriginalAuthor`. Both drafts remain inactive and no successful processor run is verified. Actual solution export, source and final acceptance remain pending; see [current status](../powerplatform/STATUS.md). It must not write into the private SQLite ledger as part of the portfolio demo.
7. **Ongoing release process.** Reconcile newer local work, add continuous integration, and update the release builder's selection when creating subsequent source archives. The original builder emits its own compact README and does not package every repository-preparation artifact.
8. **Standalone ingestion scope.** The reproducible demo creates fictional PDFs and directly seeds extraction/structured records. It exercises reporting and review, not an end-to-end OCR import of the private archive. This snapshot must not be presented as a fully reproduced historical ingestion pipeline.
9. **Measured business outcomes.** The demonstration validates selected functional behaviors. No measured revenue improvement, cost reduction or review-time reduction is established by this release.
