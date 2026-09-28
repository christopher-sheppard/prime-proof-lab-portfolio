"""Stage raw bill-to, shipper and receiver blocks from the Prime freight form.

No entity merging, geocoding, invoice revenue allocation, or accounting entries.
OCR strings and template-based roles require review against the source image.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from prime_structure import cell, connect, ident, now
from prime_review import backup
from prime_workbench import locks

CODE=Path(__file__).resolve().parent
VERSION='0.1.0'
MIGRATION='006_invoice_parties'


def party_blocks(lines,width,height):
    rows=[]
    for line in lines:
        ws=json.loads(line['words_json'])
        if not ws:continue
        rows.append({**dict(line),'words':ws,'y':sum(w[3]+w[5]/2 for w in ws)/len(ws)/height})
    # Gate the known form by three spatial anchors; never use filename or totals.
    header=next((r for r in rows if r['y']<.09 and re.search(r'UNIT\s*:',r['raw_text'])),None)
    date_row=next((r for r in rows if .12<r['y']<.18 and re.search(r'SETTLE[MNH]ENTS?\s+D[AR]TE\s*:',r['raw_text'])),None)
    shipper=next((r for r in rows if .28<r['y']<.40 and re.search(r'SHI[PR][PR]E[PR]S\s+N[O05]',cell(r['words'],width,.40,.65))),None)
    if not all((header,date_row,shipper)):
        return None,[]
    def block(selected,role,left,right):
        content=[(r,cell(r['words'],width,left,right)) for r in selected]
        content=[(r,t) for r,t in content if t]
        if not 2<=len(content)<=5:return None
        first=content[0][0]
        return {'role_candidate':role,'name_raw':content[0][1],
            'address_block_raw':'\n'.join(t for _,t in content[1:]),
            'code_raw':cell(first['words'],width,.44,.58) or None if role=='bill_to' else None,
            'evidence':{'template':'prime_freight_form_v1','role_basis':'position_on_source_form; unverified',
                'line_ids':[r['line_id'] for r,_ in content],
                'word_indices':[[w[0] for w in r['words'] if left<=(w[2]+w[4]/2)/width<right] for r,_ in content],
                'x_bounds':[left,right],'y_bounds':[content[0][0]['y'],content[-1][0]['y']],
                'warning':'OCR may substitute plausible letters/digits. Name, address, code and party role are unverified; not a facility master.'}}
    bill=block([r for r in rows if date_row['y']+.005<r['y']<.25],'bill_to',.07,.44)
    ship=block([r for r in rows if shipper['y']-.003<=r['y']<shipper['y']+.065],'shipper',.015,.30)
    receiver=block([r for r in rows if .42<r['y']<.53],'receiver',.015,.30)
    parts=[p for p in (bill,ship,receiver) if p]
    # Raw identifiers only: damaged but numeric-looking OCR must not link dispatches.
    order=re.search(r'[O05][RPK][D0][E3][RPK]:\s*(\S+)',header['raw_text'])
    dispatch=re.search(r'DIS[PR]:\s*(\S+)',header['raw_text'])
    info={'header_line_id':header['line_id'],'order_raw':order[1] if order else None,
        'dispatch_raw':dispatch[1] if dispatch else None,
        'anchor_line_ids':[header['line_id'],date_row['line_id'],shipper['line_id']]}
    return info,parts


def run(root):
    with locks(root):
        db=connect(root)
        try:
            signature=hashlib.sha256(Path(__file__).read_bytes()+(CODE/'prime_structure.py').read_bytes()+(CODE/'sql/006_invoice_parties.sql').read_bytes()).hexdigest()
            print('Database backup:',backup(root,'prime_before_invoice_details'),flush=True)
            if not db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?',(MIGRATION,)).fetchone():
                db.executescript('BEGIN IMMEDIATE;\n'+(CODE/'sql/006_invoice_parties.sql').read_text())
                db.execute('INSERT INTO schema_migrations VALUES (?,?)',(MIGRATION,now()));db.commit()
            counts=Counter()
            for s in db.execute('SELECT * FROM v_workbench_statements').fetchall():
                detail_id=ident(s['parse_id'],signature)
                if db.execute('SELECT 1 FROM invoice_detail_runs WHERE detail_id=?',(detail_id,)).fetchone():
                    counts['documents_skipped']+=1;continue
                pages=db.execute("SELECT k.page_number,p.width_pixels,p.height_pixels FROM page_classifications k JOIN source_pages p ON p.job_id=? AND p.page_number=k.page_number WHERE k.parse_id=? AND k.page_kind='freight_invoice'",(s['job_id'],s['parse_id'])).fetchall()
                if not pages:continue
                with db:
                    db.execute('INSERT INTO invoice_detail_runs VALUES (?,?,?,?,?)',(detail_id,s['parse_id'],VERSION,signature,now()))
                    for page in pages:
                        pn=page['page_number'];page_id=ident(detail_id,pn)
                        lines=db.execute('SELECT * FROM source_line_candidates WHERE parse_id=? AND page_number=? ORDER BY line_number',(s['parse_id'],pn)).fetchall()
                        info,parts=party_blocks(lines,page['width_pixels'],page['height_pixels'])
                        status='party_blocks_unverified' if info and len(parts)==3 else 'unsupported_layout'
                        counts[status]+=1
                        # Incomplete template recognition never emits guessed party roles.
                        if status=='unsupported_layout':parts=[]
                        evidence={'template':'prime_freight_form_v1','anchors':info,'notes':'Raw identifiers only; no automatic load matching. Charges and taxes remain pending.'}
                        db.execute('INSERT INTO invoice_page_candidates VALUES (?,?,?,?,?,?,?,?)',(page_id,detail_id,pn,info['header_line_id'] if info else None,info['order_raw'] if info else None,info['dispatch_raw'] if info else None,status,json.dumps(evidence)))
                        for p in parts:
                            db.execute('INSERT INTO invoice_party_candidates(party_id,invoice_page_id,role_candidate,name_raw,address_block_raw,code_raw,evidence_json) VALUES (?,?,?,?,?,?,?)',(ident(page_id,p['role_candidate']),page_id,p['role_candidate'],p['name_raw'],p['address_block_raw'],p['code_raw'],json.dumps(p['evidence'])))
                            counts['party_blocks']+=1
            result={'created_at':now(),'parser_version':VERSION,'processing':dict(counts),
                'coverage':dict(db.execute('SELECT extraction_status,count(*) FROM v_invoice_detail_coverage GROUP BY 1')),
                'current_party_blocks':db.execute('SELECT count(*) FROM v_invoice_party_candidates').fetchone()[0],
                'note':'Unverified OCR party observations only. No verified customers/facilities created. Invoice money, service dates and vendor cost detail remain pending.'}
            report=root/'reports'/('invoice_details_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
            report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));print('Report:',report)
        finally:db.close()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,default=Path.home()/'PrimeData')
    args=p.parse_args();run(args.data_root.expanduser().resolve())
