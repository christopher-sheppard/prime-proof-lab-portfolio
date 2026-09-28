"""Short-lived connections for consistent, verified ledger backups."""
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
import uuid


def backup(root,label):
    root=Path(root).resolve();output=root/'backups'/(label+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]+'.sqlite')
    output.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect((root/'database/prime.sqlite').as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(output)) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or target.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Backup validation failed')
    return output
