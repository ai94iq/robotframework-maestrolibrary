import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from MaestroLibrary.flow2robot import convert, escape, to_locator

FLOW = """\
appId: com.example.app
---
- launchApp:
    clearState: true
- tapOn:
    id: "email"
- inputText: "user@example.com"
- tapOn: "Sign in (2)"
- tapOn:
    text: "Next"
    index: 1
- assertVisible: "Welc.*"
- scrollUntilVisible:
    element:
      id: footer
    direction: UP
    timeout: 5000
- back
- stopApp
"""


class Flow2RobotTest(unittest.TestCase):
    def test_convert(self):
        self.assertEqual(convert(FLOW, "Login").splitlines()[4:], [
            "Login",
            "    Open Application    com.example.app    clear_state=True",
            "    Input Text    id\\=email    user@example.com",
            "    Click Element    regex\\=Sign in (2)",
            "    Run Flow    - {tapOn: {text: Next, index: 1}}",
            "    Wait Until Page Contains Element    regex\\=Welc.*",
            "    Scroll Up    id\\=footer    timeout=5s",
            "    Go Back",
            "    Terminate Application    com.example.app",
        ])

    def test_locators(self):
        self.assertEqual(to_locator("Network & internet"), "text=Network & internet")
        self.assertEqual(to_locator({"id": "a.b", "label": "x"}), "id_regex=a.b")
        self.assertEqual(to_locator({"point": "50%,50%"}), "point=50%,50%")
        self.assertIsNone(to_locator({"text": "OK", "index": 0}))

    def test_escape(self):
        self.assertEqual(escape(""), "${EMPTY}")
        self.assertEqual(escape("a   b "), "a \\ \\ b\\ ")
        self.assertEqual(escape("#tag"), "\\#tag")
        self.assertEqual(escape("c:\\x"), "c:\\\\x")


if __name__ == "__main__":
    unittest.main()
