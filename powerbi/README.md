# Power BI preparation — Desktop validation pending

No `.pbix`/`.pbip` or successful Desktop refresh is claimed. Use an immutable synthetic reporting batch for the public report; a private import can embed private records in the report file.

1. Copy a complete dated reporting folder to Windows. Check `manifest.json` hashes. Set an `ExportFolder` text parameter to that folder.
2. Create the `LoadExport` Power Query function from `LoadExport.pq`. Add queries `LoadExport("FactLoadLeg")`, etc., for the eight analytical fact/dimension tables. SourceRecord is optional local provenance and is not needed for aggregate visuals.
3. Keep IDs text; cents, miles and eligibility flags whole numbers. The function uses generated data_dictionary.json. Convert the relevant ISO date columns to Date after import. Empty CSV cells become null, never zero.
4. Mark DimDate as the date table. Create single-direction one-to-many relationships from DimDate[date] to FactLoadLeg[settlement_date], FactStatement[settlement_date], FactPosting[posting_date], and FactReviewIssue[settlement_date]. Create DimOrigin/DimDestination[place_id] to the corresponding leg IDs; DimOperatingPeriod[period_id] to FactLoadLeg[period_id]. Do not activate fact-to-fact relationships or a second path from statement facts to leg facts.
5. Create a disconnected `DataMode` table with `Preliminary history` and `Reconciled subset`. Add a single-select slicer and measures from Measures.dax. Use the candidate-owner-revenue label until economic classification is verified.
6. Build overview, lane history and quality pages following docs/DASHBOARD_GUIDE.md. Cash cards are statement-scoped; crew/leg-quality filters do not apply. Keep their scope visible.
7. Verify the synthetic default cohort: $400 / 300 miles = $1.3333333333, two eligible legs. Reconciled mode is blank. Repeated invoice copies and intermediate stops must not change totals.
8. Record the actual Desktop version, refresh time, snapshot ID, filtered outputs and screenshots. Only then save the real report and change this status to demonstrated.

Power Query and DAX below are preparation artifacts; their runtime validation in Desktop remains outstanding. The Linux SQLite/CSV/UI agreement is independently tested.
