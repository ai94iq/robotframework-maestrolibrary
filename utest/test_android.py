"""The logcat stream and the scrcpy mirror, without a device: subprocess is faked."""
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from MaestroLibrary import MaestroLibrary

LOGCAT = ["adb", "-s", "emulator-5554", "logcat", "-v", "threadtime", "-T", "1"]


def item(name, parent=None):
    return SimpleNamespace(full_name=name, parent=parent)


class AndroidTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        outdir = mock.patch("MaestroLibrary.keywords._screenshot.BuiltIn")
        outdir.start().return_value.get_variable_value.return_value = self.tmp
        self.addCleanup(outdir.stop)
        sp = mock.patch("MaestroLibrary.android.subprocess")
        self.sp = sp.start()
        self.addCleanup(sp.stop)
        self.sp.TimeoutExpired = subprocess.TimeoutExpired
        self.lib = MaestroLibrary(run_on_failure="Nothing")
        self.lib.platform, self.lib.device, self.lib._adb = "android", "emulator-5554", "adb"
        self.addCleanup(self.lib.logcat.stop)  # closes the log file before the temp dir goes (Windows)


class LogcatTest(AndroidTest):
    def test_one_stream_per_test_in_a_sanitized_file(self):
        suite = item("Atest.Android")
        self.lib.logcat.start_suite(suite, None)
        self.lib.logcat.start_test(item('Atest.Android.Crash: "a/b"?', suite), None)
        self.lib.logcat.ensure()
        self.lib.logcat.ensure()  # every keyword calls it; one stream per test
        self.assertEqual(self.sp.Popen.call_count, 1)
        self.assertEqual(self.sp.Popen.call_args.args[0], LOGCAT)
        path = self.sp.Popen.call_args.kwargs["stdout"].name
        self.assertEqual(os.path.basename(path), "1-Atest.Android.Crash_a_b_.txt")
        self.lib.logcat.end_test(item("x", suite), None)
        self.sp.Popen.return_value.terminate.assert_called_once()
        self.lib.logcat.ensure()  # suite teardown keywords get the suite's file
        self.assertTrue(self.sp.Popen.call_args.kwargs["stdout"].name.endswith("2-Atest.Android.txt"))
        self.lib.logcat.end_suite(item("Atest.Android"), None)
        self.lib.logcat.ensure()
        self.assertEqual(self.sp.Popen.call_count, 2)  # outside any suite: nothing

    def test_no_stream_without_android_adb_or_a_running_test(self):
        self.lib.logcat.ensure()  # no test or suite started
        self.lib.logcat.start_test(item("S.T", item("S")), None)
        self.lib._adb = ""
        self.lib.logcat.ensure()
        self.lib._adb, self.lib.platform = "adb", "ios"
        self.lib.logcat.ensure()
        self.sp.Popen.assert_not_called()

    def test_a_stream_that_died_with_the_device_ends_quietly(self):
        self.lib.logcat.start_test(item("S.T", item("S")), None)
        self.lib.logcat.ensure()
        self.sp.Popen.return_value.terminate.side_effect = OSError("gone")
        self.lib.logcat.end_test(item("S.T", item("S")), None)  # must not raise
        self.lib.logcat.start_test(item("S.U", item("S")), None)
        self.lib.logcat.ensure()
        self.assertEqual(self.sp.Popen.call_count, 2)

    def test_logcat_false_turns_it_off(self):
        self.assertIsNone(MaestroLibrary(logcat=False).logcat)

    def test_keywords_start_the_stream_through_device_id(self):
        self.lib.logcat.start_test(item("S.T", item("S")), None)
        self.lib.device_id()
        self.assertEqual(self.sp.Popen.call_args.args[0], LOGCAT)

    def test_ios_simulator_streams_its_log_wip(self):
        # WIP: the simctl command is from Apple's docs, not measured (no Mac).
        self.lib.platform, self.lib.device, self.lib._xcrun = "ios", "SIM-1", "/usr/bin/xcrun"
        self.lib.logcat.start_test(item("S.T", item("S")), None)
        self.lib.logcat.ensure()
        self.assertEqual(self.sp.Popen.call_args.args[0],
                         ["/usr/bin/xcrun", "simctl", "spawn", "SIM-1", "log", "stream", "--style", "compact"])

    def test_ios_without_xcrun_streams_nothing(self):
        self.lib.platform, self.lib.device, self.lib._xcrun = "ios", "SIM-1", ""
        self.lib.logcat.start_test(item("S.T", item("S")), None)
        self.lib.logcat.ensure()
        self.sp.Popen.assert_not_called()

    def test_an_ios_device_warns_once_that_support_is_wip(self):
        lib = MaestroLibrary(run_on_failure="Nothing", logcat=False)
        lib.mcp.call_tool = mock.Mock(return_value=[{"type": "text", "text":
            '{"devices": [{"device_id": "SIM-1", "platform": "ios", "connected": true}]}'}])
        with mock.patch("MaestroLibrary.logger.warn") as warn:
            lib.device_id()
            lib.device_id()
        self.assertEqual(warn.call_count, 1)
        self.assertIn("WIP", warn.call_args.args[0])


SCRCPY = ["scrcpy", "-s", "emulator-5554", "--no-audio", "--window-title=Maestro emulator-5554"]


class MirrorTest(AndroidTest):
    def setUp(self):
        super().setUp()
        self.sp.Popen.return_value.wait.side_effect = subprocess.TimeoutExpired("scrcpy", 2)  # stays open
        self.sp.Popen.return_value.poll.return_value = None  # still running
        find = mock.patch("MaestroLibrary.android.verified_exe", side_effect=lambda name, *args: name)
        self.find = find.start()
        self.addCleanup(find.stop)
        self.addCleanup(self.lib.screen_mirror.stop)
        self.addCleanup(setattr, self.sp.Popen.return_value.wait, "side_effect", None)

    def test_view_only_by_default_with_extra_options(self):
        self.lib.run_keyword("start_screen_mirroring", ["--max-size=1024"], {})
        self.assertEqual(self.sp.Popen.call_args.args[0], SCRCPY + ["--no-control", "--max-size=1024"])
        with self.assertRaisesRegex(AssertionError, "already running"):
            self.lib.run_keyword("start_screen_mirroring", [], {})
        self.sp.Popen.return_value.wait.side_effect = None  # scrcpy ends when terminated
        self.lib.run_keyword("stop_screen_mirroring", [], {})
        self.sp.Popen.return_value.terminate.assert_called_once()
        self.lib.run_keyword("stop_screen_mirroring", [], {})  # teardown with nothing running

    def test_control_lets_the_mouse_and_keyboard_through(self):
        self.lib.run_keyword("start_screen_mirroring", [], {"control": True})
        self.assertEqual(self.sp.Popen.call_args.args[0], SCRCPY)

    def test_missing_or_failing_scrcpy_fails_the_keyword(self):
        self.find.side_effect = AssertionError("scrcpy not found on PATH.")
        with self.assertRaisesRegex(AssertionError, "scrcpy did not run"):
            self.lib.run_keyword("start_screen_mirroring", [], {})
        self.sp.Popen.assert_not_called()
        self.find.side_effect = lambda name, *args: name
        self.sp.Popen.side_effect = FileNotFoundError
        with self.assertRaisesRegex(AssertionError, "scrcpy did not run"):
            self.lib.run_keyword("start_screen_mirroring", [], {})
        self.sp.Popen.side_effect = None
        self.sp.Popen.return_value.wait.side_effect = None
        self.sp.Popen.return_value.returncode = 1
        with self.assertRaisesRegex(AssertionError, r"scrcpy exited \(1\).*scrcpy-emulator-5554.log"):
            self.lib.run_keyword("start_screen_mirroring", [], {})

    def test_scrcpy_is_verified_by_its_version_output(self):
        self.lib.run_keyword("start_screen_mirroring", [], {})
        self.assertEqual(self.find.call_args.args[:2], ("scrcpy", ["--version"]))
        self.assertRegex("scrcpy 5.0 <https://github.com/Genymobile/scrcpy>", self.find.call_args.args[2])
        self.sp.Popen.return_value.wait.side_effect = None  # scrcpy ends when terminated
        self.lib.run_keyword("stop_screen_mirroring", [], {})
        self.find.side_effect = AssertionError("/tmp/scrcpy does not answer like scrcpy ('hi'), so it is not used.")
        with self.assertRaisesRegex(AssertionError, "scrcpy did not run: .*does not answer like scrcpy"):
            self.lib.run_keyword("start_screen_mirroring", [], {})

    def test_ios_simulator_needs_no_mirror_wip(self):
        self.lib.platform = "ios"
        self.lib.run_keyword("start_screen_mirroring", [], {})  # the Simulator window shows it already
        self.sp.Popen.assert_not_called()

    def test_mirror_import_arg_starts_on_first_device_use_and_only_warns(self):
        lib = MaestroLibrary(run_on_failure="Nothing", mirror=True, logcat=False)
        lib.mcp.call_tool = mock.Mock(return_value=[{"type": "text", "text":
            '{"devices": [{"device_id": "emulator-5554", "platform": "android", "connected": true}]}'}])
        self.sp.Popen.side_effect = FileNotFoundError
        with mock.patch("MaestroLibrary.logger.warn") as warn:
            self.assertEqual(lib.device_id(), "emulator-5554")
        self.assertIn("scrcpy did not run", warn.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
