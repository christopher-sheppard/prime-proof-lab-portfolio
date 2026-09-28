"""Build/query the SQL workbench from saved OCR; this command never runs OCR."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import uuid

import prime_structure as structure

MIGRATION = '004_workbench'
CODE = Path(__file__).resolve().parent


@contextmanager
def locks(root):
    (root / 'staging').mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        for name in ('prime_import.lock', 'prime_extract.lock'):
            handle = stack.enter_context((root / 'staging' / name).open('a'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('An import is running. Let it finish before running this command.')
        yield


def initialize(root):
    db = structure.connect(root)
    try:
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='003_structured_staging'").fetchone():
            raise RuntimeError('The completed 0.3 import is required. Do not bootstrap again.')
        if db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION,)).fetchone():
            return
        backup = root / 'backups' / ('prime_before_workbench_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8] + '.sqlite')
        backup.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(backup)
        try:
            db.backup(target)
            if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or target.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Backup verification failed; migration stopped.')
        finally:
            target.close()
        print(f'Database backup: {backup}', flush=True)
        db.executescript('BEGIN IMMEDIATE;\n' + (CODE / 'sql/004_workbench.sql').read_text())
        db.execute('INSERT INTO schema_migrations VALUES (?,?)', (MIGRATION, structure.now()))
        db.execute("INSERT INTO system_metadata(key,value) VALUES ('historical_financial_import_complete','false') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def parse_cached(root):
    db = structure.connect(root)
    counts = {}
    try:
        items = db.execute('SELECT * FROM v_latest_document_extraction ORDER BY original_filename').fetchall()
        for index, item in enumerate(items, 1):
            result = structure.parse_document(db, item)
            counts[result] = counts.get(result, 0) + 1
            if index % 25 == 0 or index == len(items):
                print(f'Cached documents processed: {index}/{len(items)} | {counts}', flush=True)
        return counts
    finally:
        db.close()


def report(root):
    db = structure.connect(root, True)
    try:
        prefix = 'WITH current AS MATERIALIZED (SELECT * FROM v_workbench_statements) '
        result = {
            'created_at': structure.now(),
            'parser_version': structure.VERSION,
            'database': str(root / 'database/prime.sqlite'),
            'status': 'SQL workbench ready; source-derived candidates remain unverified',
            'historical_financial_import_complete': False,
            'documents': db.execute('SELECT count(*) FROM v_workbench_statements').fetchone()[0],
            'weekly_statement_documents': db.execute('SELECT count(*) FROM v_weekly_settlements').fetchone()[0],
            'posting_candidates': db.execute('SELECT count(*) FROM v_postings_keyed').fetchone()[0],
            'load_leg_candidates': db.execute('SELECT count(*) FROM v_loads_keyed').fetchone()[0],
            'location_candidates': db.execute('SELECT count(*) FROM v_location_history').fetchone()[0],
            'checks': dict(db.execute(prefix + 'SELECT c.status,count(*) FROM reconciliation_checks c JOIN current s USING(parse_id) GROUP BY c.status')),
            'load_rate_quality': dict(db.execute('SELECT rate_quality,count(*) FROM v_load_economics GROUP BY rate_quality')),
            'unresolved_statement_dates': db.execute("SELECT count(*) FROM v_weekly_settlements WHERE settlement_date IS NULL").fetchone()[0],
            'candidate_date_range': dict(db.execute('SELECT min(settlement_date) AS earliest,max(settlement_date) AS latest FROM v_weekly_settlements').fetchone()),
            'note': 'Dates do not certify weekly coverage. Matching arithmetic does not verify OCR or establish business profit. Customer tables start empty.'
        }
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'status'))
    parser.add_argument('--data-root', type=Path, default=Path(os.environ.get('PRIME_DATA_DIR', Path.home() / 'PrimeData')))
    args = parser.parse_args()
    root = args.data_root.expanduser().resolve()
    if args.command == 'run':
        with locks(root):
            initialize(root)
            from prime_review import initialize as initialize_reviews, backup
            initialize_reviews(root)
            print('Database backup:', backup(root, 'prime_before_cached_parse'), flush=True)
            counts = parse_cached(root)
            result = report(root)
            result['processing'] = counts
            destination = root / 'reports' / ('workbench_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8] + '.json')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2), flush=True)
            print(f'Report: {destination}', flush=True)
            if counts.get('needs_corrected_ocr'):
                print('Some documents lack complete corrected OCR; inspect the report. No OCR was started.', flush=True)
                return 1
            print('READY: refresh prime.sqlite in DBeaver, then open Views.', flush=True)
    else:
        print(json.dumps(report(root), indent=2), flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        raise SystemExit(f'Error: {exc}')
