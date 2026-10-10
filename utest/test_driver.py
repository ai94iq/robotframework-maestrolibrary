import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from MaestroLibrary.driver import elements_from_xml, hierarchy_text

XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" resource-id="" class="android.widget.FrameLayout" content-desc="" hintText="" clickable="false"
        enabled="true" scrollable="false" selected="false" bounds="[0,0][1080,2400]">
    <node text="Apps" resource-id="com.app:id/tab" class="android.widget.TextView" content-desc="" hintText=""
          clickable="true" enabled="true" scrollable="false" selected="true" bounds="[0,100][540,200]" />
    <node text="" resource-id="" class="android.widget.EditText" content-desc="Search" hintText="Search apps"
          clickable="true" enabled="false" scrollable="true" selected="false" bounds="[0,300][1080,400]" />
  </node>
</hierarchy>"""


def response(text):
    data = text.encode()
    size, varint = len(data), b""
    while True:
        byte, size = size & 0x7F, size >> 7
        varint += bytes([byte | (0x80 if size else 0)])
        if not size:
            return b"\x0a" + varint + data


class DriverTest(unittest.TestCase):
    def test_response_is_decoded_without_protobuf(self):
        self.assertEqual(hierarchy_text(response(XML)), XML)
        self.assertEqual(hierarchy_text(response("x" * 300)), "x" * 300)      # a two-byte length
        self.assertEqual(hierarchy_text(b""), "")
        with self.assertRaises(ValueError):
            hierarchy_text(b"\x12\x01x")

    def test_xml_becomes_the_compact_tree(self):
        self.assertEqual(elements_from_xml(XML), [{"c": [{
            "b": "[0,0][1080,2400]", "cls": "android.widget.FrameLayout", "c": [
                {"b": "[0,100][540,200]", "txt": "Apps", "rid": "com.app:id/tab", "cls": "android.widget.TextView",
                 "clickable": True, "selected": True},
                {"b": "[0,300][1080,400]", "a11y": "Search", "hint": "Search apps", "cls": "android.widget.EditText",
                 "clickable": True, "scroll": True, "enabled": False}]}]}])

    def test_entities_are_refused(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE h [<!ENTITY a "aaaa">]><hierarchy><node text="&a;"/></hierarchy>'
        with self.assertRaises(ValueError):
            elements_from_xml(bomb)


class SessionReaderTest(unittest.TestCase):
    def setUp(self):
        from test_studio import FakeLib
        from MaestroLibrary.studio import Session
        self.lib = FakeLib([{"b": "[0,0][1080,2400]", "txt": "From MCP"}])
        self.Session = Session

    def test_the_reader_is_used_and_mcp_is_the_fallback(self):
        class Reader:
            fail = False

            def screen(self):
                if self.fail:
                    raise ConnectionError("driver not up")
                return elements_from_xml(XML)
        reader = Reader()
        session = self.Session(self.lib, reader=reader)
        self.assertIn("Apps", [e.get("txt") for e in session.tree(fresh=True)["elements"]])
        reader.fail = True
        self.assertEqual([e.get("txt") for e in session.tree(fresh=True)["elements"]], ["From MCP"])


if __name__ == "__main__":
    unittest.main()
