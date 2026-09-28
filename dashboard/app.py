"""Four local screens sharing a dated reporting contract and a controlled writer."""
from datetime import date,timedelta
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import uuid

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE))
import pandas as pd
import streamlit as st
from analytics.reporting import latest,read_table,metrics
from analytics.records import source_pdf
from prime_structure import connect
from review import service

st.set_page_config(page_title='Prime | Settlement workspace',page_icon='↗',layout='wide')
st.markdown('''<style>
.stApp {background:#f5f7fb;color:#142b43} [data-testid="stSidebar"] {background:#eaf0f5}
[data-testid="stMetric"] {background:white;border:1px solid #dce6ee;border-radius:12px;padding:18px}
h1,h2,h3 {color:#142b43} .block-container {padding-top:4rem;max-width:1500px}
</style>''',unsafe_allow_html=True)
ROOT=Path(os.environ.get('PRIME_DASHBOARD_ROOT',str(CODE/'demo/runtime'))).expanduser().resolve()
try:
    BATCH=latest(ROOT);manifest=json.loads((BATCH/'manifest.json').read_text())
except (OSError,ValueError) as exc:
    st.error('No prepared reporting snapshot. Run the documented demo or private refresh command.');st.stop()


@st.cache_data(show_spinner=False)
def table(batch,name):return read_table(Path(batch),name)


def money(cents):return 'Unavailable' if cents is None else f'${cents/100:,.2f}'
def number(value,fmt=',.0f'):return 'Unavailable' if value is None else format(value,fmt)


st.sidebar.title('PRIME')
st.sidebar.caption('Settlement workspace · Linux')
PAGE=st.sidebar.radio('Workspace',['Business Overview','Freight and Lane History','Data Quality and Sources','Settlement Review Desk'],key='page')
QUALITY=st.sidebar.selectbox('Quality mode',['Preliminary history','Reconciled subset'],key='quality')
DATASET='Synthetic demo' if manifest['synthetic'] else 'Private local history'
st.sidebar.info(DATASET)
st.sidebar.caption('Settlement date basis. This is historical evidence, not current freight offers.')
st.sidebar.caption('Snapshot '+manifest['snapshot_id'])
st.sidebar.caption('Saved '+manifest['created_at'][:19].replace('T',' ')+' UTC')
st.sidebar.caption('Source through '+str(manifest['source_through'])+' · weekly coverage unverified')
loads=table(str(BATCH),'FactLoadLeg');statements=table(str(BATCH),'FactStatement')
known_dates=[r['settlement_date'] for r in statements if r['settlement_date']]
if known_dates:
    start=date.fromisoformat(min(known_dates));end=date.fromisoformat(max(known_dates));default=max(start,end-timedelta(days=730))
    window=st.sidebar.date_input('Settlement date range',(default,end),min_value=start,max_value=end,key='dates')
else:window=()
crew_options=['All']+sorted({r['solo_team_raw'] for r in loads if r['solo_team_raw']})
mode=st.sidebar.selectbox('SOLO / TEAM (raw)',crew_options,index=crew_options.index('SOLO') if 'SOLO' in crew_options else 0,key='crew')
periods=table(str(BATCH),'DimOperatingPeriod');period_names={r['period_id']:r['business_mode']+' · '+r['period_id'] for r in periods}
era=st.sidebar.selectbox('Evidenced operating period',['All']+list(period_names),format_func=lambda v:period_names.get(v,v),key='era')
cohort=[r for r in loads if (len(window)!=2 or (r['settlement_date'] and window[0].isoformat()<=r['settlement_date']<=window[1].isoformat())) and (mode=='All' or r['solo_team_raw']==mode) and (era=='All' or r['period_id']==era)]
metric=metrics(cohort,QUALITY);field='reconciled_rpm_eligible' if QUALITY=='Reconciled subset' else 'preliminary_rpm_eligible'
eligible=[r for r in cohort if r[field]]
st.caption(f'{DATASET}  /  {QUALITY}  /  Settlement dates  /  {metric["eligible_legs"]:,} eligible of {metric["total_legs"]:,} filtered legs · {metric["excluded_legs"]:,} excluded')


def inspect_source(document_id,default_page=1,key='source'):
    db=connect(ROOT,True)
    try:
        s=db.execute('SELECT * FROM v_workbench_statements WHERE document_id=?',(document_id,)).fetchone()
        if not s:st.warning('Source revision no longer present. Review the latest snapshot.');return
        pages=[r[0] for r in db.execute('SELECT page_number FROM source_pages WHERE job_id=? ORDER BY page_number',(s['job_id'],))]
        if not pages:st.warning('No saved source pages.');return
        page=st.selectbox('Original PDF page',pages,index=pages.index(default_page) if default_page in pages else 0,key=key+'_page')
        saved=db.execute('SELECT layout_text FROM source_pages WHERE job_id=? AND page_number=?',(s['job_id'],page)).fetchone()
        st.caption(f'{s["original_filename"]} · page {page} · document {document_id[:16]}')
        left,right=st.columns([1.2,1])
        with right:
            st.caption('Saved extracted text · OCR may be wrong')
            st.text_area('Extracted source text',saved[0],height=480,disabled=True,key=key+'_text')
        with left:
            try:
                path=source_pdf(db,ROOT,document_id)
                image=render_page(str(path),page,document_id)
                st.image(image,caption=f'Original PDF · page {page}',width='stretch')
                st.download_button('Download registered source PDF',path.read_bytes(),file_name=path.name,mime='application/pdf',key=key+'_download')
            except (OSError,ValueError,subprocess.SubprocessError) as exc:st.warning(str(exc))
    finally:db.close()


@st.cache_data(show_spinner=False)
def render_page(path,page,document_id):
    result=subprocess.run(['pdftoppm','-f',str(page),'-l',str(page),'-singlefile','-scale-to','1200','-png',path],capture_output=True,check=True,timeout=30)
    return result.stdout


if PAGE=='Business Overview':
    st.title('Business overview')
    st.write('Candidate dispatch-associated owner revenue, measured against the same eligible miles.')
    cols=st.columns(4)
    for col,label,value in zip(cols,['Candidate owner revenue','Weighted revenue / total mile','Recorded total miles','Empty-mile share'],[money(metric['owner_cents']),('Unavailable' if metric['weighted_rpm'] is None else f'${metric["weighted_rpm"]:.3f}'),number(metric['total_miles']),('Unavailable' if metric['empty_fraction'] is None else f'{metric["empty_fraction"]:.1%}')]):col.metric(label,value)
    if not eligible:st.info('No eligible legs in this cohort. The reconciled subset stays empty until its evidence requirements are met.')
    else:
        frame=pd.DataFrame(eligible)
        weekly=frame.groupby('settlement_date')[['candidate_dispatch_owner_cents','total_miles']].sum()
        weekly['Candidate owner dollars']=weekly['candidate_dispatch_owner_cents']/100
        weekly['Weighted total-mile RPM']=weekly['Candidate owner dollars']/weekly['total_miles']
        a,b=st.columns(2)
        with a:st.subheader('Revenue by settlement date');st.bar_chart(weekly['Candidate owner dollars'],color='#147d86')
        with b:
            st.subheader('Rate by settlement date')
            if len(weekly)==1:st.scatter_chart(weekly['Weighted total-mile RPM'],color='#147d86',size=100)
            else:st.line_chart(weekly['Weighted total-mile RPM'],color='#147d86')
    st.subheader('Settlement cash, kept separate')
    cash=[r for r in statements if r['document_kind']=='owner_recap' and (len(window)!=2 or (r['settlement_date'] and window[0].isoformat()<=r['settlement_date']<=window[1].isoformat()))]
    values=[r['net_due_cents'] for r in cash if r['net_due_cents'] is not None]
    st.metric('Sum of known reported owner net due',money(sum(values) if values else None))
    st.caption(f'{len(values)} of {len(cash)} owner statement documents have a known value. Date filter only; SOLO/TEAM and leg quality filters do not apply to statement cash. Same-date documents remain distinct. Cash due is not bank-confirmed payment or profit.')
    st.info('Operating costs, trip contribution and full-period profit remain unavailable until expense classification, allocation and the payout bridge are reconciled.')
    if cash:
        chosen=st.selectbox('Inspect a statement',cash,format_func=lambda r:f'{r["settlement_date"]} · unit {r["unit_code"]} · {r["statement_id"][:10]}',key='statement')
        with st.expander('Statement and original source'):st.json(chosen);inspect_source(chosen['document_id'])

elif PAGE=='Freight and Lane History':
    st.title('Freight and lane history')
    st.write('Compare historical pickup and delivery areas. Raw labels remain visible; unverified cities are not facilities.')
    origins={r['place_id']:r['raw_label'] for r in table(str(BATCH),'DimOrigin')};destinations={r['place_id']:r['raw_label'] for r in table(str(BATCH),'DimDestination')}
    search=st.text_input('Search raw pickup or destination',key='lane_search').strip().casefold()
    minimum=st.number_input('Minimum observed legs per lane',min_value=1,max_value=100,value=3,step=1)
    st.caption('Minimum sample is a display rule, not a statistical-confidence guarantee.')
    groups={}
    for r in eligible:
        label=(origins[r['origin_id']],destinations[r['destination_id']])
        if search and search not in ' '.join(label).casefold():continue
        groups.setdefault(label,[]).append(r)
    rows=[]
    for (origin,destination),group in groups.items():
        if len(group)<minimum:continue
        m=metrics(group,QUALITY);rates=[r['candidate_dispatch_owner_cents']/100/r['total_miles'] for r in group]
        rows.append({'Pickup (raw)':origin,'Destination (raw)':destination,'Legs':len(group),'Weighted RPM':m['weighted_rpm'],'Median RPM':statistics.median(rates),'Minimum RPM':min(rates),'Maximum RPM':max(rates),'Empty share':m['empty_fraction'],'Last settlement':max(r['settlement_date'] for r in group)})
    if rows:st.dataframe(pd.DataFrame(rows).sort_values('Weighted RPM',ascending=False),hide_index=True,width='stretch')
    else:st.info('No lanes meet these filters and the minimum sample. Reduce the threshold or broaden the period explicitly.')
    st.subheader('Contributing and excluded legs')
    st.dataframe(pd.DataFrame(cohort),hide_index=True,width='stretch')
    if cohort:
        chosen=st.selectbox('Inspect a leg',cohort,format_func=lambda r:f'{r["settlement_date"]} · {r["order_key"]}/{r["dispatch_key"]} · {r["leg_id"][:10]}')
        with st.expander('Leg evidence'):st.json(chosen);inspect_source(chosen['statement_id'],chosen['page_number'],'leg_source')

elif PAGE=='Data Quality and Sources':
    st.title('Know what the data can support')
    st.write('Source coverage, arithmetic checks and full reconciliation are separate measures.')
    a,b,c,d=st.columns(4)
    for col,label,value in [(a,'Source documents',manifest['source_documents']),(b,'Extracted pages',manifest['extracted_pages']),(c,'Statement documents',len(statements)),(d,'Candidate postings',manifest['table_counts']['FactPosting'])]:col.metric(label,f'{value:,}')
    st.caption('Coverage counts describe the full snapshot. Filtered leg counts and quality mode appear above.')
    st.warning('Historical financial import is incomplete. Missing-week classification and verified financial data-through remain unresolved; an absent document is never assumed to be a zero-revenue week.')
    st.json({'arithmetic_checks':manifest['quality_counts'],'verified_financial_data_through':manifest['verified_financial_data_through'],'cohort_exclusions':metric['excluded_legs']})
    issues=table(str(BATCH),'FactReviewIssue');kinds=st.multiselect('Issue types',sorted({r['issue_kind'] for r in issues}))
    shown=[r for r in issues if (not kinds or r['issue_kind'] in kinds) and (len(window)!=2 or (r['settlement_date'] and window[0].isoformat()<=r['settlement_date']<=window[1].isoformat()))]
    st.caption(f'{len(shown):,} issue records after date/type filters. Issues are not counts of missing weeks or bad loads.')
    st.dataframe(pd.DataFrame(shown),hide_index=True,width='stretch')
    with st.expander('Snapshot manifest and limitations'):st.json(manifest)

else:
    st.title('Settlement Review Desk')
    st.write('Inspect the original source, record a decision, and follow its actual application status.')
    with st.expander('What this desk can apply'):
        st.write('Defer preserves a note. Category confirmation/rejection creates a versioned record-level classification; it does not recalculate freight or costs. Facility confirmation creates evidence-backed references and a versioned mapping for the selected invoice party. Numeric/date corrections are pending proposals for the source-image importer. Recording any decision does not reconcile a whole settlement.')
        st.write('Use stable organization and facility keys of your choosing. Two plants use different facility keys under one organization key. Existing facility evidence is immutable here: a changed address needs a new version key. Reviewer names are local labels, not authenticated enterprise identities.')
    issues=table(str(BATCH),'FactReviewIssue');records={r['record_id']:r for r in table(str(BATCH),'SourceRecord')}
    kind=st.selectbox('Queue type',['All']+sorted({r['issue_kind'] for r in issues}),key='queue_type')
    text=st.text_input('Search queue',key='queue_search').casefold()
    queue=[r for r in issues if (kind=='All' or r['issue_kind']==kind) and (not text or text in (r['description']+' '+r['statement_id']).casefold()) and (len(window)!=2 or (r['settlement_date'] and window[0].isoformat()<=r['settlement_date']<=window[1].isoformat()))]
    queue.sort(key=lambda r:(r['difference_integer'] is None,-abs(r['difference_integer'] or 0),r['issue_kind'],r['statement_id']))
    st.caption(f'{len(queue):,} issues in this date/type/search queue. Sorted by known absolute difference, then type; unknown differences receive no invented severity. Leg quality/SOLO filters do not hide source issues.')
    if not queue:st.info('No review issues match these filters.');st.stop()
    selected=st.selectbox('Review item',queue,format_func=lambda r:f'{r["settlement_date"]} · {r["issue_kind"]} · {r["description"][:85]} · {r["record_id"][:8]}',key='review_item')
    record=records[selected['record_id']]
    with st.expander('Original value and stable source identity',expanded=True):st.json(json.loads(record['original_json']));st.caption('Record '+record['record_id']+' · revision '+record['source_revision'][:16])
    inspect_source(record['document_id'],selected['page_number'] or 1,'review_source_'+record['record_id'])
    action=st.selectbox('Decision',['defer','confirm_category','reject_category','facility_mapping','numeric_correction','date_correction'],format_func=lambda x:x.replace('_',' ').title(),key='action')
    token_key='request_'+record['record_id']
    if token_key not in st.session_state:st.session_state[token_key]=str(uuid.uuid4())
    with st.form('decision_form'):
        proposed={}
        if action in ('confirm_category','reject_category'):proposed['category']=st.selectbox('Category',service.CATEGORIES)
        elif action=='facility_mapping':
            c1,c2=st.columns(2)
            for col,names in [(c1,('organization_key','organization_name','facility_key','facility_name')),(c2,('street_address','city','state_province','postal_code'))]:
                with col:
                    for name in names:proposed[name]=st.text_input(name.replace('_',' ').title())
            original=json.loads(record['original_json']);proposed['role']=original.get('role_candidate','other')
            st.caption('Selected party role: '+proposed['role'])
        elif action=='numeric_correction':proposed['integer_cents']=int(st.number_input('Proposed signed integer cents',value=0,step=1))
        elif action=='date_correction':proposed['iso_date']=st.date_input('Proposed date',date.today()).isoformat()
        reviewer=st.text_input('Local reviewer label',value='Local operator')
        reason=st.text_area('Reason for decision')
        evidence=st.text_input('Evidence reference',value=f'{record["source_filename"]}, page {selected["page_number"] or 1}')
        save=st.form_submit_button('Record decision',type='primary')
    if save:
        try:
            result=service.submit(ROOT,record,action,proposed,reason,evidence,reviewer,st.session_state[token_key]);st.session_state['last_decision']=result['decision_id'];st.success(result['state']+': '+result['detail'])
        except (ValueError,OSError) as exc:st.error(str(exc))
    if st.button('Start another decision for this record'):
        st.session_state[token_key]=str(uuid.uuid4());st.info('A new request ID is ready. Prior decisions remain in history.')
    entries=service.history(ROOT,record['record_id'])
    if entries:
        latest_ids=list(dict.fromkeys(r['decision_id'] for r in entries))
        choice=st.selectbox('Decision application',latest_ids,format_func=lambda x:f'{x[:8]} · {service.get(ROOT,x)["state"]}')
        decision=service.get(ROOT,choice);st.info(decision['state']+': '+decision['detail'])
        if decision['action'] in ('confirm_category','reject_category','facility_mapping') and decision['state'] in ('Ready to apply','Failed'):
            if st.button('Apply supported mapping and revalidate',type='primary'):
                with st.spinner('Checking source revision, backing up and validating…'):outcome=service.apply(ROOT,choice)
                if outcome['state']=='Applied and revalidated':st.success(outcome['detail']);st.cache_data.clear();st.rerun()
                else:st.error(outcome['state']+': '+outcome['detail'])
        st.subheader('Decision and application history')
        st.dataframe(pd.DataFrame([{k:r[k] for k in ('decision_id','action','reviewer','reason','state','detail','event_at')} for r in entries]),hide_index=True,width='stretch')
        with st.expander('Original, proposed and validation records'):st.json(entries)
    else:st.caption('No saved decisions for this source record yet.')
