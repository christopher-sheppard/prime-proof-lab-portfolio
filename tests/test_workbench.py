"""Synthetic regression tests; these fixtures contain no private financial data."""
import sqlite3
import sys
from pathlib import Path
import unittest

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))
from prime_structure import numeric_cell, strict_number, date_candidate, page_kind, numeric_header_date


def word(text, x=720):
    return [1, text, x, 30, 35, 20, 95, 1, 1, 1]


class ReadingTests(unittest.TestCase):
    def test_credit_signs(self):
        for raw in ('12.34-', '-12.34', '(12.34)', '12.34\u2014'):
            self.assertEqual(strict_number(raw, 2)[0], -1234)

    def test_missing_is_not_zero(self):
        self.assertIsNone(numeric_cell([], [], 1000, .7, .8)[0])
        self.assertEqual(numeric_cell([word('.00')], [word('.00')], 1000, .7, .8)[0], 0)

    def test_conflicting_digits_stay_unknown(self):
        value, evidence = numeric_cell([word('8.82')], [word('3.32')], 1000, .7, .8)
        self.assertIsNone(value)
        self.assertEqual(evidence['state'], 'disagreement')

    def test_no_invented_decimal_or_joined_amount(self):
        for raw in ('1234', '1,23.45', '12.34 56.78', '8?82', '1.57-+'):
            self.assertIsNone(strict_number(raw, 2)[0])

    def test_column_boundaries(self):
        self.assertEqual(numeric_cell([word('10.00'), word('25.00', 800)], [word('10.00'), word('25.00', 800)], 1000, .7, .8)[0], 1000)

    def test_letter_normalization_has_evidence(self):
        value, evidence = numeric_cell([word('lO.00')], [word('10.00')], 1000, .7, .8)
        self.assertEqual(value, 1000)
        self.assertEqual(evidence['state'], 'normalized_agreement')
        self.assertIn('I_or_l_to_1_in_numeric_cell', evidence['normalizations'])

    def test_dates_are_never_shifted_to_friday(self):
        self.assertEqual(date_candidate('26/09/19'), '2026-09-19')
        self.assertIsNone(date_candidate('26/19/18'))
        self.assertEqual(date_candidate('ZlfO6fl8'), '2021-06-18')

    def test_numeric_header_requires_compatible_known_digits(self):
        self.assertIsNone(numeric_header_date('26/09/18', '26109119'))
        self.assertEqual(numeric_header_date('26/09/1?', '26109118'), '2026-09-18')
        self.assertIsNone(numeric_header_date('unreadable', '26109118'))

    def test_supporting_tolls_do_not_supply_owner_dates(self):
        self.assertEqual(page_kind('SETTLEMENT DATE:26/09/18\nPREPASS BILL'), 'toll_detail')
        self.assertEqual(page_kind('SETTLEMENT DATE:26/09/18\nFLATBED  DIV\nREVENUE SECTION'), 'owner_recap')
        self.assertEqual(page_kind('SETTLEMENT DATE:18/06/29\nEARNINGS:\nTAXES:\nYTD\nSICK PAY HRS ACCRUED'), 'employee_payroll_summary')


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE statements(parse_id TEXT,document_id TEXT,job_id TEXT,original_filename TEXT,settlement_date TEXT,owner_code TEXT,unit_code TEXT,document_kind TEXT,mismatched_checks INTEGER,incomplete_checks INTEGER);
        CREATE VIEW v_settlement_review AS SELECT * FROM statements;
        CREATE TABLE settlement_posting_candidates(posting_id TEXT,parse_id TEXT,section TEXT,code_raw TEXT,order_raw TEXT,dispatch_raw TEXT,amount_cents INTEGER);
        CREATE TABLE source_line_candidates(line_id TEXT,page_number INTEGER,line_number INTEGER);
        CREATE TABLE load_leg_candidates(leg_id TEXT,parse_id TEXT,order_raw TEXT,dispatch_raw TEXT,loaded_miles INTEGER,empty_miles INTEGER,total_miles INTEGER,mileage_check TEXT);
        CREATE TABLE route_point_candidates(leg_id TEXT,sequence INTEGER,city_raw TEXT,state_raw TEXT,following_segment_marker TEXT);
        CREATE TABLE reconciliation_checks(parse_id TEXT,status TEXT,check_name TEXT,difference_integer INTEGER,unit TEXT);
        CREATE TABLE structured_issues(parse_id TEXT,issue_kind TEXT,page_number INTEGER,detail TEXT);
        CREATE TABLE structured_runs(job_id TEXT,status TEXT,created_at TEXT);
        CREATE TABLE statement_total_candidates(parse_id TEXT,metric TEXT,unit TEXT,value_integer INTEGER);
        CREATE TABLE page_classifications(parse_id TEXT,page_number INTEGER,page_kind TEXT);
        CREATE TABLE source_pages(job_id TEXT,page_number INTEGER,layout_text TEXT);
        INSERT INTO statements VALUES('p','d','j','synthetic.pdf','2026-09-18','DEMO','1','owner_recap',0,0);
        INSERT INTO source_line_candidates VALUES('rv',1,1),('fs',1,2);
        INSERT INTO settlement_posting_candidates VALUES('rv','p','revenue','RV','001','01',10000),('fs','p','revenue','FS','001','01',2000);
        INSERT INTO load_leg_candidates VALUES('rv','p','001','01',100,20,120,'match');
        INSERT INTO route_point_candidates VALUES('rv',1,'Empty start','CA','E'),('rv',2,'Pickup','CA','L'),('rv',3,'Delivery','AZ',NULL);
        INSERT INTO reconciliation_checks VALUES('p','match','revenue_sum',0,'cents');
        INSERT INTO statement_total_candidates VALUES('p','revenue_total','cents',12000),('p','total_miles_total','miles',120);
        ''')
        self.db.executescript((CODE / 'sql/004_workbench.sql').read_text())

    def tearDown(self):
        self.db.close()

    def test_stop_join_does_not_multiply_revenue(self):
        rows = self.db.execute('SELECT * FROM v_load_economics').fetchall()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r['allocated_owner_revenue_cents'], 12000)
        self.assertEqual(r['owner_revenue_per_total_mile'], 1.0)
        self.assertEqual(r['owner_revenue_per_loaded_mile'], 1.2)
        self.assertEqual(r['origin_city_raw'], 'Pickup')
        self.assertEqual(r['rate_quality'], 'arithmetic_checked_unverified')

    def test_unknown_accessorial_prevents_partial_revenue_sum(self):
        self.db.execute("UPDATE settlement_posting_candidates SET amount_cents=NULL WHERE posting_id='fs'")
        r = self.db.execute('SELECT * FROM v_load_economics').fetchone()
        self.assertIsNone(r['allocated_owner_revenue_cents'])
        self.assertEqual(r['rate_quality'], 'incomplete')
        self.assertEqual(self.db.execute('SELECT count(*) FROM v_lane_history').fetchone()[0], 0)

    def test_multiple_legs_are_not_each_allocated_full_dispatch_revenue(self):
        self.db.executescript("INSERT INTO source_line_candidates VALUES('rv2',1,4); INSERT INTO settlement_posting_candidates VALUES('rv2','p','revenue','RV','001','01',3000); INSERT INTO load_leg_candidates VALUES('rv2','p','001','01',20,0,20,'match');")
        rows = self.db.execute('SELECT * FROM v_load_economics').fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['allocated_owner_revenue_cents'] is None for r in rows))

    def test_conflicting_repeated_totals_stay_unknown(self):
        self.db.execute("INSERT INTO statement_total_candidates VALUES('p','revenue_total','cents',13000)")
        self.assertIsNone(self.db.execute('SELECT revenue_cents FROM v_weekly_settlements').fetchone()[0])

    def test_zero_miles_has_no_rate(self):
        self.db.execute('UPDATE load_leg_candidates SET total_miles=0')
        r = self.db.execute('SELECT * FROM v_load_economics').fetchone()
        self.assertIsNone(r['owner_revenue_per_total_mile'])
        self.assertEqual(r['rate_quality'], 'incomplete')

    def test_lane_rate_is_weighted(self):
        self.db.executescript("INSERT INTO source_line_candidates VALUES('rv2',1,4); INSERT INTO settlement_posting_candidates VALUES('rv2','p','revenue','RV','002','01',12000); INSERT INTO load_leg_candidates VALUES('rv2','p','002','01',50,10,60,'match'); INSERT INTO route_point_candidates VALUES('rv2',1,'Pickup','CA','L'),('rv2',2,'Delivery','AZ',NULL);")
        r = self.db.execute('SELECT * FROM v_lane_history').fetchone()
        self.assertEqual(r['candidate_load_legs'], 2)
        self.assertEqual(r['weighted_revenue_per_total_mile'], 1.333)


if __name__ == '__main__':
    unittest.main()
