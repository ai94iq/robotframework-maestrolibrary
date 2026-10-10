import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from MaestroLibrary.locators import best_locator, element_at, locator_candidates, parse_bounds

SCREEN = [
    {"b": "[0,0][1080,2400]", "cls": "FrameLayout"},
    {"b": "[0,100][1080,300]", "rid": "com.app:id/search", "txt": "Search"},
    {"b": "[0,400][1080,600]", "txt": "Apps", "clickable": True},
    {"b": "[40,420][140,580]", "cls": "ImageView"},                 # icon inside the Apps row
    {"b": "[0,700][1080,900]", "txt": "Apps"},                      # duplicate text
    {"b": "[0,1000][1080,1200]", "a11y": "Battery\n79%"},
]


class LocatorTest(unittest.TestCase):
    def test_parse_bounds(self):
        self.assertEqual(parse_bounds("[0,2274][1080,2400]"), (0, 2274, 1080, 2400))
        self.assertIsNone(parse_bounds(""))
        self.assertIsNone(parse_bounds(None))

    def test_element_at_prefers_smallest_locatable(self):
        self.assertEqual(element_at(SCREEN, 90, 500)["txt"], "Apps")      # the icon has nothing locatable
        self.assertEqual(element_at(SCREEN, 500, 200)["rid"], "com.app:id/search")
        self.assertIsNone(element_at(SCREEN, 500, 2300))                    # only the root is there

    def test_best_locator_unique_or_none(self):
        self.assertEqual(best_locator(SCREEN[1], SCREEN), "id=com.app:id/search")
        self.assertIsNone(best_locator(SCREEN[2], SCREEN))                  # "Apps" twice
        self.assertEqual(best_locator(SCREEN[5], SCREEN), "text=Battery\n79%")

    def test_candidates_carry_match_counts(self):
        self.assertEqual(locator_candidates(SCREEN[2], SCREEN), [("text=Apps", 2)])
        self.assertEqual(locator_candidates(SCREEN[1], SCREEN),
                         [("id=com.app:id/search", 1), ("text=Search", 1)])


if __name__ == "__main__":
    unittest.main()
