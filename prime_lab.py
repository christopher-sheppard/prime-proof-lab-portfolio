"""Initial source registry, status and consistent snapshots. No financial parser yet."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

CODE = Path(__file__).resolve().parent

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def connect(path, read_only=False):
    if not path.is_file():
        raise FileNotFoundError(f'Database not found: {path}. Run bootstrap.py first.')
    db=sqlite3.connect(path.as_uri()+'?mode='+('ro' if read_only else 'rw'),uri=True)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    return db

def initialize(root):
    db=connect(root/'database/prime.sqlite')
    try:
        db.executescript((CODE/'sql/001_source_registry.sql').read_text())
        with db:
            db.execute('INSERT OR IGNORE INTO schema_migrations VALUES (?,?)',('001_source_registry',timestamp()))
            db.executemany('INSERT OR IGNORE INTO system_metadata VALUES (?,?)',[
                ('historical_financial_import_complete','false'),
                ('financial_data_through','unknown'),
                ('role','one authoritative local writable database'),
            ])
    finally:
        db.close()

def status(root):
    db=connect(root/'database/prime.sqlite',True)
    try:
        result=dict(database=str(root/'database/prime.sqlite'),
                    reference_code_entries=db.execute('SELECT count(*) FROM settlement_code_entries').fetchone()[0],
                    distinct_source_documents=db.execute('SELECT count(*) FROM source_documents').fetchone()[0],
                    source_occurrences=db.execute('SELECT count(*) FROM source_occurrences').fetchone()[0],
                    metadata=dict(db.execute('SELECT key,value FROM system_metadata')))
        print(json.dumps(result,indent=2))
    finally:
        db.close()

def inventory(root):
    directory=root/'sources/settlements'
    if not directory.is_dir():
        raise FileNotFoundError(f'Create source folder: {directory}')
    files=sorted(p for p in directory.rglob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower()=='.pdf')
    db=connect(root/'database/prime.sqlite')
    run_id=uuid.uuid4().hex;now=timestamp();unique=set()
    try:
        with db:
            db.execute('INSERT INTO inventory_runs VALUES (?,?,?,?)',(run_id,now,'sources/settlements',len(files)))
            for path in files:
                h=hashlib.sha256()
                with path.open('rb') as f:
                    for block in iter(lambda:f.read(1024*1024),b''):
                        h.update(block)
                digest=h.hexdigest();unique.add(digest)
                db.execute('INSERT OR IGNORE INTO source_documents(document_id,sha256,original_filename,size_bytes,first_seen_at) VALUES (?,?,?,?,?)',
                           (digest,digest,path.name,path.stat().st_size,now))
                db.execute('''INSERT INTO source_occurrences(document_id,relative_path,first_seen_at,last_seen_run_id)
                              VALUES (?,?,?,?) ON CONFLICT(document_id,provider,relative_path)
                              DO UPDATE SET last_seen_run_id=excluded.last_seen_run_id''',
                           (digest,path.relative_to(root).as_posix(),now,run_id))
        result=dict(scanned_at=now,run_id=run_id,files_seen=len(files),distinct_file_hashes=len(unique),
                    extra_exact_copies=len(files)-len(unique),
                    status='Files inventoried; dates, pages and financial contents not yet extracted or reconciled')
        duplicates=[]
        for digest,count in db.execute('SELECT document_id,count(*) FROM source_occurrences WHERE last_seen_run_id=? GROUP BY document_id HAVING count(*)>1',(run_id,)):
            paths=[row[0] for row in db.execute('SELECT relative_path FROM source_occurrences WHERE last_seen_run_id=? AND document_id=? ORDER BY relative_path',(run_id,digest))]
            duplicates.append(dict(sha256=digest,copies=count,paths=paths))
        result['exact_duplicate_groups']=duplicates
        out=root/'reports'/f'inventory_{run_id}.json';out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({**result,'report':str(out)},indent=2))
    finally:
        db.close()

def snapshot(root):
    destination=root/'exports';destination.mkdir(parents=True,exist_ok=True)
    name='prime_snapshot_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    output=destination/(name+'.sqlite')
    source=connect(root/'database/prime.sqlite',True)
    target=sqlite3.connect(output)
    try:
        source.backup(target)
        integrity=target.execute('PRAGMA integrity_check').fetchall()
        if integrity != [('ok',)]:
            raise ValueError(f'Snapshot integrity failed: {integrity}')
        if target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Snapshot contains broken foreign-key relationships')
        info=dict(created_at=timestamp(),filename=output.name,
                  metadata=dict(target.execute('SELECT key,value FROM system_metadata')),
                  source_document_count=target.execute('SELECT count(*) FROM source_documents').fetchone()[0],
                  note='Snapshot creation time is not the financial data-through date. Preserve the source archive separately.')
    finally:
        target.close();source.close()
    info['sha256']=hashlib.sha256(output.read_bytes()).hexdigest()
    manifest=destination/(name+'.json');manifest.write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps(dict(snapshot=str(output),manifest=str(manifest),**info),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,default=Path(os.environ.get('PRIME_DATA_DIR',Path.home()/'PrimeData')))
    parser.add_argument('command',choices=['initialize','status','inventory','snapshot'])
    args=parser.parse_args();root=args.data_root.expanduser().resolve()
    try:
        dict(initialize=initialize,status=status,inventory=inventory,snapshot=snapshot)[args.command](root)
    except (OSError,ValueError,sqlite3.Error) as exc:
        raise SystemExit(f'Error: {exc}') from exc
