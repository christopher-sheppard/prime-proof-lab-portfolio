"""Convert OCR evidence into reviewable SQL candidates. Nothing is auto-approved."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import statistics
import uuid

VERSION = '0.4.2'
CODE = Path(__file__).resolve().parent
MIGRATION = '003_structured_staging'


def now():
    return datetime.now(timezone.utc).isoformat()


def ident(*parts):
    return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()


def connect(root, readonly=False):
    path = root / 'database/prime.sqlite'
    if not path.is_file():
        raise RuntimeError(f'Existing database missing: {path}')
    db = sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=30000')
    return db


def initialize(root):
    db = connect(root)
    try:
        if db.execute('SELECT 1 FROM schema_migrations WHERE migration_id=?', (MIGRATION,)).fetchone():
            return
        if not db.execute("SELECT 1 FROM schema_migrations WHERE migration_id='002_page_extraction'").fetchone():
            raise RuntimeError('Install the page extraction update first. Do not bootstrap again.')
        (root / 'backups').mkdir(parents=True, exist_ok=True)
        destination = root / 'backups' / f'prime_before_structured_import_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}.sqlite'
        target = sqlite3.connect(destination)
        try:
            db.backup(target)
            if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or target.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Backup verification failed; migration stopped.')
        finally:
            target.close()
        db.executescript('BEGIN IMMEDIATE;\n' + (CODE / 'sql/003_structured_staging.sql').read_text())
        db.execute('INSERT INTO schema_migrations VALUES (?,?)', (MIGRATION, now()))
        db.commit()
        print(f'Database backup: {destination}', flush=True)
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def word_rows(words):
    """Group by physical baseline, retaining every word and its original coordinates."""
    if not words:
        return []
    tolerance = max(2, statistics.median(w[5] for w in words if w[5] > 0) * .42)
    rows = []
    for w in sorted(words, key=lambda w: (w[3] + w[5]/2, w[2])):
        cy = w[3] + w[5]/2
        if not rows or abs(cy - rows[-1]['y']) > tolerance:
            rows.append({'y': cy, 'words': [w]})
        else:
            rows[-1]['words'].append(w)
    for row in rows:
        row['words'].sort(key=lambda w: w[2])
        row['text'] = ' '.join(w[1] for w in row['words'])
        row['height'] = max(w[5] for w in row['words'])
    return rows


def cell(words, width, left, right):
    return ' '.join(w[1] for w in words if left <= (w[2]+w[4]/2)/width < right).strip()


def strict_number(raw, decimals, allow_zero_letters=False):
    """Never infer missing punctuation/digits. O->0 is a recorded candidate rule only."""
    text = raw.strip().replace('\u2212', '-').replace('\u2014', '-').replace('\u2013', '-')
    changed = []
    if allow_zero_letters and re.search('[Oo]', text):
        text = text.replace('O', '0').replace('o', '0')
        changed.append('O_to_0_in_numeric_cell')
    if allow_zero_letters and re.search('[Il]',text):
        text=text.replace('I','1').replace('l','1')
        changed.append('I_or_l_to_1_in_numeric_cell')
    # Spaces between separate tokens are not removed: that could merge two amounts.
    sign = 1
    if text.startswith('(') and text.endswith(')'):
        sign, text = -1, text[1:-1]
    elif text.endswith('-'):
        sign, text = -1, text[:-1]
    elif text.startswith('-'):
        sign, text = -1, text[1:]
    text = text.strip()
    whole = r'(?:\d{1,3}(?:,\d{3})+|\d+)'
    pattern = whole if decimals == 0 else rf'(?:{whole})?\.\d{{{decimals}}}'
    if not re.fullmatch(pattern, text):
        return None, changed
    try:
        return sign * int(Decimal(text.replace(',', '')) * 10**decimals), changed
    except (InvalidOperation, ValueError):
        return None, changed


def numeric_cell(general, numeric, width, left, right, decimals=2):
    raw_g, raw_n = cell(general, width, left, right), cell(numeric, width, left, right)
    g, changes = strict_number(raw_g, decimals, True)
    n, _ = strict_number(raw_n, decimals)
    if g is not None and n is not None:
        state = 'normalized_agreement' if changes else 'agreement'
        value = g
        if g != n:
            value, state = None, 'disagreement'
    elif g is not None:
        value, state = g, 'general_only'
    elif n is not None:
        value, state = n, 'numeric_only'
    else:
        value, state = None, 'missing' if not raw_g and not raw_n else 'unparsed'
    return value, {'general_raw': raw_g, 'numeric_raw': raw_n, 'general_candidate': g,
                   'numeric_candidate': n, 'state': state, 'normalizations': changes,
                   'decimal_places': decimals, 'x_bounds': [left, right]}


def date_candidate(raw, year_first=True):
    text = raw.strip()
    # Letter f or X in slash positions and O in digit positions occur in the legacy font.
    parts = re.fullmatch(r'([0-9OoIlZ]{1,4})[/fXx]([0-9OoIl]{1,2})[/fXx]([0-9OoIl]{1,4})', text)
    if not parts:
        return None
    parts = [int(x.translate(str.maketrans({'O':'0','o':'0','I':'1','l':'1','Z':'2'}))) for x in parts.groups()]
    y, m, d = parts if year_first else [parts[2], parts[0], parts[1]]
    if y < 100:
        y += 2000
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def page_kind(text):
    upper = text.upper().replace("'", '')
    if re.search(r'OPERATIN[GC]\s+STATE[MNH]ENT', upper[:1500]):
        return 'operating_statement'
    if re.search(r'DRIVERS?\s+PAYROLL\s+RECAP', upper[:1500]):
        return 'employee_payroll'
    if (re.search(r'SICK\s+[PR]AY', upper) and 'EARNINGS:' in upper and
            'TAXES:' in upper and 'YTD' in upper):
        return 'employee_payroll_summary'
    if re.search(r'FUEL\s+TAX\s+RECON', upper[:1500]):
        return 'fuel_tax_statement'
    if re.search(r'(?:E\W*Z\W*[PR]ASS|PRE[PR]ASS|DRIVE.{0,4}YZE|DRIVEL.{0,3}YZE)\s+BILL', upper[:700]):
        return 'toll_detail'
    if re.search(r'SHI[PR][PR]E[PR]S',upper) or ('DISP:' in upper[:350] and 'ORDER:' in upper[:350]):
        return 'freight_invoice'
    if any(x in upper for x in ('REPAIR ORDER', 'WORK ORDER', 'VMRS', 'PARENT UNIT', 'CUSTOMER INVOICE','INVOICE DETAIL')):
        return 'maintenance_or_vendor_invoice'
    if re.search(r'SETTLEMENTS?\s+DATE', upper[:700]) and (re.search(r'FLATBED\s+DIV',upper[:1000]) or re.search(r'SET[1LI][5S]',upper[:1000])):
        return 'owner_recap'
    return 'unclassified'


def numeric_header_date(raw_general,raw_numeric):
    """Recover only a date with evidenced separator positions and compatible digits."""
    g=raw_general.replace("'",'').replace('\u2019','')
    if not re.fullmatch(r'.{2}[/fXx].{2}[/fXx].{2}',g):return None
    n=raw_numeric.replace(',','')
    if not re.fullmatch(r'\d{2}[13/]\d{2}[13/]\d{2}',n):return None
    trans=str.maketrans({'O':'0','o':'0','I':'1','l':'1','Z':'2'})
    g=g.translate(trans)
    for pos in (0,1,3,4,6,7):
        if g[pos].isdigit() and g[pos]!=n[pos]:return None
    return date_candidate(n[:2]+'/'+n[3:5]+'/'+n[6:])



# Raw jurisdiction tokens are preserved. Unknown/OCR-damaged codes stay reviewable.
ROUTE_JURISDICTIONS = frozenset("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AB BC MB NB NL NS NT NU ON PE QC SK YT".split())


def parse_route_text(text):
    """Read complete city/state chunks while retaining OCR spellings.

    E/L/U follows a jurisdiction; a leading E in East Peoria or East Setauket
    belongs to the city. Require full coverage so damaged text stays reviewable.
    """
    text = text.strip()
    pattern = re.compile(r"([\w'‘’ ,.{}()\-]+?)\s+([A-Z0-9'‘’]{1,6})(?:\s+([ELU])(?=\s|$)|(?=\s*$))")
    points = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        match = pattern.match(text, position)
        if not match or not any(c.isalpha() for c in match[1]) or not any(c.isalpha() for c in match[2]):
            return []
        points.append((match[1].strip(), match[2], match[3]))
        position = match.end()
    if len(points) == 1 and points[0][2] is None and points[0][1] not in ROUTE_JURISDICTIONS:
        return []
    return points


def uncoded_deduction(words, numeric, width, section):
    """Recognize evidenced PO disbursements only inside the deduction section."""
    if section != 'deduction':
        return None
    description = cell(words,width,.013,.647)
    pattern = r'(?:EFUND|ADV\s+EMERG\s+FUND|REPLACE\s+CK\s+[0-9OoIl]+)\s+PO[#§:]\s*:?\s*[0-9OoIl]+\s*'
    if not re.fullmatch(pattern,description,re.I):
        return None
    # Require two actual financial cells, not a prose continuation mentioning a PO.
    balance, _ = numeric_cell(words,numeric,width,.647,.706)
    amount, _ = numeric_cell(words,numeric,width,.706,.777)
    if balance is None or amount is None:
        return None
    return description


def parse_document(db, item):
    job = item['job_id']
    code_hash = hashlib.sha256(Path(__file__).read_bytes() + (CODE/'prime_review.py').read_bytes()).hexdigest()
    from prime_review import review_inputs, apply_total_review
    reviews, review_hash = review_inputs(db, job)
    source_code_hash = code_hash
    if reviews:
        code_hash = ident(code_hash, review_hash)
    pid = ident(job, code_hash)
    if db.execute('SELECT 1 FROM structured_runs WHERE parse_id=?', (pid,)).fetchone():
        return 'skipped'
    settings = json.loads(item['settings_json'])
    if item['job_status'] != 'complete' or settings.get('numeric_pass') != 'legacy_digits_v1':
        return 'needs_corrected_ocr'
    pages = [dict(r) for r in db.execute('SELECT * FROM source_pages WHERE job_id=? ORDER BY page_number', (job,))]
    if len(pages) != item['page_count']:
        return 'needs_corrected_ocr'
    headers = []
    owner, name, unit = None, None, None
    first_kind = page_kind(pages[0]['layout_text'])
    for pg in pages:
        if page_kind(pg['layout_text']) not in ('owner_recap', 'employee_payroll', 'employee_payroll_summary'):
            continue
        # Embedded trainee payroll dates are not owner settlement dates.
        if first_kind == 'owner_recap' and page_kind(pg['layout_text']) != 'owner_recap':
            continue
        for line in pg['layout_text'].splitlines()[:18]:
            m = re.search(r'(SETTLEMENTS?\s+DATE\s*:\s*|PAYROLL\s+ENDING\s*)(\S+)', line, re.I)
            if m:
                candidate=date_candidate(m[2]);numeric_raw=None;basis='general_header'
                if candidate is None and first_kind=='owner_recap':
                    nr=db.execute('SELECT words_json FROM source_numeric_pages WHERE job_id=? AND page_number=?',(job,pg['page_number'])).fetchone()
                    words=[list(r) for r in db.execute('SELECT word_index,raw_text,left_px,top_px,width_px,height_px,confidence,block_number,paragraph_number,line_number FROM source_words WHERE job_id=? AND page_number=?',(job,pg['page_number']))]
                    for rr in word_rows(words):
                        if 'SETTLEMENT' in rr['text'].upper() and 'DATE' in rr['text'].upper():
                            nw=[w for w in json.loads(nr[0]) if abs(w[3]+w[5]/2-rr['y'])<=max(4,rr['height']*.5)] if nr else []
                            numeric_raw=cell(nw,pg['width_pixels'],.150,.220)
                            candidate=numeric_header_date(m[2],numeric_raw)
                            if candidate:basis='numeric_header_with_evidenced_separator_positions'
                            break
                headers.append({'page': pg['page_number'], 'raw': m[2], 'candidate': candidate, 'numeric_raw':numeric_raw,'basis':basis,'line': line})
            if pg['page_number'] == 1:
                m = re.search(r'OWNER\s+(\S+)\s+(.+?)\s+CITY:', line, re.I)
                if m:
                    owner, name = m[1], m[2].strip()
                m = re.search(r'^\s*UNIT\s*:?\s+(\S+)', line, re.I)
                if m:
                    unit = m[1]
                m = re.search(r'EMPLOYEE:\s*(\S+)\s+(.+?)(?:\s{3,}|$)', line, re.I)
                if m and not owner:
                    owner, name = m[1], m[2].strip()
    dates = {h['candidate'] for h in headers if h['candidate']}
    settlement_date = next(iter(dates)) if len(dates) == 1 else None
    reviewed_date = next((r for r in reviews if r['field_name']=='settlement_date'), None)
    if reviewed_date:
        settlement_date = json.loads(reviewed_date['value_json'])
        headers.append({'basis':'source_image_review','review_id':reviewed_date['review_id'],
                        'candidate':settlement_date,'page':reviewed_date['page_number']})
    # A plausible OCR date is a candidate, never a verified coverage assertion.
    with db:
        db.execute('INSERT INTO structured_runs VALUES (?,?,?,?,?,?)', (pid,job,VERSION,code_hash,now(),'complete'))
        if reviews:
            db.execute('INSERT INTO structured_review_inputs VALUES (?,?,?,?)',
                       (pid,source_code_hash,review_hash,json.dumps([r['review_id'] for r in reviews])))
        db.execute('INSERT INTO statement_candidates(parse_id,document_kind,settlement_date,owner_code,owner_name,unit_code,header_evidence_json) VALUES (?,?,?,?,?,?,?)',
                   (pid, first_kind, settlement_date, owner, name, unit, json.dumps(headers)))

        def issue(kind, detail, pg=None, line=None):
            db.execute('INSERT OR IGNORE INTO structured_issues VALUES (?,?,?,?,?,?)',
                       (ident(pid,pg,line,kind,detail),pid,pg,line,kind,detail))

        if settlement_date is None:
            issue('settlement_date_unresolved','No single agreeing readable settlement/payroll date across the relevant headers.')
        elif date.fromisoformat(settlement_date).weekday() != 4:
            issue('non_friday_candidate','Review special dates and OCR; never shift this candidate automatically.')
        if settlement_date and not '2018-01-01' <= settlement_date <= date.today().isoformat():
            issue('date_outside_expected_history','Candidate is outside the expected historical range.')
        if len(headers) == 1 or any(not h['candidate'] for h in headers):
            issue('header_date_review','Some header evidence is unreadable or has no repeated date for comparison.')

        totals = {}
        postings = {s: [] for s in ('revenue','reimbursement','deduction','wage_expense')}
        legs = []
        current_section = None
        last_leg = None
        route_seq = 0
        operating_income_block = False

        def add_total(line_id, metric, value, ev, unit_name='cents'):
            value,ev = apply_total_review(reviews, pn, raw, metric, value, ev)
            db.execute('INSERT INTO statement_total_candidates VALUES (?,?,?,?,?,?,?)',
                       (ident(line_id,metric),pid,line_id,metric,value,unit_name,json.dumps(ev)))
            totals.setdefault(metric, []).append(value)

        for pg in pages:
            pn, width = pg['page_number'], pg['width_pixels']
            kind = page_kind(pg['layout_text'])
            supported = 'owner_postings_and_loads' if kind == 'owner_recap' else ('payroll_summary' if kind=='employee_payroll' else 'raw_lines_preserved_detail_parser_pending')
            db.execute('INSERT INTO page_classifications VALUES (?,?,?,?)', (pid,pn,kind,supported))
            if kind not in ('owner_recap','employee_payroll'):
                issue('detail_parser_pending',f'{kind}: raw text, numeric pass and coordinates are retained; detailed structured import is pending.',pn)
            words = [list(r) for r in db.execute('SELECT word_index,raw_text,left_px,top_px,width_px,height_px,confidence,block_number,paragraph_number,line_number FROM source_words WHERE job_id=? AND page_number=? ORDER BY word_index',(job,pn))]
            numeric_record = db.execute('SELECT words_json FROM source_numeric_pages WHERE job_id=? AND page_number=?',(job,pn)).fetchone()
            if not numeric_record:
                raise RuntimeError(f'Missing numeric OCR for page {pn}; resume extraction first.')
            numeric_words = json.loads(numeric_record[0])
            last_leg = None
            for ln, row in enumerate(word_rows(words), 1):
                line_id = ident(pid,pn,ln)
                raw = row['text']
                upper = raw.upper().replace("'", '')
                numeric = [w for w in numeric_words if abs(w[3]+w[5]/2-row['y']) <= max(4,row['height']*.5)]
                ws = row['words']
                role = 'source_text'
                if kind == 'owner_recap':
                    for marker, section in [('REVENUE SECTION','revenue'),('REIMBURSEMENT SECTION','reimbursement'),('DEDUCTION SECTION','deduction'),('WAGE EXPENSE','wage_expense')]:
                        if marker in upper and 'TOTAL' not in upper:
                            current_section, last_leg, role = section,None,'section_header'
                    if re.search(r'W[ACEG]{3}\s+EXPENSE',upper) and 'TOTAL' not in upper:
                        current_section,last_leg,role='wage_expense',None,'section_header'
                    if upper == 'ACCOUNTS' or 'SETTLEMENT RECAP' in upper or upper == 'INTEREST':
                        current_section, last_leg = None, None
                else:
                    current_section = None
                db.execute('INSERT INTO source_line_candidates VALUES (?,?,?,?,?,?,?,?,?)',
                           (line_id,pid,pn,ln,kind,current_section,raw,json.dumps(ws),role))
                # The standard owner recap has fixed columns. Gate with recognized headers.
                if kind == 'owner_recap':
                    metric = None
                    for needle, key in [('TOTAL REIMBURSED','reimbursement_total'),('TOTAL DEDUCTIONS FROM TRUCK','deduction_total'),
                                        ('TOTAL WAGE EXPENSE','wage_expense_total'),('GROSS AMOUNT DUE UNIT','gross_due'),
                                        ('NET AMOUNT DUE UNIT','net_due')]:
                        if needle in upper:
                            metric = key
                            break
                    if re.search(r'[GC]ROSS\s+AMOUNT\s+DUE\s+UNIT',upper):
                        metric='gross_due'
                    if re.search(r'TOTAL\s+WA[GC]E\s+EXPENSE',upper):
                        metric='wage_expense_total'
                    if re.search(r'TOTAL\s+(?:REC[.,]?\s+)?REV(?:ENUE)?(?:\W|$)',upper) and 'FROM SETTLEMENTS' not in upper:
                        metric = 'revenue_total'
                    if metric:
                        value,ev = numeric_cell(ws,numeric,width,.803,.883)
                        add_total(line_id,metric,value,ev)
                        if metric.endswith('_total'):
                            current_section,last_leg = None,None
                        db.execute("UPDATE source_line_candidates SET row_role='reported_total' WHERE line_id=?",(line_id,))
                    if re.search(r'TOTAL\s+(?:REC[.,]?\s+)?(?:REVENUE\s+&\s+)?MILES', upper) and 'SOLO' not in upper:
                        for key,left,right in [('loaded_miles_total',.550,.602),('empty_miles_total',.602,.653),('total_miles_total',.653,.700)]:
                            value,ev = numeric_cell(ws,numeric,width,left,right,0)
                            add_total(line_id,key,value,ev,'miles')
                    if current_section and role!='section_header':
                        code = cell(ws,width,.013,.039)
                        desc_end = .440 if current_section=='revenue' else .650
                        desc = cell(ws,width,.171,desc_end)
                        mmdd = cell(ws,width,.135,.171)
                        mmdd_n = cell(numeric,width,.135,.171)
                        amount_bounds=(.803,.883) if current_section=='revenue' else (.706,.777)
                        amount_text=cell(ws,width,*amount_bounds)
                        date_shaped=bool(re.fullmatch('[0-9OoIl?\u2019\u0027]{4,6}',mmdd) or re.fullmatch('[0-9]{4}',mmdd_n))
                        money_shaped=bool(re.search(r'[0-9OoIl?]*\.[0-9OoIl?]{2}',amount_text))
                        # An OCR apostrophe inside a short code must not discard its row.
                        code_gate = code.replace("'", '').replace('\u2019', '')
                        uncoded_desc = uncoded_deduction(ws, numeric, width, current_section)
                        is_posting = bool(uncoded_desc or (re.fullmatch('[A-Za-z0-9]{1,4}',code_gate) and desc and (date_shaped or money_shaped)))
                        if is_posting:
                            amount, ev = numeric_cell(ws,numeric,width,*((.803,.883) if current_section=='revenue' else (.706,.777)))
                            balance,be = (None,{}) if current_section=='revenue' else numeric_cell(ws,numeric,width,.647,.706)
                            discount,de = (None,{}) if current_section=='revenue' else numeric_cell(ws,numeric,width,.777,.850)
                            order = cell(ws,width,.039,.095)
                            dsp = cell(ws,width,.095,.119)
                            seq = cell(ws,width,.119,.135)
                            if uncoded_desc:
                                code,order,dsp,seq,mmdd,desc = None,None,None,None,None,uncoded_desc
                            effect = None if amount is None else (amount if current_section in ('revenue','reimbursement') else -amount)
                            evidence = {'amount':ev,'balance':be,'discount':de}
                            db.execute('INSERT INTO settlement_posting_candidates(posting_id,parse_id,section,code_raw,order_raw,dispatch_raw,sequence_raw,date_mmdd_raw,description_raw,amount_cents,balance_cents,fuel_discount_cents,payout_effect_cents,numeric_evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                       (line_id,pid,current_section,code,order,dsp,seq,mmdd,desc,amount,balance,discount,effect,json.dumps(evidence)))
                            postings[current_section].append(amount)
                            db.execute("UPDATE source_line_candidates SET row_role='posting_candidate' WHERE line_id=?",(line_id,))
                            if amount is None:
                                issue('posting_amount_unresolved',json.dumps(ev),pn,line_id)
                            if uncoded_desc:
                                issue('uncoded_deduction_source_row','Source deduction has a PO reference and amount but no standard code/date/order columns; absent keys remain NULL.',pn,line_id)
                            elif not re.fullmatch('[0-9OoIl]{4}',mmdd):
                                issue('posting_date_raw_review','Payment line retained despite an unreadable month/day; its raw date is preserved.',pn,line_id)
                            if ev['state'] not in ('agreement','normalized_agreement'):
                                issue('numeric_review',f"Amount uses {ev['state']}; candidate remains unverified.",pn,line_id)
                            if current_section=='deduction' and re.search(r'TRACTOR\s+(FUEL|DEF)',desc.upper()):
                                product=re.search(r'TRACTOR\s+(FUEL|DEF)',desc.upper())[1]
                                gallons_match=re.search(r'([0-9Oo]+\.[0-9Oo])\s+GALS',desc)
                                gallons_raw=gallons_match[1] if gallons_match else None
                                gallons=strict_number(gallons_raw,1,True)[0]*100 if gallons_raw and strict_number(gallons_raw,1,True)[0] is not None else None
                                db.execute('INSERT INTO fuel_event_candidates(fuel_id,parse_id,product_raw,gallons_raw,gallons_thousandths,description_raw) VALUES (?,?,?,?,?,?)',
                                           (line_id,pid,product,gallons_raw,gallons,desc))
                            # Labels and number columns establish trip rows; raw codes are preserved.
                            if current_section=='revenue' and re.search(r'TRIP\s+REVENUE',desc.upper().replace("'",'')):
                                spec=[('load_miles',.440,.480,0),('load_revenue_cents',.480,.551,2),('loaded_miles',.551,.602,0),('empty_miles',.602,.653,0),('total_miles',.653,.700,0),('trip_revenue_cents',.700,.765,2),('owner_rate_millionths',.765,.812,3)]
                                values,evid={},{}
                                for key,left,right,dec in spec:
                                    v,e=numeric_cell(ws,numeric,width,left,right,dec)
                                    values[key] = v*1000 if v is not None and key=='owner_rate_millionths' else v
                                    evid[key]=e
                                loaded,empty,total=(values[k] for k in ('loaded_miles','empty_miles','total_miles'))
                                # A blank category may be derived as zero only when the other
                                # independently read category exactly equals the trip total.
                                for absent,other in [('empty_miles','loaded_miles'),('loaded_miles','empty_miles')]:
                                    if values[absent] is None and evid[absent]['state']=='missing' and values[other] is not None and values[other]==total:
                                        values[absent]=0
                                        evid[absent]['state']='derived_zero_from_mileage_identity'
                                        evid[absent]['derivation']=f'total_miles ({total}) minus {other} ({values[other]})'
                                loaded,empty,total=(values[k] for k in ('loaded_miles','empty_miles','total_miles'))
                                check='incomplete' if any(v is None for v in (loaded,empty,total)) else ('match' if loaded+empty==total else 'mismatch')
                                note='Whole-load miles differ from performed trip miles; review partial load, repower or allocation.' if values['load_miles'] is not None and total is not None and values['load_miles']!=total else None
                                db.execute('INSERT INTO load_leg_candidates(leg_id,parse_id,order_raw,dispatch_raw,load_miles,load_revenue_cents,loaded_miles,empty_miles,total_miles,trip_revenue_cents,owner_rate_millionths,owner_revenue_cents,solo_team_raw,mileage_check,allocation_note,numeric_evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                           (line_id,pid,order,dsp,*[values[k] for k,_,_,_ in spec],amount,cell(ws,width,.897,.948),check,note,json.dumps(evid)))
                                legs.append(values)
                                last_leg,route_seq=line_id,0
                                if check!='match':issue('load_mileage_review',f'Loaded + empty versus total: {check}.',pn,line_id)
                        elif last_leg and (not code or re.fullmatch(r'\*+',code)):
                            route = cell(ws,width,.039,.900)
                            points = parse_route_text(route)
                            if points:
                                for city_raw,state_raw,marker in points:
                                    route_seq += 1
                                    db.execute('INSERT INTO route_point_candidates(point_id,leg_id,line_id,sequence,city_raw,state_raw,following_segment_marker) VALUES (?,?,?,?,?,?,?)',
                                               (ident(last_leg,route_seq),last_leg,line_id,route_seq,city_raw,state_raw,marker))
                                    if state_raw not in ROUTE_JURISDICTIONS:
                                        issue('route_jurisdiction_review',f'Raw jurisdiction token {state_raw!r} retained; confirm its intended state/province.',pn,line_id)
                                    if re.search(r'[0-9{}]',city_raw):
                                        issue('route_city_spelling_review',f'Raw city text {city_raw!r} retained; confirm the spelling.',pn,line_id)
                                if code:
                                    issue('route_source_annotation',f'Original route begins with {code!r}; retain and clarify the statement annotation.',pn,line_id)
                                db.execute("UPDATE source_line_candidates SET row_role='route_candidate' WHERE line_id=?",(line_id,))
                        elif code and len(code)<=4 and desc and not metric and any(c.isdigit() for c in cell(ws,width,.706,.883)):
                            # Financial-looking rows that fail the fixed-column/date recognition gate remain explicit.
                            issue('possible_unparsed_posting','Review raw line: column/date pattern did not match a posting.',pn,line_id)
                elif kind=='employee_payroll':
                    for needle,key in [('TOTAL GROSS PAY','payroll_gross'),('TOTAL TAXES','payroll_taxes'),('TOTAL REIMBURSEMENTS','payroll_reimbursements'),('TOTAL CHARGES','payroll_charges'),('TRAVEL ALLOWANCE','payroll_travel'),('NET EARNED','payroll_net'),('AMOUNT LOADED ON CARD','payroll_card')]:
                        if needle in upper:
                            value,ev=numeric_cell(ws,numeric,width,.826,.944)
                            # Metric is page-scoped: an owner's document can contain several employees.
                            add_total(line_id,f'payroll_page_{pn}_{key}',value,ev)
                elif kind=='operating_statement':
                    if re.search(r'STATE[MH]ENT\s+OF\s+INCO[MH]E',upper) or 'OPERATING EXPENSES' in upper or 'OTHER INCOME AND EXPENSE' in upper:
                        operating_income_block=True
                    label=cell(ws,width,.015,.291)
                    if operating_income_block and label:
                        spec=[('week',.291,.377,2),('ytd',.459,.558,2),('ltd',.631,.733,2),
                              ('week_rate',.377,.459,3),('ytd_rate',.558,.631,3),('ltd_rate',.733,.812,3)]
                        values,ev={},{}
                        for key,left,right,dec in spec:
                            values[key],ev[key]=numeric_cell(ws,numeric,width,left,right,dec)
                        # A financial row must have an actual number in the general text, too;
                        # the digit-only reader deliberately turns prose into meaningless digits.
                        if any(re.search(r'[0-9Oo][.,][0-9Oo]',ev[k]['general_raw']) for k in ('week','ytd','ltd')):
                            unit_name='miles' if re.fullmatch('[MH]ILES',label.upper()) else ('unresolved' if 'POINTS' in label.upper() else 'USD')
                            if unit_name=='unresolved':
                                issue('operating_measure_unit_review','Confirm whether this rewards row reports points or a currency value before using it.',pn,line_id)
                            db.execute('INSERT INTO operating_measure_candidates(measure_id,parse_id,label_raw,reported_unit,week_hundredths,ytd_hundredths,ltd_hundredths,week_rate_thousandths,ytd_rate_thousandths,ltd_rate_thousandths,numeric_evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                                       (line_id,pid,label,unit_name,*[values[k] for k,_,_,_ in spec],json.dumps(ev)))
                            db.execute("UPDATE source_line_candidates SET row_role='operating_measure_candidate' WHERE line_id=?",(line_id,))

        def total(metric):
            values=totals.get(metric,[])
            if not values or any(v is None for v in values) or len(set(values))!=1:return None
            return values[0]

        def check(name, calculated, reported, unit_name='cents', detail=''):
            status='incomplete' if calculated is None or reported is None else ('match' if calculated==reported else 'mismatch')
            difference=None if calculated is None or reported is None else calculated-reported
            db.execute('INSERT INTO reconciliation_checks VALUES (?,?,?,?,?,?,?,?,?)',
                       (ident(pid,name),pid,name,status,calculated,reported,difference,unit_name,detail or 'Arithmetic agreement is not verification of OCR, coding, completeness or accounting treatment.'))

        if first_kind=='owner_recap':
            for section,amounts in postings.items():
                reported=total(section+'_total')
                # Zero lines are only a complete sum when an explicit zero total was read.
                summed=sum(amounts) if amounts and all(x is not None for x in amounts) else (0 if not amounts and reported==0 else None)
                check(section+'_sum',summed,reported)
            for key in ('loaded_miles','empty_miles','total_miles'):
                values=[l[key] for l in legs]
                summed=sum(values) if values and all(x is not None for x in values) else (0 if not values and total(key+'_total')==0 else None)
                check(key+'_sum',summed,total(key+'_total'),'miles')
            parts=[total(x) for x in ('revenue_total','reimbursement_total','deduction_total','wage_expense_total')]
            calc=parts[0]+parts[1]-parts[2]-parts[3] if all(x is not None for x in parts) else None
            check('section_totals_to_gross_due',calc,total('gross_due'),detail='Revenue + reimbursement - deductions - wage expense. Net payout can include funds, balance forward and interest; it is not profit.')
            issue('final_payout_bridge_pending','Fund movements, balance forward, reconciliation adjustments, interest and deposits still require the full payout bridge.')
        if first_kind=='employee_payroll':
            for pg in pages:
                if page_kind(pg['layout_text'])!='employee_payroll':
                    continue
                prefix=f"payroll_page_{pg['page_number']}_payroll_"
                parts=[total(prefix+x) for x in ('gross','taxes','reimbursements','charges','travel')]
                calc=parts[0]-parts[1]+parts[2]-parts[3]+parts[4] if all(x is not None for x in parts) else None
                check(prefix+'net_bridge',calc,total(prefix+'net'))
    return 'complete'


def run(root):
    initialize(root)
    db=connect(root)
    try:
        counts=Counter()
        for item in db.execute('SELECT * FROM v_latest_document_extraction ORDER BY original_filename').fetchall():
            counts[parse_document(db,item)]+=1
        return dict(counts)
    finally:
        db.close()


def report(root):
    db=connect(root,True)
    try:
        summary={'created_at':now(),'status':'UNVERIFIED CANDIDATES; financial import is not complete',
                 'statements':db.execute('SELECT count(*) FROM v_settlement_review').fetchone()[0],
                 'posting_candidates':db.execute('SELECT count(*) FROM v_candidate_transactions').fetchone()[0],
                 'load_leg_candidates':db.execute('SELECT count(*) FROM v_candidate_loads').fetchone()[0],
                 'operating_measure_candidates':db.execute('SELECT count(*) FROM v_candidate_operating_measures').fetchone()[0],
                 'checks':dict(db.execute('SELECT status,count(*) FROM v_parse_checks GROUP BY status')),
                 'pages_by_kind':dict(db.execute('SELECT p.page_kind,count(*) FROM page_classifications p JOIN v_settlement_review s USING(parse_id) GROUP BY p.page_kind')),
                 'duplicate_date_groups':[dict(r) for r in db.execute('SELECT settlement_date,owner_code,unit_code,count(*) AS documents FROM v_settlement_review WHERE settlement_date IS NOT NULL GROUP BY settlement_date,owner_code,unit_code HAVING count(*)>1')],
                 'note':'Duplicate candidate keys can be variants or adjustments. No document was deleted or merged.'}
        return summary
    finally:db.close()


def document_export(db, job):
    r=db.execute('SELECT parse_id FROM v_latest_structured_run WHERE job_id=?',(job,)).fetchone()
    if not r:return None
    pid=r[0]
    result={'structured_run':dict(db.execute('SELECT * FROM structured_runs WHERE parse_id=?',(pid,)).fetchone())}
    for table in ['statement_candidates','page_classifications','settlement_posting_candidates','load_leg_candidates','statement_total_candidates','operating_measure_candidates','fuel_event_candidates','reconciliation_checks','structured_issues']:
        result[table]=[dict(x) for x in db.execute(f'SELECT * FROM {table} WHERE parse_id=?',(pid,))]
    result['route_point_candidates']=[dict(x) for x in db.execute('SELECT p.* FROM route_point_candidates p JOIN load_leg_candidates l USING(leg_id) WHERE l.parse_id=?',(pid,))]
    return result


@contextmanager
def database_lock(root):
    (root/'staging').mkdir(parents=True,exist_ok=True)
    with (root/'staging/prime_extract.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another extraction/import command is using this database.')
        yield


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['run','status','initialize'])
    p.add_argument('--data-root',type=Path,default=Path(os.environ.get('PRIME_DATA_DIR',Path.home()/'PrimeData')))
    a=p.parse_args();root=a.data_root.expanduser().resolve()
    with database_lock(root):
        initialize(root)
        if a.command=='run':print(json.dumps(run(root),indent=2))
        if a.command!='initialize':print(json.dumps(report(root),indent=2))
