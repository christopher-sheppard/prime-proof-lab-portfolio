# Two-minute walkthrough

1. Run `prime_dashboard.py demo`, then `prime_dashboard.py serve`. Point out the Synthetic demo badge and dated snapshot.
2. On Business Overview, explain why $100/100 miles plus $300/200 miles gives $400/300 = $1.333 RPM, not the average of two rates. The owner amount is a candidate dispatch sum, not a customer invoice or profit.
3. Change Quality mode to Reconciled subset. Show the intentional empty state. Switch back before exploring lanes.
4. In Freight and Lane History, lower the minimum sample to two to show the fictional lane. Show the excluded unknown-mile, zero-mile, disputed-annotation and repower records.
5. Open Data Quality and Sources. Explain that arithmetic agreement, source coverage and full reconciliation are different.
6. In the Review Desk, inspect a fictional PDF next to its extracted text. Save a defer decision with a reason, reload, and show its history. No financial correction was claimed.

For a deeper walkthrough, select an invoice-party review, supply explicit fictional organization/plant/address keys, record and apply its mapping, and inspect the validation result. Use another facility key for a second plant under the same organization. Explain how duplicate requests and post-commit recovery avoid repeating effects.

The numerical fixture, screenshots and browser decisions are synthetic. Power BI and the Microsoft review lab are preparation/pending work, not part of the running demonstration.
