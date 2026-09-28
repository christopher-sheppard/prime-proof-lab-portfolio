"""Regression checks for important financial-reading failure modes; no private data."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prime_structure import numeric_cell, strict_number, date_candidate, page_kind


def word(text,x=720):return [1,text,x,30,35,20,95,1,1,1]


class FinancialEvidenceTests(unittest.TestCase):
    def test_credit_signs_survive(self):
        for raw in ('12.34-','-12.34','(12.34)','12.34\u2014'):
            self.assertEqual(strict_number(raw,2)[0],-1234)

    def test_missing_is_not_zero(self):
        self.assertIsNone(numeric_cell([],[],1000,.7,.8)[0])
        self.assertEqual(numeric_cell([word('.00')],[word('.00')],1000,.7,.8)[0],0)

    def test_conflicting_readings_are_not_chosen_for_convenience(self):
        value,evidence=numeric_cell([word('8.82')],[word('3.32')],1000,.7,.8)
        self.assertIsNone(value)
        self.assertEqual(evidence['state'],'disagreement')
        self.assertEqual((evidence['general_candidate'],evidence['numeric_candidate']),(882,332))

    def test_single_reader_is_explicit(self):
        value,evidence=numeric_cell([word('8.?2')],[word('8.72')],1000,.7,.8)
        self.assertEqual(value,872)
        self.assertEqual(evidence['state'],'numeric_only')

    def test_no_invented_punctuation_or_merged_amounts(self):
        for raw in ('1234','1,23.45','12.34 56.78','8?82','1.57-+'):
            self.assertIsNone(strict_number(raw,2)[0])

    def test_zero_letter_normalization_is_recorded(self):
        value,evidence=numeric_cell([word('1O.00')],[word('10.00')],1000,.7,.8)
        self.assertEqual(value,1000)
        self.assertEqual(evidence['state'],'normalized_agreement')
        self.assertEqual(evidence['normalizations'],['O_to_0_in_numeric_cell'])

    def test_dates_are_not_shifted_to_friday(self):
        self.assertEqual(date_candidate('26f09f18'),'2026-09-18')
        self.assertEqual(date_candidate('26/09/19'),'2026-09-19')
        self.assertIsNone(date_candidate('26/19/18'))
        self.assertIsNone(date_candidate('26/09/1?'))

    def test_employee_year_to_date_summary_is_not_owner_revenue(self):
        for pay in ('PAY','RAY'):
            sample=f'SETTLEMENT DATE: 18f06f29\nEARNINGS:\nTAXES:\nYTD\nSICK {pay} HRS ACCRUED'
            self.assertEqual(page_kind(sample),'employee_payroll_summary')
        self.assertEqual(page_kind('SETTLEMENT DATE:26/09/18\nFLATBED DIV\nOWNER TEST\nREVENUE SECTION'),'owner_recap')

    def test_neighboring_column_is_not_added_to_amount(self):
        value,evidence=numeric_cell([word('10.00'),word('25.00',800)],[word('10.00'),word('25.00',800)],1000,.7,.8)
        self.assertEqual(value,1000)
        self.assertEqual(evidence['general_raw'],'10.00')


if __name__=='__main__':unittest.main()
