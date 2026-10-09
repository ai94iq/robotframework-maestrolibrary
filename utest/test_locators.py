import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from MaestroLibrary.locators import matches, to_selector, walk


class ToSelectorTest(unittest.TestCase):
    def test_strategies(self):
        cases = {
            "Log in (2)": {"text": r"Log\ in\ \(2\)"},
            "text=OK": {"text": "OK"},
            "accessibility_id=Back": {"text": "Back"},
            "regex=Net.*": {"text": "Net.*"},
            "id=com.app:id/login": {"id": r"com\.app:id/login"},
            "id_regex=.*login": {"id": ".*login"},
            "point=50%, 50%": {"point": "50%,50%"},
            "Total = 5": {"text": r"Total\ =\ 5"},
        }
        for locator, expected in cases.items():
            with self.subTest(locator=locator):
                self.assertEqual(to_selector(locator), expected)

    def test_unknown_strategy(self):
        with self.assertRaisesRegex(ValueError, "Unknown locator strategy 'foo'"):
            to_selector("foo=bar")

    def test_unsupported_strategies_fail_fast(self):
        for locator in ("//android.widget.Button", "xpath=//a", "class=Button", "android=new UiSelector()"):
            with self.subTest(locator=locator), self.assertRaisesRegex(ValueError, "not supported by Maestro"):
                to_selector(locator)


class MatchesTest(unittest.TestCase):
    tree = [{"rid": "root", "c": [{"txt": "Log in"}, {"a11y": "Back", "c": [{"hint": "Password"}]}]}]

    def find(self, locator):
        return [e for e in walk(self.tree) if matches(e, to_selector(locator))]

    def test_text_matches_text_content_desc_and_hint(self):
        self.assertEqual(len(self.find("Log in")), 1)
        self.assertEqual(len(self.find("accessibility_id=Back")), 1)
        self.assertEqual(len(self.find("Password")), 1)

    def test_literal_text_is_whole_match(self):
        self.assertEqual(self.find("Log"), [])
        self.assertEqual(len(self.find("regex=Log.*")), 1)

    def test_id(self):
        self.assertEqual(self.find("id=root")[0]["rid"], "root")


if __name__ == "__main__":
    unittest.main()
