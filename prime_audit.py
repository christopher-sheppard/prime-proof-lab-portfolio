"""Read-only database audit and source-linked triage of incomplete arithmetic."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from prime_structure import connect


def audit(root):
    db=connect(root,True)
    try:
        db.execute('BEGIN')
        statements=[dict(r) for r in db.execute('SELECT * FROM v_workbench_statements')]
        by_parse={s['parse_id']:s for s in statements}
        checks=[dict(r) for r in db.execute('SELECT * FROM reconciliation_checks') if r['parse_id'] in by_parse]
        totals=defaultdict(lambda:defaultdict(list))
        for r in db.execute('SELECT * FROM statement_total_candidates'):
            if r['parse_id'] in by_parse:totals[r['parse_id']][r['metric']].append(dict(r))
        postings=defaultdict(lambda:defaultdict(list))
        for r in db.execute('SELECT * FROM settlement_posting_candidates'):
            if r['parse_id'] in by_parse:postings[r['parse_id']][r['section']].append(dict(r))
        legs=defaultdict(list)
        for r in db.execute('SELECT * FROM load_leg_candidates'):
            if r['parse_id'] in by_parse:legs[r['parse_id']].append(dict(r))
        exceptions=[]
        for check in checks:
            if check['status'] not in ('incomplete','mismatch'):continue
            pid=check['parse_id']; name=check['check_name']; dependencies=[]
            def total_input(metric):
                rows=totals[pid][metric]
                values=[r['value_integer'] for r in rows]
                reason='missing_reported_total' if not rows else ('unreadable_reported_total' if None in values else ('conflicting_reported_totals' if len(set(values))>1 else None))
                if reason:dependencies.append({'reason':reason,'metric':metric,'evidence':[{'line_id':r['line_id'],'numeric_evidence':json.loads(r['numeric_evidence_json'])} for r in rows]})
            if name.endswith('_sum'):
                key=name[:-4];total_input(key+'_total')
                if key in ('revenue','reimbursement','deduction','wage_expense'):
                    rows=postings[pid][key]
                    bad=[r for r in rows if r['amount_cents'] is None]
                    if bad:dependencies.append({'reason':'unreadable_posting_amount','section':key,'evidence':[{'line_id':r['posting_id'],'numeric_evidence':json.loads(r['numeric_evidence_json'])} for r in bad]})
                else:
                    rows=legs[pid];bad=[r for r in rows if r[key] is None]
                    if bad:dependencies.append({'reason':'unreadable_leg_miles','metric':key,'evidence':[{'line_id':r['leg_id'],'numeric_evidence':json.loads(r['numeric_evidence_json'])[key]} for r in bad]})
                if not rows and check['calculated_integer'] is None:
                    dependencies.append({'reason':'no_candidate_rows_without_explicit_zero_total','metric':key})
            elif name=='section_totals_to_gross_due':
                for metric in ('revenue_total','reimbursement_total','deduction_total','wage_expense_total','gross_due'):total_input(metric)
            elif name.endswith('_net_bridge'):
                prefix=name.removesuffix('net_bridge')
                for metric in ('gross','taxes','reimbursements','charges','travel','net'):total_input(prefix+metric)
            s=by_parse[pid]
            exceptions.append({**check,'document_id':s['document_id'],'job_id':s['job_id'],'original_filename':s['original_filename'],'settlement_date':s['settlement_date'],'document_kind':s['document_kind'],'unresolved_inputs':dependencies,
                'classification':'unresolved_source_arithmetic' if check['status']=='mismatch' else 'applicable_but_missing_or_conflicting_evidence'})
        page_counts=Counter();page_jobs={s['job_id'] for s in statements}
        classified=0
        for r in db.execute('SELECT parse_id,page_kind,count(*) n FROM page_classifications GROUP BY 1,2'):
            if r['parse_id'] in by_parse:page_counts[r['page_kind']]+=r['n'];classified+=r['n']
        saved_pages=sum(r[1] for r in db.execute('SELECT job_id,count(*) FROM source_pages GROUP BY job_id') if r[0] in page_jobs)
        numeric_pages=sum(r[1] for r in db.execute('SELECT job_id,count(*) FROM source_numeric_pages GROUP BY job_id') if r[0] in page_jobs)
        registered={r[0] for r in db.execute('SELECT sha256 FROM source_documents')}
        files=[p for p in (root/'sources/settlements').rglob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower()=='.pdf']
        hashes=Counter(hashlib.sha256(p.read_bytes()).hexdigest() for p in files)
        reasons=Counter(d['reason'] for c in exceptions for d in c['unresolved_inputs'])
        unresolved_dates=[{'document_id':s['document_id'],'original_filename':s['original_filename'],'headers':json.loads(s['header_evidence_json'])} for s in statements if s['document_kind'] in ('owner_recap','employee_payroll') and s['settlement_date'] is None]
        return {'created_at':datetime.now(timezone.utc).isoformat(),'historical_financial_import_complete':False,
            'integrity_check':[r[0] for r in db.execute('PRAGMA integrity_check')],
            'foreign_key_violations':[list(r) for r in db.execute('PRAGMA foreign_key_check')],
            'source_files':len(files),'distinct_source_hashes':len(hashes),'unregistered_source_hashes':sorted(set(hashes)-registered),
            'registered_hashes_absent_from_archive':sorted(registered-set(hashes)),
            'current_documents':len(statements),'saved_pages':saved_pages,'numeric_pages':numeric_pages,'classified_pages':classified,'page_kinds':dict(page_counts),
            'check_statuses':dict(Counter(c['status'] for c in checks)),
            'incomplete_dependency_counts':dict(reasons),'exceptions':exceptions,'unresolved_statement_dates':unresolved_dates,
            'candidate_date_range':[min(s['settlement_date'] for s in statements if s['settlement_date']),max(s['settlement_date'] for s in statements if s['settlement_date'])],
            'note':'Every incomplete check remains applicable and unresolved. Dependency counts overlap. Page classification does not establish structured detail coverage. Dates do not establish continuous weekly coverage. Source-image transcriptions do not approve accounting treatment.'}
    finally:db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,default=Path.home()/'PrimeData')
    args=p.parse_args();root=args.data_root.expanduser().resolve()
    result=audit(root)
    output=root/'reports'/('audit_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('exceptions','unresolved_statement_dates')},indent=2))
    print('Unresolved statement dates:',len(result['unresolved_statement_dates']))
    print('Report:',output)
