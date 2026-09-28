# Implementation decisions

1. **Keep the existing SQLite ledger.** Additive migration 007 introduces applied-decision keys and versioned mappings. Original OCR, postings, parser versions, source-image reviews and invoice candidates remain intact.
2. **Use immutable reporting batches.** A consistent SQLite backup supplies every export. A successful batch atomically replaces the latest pointer; a failed build leaves the prior published batch available.
3. **Keep cents integer and cohorts paired.** Weighted RPM sums eligible owner cents and the same rows' miles. Unknown values stay null; invoice and stop records never join into leg amounts.
4. **Separate workflow from accounting.** Recording is not applying. Category/facility decisions have explicit tested nonfinancial paths; numerical/date corrections remain source-linked proposals. No decision implies complete statement reconciliation.
5. **Keep the journal separate, with recovery keys.** The ledger's unique decision ID repairs an interrupted acknowledgement. The system does not claim a transaction spanning two databases.
6. **Bind locally and default to fiction.** The default root is the deterministic demo. Private data is an explicit launch option. No public hosting, Microsoft tenant or account credentials are required.
7. **Prepare Microsoft artifacts honestly.** Typed exports, DAX and Power Query are present. No untested report file, screenshot or flow runtime is presented as finished.
