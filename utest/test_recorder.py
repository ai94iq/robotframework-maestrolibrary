import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from MaestroLibrary import recorder
from MaestroLibrary.recorder import FlowRecorder


class FlowRecorderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = tmp.name
        self.variables = {"${SUITE SOURCE}": "s.robot", "${SUITE NAME}": "S", "${TEST NAME}": "Log In"}
        builtin = mock.patch.object(recorder, "BuiltIn")
        builtin.start().return_value.get_variables.return_value = self.variables
        self.addCleanup(builtin.stop)
        for name, target in (("output_path", lambda f: os.path.join(self.out, f)), ("log_link", mock.Mock())):
            patch = mock.patch.object(recorder, name, target)
            patch.start()
            self.addCleanup(patch.stop)
        os.makedirs(os.path.join(self.out, "flows"))

    def read(self, name):
        with open(os.path.join(self.out, "flows", name), encoding="utf-8") as f:
            return f.read()

    def test_one_replayable_flow_per_test(self):
        rec = FlowRecorder()
        rec.commands("com.app", [{"tapOn": {"id": "user"}}, {"inputText": "me"}], secret=False)
        rec.commands("com.app", [{"tapOn": {"id": "pw"}}, {"inputText": "s3cret"},
                                 {"waitForAnimationToEnd": {"timeout": 1}}], secret=True)
        rec.yaml("com.app", "appId: x\n---\n- back\n", env={"N": "1"})
        rec.files("com.app", ["/f/a.yaml"])
        self.variables["${TEST NAME}"] = "Next"
        rec.commands("com.app", ["back"], secret=False)
        self.assertEqual(self.read("1-Log_In.yaml"), "\n".join([
            'appId: "com.app"', "---",
            '- {"tapOn": {"id": "user"}}', '- {"inputText": "me"}',
            '- {"tapOn": {"id": "pw"}}', '- {"inputText": "${PASSWORD}"}',
            "- runFlow:", '    env: {"N": "1"}', "    commands:", "      - back",
            '- runFlow: "/f/a.yaml"', ""]))
        self.assertEqual(self.read("2-Next.yaml"), 'appId: "com.app"\n---\n- "back"\n')

    def test_settle_waits_alone_record_nothing(self):
        FlowRecorder().commands("com.app", [{"waitForAnimationToEnd": {"timeout": 1}}], secret=True)
        self.assertEqual(os.listdir(os.path.join(self.out, "flows")), [])


if __name__ == "__main__":
    unittest.main()
