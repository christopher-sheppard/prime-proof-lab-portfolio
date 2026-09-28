"""Regression cases from route-reading patterns, with no financial records."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prime_structure import parse_route_text


class RouteTests(unittest.TestCase):
    def test_multistop_with_empty_approach(self):
        self.assertEqual(parse_route_text('Springfld MO E Blythevl AR L Jacksonvl FL L Auburndale FL'), [
            ('Springfld','MO','E'),('Blythevl','AR','L'),('Jacksonvl','FL','L'),('Auburndale','FL',None)])

    def test_apostrophe_is_part_of_city(self):
        self.assertEqual(parse_route_text("C D Alene ID E Oldtow'n ID L Waller TX")[1], ("Oldtow'n",'ID','L'))

    def test_ocr_digits_in_city_are_preserved(self):
        self.assertEqual(parse_route_text('Manchester TN E Russe11v1 KY L Pittston PA')[1], ('Russe11v1','KY','L'))

    def test_damaged_state_is_retained_for_review(self):
        self.assertEqual(parse_route_text('Phoenix AZ E Morenci A2 L Denton TX')[1], ('Morenci','A2','L'))
        self.assertEqual(parse_route_text('Hayward IIJI L Lebanon MO')[0], ('Hayward','IIJI','L'))

    def test_empty_movement_has_no_invented_loaded_stop(self):
        points = parse_route_text('Bronx NY E Pittston PA')
        self.assertEqual(points, [('Bronx','NY','E'),('Pittston','PA',None)])
        self.assertFalse(any(p[2]=='L' for p in points))

    def test_prose_and_financial_lines_are_rejected(self):
        for line in ('TRAIN COOCHR','TOTAL 3,139.85','LTD MILES = 459,491','TEAM: O O O','Invoice 1234 L City IL',''):
            self.assertEqual(parse_route_text(line), [], line)

    def test_punctuation_and_multiword_city(self):
        self.assertEqual(parse_route_text('St, Joseph MO E Salt, Lk Cy UT L Fort, Bliss TX')[-1], ('Fort, Bliss','TX',None))

    def test_unmarked_continuation_must_have_known_state(self):
        self.assertEqual(parse_route_text('Los Angeles CA'), [('Los Angeles','CA',None)])
        self.assertEqual(parse_route_text('Los Angeles XX'), [])

    def test_east_prefix_is_not_an_empty_segment_marker(self):
        self.assertEqual(parse_route_text('Alta IA E E Peoria IL L Arvin CA')[1], ('E Peoria','IL','L'))
        self.assertEqual(parse_route_text('Monroe NC L Piscataway NJ L E Setauket, NY')[-1], ('E Setauket,','NY',None))

    def test_unicode_city_spelling_is_preserved(self):
        self.assertEqual(parse_route_text('Thomasvl NC E Monroe NC L La Verg‘ne TN')[-1], ('La Verg‘ne','TN',None))
        self.assertEqual(parse_route_text('Gainesvl GA L PrtIﬂntwrth GA')[-1], ('PrtIﬂntwrth','GA',None))

    def test_punctuated_state_is_retained_for_review(self):
        self.assertEqual(parse_route_text("Billings MT E Lovell W'Y E Cedar City UT L San Diego CA")[1], ('Lovell',"W'Y",'E'))


if __name__ == '__main__':
    unittest.main()
