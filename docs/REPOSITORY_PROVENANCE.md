# Repository preparation

Prepared September 28, 2026 from the user-supplied Prime_Synthetic_Dashboard_1_1_20260928T000244Z.zip.

Input archive SHA-256:
`09d59024c8270e32f086f0b128f1fcd9d9083556942d9440ce71a9bdcfe59181`

The input contains 64 files. Its ZIP integrity was checked. release_manifest.json is preserved as the **original archive manifest**: its hashes and publication status describe that input snapshot, not later repository documentation or commits. The Jobs_Prime_Release documents are also dated release records.

Repository preparation adds a portfolio README, known limitations, this provenance record, Git exclusions and an independently executed test log. It does not change application code, SQL migrations, fictional fixtures, dependencies or the user's active PC checkout.

## Verification

uv sync --frozen installed the supplied lock file with Python 3.13.15, Streamlit 1.64.0 and pandas 3.0.6. The command .venv/bin/python -m unittest discover -s tests -v passed all 65 tests. The log and machine-readable record are under evidence/repository_preparation_*.

This execution includes Streamlit AppTest checks. The separate Chromium smoke run and its screenshots are supplied-release evidence, not a new browser run performed during this preparation. No private settlement archive was imported or revalidated here.

## Integration with the ongoing PC work

The uploaded snapshot may predate changes still being made by local Codex. Compare it with the existing ~/Projects/prime-proof-lab working tree before integrating. Preserve existing commits and uncommitted work; do not replace that directory, force-push, reset it, or copy this snapshot over it wholesale.

Keep ~/PrimeData, source documents, runtime databases, local exports and credentials outside the repository. Future commits need a staged-file review because Git exclusions alone do not remove files already tracked.

## Portfolio presentation update — September 28, 2026

A documentation-only pass expands the root overview and adds a business case study, a visual tour using the existing release screenshots, an architecture guide and a skill/test evidence map. It also makes the directly seeded demo and unmeasured business outcomes explicit. Application code, SQL, dependencies, fixtures and original evidence files are unchanged. The 65-test result above remains the independently executed baseline; the presentation update does not claim a new test or browser run.

## Operational screenshot update — September 28, 2026

Four operator-supplied screenshots of the private local installation are added under `evidence/private-history-redacted/`. They use lossless crops and one opaque source-identifier mask. Original screenshot files and rejected generated editing attempts are excluded from the repository. The redaction manifest records source/output hashes and verifies exact original pixels outside the mask. The README links to a separate operational gallery so private-history screen values are not confused with the reproducible synthetic fixture or independently audited financial results. Application code and the original test evidence remain unchanged.
