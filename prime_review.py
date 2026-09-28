"""Audited source-image transcriptions, kept separately from immutable OCR evidence."""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

CODE = Path(__file__).resolve().parent
MIGRATION = '005_source_reviews'


def backup(root, label):
    output = root / 'backups' / (label + '_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8] + '.sqlite')
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect((root/'database/prime.sqlite').as_uri()+'?mode=ro', uri=True) as source:
        target = sqlite3.connect(output)
        try:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or target.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Backup verification failed')
        finally:
            target.close()
    return output


def initialize(root):
    db = sqlite3.connect((root/'database/prime.sqlite').as_uri()+'?mode=rw', uri=True)
    try:
        if db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION,)).fetchone():
            return
        print('Database backup:', backup(root, 'prime_before_source_reviews'), flush=True)
        db.executescript('BEGIN IMMEDIATE;\n'+(CODE/'sql/005_source_reviews.sql').read_text())
        db.execute('INSERT INTO schema_migrations VALUES (?,?)',(MIGRATION,datetime.now(timezone.utc).isoformat()))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def review_inputs(db, job):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_field_reviews'").fetchone():
        return [], ''
    rows = [dict(r) for r in db.execute('''SELECT * FROM (
        SELECT *,row_number() OVER(PARTITION BY field_name,page_number,raw_line ORDER BY created_at DESC,rowid DESC) n
        FROM source_field_reviews WHERE job_id=?) WHERE n=1
        ORDER BY field_name,page_number,raw_line''',(job,))]
    if sum(r['field_name']=='settlement_date' for r in rows)>1:
        raise ValueError('Conflicting statement-date review locations')
    for row in rows:
        source = db.execute('SELECT text_sha256 FROM source_pages WHERE job_id=? AND page_number=?',(job,row['page_number'])).fetchone()
        if not source or source[0] != row['page_text_sha256']:
            raise ValueError('Review evidence no longer matches saved source page')
    digest = hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    return rows, digest


def apply_total_review(reviews, page, raw, metric, value, evidence):
    for review in reviews:
        if (review['page_number'],review['raw_line'],review['field_name']) == (page,raw,metric):
            return json.loads(review['value_json']), {**evidence,'pre_review_value':value,
                'state':'source_image_review','review_id':review['review_id'],
                'ocr_state':evidence['state']}
    return value,evidence


def import_reviews(root, records):
    """Import explicitly reviewed records with source and rendered-evidence hashes."""
    from prime_workbench import locks
    from prime_structure import connect
    with locks(root):
        initialize(root)
        db = connect(root)
        try:
            validated = []
            for record in records:
                field = record['field_name']; value = record['value']
                if field == 'settlement_date':
                    if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:
                        raise ValueError('Expected ISO settlement date')
                elif field == 'gross_due':
                    if type(value) is not int:
                        raise ValueError('Expected integer cents')
                else:
                    raise ValueError('Unsupported review field')
                page = db.execute('''SELECT p.*,d.sha256 FROM source_pages p
                    JOIN page_extraction_jobs j USING(job_id) JOIN source_documents d USING(document_id)
                    WHERE p.job_id=? AND p.page_number=?''',(record['job_id'],record['page_number'])).fetchone()
                if not page or page['text_sha256'] != record['page_text_sha256']:
                    raise ValueError('Wrong source page evidence')
                source = (root/record['source_path']).resolve()
                source.relative_to(root.resolve())
                if hashlib.sha256(source.read_bytes()).hexdigest()!=page['sha256']:
                    raise ValueError('Source PDF hash mismatch')
                if not record['raw_line'] or not record['reason'] or not record['reviewer']:
                    raise ValueError('Review needs a locator, reason and reviewer')
                # Exact physical row text is a stable locator across parser versions.
                from prime_structure import word_rows
                words = [list(r) for r in db.execute('SELECT word_index,raw_text,left_px,top_px,width_px,height_px,confidence,block_number,paragraph_number,line_number FROM source_words WHERE job_id=? AND page_number=?',(record['job_id'],record['page_number']))]
                if sum(r['text']==record['raw_line'] for r in word_rows(words))!=1:
                    raise ValueError('Review locator must match exactly one source row')
                evidence = []
                for image in record['images']:
                    path = (root/image).resolve();path.relative_to(root.resolve())
                    evidence.append({'path':image,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
                if not evidence:
                    raise ValueError('Source-image evidence is required')
                ev = json.dumps({'source_path':record['source_path'],'source_sha256':page['sha256'],'images':evidence},sort_keys=True)
                payload = [record['job_id'],record['page_number'],field,record['raw_line'],page['text_sha256'],json.dumps(value),ev,record['reviewer'],record['reason']]
                rid = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
                validated.append((rid,*payload,datetime.now(timezone.utc).isoformat()))
            if any(not db.execute('SELECT 1 FROM source_field_reviews WHERE review_id=?',(r[0],)).fetchone() for r in validated):
                print('Database backup:',backup(root,'prime_before_review_import'),flush=True)
            with db:
                db.executemany('INSERT OR IGNORE INTO source_field_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?)',validated)
            return len(validated)
        finally:
            db.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--data-root',type=Path,default=Path.home()/'PrimeData')
    args = parser.parse_args()
    print('Reviewed fields:',import_reviews(args.data_root.expanduser().resolve(),json.loads(args.manifest.read_text())))
