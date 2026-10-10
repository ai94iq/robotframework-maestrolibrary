import json
import os
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from MaestroLibrary.mcp import MaestroError, MaestroMCP, find_exe, verified_exe

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_mcp.py")]


class FindExeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cwd, self.bin = os.path.join(tmp.name, "cwd"), os.path.join(tmp.name, "bin")
        self.planted, self.real = self.tool(self.cwd), self.tool(self.bin)
        cwd = os.getcwd()
        os.chdir(self.cwd)
        self.addCleanup(os.chdir, cwd)

    @staticmethod
    def tool(folder):
        os.makedirs(folder)
        path = os.path.join(folder, "tool.exe" if os.name == "nt" else "tool")
        with open(path, "w") as f:
            f.write("")
        os.chmod(path, 0o755)
        return path

    def test_a_tool_in_the_working_directory_is_never_picked(self):
        # Windows runs an exe in the working directory before PATH (CWE-427, measured on Python 3.14).
        env = {"PATH": os.pathsep.join([".", "", self.bin]), "NoDefaultCurrentDirectoryInExePath": ""}
        with mock.patch.dict(os.environ, env):
            del os.environ["NoDefaultCurrentDirectoryInExePath"]
            self.assertEqual(os.path.normcase(find_exe("tool")), os.path.normcase(self.real))

    def test_missing_tool_and_explicit_path(self):
        with mock.patch.dict(os.environ, {"PATH": self.cwd + "-nothing"}):
            self.assertIsNone(find_exe("tool"))
        self.assertEqual(find_exe(self.real), self.real)  # a path is used as given
        self.assertIsNone(find_exe(os.path.join(self.bin, "missing")))


class VerifiedExeTest(unittest.TestCase):
    """Real child processes stand in for adb: python printing what the tool would."""
    ADB = r"Android Debug Bridge version \d"

    def answer(self, code, **kwargs):
        return verified_exe(sys.executable, ["-c", code], self.ADB, **kwargs)

    def test_a_tool_that_answers_as_expected_is_used(self):
        self.assertEqual(self.answer("print('Android Debug Bridge version 1.0.41')"), sys.executable)

    def test_an_impostor_is_refused(self):
        with self.assertRaisesRegex(AssertionError, "does not answer like .*'hello'"):
            self.answer("print('hello')")

    def test_a_tool_that_does_not_answer_is_killed_and_refused(self):
        with self.assertRaisesRegex(AssertionError, "did not answer within 1 s"):
            self.answer("import time; time.sleep(30)", timeout=1)

    def test_a_missing_tool_is_reported(self):
        with self.assertRaisesRegex(AssertionError, "not found on PATH"):
            verified_exe("no-such-tool-for-maestro-tests", ["version"], self.ADB)


class MaestroMCPTest(unittest.TestCase):
    def test_a_server_that_is_not_maestro_is_killed(self):
        with mock.patch.dict(os.environ, {"FAKE_MCP_NAME": "impostor"}):
            mcp = MaestroMCP(FAKE)
            with self.assertRaisesRegex(MaestroError, "is not Maestro.*impostor"):
                mcp.start()
        self.assertFalse(mcp.running)

    def setUp(self):
        self.mcp = MaestroMCP(FAKE)
        self.addCleanup(self.mcp.close)

    def test_calls_from_several_threads_take_turns(self):
        import threading
        import time
        inside, overlaps = [0], []

        def request(method, params, timeout):
            inside[0] += 1
            overlaps.append(inside[0])
            time.sleep(0.05)
            inside[0] -= 1
            return {"content": []}
        self.mcp.start()
        with mock.patch.object(self.mcp, "_request", side_effect=request):
            threads = [threading.Thread(target=self.mcp.call_tool, args=("run", {})) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(overlaps, [1, 1, 1, 1])

    def test_call_returns_content_without_viewer_notice(self):
        content = self.mcp.call_tool("run", {"yaml": "- back"})
        self.assertEqual([json.loads(c["text"]) for c in content], [{"yaml": "- back"}])

    def test_tool_error_raises_with_maestro_reason(self):
        with self.assertRaisesRegex(MaestroError, r'^Assertion is false: "X" is visible$'):
            self.mcp.call_tool("fail", {})

    def test_server_exit_raises_and_next_call_restarts(self):
        with self.assertRaisesRegex(MaestroError, "exited"):
            self.mcp.call_tool("exit", {})
        self.assertTrue(self.mcp.call_tool("run", {}))

    def test_unanswered_call_restarts_the_server_instead_of_leaving_it_busy(self):
        with self.assertRaisesRegex(MaestroError, "did not answer 'tools/call' within 0.5 s"):
            self.mcp.call_tool("hang", {}, timeout=0.5)
        self.assertFalse(self.mcp.running)
        self.assertTrue(self.mcp.call_tool("run", {}))

    def test_a_server_that_ignores_close_is_killed_with_its_child_processes_on_windows(self):
        proc = mock.Mock(pid=4242)
        proc.wait.side_effect = [subprocess.TimeoutExpired("maestro", 10), 0]
        self.mcp._proc = proc
        taskkill = "/windows/taskkill.exe"
        with mock.patch("MaestroLibrary.mcp.os") as fake_os, mock.patch("MaestroLibrary.mcp.subprocess.run") as run, \
                mock.patch("MaestroLibrary.mcp.find_exe", return_value=taskkill):
            fake_os.name = "nt"
            self.mcp.close()
        # maestro.bat starts a JVM; killing only the .bat would leave the JVM driving the device.
        self.assertEqual(run.call_args.args[0], [taskkill, "/F", "/T", "/PID", "4242"])
        proc.kill.assert_not_called()

    def test_missing_executable_is_reported(self):
        with self.assertRaisesRegex(MaestroError, "not found on PATH"):
            MaestroMCP(["no-such-maestro-binary", "mcp"]).start()


if __name__ == "__main__":
    unittest.main()
