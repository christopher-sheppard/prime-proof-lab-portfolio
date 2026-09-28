"""Synthetic form tests: parties stay separate from freight money and identities."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prime_details import party_blocks


def row(number,y,*cells):
    words=[[i,text,x,y,20,10,95,1,1,number] for i,(x,text) in enumerate(cells,1)]
    return {'line_id':str(number),'raw_text':' '.join(t for _,t in cells),'words_json':json.dumps(words)}


class InvoiceFormTests(unittest.TestCase):
    def fixture(self):
        return [row(1,50,(20,'UNIT: 123 OWNER: TEST ORDER: O123 DISP: O1')),
            row(2,150,(20,'SETTLEMENTS DATE: 26/09/18')),
            row(3,170,(120,'EXAMPLE CUSTOMER'),(460,'DEMO1')),
            row(4,185,(120,'10 BILLING ST')),
            row(5,200,(120,'TESTVILLE, CA 90000')),
            row(6,330,(20,'EXAMPLE PLANT'),(460,'SHIPPERS NO. 123')),
            row(7,345,(20,'20 FACTORY ST')),
            row(8,360,(20,'TESTVILLE, CA 90001')),
            row(9,440,(20,'EXAMPLE RECEIVER'),(350,'STEEL PRODUCTS')),
            row(10,455,(20,'30 DELIVERY ST'),(350,'FLAT RATE 1000.00')),
            row(11,470,(20,'SAMPLE CITY, AZ 80000'),(350,'FUEL SURCHARGE 200.00'))]

    def test_three_distinct_roles_with_source_locators(self):
        info,parts=party_blocks(self.fixture(),1000,1000)
        self.assertEqual(info['order_raw'],'O123')
        self.assertEqual(info['dispatch_raw'],'O1')
        self.assertEqual([p['role_candidate'] for p in parts],['bill_to','shipper','receiver'])
        self.assertEqual(parts[0]['code_raw'],'DEMO1')
        self.assertIsNone(parts[1]['code_raw'])
        self.assertEqual(parts[2]['name_raw'],'EXAMPLE RECEIVER')
        self.assertNotIn('1000.00',parts[2]['address_block_raw'])
        self.assertEqual(parts[2]['evidence']['line_ids'],['9','10','11'])

    def test_missing_anchor_is_unsupported(self):
        self.assertEqual(party_blocks(self.fixture()[1:],1000,1000),(None,[]))
        self.assertEqual(party_blocks([r for r in self.fixture() if r['line_id']!='6'],1000,1000),(None,[]))

    def test_single_name_does_not_invent_an_address(self):
        _,parts=party_blocks([r for r in self.fixture() if r['line_id'] not in ('10','11')],1000,1000)
        self.assertEqual(len(parts),2)


if __name__=='__main__':unittest.main()
