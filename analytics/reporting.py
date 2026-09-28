"""Contract 1.1: one consistent source snapshot, matching SQLite/CSV/JSON exports."""
import csv
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from analytics.records import digest,encoded,exists,record_for_check,record_for_issue,record_for_party
from prime_structure import connect

CONTRACT='1.1'
SCHEMA={
'FactStatement':{'statement_id':'TEXT','document_id':'TEXT','source_revision':'TEXT','settlement_date':'TEXT','document_kind':'TEXT','owner_code':'TEXT','unit_code':'TEXT','revenue_cents':'INTEGER','net_due_cents':'INTEGER','arithmetic_status':'TEXT'},
'FactLoadLeg':{'leg_id':'TEXT','statement_id':'TEXT','settlement_date':'TEXT','period_id':'TEXT','origin_id':'TEXT','destination_id':'TEXT','order_key':'TEXT','dispatch_key':'TEXT','solo_team_raw':'TEXT','loaded_miles':'INTEGER','empty_miles':'INTEGER','total_miles':'INTEGER','candidate_dispatch_owner_cents':'INTEGER','preliminary_rpm_eligible':'INTEGER','reconciled_rpm_eligible':'INTEGER','exclusion_reasons':'TEXT','allocation_status':'TEXT','source_annotation':'TEXT','page_number':'INTEGER','line_number':'INTEGER'},
'FactPosting':{'posting_id':'TEXT','statement_id':'TEXT','posting_date':'TEXT','service_date':'TEXT','section':'TEXT','code_raw':'TEXT','description_raw':'TEXT','amount_cents':'INTEGER','payout_effect_cents':'INTEGER','economic_category':'TEXT','allocation_status':'TEXT','page_number':'INTEGER','line_number':'INTEGER'},
'FactReviewIssue':{'issue_id':'TEXT','record_id':'TEXT','statement_id':'TEXT','settlement_date':'TEXT','issue_kind':'TEXT','description':'TEXT','difference_integer':'INTEGER','unit':'TEXT','page_number':'INTEGER','line_number':'INTEGER','status':'TEXT'},
'DimDate':{'date':'TEXT','year':'INTEGER','quarter':'INTEGER','month':'INTEGER','iso_year':'INTEGER','iso_week':'INTEGER'},
'DimOperatingPeriod':{'period_id':'TEXT','start_date':'TEXT','end_date':'TEXT','owner_code':'TEXT','unit_code':'TEXT','business_mode':'TEXT','trainer':'INTEGER'},
'DimOrigin':{'place_id':'TEXT','raw_label':'TEXT','display_label':'TEXT','mapping_status':'TEXT','facility_id':'TEXT','coordinate_precision':'TEXT'},
'DimDestination':{'place_id':'TEXT','raw_label':'TEXT','display_label':'TEXT','mapping_status':'TEXT','facility_id':'TEXT','coordinate_precision':'TEXT'},
'SourceRecord':{'record_id':'TEXT','document_id':'TEXT','source_revision':'TEXT','value_fingerprint':'TEXT','reference_json':'TEXT','original_json':'TEXT','page_number':'INTEGER','line_number':'INTEGER','settlement_date':'TEXT','source_filename':'TEXT','source_job_id':'TEXT','statement_id':'TEXT','record_kind':'TEXT'},
}
KEYS={t:next(iter(cols)) for t,cols in SCHEMA.items()}


def eligibility(r,annotation=False):
    reasons=[]
    if r['allocated_owner_revenue_cents'] is None:reasons.append('unknown owner amount')
    for key in ('loaded_miles','empty_miles','total_miles'):
        if r[key] is None:reasons.append('unknown '+key)
    if r['loaded_miles'] is not None and r['loaded_miles']<=0:reasons.append('no positive loaded miles')
    if r['total_miles'] is not None and r['total_miles']<=0:reasons.append('no positive total miles')
    if r['empty_miles'] is not None and r['empty_miles']<0:reasons.append('negative empty miles')
    if r['mileage_check']!='match':reasons.append('mileage arithmetic unresolved')
    if r['dispatch_leg_count']!=1:reasons.append('ambiguous dispatch allocation')
    if r['possible_duplicate_legs']!=1:reasons.append('possible duplicate identity')
    if r['statement_revenue_check']!='match':reasons.append('statement revenue unresolved')
    if not r['settlement_date']:reasons.append('unknown settlement date')
    if annotation:reasons.append('source approval annotation unresolved')
    return not reasons,reasons


def collect(db):
    tables={name:[] for name in SCHEMA}
    statements={r['parse_id']:dict(r) for r in db.execute('SELECT * FROM v_workbench_statements')}
    for r in db.execute('SELECT * FROM v_weekly_settlements'):
        tables['FactStatement'].append({'statement_id':r['document_id'],'document_id':r['document_id'],'source_revision':r['parse_id'],**{k:r[k] for k in ('settlement_date','document_kind','owner_code','unit_code','revenue_cents','net_due_cents','arithmetic_status')}})
    periods=[dict(r) for r in db.execute('SELECT * FROM operating_periods')]
    tables['DimOperatingPeriod']=[{'period_id':'unknown','business_mode':'unknown'}]+periods
    lines={r['line_id']:dict(r) for r in db.execute('SELECT line_id,parse_id,page_number,line_number FROM source_line_candidates') if r['parse_id'] in statements}
    annotations={r[0] for r in db.execute("SELECT DISTINCT p.leg_id FROM route_point_candidates p JOIN structured_issues i ON i.line_id=p.line_id WHERE i.issue_kind='route_source_annotation'")}
    places={'DimOrigin':{},'DimDestination':{}}
    for r in db.execute('SELECT * FROM v_load_economics'):
        s=statements[r['parse_id']];line=lines[r['leg_id']]
        good,reasons=eligibility(r,r['leg_id'] in annotations)
        matching=[p['period_id'] for p in periods if p['owner_code']==r['owner_code'] and p['unit_code']==r['unit_code'] and r['settlement_date'] and p['start_date']<=r['settlement_date'] and (not p['end_date'] or p['end_date']>=r['settlement_date'])]
        loc={}
        for role,table in [('origin','DimOrigin'),('destination','DimDestination')]:
            city,state=r[role+'_city_raw'],r[role+'_state_raw'];key=digest([city,state]);label=' '.join(x for x in (city,state) if x) or 'Unknown raw location'
            places[table][key]={'place_id':key,'raw_label':label,'display_label':label,'mapping_status':'unverified OCR','facility_id':None,'coordinate_precision':'unknown'};loc[role+'_id']=key
        tables['FactLoadLeg'].append({'leg_id':digest([s['document_id'],'leg',line['page_number'],line['line_number']]),'statement_id':s['document_id'],
            'period_id':matching[0] if len(matching)==1 else 'unknown',**loc,**{k:r[k] for k in ('settlement_date','order_key','dispatch_key','solo_team_raw','loaded_miles','empty_miles','total_miles')},
            'candidate_dispatch_owner_cents':r['allocated_owner_revenue_cents'],'preliminary_rpm_eligible':int(good),'reconciled_rpm_eligible':0,
            'exclusion_reasons':'; '.join(reasons),'allocation_status':'unique candidate dispatch' if r['dispatch_leg_count']==1 else 'unresolved repower/multi-leg allocation',
            'source_annotation':'unresolved' if r['leg_id'] in annotations else 'not recorded; not a business approval',
            'page_number':line['page_number'],'line_number':line['line_number']})
    for table,rows in places.items():tables[table]=list(rows.values())
    for r in db.execute('SELECT * FROM v_postings_keyed'):
        s=statements[r['parse_id']]
        tables['FactPosting'].append({'posting_id':digest([s['document_id'],'posting',r['page_number'],r['line_number']]),'statement_id':s['document_id'],'posting_date':r['settlement_date'],'service_date':None,
            **{k:r[k] for k in ('section','code_raw','description_raw','amount_cents','payout_effect_cents','page_number','line_number')},'economic_category':None,'allocation_status':'pending economic classification'})
    def add(record,kind,description,page=None,difference=None,unit=None):
        tables['SourceRecord'].append(record)
        statement_id=record['statement_id'] if any(s['statement_id']==record['statement_id'] for s in tables['FactStatement']) else None
        tables['FactReviewIssue'].append({'issue_id':record['record_id'],'record_id':record['record_id'],'statement_id':statement_id,'settlement_date':record['settlement_date'],
            'issue_kind':kind,'description':description,'difference_integer':difference,'unit':unit,'page_number':page or record['page_number'],'line_number':record['line_number'],'status':'open'})
    for r in db.execute("SELECT * FROM reconciliation_checks WHERE status NOT IN ('match','not_applicable')"):
        if r['parse_id'] in statements:
            record,page=record_for_check(db,statements[r['parse_id']],r)
            add(record,'arithmetic_'+r['status'],r['check_name'],page,r['difference_integer'],r['unit'])
    for r in db.execute('SELECT * FROM structured_issues'):
        if r['parse_id'] in statements:
            add(record_for_issue(db,statements[r['parse_id']],r),r['issue_kind'],r['detail'])
    if exists(db,'v_invoice_party_candidates'):
        for r in db.execute('SELECT * FROM v_invoice_party_candidates'):
            add(record_for_party(db,statements[r['parse_id']],r),'invoice_party_review',r['role_candidate']+': '+r['name_raw'])
    dates=[s['settlement_date'] for s in statements.values() if s['settlement_date']]
    if dates:
        day=date.fromisoformat(min(dates));last=date.fromisoformat(max(dates))
        while day<=last:
            iso=day.isocalendar();tables['DimDate'].append({'date':day.isoformat(),'year':day.year,'quarter':(day.month-1)//3+1,'month':day.month,'iso_year':iso.year,'iso_week':iso.week});day+=timedelta(days=1)
    metadata=dict(db.execute('SELECT key,value FROM system_metadata'))
    current_jobs={s['job_id'] for s in statements.values()}
    info={'source_documents':len(statements),'extracted_pages':sum(r[1] for r in db.execute('SELECT job_id,count(*) FROM source_pages GROUP BY job_id') if r[0] in current_jobs),
        'source_through':max(dates) if dates else None,'date_basis':'settlement date','verified_financial_data_through':metadata.get('financial_data_through','unknown'),
        'historical_financial_import_complete':False,'synthetic':metadata.get('synthetic')=='true',
        'schema_versions':[r[0] for r in db.execute('SELECT migration_id FROM schema_migrations ORDER BY migration_id')],
        'parser_versions':sorted({r[0] for r in db.execute('SELECT parser_version FROM structured_runs WHERE parse_id IN (SELECT parse_id FROM v_workbench_statements)')}),
        'quality_counts':dict(db.execute('SELECT status,count(*) FROM reconciliation_checks WHERE parse_id IN (SELECT parse_id FROM v_workbench_statements) GROUP BY status')),
        'limitations':['Arithmetic eligibility is preliminary, not source reconciliation.','No private legs are certified reconciled.','Economic categories, payout bridge, continuous weekly coverage and operating eras remain incomplete.','Facility decisions do not automatically link raw route endpoints to verified facilities.']}
    return tables,info


def metrics(rows,mode='Preliminary history'):
    field='reconciled_rpm_eligible' if mode=='Reconciled subset' else 'preliminary_rpm_eligible'
    eligible=[r for r in rows if r[field]]
    cents=sum(r['candidate_dispatch_owner_cents'] for r in eligible);miles=sum(r['total_miles'] for r in eligible)
    loaded=sum(r['loaded_miles'] for r in eligible);empty=sum(r['empty_miles'] for r in eligible)
    return {'total_legs':len(rows),'eligible_legs':len(eligible),'excluded_legs':len(rows)-len(eligible),
        'owner_cents':cents if eligible else None,'total_miles':miles if eligible else None,
        'weighted_rpm':cents/100/miles if miles else None,'loaded_rpm':cents/100/loaded if loaded else None,'empty_fraction':empty/miles if miles else None}


def write_tables(output,tables):
    report=sqlite3.connect(output/'reporting.sqlite')
    try:
        for name,cols in SCHEMA.items():
            fields=list(cols);report.execute(f'CREATE TABLE {name} ('+','.join(f'{k} {v}'+(' PRIMARY KEY' if k==KEYS[name] else '') for k,v in cols.items())+')')
            rows=sorted(tables[name],key=lambda r:str(r[KEYS[name]]))
            report.executemany(f'INSERT INTO {name} VALUES ('+','.join('?' for _ in fields)+')',[[r.get(k) for k in fields] for r in rows])
            with (output/(name+'.csv')).open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(fields);writer.writerows([[r.get(k) for k in fields] for r in rows])
            (output/(name+'.json')).write_text(encoded([{k:r.get(k) for k in fields} for r in rows])+'\n')
        report.commit()
        assert report.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    finally:report.close()


def export(root):
    root=Path(root).resolve();batch=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    output=root/'reporting'/batch;output.mkdir(parents=True)
    source=connect(root,True);target=sqlite3.connect(output/'source.sqlite')
    try:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or target.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Source snapshot validation failed')
    finally:target.close();source.close()
    db=sqlite3.connect((output/'source.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:tables,info=collect(db)
    finally:db.close()
    write_tables(output,tables)
    (output/'data_dictionary.json').write_text(json.dumps({'contract_version':CONTRACT,'tables':SCHEMA,'keys':KEYS,'nulls':'Empty CSV cells represent SQL NULL; never replace unknown money or miles with zero.','money':'Signed integer cents; ratios use sums of the same eligible rows.'},indent=2)+'\n')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}
    manifest={'snapshot_id':batch,'contract_version':CONTRACT,'created_at':datetime.now(timezone.utc).isoformat(),**info,
        'table_counts':{k:len(v) for k,v in tables.items()},'file_sha256':hashes,
        'cohort_metrics':{'preliminary':metrics(tables['FactLoadLeg']),'reconciled':metrics(tables['FactLoadLeg'],'Reconciled subset')}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    pointer=root/'reporting/latest.json';temp=pointer.with_name('latest_'+uuid.uuid4().hex+'.tmp')
    temp.write_text(encoded({'snapshot_id':batch}));os.replace(temp,pointer)
    return output


def latest(root):
    root=Path(root).resolve();pointer=json.loads((root/'reporting/latest.json').read_text())
    out=(root/'reporting'/pointer['snapshot_id']).resolve();out.relative_to(root/'reporting')
    return out


def read_table(batch,table):
    if table not in SCHEMA:raise ValueError('Unknown reporting table')
    db=sqlite3.connect((Path(batch)/'reporting.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:return [dict(r) for r in db.execute('SELECT * FROM '+table)]
    finally:db.close()
