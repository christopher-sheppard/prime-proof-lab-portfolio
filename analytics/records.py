"""Stable source locators shared by the export and controlled review writer."""
import hashlib
import json
from pathlib import Path


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def exists(db,table):
    return db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() is not None


def make_record(db,statement,kind,locator,page,original,line=None):
    ref={'document_id':statement['document_id'],'kind':kind,'locator':locator,'page_number':page}
    rid=digest(ref)
    head=None
    if exists(db,'desk_applied_changes'):
        row=db.execute('SELECT decision_id FROM desk_applied_changes WHERE record_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(rid,)).fetchone()
        head=row[0] if row else None
    revision=digest([statement['job_id'],statement['parse_id'],head])
    return {'record_id':rid,'document_id':statement['document_id'],'source_revision':revision,
        'value_fingerprint':digest(original),'reference_json':encoded(ref),'original_json':encoded(original),
        'page_number':page,'line_number':line,'settlement_date':statement['settlement_date'],
        'source_filename':statement['original_filename'],'source_job_id':statement['job_id'],
        'statement_id':statement['document_id'],'record_kind':kind}


def record_for_check(db,s,r):
    totals=db.execute('''SELECT l.page_number,l.line_number FROM statement_total_candidates t
        JOIN source_line_candidates l USING(line_id) WHERE t.parse_id=? AND t.metric=? LIMIT 1''',
        (s['parse_id'],r['check_name'].replace('_sum','_total'))).fetchone()
    original={k:r[k] for k in ('check_name','status','calculated_integer','reported_integer','difference_integer','unit','detail')}
    return make_record(db,s,'check',r['check_name'],None,original), (totals[0] if totals else 1)


def record_for_issue(db,s,r):
    line=db.execute('SELECT * FROM source_line_candidates WHERE line_id=?',(r['line_id'],)).fetchone() if r['line_id'] else None
    raw=line['raw_text'] if line else None
    original={'issue_kind':r['issue_kind'],'detail':r['detail'],'raw_text':raw}
    if line:
        p=db.execute('SELECT section,code_raw,description_raw,amount_cents,payout_effect_cents FROM settlement_posting_candidates WHERE posting_id=?',(line['line_id'],)).fetchone()
        if p:original['posting']=dict(p)
    locator={'issue_kind':r['issue_kind'],'detail_hash':digest(r['detail']),'raw_hash':digest(raw),
             'line_number':line['line_number'] if line else None}
    return make_record(db,s,'issue',locator,r['page_number'],original,line['line_number'] if line else None)


def record_for_party(db,s,r):
    original={k:r[k] for k in ('role_candidate','name_raw','address_block_raw','code_raw','order_raw','dispatch_raw')}
    return make_record(db,s,'party',r['role_candidate'],r['page_number'],original)


def resolve(db,reference):
    s=db.execute('SELECT * FROM v_workbench_statements WHERE document_id=?',(reference['document_id'],)).fetchall()
    if len(s)!=1:raise ValueError('Source identity is missing or ambiguous; re-review required')
    s=dict(s[0]);kind=reference['kind'];loc=reference['locator']
    if kind=='check':
        rows=db.execute('SELECT * FROM reconciliation_checks WHERE parse_id=? AND check_name=?',(s['parse_id'],loc)).fetchall()
        if len(rows)==1:return record_for_check(db,s,rows[0])[0]
    elif kind=='issue':
        matches=[]
        for r in db.execute('SELECT * FROM structured_issues WHERE parse_id=? AND issue_kind=? AND page_number IS ?',(s['parse_id'],loc['issue_kind'],reference['page_number'])):
            candidate=record_for_issue(db,s,r)
            if json.loads(candidate['reference_json'])==reference:matches.append(candidate)
        if len(matches)==1:return matches[0]
    elif kind=='party' and exists(db,'v_invoice_party_candidates'):
        rows=db.execute('SELECT * FROM v_invoice_party_candidates WHERE document_id=? AND page_number=? AND role_candidate=?',(s['document_id'],reference['page_number'],loc)).fetchall()
        if len(rows)==1:return record_for_party(db,s,rows[0])
    raise ValueError('Source record cannot be resolved uniquely; re-review required')


def source_pdf(db,root,document_id):
    """Resolve only registered PDFs confined to the configured source archive."""
    archive=(Path(root)/'sources/settlements').resolve()
    for row in db.execute('SELECT relative_path FROM source_occurrences WHERE document_id=? ORDER BY occurrence_id',(document_id,)):
        path=(Path(root)/row[0]).resolve()
        try:path.relative_to(archive)
        except ValueError:continue
        if path.is_file() and path.suffix.lower()=='.pdf':
            if hashlib.sha256(path.read_bytes()).hexdigest()!=document_id:
                raise ValueError('Registered PDF hash changed; source review required')
            return path
    raise FileNotFoundError('The registered local PDF is missing. Saved extraction and review history are still available.')
