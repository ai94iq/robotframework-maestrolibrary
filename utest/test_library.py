import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from MaestroLibrary import MaestroLibrary
from MaestroLibrary.mcp import MaestroMCP

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_mcp.py")]


class OpenApplicationTest(unittest.TestCase):
    def setUp(self):
        self.lib = MaestroLibrary(run_on_failure="Nothing")
        self.lib.mcp = MaestroMCP(FAKE)
        self.addCleanup(self.lib.mcp.close)

    def test_adb_is_verified_once_by_running_it(self):
        with mock.patch("MaestroLibrary.verified_exe", return_value="/sdk/adb") as verify:
            self.assertEqual(self.lib.adb(), "/sdk/adb")
            self.assertEqual(self.lib.adb(), "/sdk/adb")
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[:2], ("adb", ["version"]))
        self.assertRegex("Android Debug Bridge version 1.0.41\nVersion 37.0.1", verify.call_args.args[2])

    def test_xcrun_is_verified_once_by_running_it(self):
        with mock.patch("MaestroLibrary.verified_exe", return_value="/usr/bin/xcrun") as verify:
            self.assertEqual(self.lib.xcrun(), "/usr/bin/xcrun")
            self.assertEqual(self.lib.xcrun(), "/usr/bin/xcrun")
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[:2], ("xcrun", ["--version"]))
        with mock.patch("MaestroLibrary.verified_exe", side_effect=AssertionError("xcrun not found on PATH.")),                 mock.patch("MaestroLibrary.logger.warn"):
            self.lib._xcrun = None
            self.assertIsNone(self.lib.xcrun())

    def test_missing_or_impostor_adb_is_not_used(self):
        impostor = AssertionError("/tmp/adb does not answer like adb ('hello'), so it is not used.")
        with mock.patch("MaestroLibrary.verified_exe", side_effect=impostor), \
                mock.patch("MaestroLibrary.logger.warn") as warn:
            self.assertIsNone(self.lib.adb())
            self.assertIn("does not answer like adb", warn.call_args_list[0].args[0])
            self.assertIsNone(self.lib.adb_shell("dumpsys", purpose="checking"))
        self.assertIn("adb did not run", warn.call_args.args[0])

    def test_without_adb_on_path_opens_the_app_without_the_focus_wait(self):
        with mock.patch.dict(os.environ, {"PATH": ""}), mock.patch("MaestroLibrary.logger.warn") as warn:
            self.lib.run_keyword("open_application", ["com.example.app"])
        self.assertEqual(self.lib.app_id, "com.example.app")
        self.assertIn("adb", warn.call_args.args[0])


    def test_hung_adb_ends_the_focus_wait_instead_of_hanging_the_run(self):
        hung = subprocess.TimeoutExpired("adb", 10)
        self.lib.mcp.start()  # before patching: subprocess is patched module-wide
        self.lib._adb = "adb"
        with mock.patch("MaestroLibrary.subprocess.run", side_effect=hung) as run, \
                mock.patch("MaestroLibrary.logger.warn") as warn:
            self.lib.run_keyword("open_application", ["com.example.app"])
        self.assertIn("timeout", run.call_args.kwargs)
        self.assertIn("adb", warn.call_args.args[0])


    def test_hung_adb_fails_execute_adb_shell_with_a_timeout_message(self):
        self.lib.mcp.start()
        self.lib._adb = "adb"
        with mock.patch("MaestroLibrary.keywords._applicationmanagement.subprocess.run",
                           side_effect=subprocess.TimeoutExpired("adb", 30)) as run:
            with self.assertRaisesRegex(AssertionError, "adb shell echo timed out after 30 s"):
                self.lib.run_keyword("execute_adb_shell", ["echo", "hi"])
        self.assertIn("timeout", run.call_args.kwargs)


    def test_focus_is_polled_at_most_once_a_second(self):
        self.lib.mcp.start()
        self.lib._adb = "adb"
        with mock.patch("MaestroLibrary.subprocess.run", return_value=mock.Mock(stdout="")), \
                mock.patch("MaestroLibrary.time.sleep") as sleep, \
                mock.patch("MaestroLibrary.time.monotonic", side_effect=[0, 0, 5, 30]), \
                mock.patch("MaestroLibrary.logger.warn"):
            self.lib.wait_for_app_focus("com.example.app")
        self.assertGreaterEqual(sleep.call_args.args[0], 1)


class SpeedTest(unittest.TestCase):
    def test_speed_pauses_before_every_maestro_command(self):
        lib = MaestroLibrary(run_on_failure="Nothing", speed=timedelta(milliseconds=300))
        lib.mcp = MaestroMCP(FAKE)
        self.addCleanup(lib.mcp.close)
        lib.mcp.start()
        with mock.patch("MaestroLibrary.time.sleep") as sleep:
            lib.run_keyword("go_back", [])
            lib.run_keyword("go_back", [])
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.3, 0.3])

    def test_no_pause_by_default(self):
        lib = MaestroLibrary(run_on_failure="Nothing")
        lib.mcp = MaestroMCP(FAKE)
        self.addCleanup(lib.mcp.close)
        lib.mcp.start()
        with mock.patch("MaestroLibrary.time.sleep") as sleep:
            lib.run_keyword("go_back", [])
        sleep.assert_not_called()


    def test_adb_runs_from_the_path_it_was_found_at(self):
        self.lib = MaestroLibrary(run_on_failure="Nothing")
        self.lib.mcp = MaestroMCP(FAKE)
        self.addCleanup(self.lib.mcp.close)
        self.lib.mcp.start()
        self.lib._adb = adb = r"C:\sdk\platform-tools\adb.exe"
        done = mock.Mock(stdout="ok", returncode=0, stderr="")
        with mock.patch("MaestroLibrary.subprocess.run", return_value=done) as run:
            self.lib.adb_shell("echo", purpose="testing")
            self.assertEqual(run.call_args.args[0][0], adb)
            self.lib.run_keyword("execute_adb_shell", ["echo"])
            self.assertEqual(run.call_args.args[0][0], adb)


class ScreenshotTest(unittest.TestCase):
    def test_file_on_another_drive_than_the_output_dir_is_still_saved_and_linked(self):
        lib = MaestroLibrary(run_on_failure="Nothing")
        lib.mcp = MaestroMCP(FAKE)
        self.addCleanup(lib.mcp.close)
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "shot.jpg")
            # Windows raises this for paths on different drives.
            with mock.patch("MaestroLibrary.keywords._screenshot.BuiltIn") as builtin, \
                    mock.patch("os.path.relpath", side_effect=ValueError("path is on mount 'D:'")), \
                    mock.patch("MaestroLibrary.keywords._screenshot.logger.info") as info:
                builtin.return_value.get_variable_value.return_value = tmp
                path = lib.run_keyword("capture_page_screenshot", [target])
            self.assertTrue(os.path.isfile(path))
            self.assertIn("file:", info.call_args.args[0])


class TimeoutTest(unittest.TestCase):
    def test_zero_timeout_is_not_replaced_by_the_default(self):
        lib = MaestroLibrary(timeout=timedelta(seconds=5))
        self.assertEqual(lib.timeout_ms(timedelta(0)), 0)
        self.assertEqual(lib.timeout_ms(None), 5000)


if __name__ == "__main__":
    unittest.main()
