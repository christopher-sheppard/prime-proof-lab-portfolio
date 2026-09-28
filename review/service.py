"""Single-user local journal and controlled nonfinancial mapping writer."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import uuid

from analytics.records import digest,encoded,resolve,source_pdf
from prime_structure import connect
from analytics.storage import backup
from prime_workbench import locks

CODE=Path(__file__).resolve().parents[1]
CATEGORIES=('freight_compensation','fuel_surcharge','accessorial','fuel_purchase','maintenance','owner_trainer_charge','reserve_transfer','advance_or_principal','payroll_summary_not_owner_cost','unknown')
ACTIONS=('defer','confirm_category','reject_category','facility_mapping','numeric_correction','date_correction')


def now():return datetime.now(timezone.utc).isoformat()


def initialize(root):
    root=Path(root).resolve()
    with locks(root):
        db=connect(root)
        try:
            if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='007_review_desk'").fetchone():
                saved=backup(root,'prime_before_review_desk')
                db.executescript('BEGIN IMMEDIATE;\n'+(CODE/'sql/007_review_desk.sql').read_text())
                db.execute('INSERT INTO schema_migrations VALUES (?,?)',('007_review_desk',now()));db.commit()
                print('Review desk migration backup:',saved,flush=True)
        finally:db.close()
    journal(root).close()


def journal(root):
    path=Path(root)/'review/review.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30);db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=30000')
    db.executescript('''CREATE TABLE IF NOT EXISTS decisions (
        decision_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,payload_hash TEXT NOT NULL,
        record_id TEXT NOT NULL,document_id TEXT NOT NULL,reference_json TEXT NOT NULL,
        expected_revision TEXT NOT NULL,value_fingerprint TEXT NOT NULL,original_json TEXT NOT NULL,
        action TEXT NOT NULL,proposed_json TEXT NOT NULL,reason TEXT NOT NULL,evidence TEXT NOT NULL,
        reviewer TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
        event_id INTEGER PRIMARY KEY,decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
        state TEXT NOT NULL,detail TEXT NOT NULL,validation_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_decision ON events(decision_id,event_id);
        CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON decisions
        BEGIN SELECT RAISE(ABORT,'Decisions are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions
        BEGIN SELECT RAISE(ABORT,'Decisions are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT,'Events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
        BEGIN SELECT RAISE(ABORT,'Events are append-only'); END;''')
    return db


def get(root,decision_id):
    db=journal(root)
    try:
        r=db.execute('SELECT * FROM decisions WHERE decision_id=?',(decision_id,)).fetchone()
        if not r:raise ValueError('Unknown decision')
        event=db.execute('SELECT * FROM events WHERE decision_id=? ORDER BY event_id DESC LIMIT 1',(decision_id,)).fetchone()
        return {**dict(r),'state':event['state'],'detail':event['detail'],'validation_json':event['validation_json']}
    finally:db.close()


def event(root,decision_id,state,detail,validation=None):
    db=journal(root)
    try:
        with db:db.execute('INSERT INTO events(decision_id,state,detail,validation_json,created_at) VALUES (?,?,?,?,?)',(decision_id,state,detail,encoded(validation or {}),now()))
    finally:db.close()
    return get(root,decision_id)


def history(root,record_id=None):
    db=journal(root)
    try:
        query='SELECT d.*,e.state,e.detail,e.validation_json,e.created_at AS event_at FROM decisions d JOIN events e USING(decision_id)'
        return [dict(r) for r in db.execute(query+(' WHERE d.record_id=?' if record_id else '')+' ORDER BY e.event_id DESC',(record_id,) if record_id else ())]
    finally:db.close()


def validate_proposal(action,value,record):
    if action not in ACTIONS:raise ValueError('Unknown decision action')
    if action in ('confirm_category','reject_category'):
        if value.get('category') not in CATEGORIES:raise ValueError('Choose a supported category')
    elif action=='facility_mapping':
        if record['record_kind']!='party':raise ValueError('Select an invoice party for a facility mapping')
        for key in ('organization_key','organization_name','facility_key','facility_name','street_address','city','state_province','postal_code','role'):
            if not isinstance(value.get(key),str) or not value[key].strip():raise ValueError('Facility mapping requires '+key)
        if value['role'] not in ('shipper','receiver','bill_to','vendor','other'):raise ValueError('Invalid facility role')
        if value['role']!=json.loads(record['original_json'])['role_candidate']:raise ValueError('Role must match the selected invoice party')
    elif action=='numeric_correction':
        if type(value.get('integer_cents')) is not int:raise ValueError('Use integer cents')
    elif action=='date_correction':
        from datetime import date
        date.fromisoformat(value['iso_date'])


def submit(root,record,action,proposed,reason,evidence,reviewer,request_id):
    if not all(isinstance(v,str) and v.strip() for v in (reason,evidence,reviewer,request_id)):raise ValueError('Reason, evidence, reviewer and request ID are required')
    validate_proposal(action,proposed,record)
    payload={'record':record,'action':action,'proposed':proposed,'reason':reason,'evidence':evidence,'reviewer':reviewer};ph=digest(payload)
    db=journal(root)
    try:
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT * FROM decisions WHERE request_id=?',(request_id,)).fetchone()
        if prior:
            if prior['payload_hash']!=ph:raise ValueError('Request ID already belongs to different content')
            db.commit();return get(root,prior['decision_id'])
        rid=str(uuid.uuid4());state='Recorded';detail='Decision recorded; no source financial facts changed.'
        source=connect(Path(root),True)
        try:
            current=resolve(source,json.loads(record['reference_json']))
            if current['source_revision']!=record['source_revision'] or current['value_fingerprint']!=record['value_fingerprint']:
                state='Conflict';detail='Source revision or current value changed; re-review the current record.'
        except ValueError as exc:state='Conflict';detail=str(exc)
        finally:source.close()
        if state!='Conflict':
            if action in ('facility_mapping','confirm_category','reject_category'):
                state='Ready to apply';detail='A versioned nonfinancial mapping can be applied after another source revision check.'
            elif action in ('numeric_correction','date_correction'):
                detail='Pending: financial/date proposals require the source-image review importer and a tested targeted reparse. This desk does not apply them.'
            elif action=='defer':detail='Deferred with a note. The source issue remains unresolved.'
        db.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(rid,request_id,ph,record['record_id'],record['document_id'],record['reference_json'],record['source_revision'],record['value_fingerprint'],record['original_json'],action,encoded(proposed),reason,evidence,reviewer,now()))
        db.execute('INSERT INTO events(decision_id,state,detail,validation_json,created_at) VALUES (?,?,?,?,?)',(rid,state,detail,'{}',now()));db.commit()
        return get(root,rid)
    except BaseException:db.rollback();raise
    finally:db.close()


def apply(root,decision_id,publish=True,failpoint=None):
    """No distributed transaction: the ledger's unique decision key repairs lost ACKs."""
    root=Path(root).resolve();d=get(root,decision_id)
    if d['action'] not in ('facility_mapping','confirm_category','reject_category'):
        raise ValueError('This decision is recorded only; its correction type is not supported by the writer')
    with locks(root):
        db=connect(root)
        try:
            existing=db.execute('SELECT validation_json FROM desk_applied_changes WHERE decision_id=?',(decision_id,)).fetchone()
            if existing and d['state']=='Applied and revalidated':return d
            if not existing:
                if d['state']=='Conflict':return d
                try:current=resolve(db,json.loads(d['reference_json']))
                except ValueError as exc:return event(root,decision_id,'Conflict',str(exc))
                if current['source_revision']!=d['expected_revision'] or current['value_fingerprint']!=d['value_fingerprint']:
                    return event(root,decision_id,'Conflict','The source changed after submission; no ledger change was made.')
                source_pdf(db,root,d['document_id'])
                saved=backup(root,'prime_before_review_apply')
                db.execute('BEGIN IMMEDIATE')
                # Validate again with the database write lock held.
                current=resolve(db,json.loads(d['reference_json']))
                if current['source_revision']!=d['expected_revision'] or current['value_fingerprint']!=d['value_fingerprint']:
                    db.rollback();return event(root,decision_id,'Conflict','Source changed while acquiring the write transaction.')
                value=json.loads(d['proposed_json']);validation={'foreign_keys':'ok','integrity':'ok','financial_rows_changed':0,'backup':str(saved)}
                db.execute('INSERT INTO desk_applied_changes VALUES (?,?,?,?,?,?,?)',(decision_id,d['record_id'],d['expected_revision'],d['action'],d['proposed_json'],encoded(validation),now()))
                if d['action']=='facility_mapping':
                    org='desk-org:'+value['organization_key'];facility='desk-facility:'+value['facility_key']
                    old=db.execute('SELECT name FROM organizations WHERE organization_id=?',(org,)).fetchone()
                    if old and old[0]!=value['organization_name']:raise ValueError('Organization key already has a different name')
                    db.execute('INSERT OR IGNORE INTO organizations(organization_id,name,notes) VALUES (?,?,?)',(org,value['organization_name'],'Local source-reviewed reference; see decision '+decision_id))
                    vals=(org,value['facility_name'],value['street_address'],value['city'],value['state_province'],value['postal_code'])
                    old=db.execute('SELECT organization_id,name,street_address,city,state_province,postal_code FROM facilities WHERE facility_id=?',(facility,)).fetchone()
                    if old and tuple(old)!=vals:raise ValueError('Facility key already has different evidence. Use a new version key; prior facility evidence is preserved.')
                    db.execute('INSERT OR IGNORE INTO facilities(facility_id,organization_id,name,street_address,city,state_province,postal_code,location_precision,evidence_note,verified) VALUES (?,?,?,?,?,?,?,?,?,?)',(facility,*vals,'street',d['evidence'],1))
                    raw=json.loads(d['original_json']).get('code_raw')
                    db.execute('INSERT INTO desk_facility_mapping_versions VALUES (?,?,?,?,?,?,?,?)',(decision_id,d['record_id'],d['document_id'],org,facility,value['role'],raw,d['evidence']))
                    if raw:db.execute('INSERT INTO facility_codes(facility_code_id,facility_id,code,role,evidence_note) VALUES (?,?,?,?,?)',(decision_id,facility,raw,value['role'],d['evidence']))
                else:
                    db.execute('INSERT INTO desk_classification_versions VALUES (?,?,?,?,?,?,?)',(decision_id,d['record_id'],d['document_id'],current['page_number'],value['category'],'confirmed' if d['action']=='confirm_category' else 'rejected',d['evidence']))
                if failpoint=='validation':raise RuntimeError('Simulated validation failure before commit')
                if db.execute('PRAGMA foreign_key_check').fetchall() or db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Ledger validation failed')
                db.commit()
                if failpoint=='after_commit':raise SystemExit('Simulated interruption after ledger commit, before journal ACK')
            else:validation=json.loads(existing[0])
        except Exception as exc:
            db.rollback();return event(root,decision_id,'Failed',str(exc),{'ledger_key_present':bool(db.execute('SELECT 1 FROM desk_applied_changes WHERE decision_id=?',(decision_id,)).fetchone())})
        finally:db.close()
        if publish:
            try:
                from analytics.reporting import export
                validation['reporting_snapshot']=export(root).name
            except Exception as exc:
                return event(root,decision_id,'Failed','Ledger change committed and validated; snapshot publication failed. Retry recovers by decision ID: '+str(exc),validation)
        return event(root,decision_id,'Applied and revalidated','Nonfinancial mapping applied; original financial facts and source issues remain unchanged.',validation)


def backup_journal(root,destination):
    db=journal(root);target=sqlite3.connect(destination)
    try:
        db.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Journal backup invalid')
    finally:target.close();db.close()
