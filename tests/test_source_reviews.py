"""Synthetic regression coverage for uncoded deductions and audited transcriptions."""
import json
from pathlib import Path
import sqlite3
import sys
import unittest

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE))
from prime_structure import uncoded_deduction
from prime_review import review_inputs, apply_total_review


def word(text,x,width=30):
    return [1,text,x,30,width,20,95,1,1,1]


class DeductionTests(unittest.TestCase):
    def test_uncoded_fund_and_replacement_check(self):
        for desc in ('EFUND PO§:1234567','ADV EMERG FUND PO#:1234567','REPLACE CK 12345678 PO#:1234567'):
            words=[word(desc,20,500),word('.00',660),word('123.45',720)]
            self.assertEqual(uncoded_deduction(words,words,1000,'deduction'),desc)
            self.assertIsNone(uncoded_deduction(words,words,1000,'reimbursement'))

    def test_prose_and_missing_money_are_not_postings(self):
        for desc in ('Please pay EFUND PO#:1234567','TOTAL EFUND PO#:1234567','EFUND PO#:'):
            words=[word(desc,20,500),word('.00',660),word('123.45',720)]
            self.assertIsNone(uncoded_deduction(words,words,1000,'deduction'))
        words=[word('EFUND PO#:1234567',20,500)]
        self.assertIsNone(uncoded_deduction(words,words,1000,'deduction'))

    def test_conflicting_money_does_not_become_a_balancing_entry(self):
        words=[word('EFUND PO#:1234567',20,500),word('.00',660),word('123.45',720)]
        numeric=[word('.00',660),word('128.45',720)]
        self.assertIsNone(uncoded_deduction(words,numeric,1000,'deduction'))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''CREATE TABLE source_pages(job_id TEXT,page_number INTEGER,text_sha256 TEXT,PRIMARY KEY(job_id,page_number));
            CREATE TABLE structured_runs(parse_id TEXT PRIMARY KEY);
            INSERT INTO source_pages VALUES('job',2,'pagehash');''')
        self.db.executescript((CODE/'sql/005_source_reviews.sql').read_text())
        self.add('first',12345,'2026-01-01')

    def tearDown(self):
        self.db.close()

    def add(self,rid,value,created):
        self.db.execute('INSERT INTO source_field_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (rid,'job',2,'gross_due','GROSS AMOUNT DUE UNIT: 123.45','pagehash',json.dumps(value),'{}','synthetic reviewer','source image',created))

    def test_exact_field_page_and_line_only(self):
        reviews,_=review_inputs(self.db,'job')
        ev={'state':'agreement','general_raw':'128.45','numeric_raw':'128.45'}
        value,out=apply_total_review(reviews,2,'GROSS AMOUNT DUE UNIT: 123.45','gross_due',12845,ev)
        self.assertEqual(value,12345)
        self.assertEqual(out['pre_review_value'],12845)
        self.assertEqual(out['general_raw'],'128.45')
        self.assertEqual(out['review_id'],'first')
        self.assertEqual(apply_total_review(reviews,3,'GROSS AMOUNT DUE UNIT: 123.45','gross_due',12845,ev),(12845,ev))

    def test_superseding_review_changes_signature_preserves_history(self):
        _,old_hash=review_inputs(self.db,'job')
        self.add('second',12346,'2026-01-02')
        rows,new_hash=review_inputs(self.db,'job')
        self.assertNotEqual(old_hash,new_hash)
        self.assertEqual([r['review_id'] for r in rows],['second'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_field_reviews').fetchone()[0],2)

    def test_changed_source_and_ledger_mutations_fail(self):
        for query in ('DELETE FROM source_field_reviews',"UPDATE source_field_reviews SET value_json='0'"):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(query)
        self.db.execute("UPDATE source_pages SET text_sha256='changed'")
        with self.assertRaises(ValueError):review_inputs(self.db,'job')

    def test_other_job_cannot_inherit_review(self):
        rows,_=review_inputs(self.db,'another-job')
        self.assertEqual(rows,[])


if __name__=='__main__':unittest.main()
