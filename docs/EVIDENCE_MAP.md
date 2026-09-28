# Skill and test evidence

[README](../README.md) · [Case study](CASE_STUDY.md) · [Visual tour](VISUAL_TOUR.md)

## Verified baseline

An independent execution of the supplied synthetic release on **September 28, 2026** ran:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

**Result: 65 tests passed; exit code 0.** The environment used Python 3.13.15, Streamlit 1.64.0 and pandas 3.0.6. The [machine-readable record](../evidence/repository_preparation_validation.json) includes the command, timestamps and log hash; the [full test log](../evidence/repository_preparation_unittest.txt) lists the checks.

This is a local test result, not a GitHub Actions run. The later portfolio documentation update leaves application code, fixtures and dependencies unchanged.

## Claim-to-evidence map

| Skill or behavior | Inspect the implementation | Inspect the supporting evidence |
|---|---|---|
| Business requirements translated into data rules | [Case study](CASE_STUDY.md), [requirements](REQUIREMENTS.md) | [Calculation example](CASE_STUDY.md#a-calculation-you-can-explain-in-an-interview), [dashboard tests](../tests/test_dashboard.py) |
| SQL data modeling and source provenance | [Migrations](../sql/), [reporting adapter](../analytics/reporting.py) | [Reporting contract](REPORTING_CONTRACT.md), [workbench tests](../tests/test_workbench.py) |
| Weighted freight-rate analysis | `eligibility` and `metrics` in [reporting.py](../analytics/reporting.py) | `test_weighted_unequal_distances_and_exclusions` in [dashboard tests](../tests/test_dashboard.py) |
| Handling repowers and repeated detail | [Workbench views](../sql/004_workbench.sql) | Repower, zero-mile, annotation, multistop and invoice-repetition checks in [dashboard tests](../tests/test_dashboard.py) |
| Consistent SQL/CSV/JSON exports | `export` and `write_tables` in [reporting.py](../analytics/reporting.py) | `test_sql_csv_json_repeated_export_and_snapshot_restore` in [dashboard tests](../tests/test_dashboard.py) |
| Interactive dashboards and source inspection | [Streamlit app](../dashboard/app.py), [source records](../analytics/records.py) | [Actual screenshots](VISUAL_TOUR.md), four-page Streamlit AppTest checks in [dashboard tests](../tests/test_dashboard.py) |
| Persistent decisions and duplicate protection | [Review service](../review/service.py), [review migration](../sql/007_review_desk.sql) | Persistence/request-collision and stale-source checks in [dashboard tests](../tests/test_dashboard.py) |
| Rollback and recovery | `apply` in [review/service.py](../review/service.py) | Validation-failure, after-commit interruption and snapshot-publication failure checks in [dashboard tests](../tests/test_dashboard.py) |
| Distinct customer facilities and source roles | [Invoice parties](../sql/006_invoice_parties.sql), [review service](../review/service.py) | [Invoice tests](../tests/test_invoice_details.py), two-plants/one-organization check in [dashboard tests](../tests/test_dashboard.py) |

## Evidence boundaries

| Evidence | Supports | Does not establish |
|---|---|---|
| Independent automated test run | The listed behaviors on synthetic test cases | Complete historical reconciliation, all real-world inputs or production readiness |
| Supplied browser screenshots and [result record](../evidence/browser/result.json) | Rendered screens, source-page display and a decision surviving reload in that supplied run | A newly repeated browser session or measured business improvement |
| Operator-supplied [operational screenshots](OPERATIONAL_SCREENSHOTS.md), with exact crops and redaction | Visible private-installation screens, filters, reported counts and preliminary status | Independent financial validation, exact private code revision or full historical completeness |
| Deterministic fixture and runnable demo | Reproduction of the reporting and review scenario | End-to-end OCR ingestion of the private archive |
| [Power Query and DAX files](../powerbi/) | Preparation for a reporting integration | A completed and verified Power BI Desktop dashboard |
| Separate [Power Platform lab](https://github.com/christopher-sheppard/prime-power-platform-portfolio) | Documented workflow design, acceptance criteria and a sanitized Hermes-reported Save blocker | Independently verified Canvas deployment, export/import reproduction or successful cloud-flow processing |

The strongest supported project description is a **working, AI-assisted Python/SQLite/Streamlit analytics and review prototype grounded in owner-operator requirements**. No quantified revenue gain, cost saving or time saving is claimed. See [known limitations](KNOWN_LIMITATIONS.md) and [release provenance](REPOSITORY_PROVENANCE.md).
