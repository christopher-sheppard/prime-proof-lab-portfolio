"""Deterministic fictional fixtures, authored independently of private records."""
import hashlib
import json
from pathlib import Path
import sqlite3

CODE=Path(__file__).resolve().parents[1]


def pdf_bytes(pages):
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids=[]
    for lines in pages:
        pnum=len(objects)+1;streamnum=pnum+1;kids.append(f'{pnum} 0 R')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {streamnum} 0 R >>'.encode())
        stream='BT /F1 12 Tf 40 750 Td 18 TL\n'
        for line in lines:
            escaped=line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)');stream+=f'({escaped}) Tj T*\n'
        stream+='ET';body=stream.encode('ascii')
        objects.append(b'<< /Length '+str(len(body)).encode()+b' >>\nstream\n'+body+b'\nendstream')
    objects[1]=f'<< /Type /Pages /Count {len(kids)} /Kids [{" ".join(kids)}] >>'.encode()
    out=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(out));out.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    start=len(out);out.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:out.extend(f'{offset:010d} 00000 n \n'.encode())
    out.extend(f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode());return bytes(out)


def generate(root):
    root=Path(root).resolve();path=root/'database/prime.sqlite'
    if path.exists():
        db=sqlite3.connect(path)
        try:
            if db.execute("SELECT value FROM system_metadata WHERE key='synthetic'").fetchone()!=('true',):raise ValueError('Refusing to replace a non-synthetic database')
        finally:db.close()
        return root
    (root/'database').mkdir(parents=True,exist_ok=True);(root/'sources/settlements').mkdir(parents=True,exist_ok=True)
    for folder in ('reports','backups','exports','staging'): (root/folder).mkdir(exist_ok=True)
    db=sqlite3.connect(path);db.execute('PRAGMA foreign_keys=ON')
    try:
        for name in ('001_source_registry','002_page_extraction','003_structured_staging','004_workbench','005_source_reviews','006_invoice_parties','007_review_desk'):
            db.executescript((CODE/'sql'/f'{name}.sql').read_text());db.execute('INSERT INTO schema_migrations VALUES (?,?)',(name,'2026-09-27T00:00:00Z'))
        db.executemany('INSERT INTO system_metadata VALUES (?,?)',[('synthetic','true'),('historical_financial_import_complete','false'),('financial_data_through','unknown')])
        db.execute("INSERT INTO inventory_runs VALUES ('demo_inventory','2026-09-27T00:00:00Z','sources/settlements',2)")
        documents=[]
        for i in (1,2):
            pages=[['FICTIONAL DEMO - NO REAL SETTLEMENT DATA',f'Example Haulage / Unit DEMO-{i} / Settlement 2026-09-18','Leg A: owner $100 / loaded 80 + empty 20 = 100 miles','Leg B: owner $300 / loaded 180 + empty 20 = 200 miles','Unknown empty miles: excluded from both rate sums','Repower: two legs, allocation unresolved','Trainee gross $900; evidenced owner charge only $200','Reserve release $50 is cash, not freight earnings','Late repair adjustment $25: service date unresolved'],
                   ['FICTIONAL INVOICE COPY 1','Example Products / NORTH PLANT','100 Example Road, Sample City, ZZ 00000','Bill to is separate from the physical plant','This supporting invoice creates no settlement posting'],
                   ['FICTIONAL INVOICE COPY 2','Example Products / SOUTH PLANT','200 Example Road, Sample City, ZZ 00000','A repeated supporting invoice creates no added revenue']]
            content=pdf_bytes(pages);doc=hashlib.sha256(content).hexdigest();job=f'demo-job-{i}';pid=f'demo-parse-{i}'
            file=f'fictional_statement_{i}.pdf';(root/'sources/settlements'/file).write_bytes(content)
            db.execute('INSERT INTO source_documents(document_id,sha256,original_filename,size_bytes,page_count,first_seen_at) VALUES (?,?,?,?,?,?)',(doc,doc,file,len(content),3,'2026-09-27T00:00:00Z'))
            db.execute('INSERT INTO source_occurrences(document_id,relative_path,first_seen_at,last_seen_run_id) VALUES (?,?,?,?)',(doc,'sources/settlements/'+file,'2026-09-27T00:00:00Z','demo_inventory'))
            db.execute('INSERT INTO page_extraction_jobs VALUES (?,?,?,?,?,?,?,?,?,?)',(job,doc,'demo',json.dumps({'numeric_pass':'synthetic'}),3,'2026-09-27','2026-09-27','2026-09-27','complete',None))
            for pn,text in enumerate(pages,1):
                layout='\n'.join(text)
                db.execute('INSERT INTO source_pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(job,pn,'extracted',612,792,layout,layout,layout,hashlib.sha256(layout.encode()).hexdigest(),len(layout.split()),100.0,0,'[]','2026-09-27','unverified'))
                db.execute('INSERT INTO source_numeric_pages VALUES (?,?,?,?)',(job,pn,layout,'[]'))
            db.execute('INSERT INTO structured_runs VALUES (?,?,?,?,?,?)',(pid,job,'synthetic-1.1','demo-code-'+str(i),'2026-09-27T01:00:00Z','complete'))
            db.execute('INSERT INTO statement_candidates(parse_id,document_kind,settlement_date,owner_code,owner_name,unit_code,header_evidence_json) VALUES (?,?,?,?,?,?,?)',(pid,'owner_recap','2026-09-18','DEMO','Example Haulage',f'DEMO-{i}','[]'))
            if i==1:
                db.execute('INSERT INTO structured_runs VALUES (?,?,?,?,?,?)',('old-demo-parse',job,'synthetic-old','old-code','2026-09-26T00:00:00Z','complete'))
                db.execute("INSERT INTO statement_candidates(parse_id,document_kind,settlement_date,header_evidence_json) VALUES ('old-demo-parse','owner_recap','2026-09-18','[]')")
            for pn in (1,2,3):db.execute('INSERT INTO page_classifications VALUES (?,?,?,?)',(pid,pn,'owner_recap' if pn==1 else 'freight_invoice','synthetic'))
            documents.append((doc,job,pid))
            def line(n,raw,page=1):
                lid=f'{pid}-p{page}-l{n}';words=[[1,raw,40,40+n*18,400,12,100,1,1,n]]
                db.execute('INSERT INTO source_line_candidates VALUES (?,?,?,?,?,?,?,?,?)',(lid,pid,page,n,'owner_recap' if page==1 else 'freight_invoice',None,raw,json.dumps(words),'source_text'));return lid
            specs=[('A',10000,80,20,100,'01'),('B',30000,180,20,200,'01'),('UNKNOWN',10000,100,None,None,'01'),('REPOWER',7500,50,10,60,'01'),('REPOWER',12500,70,10,80,'01'),('ZERO',5000,0,0,0,'01'),('ANNOTATION',10000,90,10,100,'01')] if i==1 else []
            for n,(order,cents,loaded,empty,total,dispatch) in enumerate(specs,1):
                lid=line(n,f'RV {order} Trip compensation {cents/100:.2f} loaded {loaded} empty {empty}')
                db.execute('INSERT INTO settlement_posting_candidates(posting_id,parse_id,section,code_raw,order_raw,dispatch_raw,description_raw,amount_cents,payout_effect_cents,numeric_evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?)',(lid,pid,'revenue','RV',order,dispatch,'TRIP REVENUE',cents,cents,'{}'))
                db.execute('INSERT INTO load_leg_candidates(leg_id,parse_id,order_raw,dispatch_raw,loaded_miles,empty_miles,total_miles,owner_revenue_cents,solo_team_raw,mileage_check,numeric_evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(lid,pid,order,dispatch,loaded,empty,total,cents,'SOLO','match' if total is not None else 'incomplete','{}'))
                for seq,(city,marker) in enumerate([('Example Pickup','L'),('Example Stop','L'),('Example Delivery',None)],1):
                    db.execute('INSERT INTO route_point_candidates(point_id,leg_id,line_id,sequence,city_raw,state_raw,following_segment_marker) VALUES (?,?,?,?,?,?,?)',(lid+f'-stop{seq}',lid,lid,seq,city,'ZZ',marker))
                if order=='ANNOTATION':db.execute('INSERT INTO structured_issues VALUES (?,?,?,?,?,?)',(lid+'-annotation',pid,1,lid,'route_source_annotation','Fictional disputed approval annotation'))
                if order=='UNKNOWN':db.execute('INSERT INTO structured_issues VALUES (?,?,?,?,?,?)',(lid+'-issue',pid,1,lid,'load_mileage_review','Empty miles are unknown; do not infer zero'))
            for n,section,desc,cents in [(20,'wage_expense','EVIDENCED OWNER TRAINEE CHARGE',20000),(21,'reimbursement','RESERVE RELEASE',5000),(22,'deduction','LATE REPAIR ADJUSTMENT',2500)]:
                lid=line(n,desc)
                db.execute('INSERT INTO settlement_posting_candidates(posting_id,parse_id,section,code_raw,description_raw,amount_cents,payout_effect_cents,numeric_evidence_json) VALUES (?,?,?,?,?,?,?,?)',(lid,pid,section,'DEMO',desc,cents,cents if section=='reimbursement' else -cents,'{}'))
                db.execute('INSERT INTO structured_issues VALUES (?,?,?,?,?,?)',(lid+'-review',pid,1,lid,'classification_review','Confirm economic treatment from fictional source'))
            for n,metric,value in [(30,'revenue_total',85000 if i==1 else 0),(31,'net_due',67500 if i==1 else -17500),(32,'payroll_page_2_payroll_gross',90000)]:
                lid=line(n,metric+' '+str(value));db.execute('INSERT INTO statement_total_candidates VALUES (?,?,?,?,?,?,?)',(lid+'-total',pid,lid,metric,value,'cents','{}'))
            db.execute('INSERT INTO reconciliation_checks VALUES (?,?,?,?,?,?,?,?,?)',(pid+'-rev',pid,'revenue_sum','match',85000 if i==1 else 0,85000 if i==1 else 0,0,'cents','Synthetic arithmetic only'))
            db.execute('INSERT INTO reconciliation_checks VALUES (?,?,?,?,?,?,?,?,?)',(pid+'-miles',pid,'empty_miles_sum','incomplete',None,70,None,'miles','Unknown empty miles'))
            db.execute('INSERT INTO invoice_detail_runs VALUES (?,?,?,?,?)',(pid+'-detail',pid,'synthetic','demo','2026-09-27'))
            for pn,plant in [(2,'NORTH'),(3,'SOUTH')]:
                lid=line(1,'Example Products '+plant+' PLANT',pn);ip=pid+f'-invoice{pn}'
                db.execute('INSERT INTO invoice_page_candidates VALUES (?,?,?,?,?,?,?,?)',(ip,pid+'-detail',pn,lid,'A','01','party_blocks_unverified','{}'))
                for role in ('bill_to','shipper','receiver'):
                    db.execute('INSERT INTO invoice_party_candidates VALUES (?,?,?,?,?,?,?,?)',(ip+role,ip,role,'Example Products '+plant,'100 Fictional Road\nSample City ZZ 00000','EXAMPLE',json.dumps({'line_ids':[lid]}),'unverified'))
        db.commit()
        if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Synthetic foreign-key failure')
    except BaseException:
        db.close();path.unlink(missing_ok=True);raise
    finally:db.close()
    return root
