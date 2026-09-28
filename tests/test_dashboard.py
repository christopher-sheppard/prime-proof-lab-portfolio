"""End-to-end synthetic acceptance checks for reporting and the local review desk."""
import csv
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

CODE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(CODE))
from demo.generate import generate
from analytics.reporting import collect,export,metrics,read_table,latest
from analytics.records import resolve,source_pdf
from prime_structure import connect
from review import service


class Dataset(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);generate(self.root)
        db=connect(self.root,True)
        try:self.tables,self.info=collect(db)
        finally:db.close()

    def tearDown(self):self.tmp.cleanup()

    def record(self,kind='party'):
        return next(r for r in self.tables['SourceRecord'] if r['record_kind']==kind)

    def decision(self,record=None,action='confirm_category',value=None,request='request-one'):
        return service.submit(self.root,record or self.record(),action,value or {'category':'freight_compensation'},'Synthetic review rationale','Fictional PDF source','Test reviewer',request)

    def mapping(self,key='north'):
        return {'organization_key':'products','organization_name':'Example Products','facility_key':key,'facility_name':key.title()+' Plant','street_address':'100 Fictional Road','city':'Sample City','state_province':'ZZ','postal_code':'00000','role':json.loads(self.record()['original_json'])['role_candidate']}


class MetricTests(Dataset):
    def test_weighted_unequal_distances_and_exclusions(self):
        result=metrics(self.tables['FactLoadLeg'])
        self.assertEqual(result['eligible_legs'],2);self.assertEqual(result['owner_cents'],40000)
        self.assertEqual(result['total_miles'],300);self.assertAlmostEqual(result['weighted_rpm'],4/3)
        self.assertNotEqual(result['weighted_rpm'],1.25)
        unknown=next(r for r in self.tables['FactLoadLeg'] if r['order_key']=='UNKNOWN')
        self.assertIsNone(unknown['empty_miles']);self.assertFalse(unknown['preliminary_rpm_eligible'])

    def test_repower_zero_and_approval_are_preserved_but_excluded(self):
        legs=self.tables['FactLoadLeg']
        self.assertEqual(len(legs),7)
        for r in legs:
            if r['order_key'] in ('REPOWER','ZERO','ANNOTATION'):self.assertFalse(r['preliminary_rpm_eligible'])
        self.assertEqual(sum(r['order_key']=='REPOWER' for r in legs),2)

    def test_same_date_different_units_and_duplicate_revision(self):
        self.assertEqual(len(self.tables['FactStatement']),2)
        self.assertEqual(len({r['unit_code'] for r in self.tables['FactStatement']}),2)
        self.assertNotIn('old-demo-parse',[r['source_revision'] for r in self.tables['FactStatement']])

    def test_multistop_and_invoice_repetition_do_not_multiply(self):
        self.assertEqual(len([r for r in self.tables['SourceRecord'] if r['record_kind']=='party']),12)
        self.assertEqual(metrics(self.tables['FactLoadLeg'])['owner_cents'],40000)
        self.assertEqual(metrics(self.tables['FactLoadLeg'])['total_miles'],300)

    def test_trainee_gross_is_not_owner_cost_and_cash_is_separate(self):
        first=self.tables['FactStatement'][0]['statement_id']
        postings=[r for r in self.tables['FactPosting'] if r['statement_id']==first]
        self.assertEqual(sum(r['amount_cents'] for r in postings if r['section']=='wage_expense'),20000)
        self.assertNotIn(90000,[r['amount_cents'] for r in postings])
        self.assertTrue(any(r['description_raw']=='RESERVE RELEASE' and r['economic_category'] is None for r in postings))

    def test_empty_and_reconciled_stay_empty(self):
        for rows,mode in [([], 'Preliminary history'),(self.tables['FactLoadLeg'],'Reconciled subset')]:
            result=metrics(rows,mode);self.assertIsNone(result['weighted_rpm']);self.assertIsNone(result['owner_cents'])

    def test_sql_csv_json_repeated_export_and_snapshot_restore(self):
        a=export(self.root);b=export(self.root)
        for name in self.tables:self.assertEqual(read_table(a,name),read_table(b,name))
        db=sqlite3.connect(b/'reporting.sqlite')
        expected=db.execute('SELECT sum(candidate_dispatch_owner_cents),sum(total_miles) FROM FactLoadLeg WHERE preliminary_rpm_eligible=1').fetchone();db.close()
        self.assertEqual(expected,(40000,300))
        with (b/'FactLoadLeg.csv').open() as f:rows=list(csv.DictReader(f))
        self.assertEqual(sum(int(r['candidate_dispatch_owner_cents']) for r in rows if r['preliminary_rpm_eligible']=='1'),40000)
        unknown=next(r for r in rows if r['order_key']=='UNKNOWN');self.assertEqual(unknown['empty_miles'],'')
        restored=self.root/'restored.sqlite';shutil.copyfile(b/'source.sqlite',restored)
        db=sqlite3.connect(restored);db.row_factory=sqlite3.Row
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        tables,_=collect(db);db.close();self.assertEqual(metrics(tables['FactLoadLeg'])['owner_cents'],40000)

    def test_generator_is_deterministic_and_rerun_safe(self):
        before=[r['document_id'] for r in self.tables['FactStatement']];generate(self.root)
        other=self.root/'independent';generate(other);db=connect(other,True)
        tables,_=collect(db);db.close();self.assertEqual(before,[r['document_id'] for r in tables['FactStatement']])


class ReviewTests(Dataset):
    def test_reparse_preserves_stable_identity_but_rejects_old_revision(self):
        record=self.record('check');decision=self.decision(record)
        db=connect(self.root)
        s=db.execute('SELECT * FROM v_workbench_statements WHERE document_id=?',(record['document_id'],)).fetchone()
        with db:
            db.execute('INSERT INTO structured_runs VALUES (?,?,?,?,?,?)',('new-reparse',s['job_id'],'synthetic-next','next-code','2099-01-01','complete'))
            db.execute('INSERT INTO statement_candidates SELECT ?,document_kind,settlement_date,owner_code,owner_name,unit_code,header_evidence_json,review_status FROM statement_candidates WHERE parse_id=?',('new-reparse',s['parse_id']))
            db.execute('INSERT INTO reconciliation_checks SELECT check_id||?, ?,check_name,status,calculated_integer,reported_integer,difference_integer,unit,detail FROM reconciliation_checks WHERE parse_id=?',('-new','new-reparse',s['parse_id']))
        current=resolve(db,json.loads(record['reference_json']));db.close()
        self.assertEqual(current['record_id'],record['record_id']);self.assertNotEqual(current['source_revision'],record['source_revision'])
        self.assertEqual(service.apply(self.root,decision['decision_id'],publish=False)['state'],'Conflict')

    def test_persistence_duplicate_and_request_collision(self):
        r=self.decision();again=self.decision();self.assertEqual(r['decision_id'],again['decision_id'])
        self.assertEqual(service.get(self.root,r['decision_id'])['state'],'Ready to apply')
        self.assertEqual(len(service.history(self.root)),1)
        with self.assertRaises(ValueError):self.decision(value={'category':'maintenance'})

    def test_proposals_and_defer_never_claim_applied(self):
        for action,value in [('defer',{}),('numeric_correction',{'integer_cents':12345}),('date_correction',{'iso_date':'2026-09-19'})]:
            r=self.decision(action=action,value=value,request=action)
            self.assertEqual(r['state'],'Recorded')
            with self.assertRaises(ValueError):service.apply(self.root,r['decision_id'],publish=False)

    def test_stale_value_and_reparse_rejected(self):
        record=self.record();decision=self.decision(record)
        db=connect(self.root)
        with db:db.execute("UPDATE invoice_party_candidates SET name_raw='Changed source'")
        db.close()
        self.assertEqual(service.apply(self.root,decision['decision_id'],publish=False)['state'],'Conflict')
        new=self.decision(record,request='stale-at-submit');self.assertEqual(new['state'],'Conflict')

    def test_two_plants_one_organization_and_versioned_mapping(self):
        record=self.record();d=self.decision(record,'facility_mapping',self.mapping('north'))
        self.assertEqual(service.apply(self.root,d['decision_id'],publish=False)['state'],'Applied and revalidated')
        db=connect(self.root,True);current=resolve(db,json.loads(record['reference_json']));db.close()
        d2=self.decision(current,'facility_mapping',self.mapping('south'),request='south')
        self.assertEqual(service.apply(self.root,d2['decision_id'],publish=False)['state'],'Applied and revalidated')
        db=connect(self.root,True)
        self.assertEqual(db.execute('SELECT count(*) FROM organizations').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM facilities').fetchone()[0],2)
        self.assertEqual(db.execute('SELECT count(*) FROM desk_facility_mapping_versions').fetchone()[0],2);db.close()

    def test_validation_failure_rolls_back_and_retry_succeeds(self):
        d=self.decision(action='facility_mapping',value=self.mapping())
        result=service.apply(self.root,d['decision_id'],publish=False,failpoint='validation');self.assertEqual(result['state'],'Failed')
        db=connect(self.root,True)
        self.assertEqual(db.execute('SELECT count(*) FROM desk_applied_changes').fetchone()[0],0)
        self.assertEqual(db.execute('SELECT count(*) FROM facilities').fetchone()[0],0)
        tables,_=collect(db);db.close();self.assertEqual(metrics(tables['FactLoadLeg'])['owner_cents'],40000)
        self.assertEqual(service.apply(self.root,d['decision_id'],publish=False)['state'],'Applied and revalidated')

    def test_crash_after_commit_recovers_by_unique_decision_id(self):
        d=self.decision()
        with self.assertRaises(SystemExit):service.apply(self.root,d['decision_id'],publish=False,failpoint='after_commit')
        self.assertEqual(service.get(self.root,d['decision_id'])['state'],'Ready to apply')
        result=service.apply(self.root,d['decision_id'],publish=False);self.assertEqual(result['state'],'Applied and revalidated')
        self.assertEqual(service.apply(self.root,d['decision_id'],publish=False),result)
        db=connect(self.root,True);self.assertEqual(db.execute('SELECT count(*) FROM desk_applied_changes').fetchone()[0],1);db.close()

    def test_snapshot_publication_failure_keeps_prior_batch_then_recovers(self):
        prior=export(self.root);d=self.decision()
        with patch('analytics.reporting.export',side_effect=OSError('synthetic disk failure')):
            self.assertEqual(service.apply(self.root,d['decision_id'])['state'],'Failed')
        self.assertEqual(latest(self.root),prior)
        self.assertEqual(service.apply(self.root,d['decision_id'])['state'],'Applied and revalidated')
        self.assertNotEqual(latest(self.root),prior)

    def test_missing_pdf_preserves_history_and_blocks_apply(self):
        r=self.record();d=self.decision(r);db=connect(self.root,True);pdf=source_pdf(db,self.root,r['document_id']);db.close();pdf.unlink()
        self.assertEqual(service.apply(self.root,d['decision_id'],publish=False)['state'],'Failed')
        self.assertEqual(len(service.history(self.root,r['record_id'])),2)

    def test_source_path_traversal_rejected(self):
        r=self.record();db=connect(self.root)
        with db:db.execute("UPDATE source_occurrences SET relative_path='../../outside.pdf' WHERE document_id=?",(r['document_id'],))
        with self.assertRaises(FileNotFoundError):source_pdf(db,self.root,r['document_id'])
        db.close()


class ScreenTests(Dataset):
    def test_all_four_pages_with_empty_reporting_dataset(self):
        from streamlit.testing.v1 import AppTest
        from analytics.reporting import SCHEMA,write_tables
        batch=self.root/'reporting/empty';batch.mkdir(parents=True)
        write_tables(batch,{k:[] for k in SCHEMA})
        (batch/'manifest.json').write_text(json.dumps({**self.info,'snapshot_id':'empty','source_through':None,'source_documents':0,'extracted_pages':0,'created_at':'2026-09-27T00:00:00Z','table_counts':{k:0 for k in SCHEMA},'quality_counts':{}}))
        (self.root/'reporting/latest.json').write_text(json.dumps({'snapshot_id':'empty'}))
        with patch.dict(os.environ,{'PRIME_DASHBOARD_ROOT':str(self.root)}):
            app=AppTest.from_file(str(CODE/'dashboard/app.py'),default_timeout=30).run()
            self.assertEqual(app.metric[0].value,'Unavailable')
            for page in ('Business Overview','Freight and Lane History','Data Quality and Sources','Settlement Review Desk'):
                app.radio(key='page').set_value(page).run();self.assertEqual(len(app.exception),0)

    def test_all_four_pages_and_reconciled_empty(self):
        from streamlit.testing.v1 import AppTest
        export(self.root)
        with patch.dict(os.environ,{'PRIME_DASHBOARD_ROOT':str(self.root)}):
            app=AppTest.from_file(str(CODE/'dashboard/app.py'),default_timeout=30).run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(app.metric[1].value,'$1.333')
            app.selectbox(key='quality').set_value('Reconciled subset').run();self.assertEqual(app.metric[1].value,'Unavailable')
            for page in ('Freight and Lane History','Data Quality and Sources','Settlement Review Desk'):
                app.radio(key='page').set_value(page).run();self.assertEqual(len(app.exception),0)
            app.text_area[1].set_value('Synthetic UI persistence test')
            app.button[0].click().run();self.assertEqual(len(app.exception),0)
            self.assertEqual(len(service.history(self.root)),1)
            restarted=AppTest.from_file(str(CODE/'dashboard/app.py'),default_timeout=30).run()
            restarted.radio(key='page').set_value('Settlement Review Desk').run();self.assertEqual(len(restarted.exception),0)
            self.assertTrue(any('Deferred' in v.value for v in restarted.info))


if __name__=='__main__':unittest.main()
