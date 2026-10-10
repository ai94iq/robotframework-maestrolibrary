"""What each keyword sends to Maestro, and how snapshot keywords read a screen, without a device."""
import json
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
SCREEN = [{"rid": "root", "c": [
    {"txt": "Log in", "cls": "android.widget.Button", "b": "[0,0][10,10]"},
    {"a11y": "Assigned\n40", "clickable": True},
    {"rid": "pin", "cls": "android.widget.EditText", "enabled": False, "hint": "Code"},
]}]


class KeywordTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = os.path.join(tmp.name, "calls.jsonl")
        screen = os.path.join(tmp.name, "screen.json")
        with open(screen, "w", encoding="utf-8") as f:
            json.dump(SCREEN, f)
        env = mock.patch.dict(os.environ, {"FAKE_MCP_LOG": self.log, "FAKE_MCP_SCREEN": screen})
        env.start()
        self.addCleanup(env.stop)
        self.lib = MaestroLibrary(run_on_failure="Nothing", timeout=timedelta(seconds=7))
        self.lib.mcp = MaestroMCP(FAKE)
        self.addCleanup(self.lib.mcp.close)
        adb = mock.patch.object(self.lib, "adb_shell",
                                return_value="mCurrentFocus=Window{1 u0 com.app/x}\nmInputShown=true")
        adb.start()
        self.addCleanup(adb.stop)

    def run_kw(self, name, *args, **kwargs):
        return self.lib.run_keyword(name, list(args), kwargs)

    def steps(self):
        """The Maestro steps of every `run` call, minus the settle step snapshot keywords add."""
        steps = []
        with open(self.log, encoding="utf-8") as f:
            for call in map(json.loads, f):
                if call["tool"] == "run" and "yaml" in call["arguments"]:
                    for line in call["arguments"]["yaml"].split("---\n", 1)[1].splitlines():
                        step = json.loads(line[2:])
                        if not (isinstance(step, dict) and "waitForAnimationToEnd" in step):
                            steps.append(step)
        return steps

    def headers(self):
        with open(self.log, encoding="utf-8") as f:
            return [c["arguments"]["yaml"].split("\n")[0] for c in map(json.loads, f)
                    if c["tool"] == "run" and "yaml" in c["arguments"]]


class ActionKeywordsTest(KeywordTest):
    def test_open_application_launches_and_sets_the_app_id(self):
        self.run_kw("open_application", "com.app", clear_state=True)
        self.run_kw("go_back")
        self.assertEqual(self.steps(), [
            {"launchApp": {"appId": "com.app", "clearState": True, "stopApp": True}}, "back"])
        self.assertEqual(self.headers()[-1], 'appId: "com.app"')

    def test_click_and_input(self):
        self.run_kw("click_element", "id=login")
        self.run_kw("click_text", "Log", exact_match=False)
        self.run_kw("input_text", "Code", "123")
        self.run_kw("clear_text", "id=pin")
        self.assertEqual(self.steps(), [
            {"tapOn": {"id": "login"}},
            {"tapOn": {"text": ".*Log.*"}},
            {"tapOn": {"text": "Code"}}, {"inputText": "123"},
            {"tapOn": {"id": "pin"}}, {"eraseText": 50},
        ])

    def test_input_password_keeps_the_text_out_of_the_log(self):
        with mock.patch("MaestroLibrary.logger.debug") as debug:
            self.run_kw("input_password", "id=pin", "s3cret")
        self.assertIn({"inputText": "s3cret"}, self.steps())
        self.assertNotIn("s3cret", str(debug.call_args_list))

    def test_waits_use_the_library_timeout_unless_given(self):
        self.run_kw("wait_until_element_is_visible", "Log in")
        self.run_kw("wait_until_page_does_not_contain", "Gone", timeout=timedelta(seconds=2))
        self.run_kw("expect_element", "id=pin", "disabled")
        self.assertEqual(self.steps(), [
            {"extendedWaitUntil": {"visible": {"text": "Log\\ in"}, "timeout": 7000}},
            {"extendedWaitUntil": {"notVisible": {"text": ".*Gone.*"}, "timeout": 2000}},
            {"extendedWaitUntil": {"visible": {"id": "pin", "enabled": False}, "timeout": 7000}},
        ])

    def test_touch_and_keys(self):
        self.run_kw("swipe", start_x=1, start_y=2, end_x=3, end_y=4)
        self.run_kw("swipe_by_percent", 50, 80, 50, 20, duration=timedelta(milliseconds=300))
        self.run_kw("swipe_by_percent", 50, 80, 50, 20, duration=1500)  # a bare number is ms, as in AppiumLibrary
        self.run_kw("scroll_down", "About", timeout=timedelta(seconds=3))
        self.run_kw("tap", "OK", count=2)
        self.run_kw("press_keycode", 66)
        self.assertEqual(self.steps(), [
            {"swipe": {"start": "1, 2", "end": "3, 4", "duration": 1000}},
            {"swipe": {"start": "50%, 80%", "end": "50%, 20%", "duration": 300}},
            {"swipe": {"start": "50%, 80%", "end": "50%, 20%", "duration": 1500}},
            {"scrollUntilVisible": {"element": {"text": "About"}, "direction": "DOWN", "timeout": 3000}},
            {"tapOn": {"text": "OK", "repeat": 2}},
            {"pressKey": "Enter"},
        ])

    def test_hide_keyboard_presses_only_when_a_keyboard_is_shown(self):
        self.run_kw("hide_keyboard")
        self.lib.adb_shell.return_value = "mInputShown=false"
        self.run_kw("hide_keyboard")
        self.assertEqual(self.steps(), ["hideKeyboard"])

    def test_ios_keywords_on_android(self):
        self.run_kw("hide_keyboard", "Done")  # key_name is iOS only, as in AppiumLibrary
        self.run_kw("click_alert_button", "OK")
        with self.assertRaisesRegex(AssertionError, "needs an iOS simulator"):
            self.run_kw("clear_keychain")
        self.assertEqual(self.steps(), ["hideKeyboard", {"tapOn": {"text": "OK"}}])


class ApplicationKeywordsTest(KeywordTest):
    def test_app_lifecycle(self):
        self.run_kw("activate_application", "com.app")
        self.run_kw("go_to_url", "app://home")
        self.run_kw("terminate_application", "com.other")
        self.run_kw("close_application")
        self.assertEqual(self.steps(), [
            {"launchApp": {"appId": "com.app", "stopApp": False}}, {"openLink": "app://home"},
            {"stopApp": "com.other"}, {"stopApp": "com.app"}])
        self.assertIsNone(self.lib.app_id)

    def test_run_flow_inline_gets_the_current_app_header_and_env(self):
        self.lib.app_id = "com.app"
        self.run_kw("run_flow", "- back", NAME="x")
        with open(self.log, encoding="utf-8") as f:
            call = [c for c in map(json.loads, f) if c["tool"] == "run"][-1]["arguments"]
        self.assertEqual(call["yaml"], 'appId: "com.app"\n---\n- back')
        self.assertEqual(call["env"], {"NAME": "x"})

    def test_run_flow_file_is_sent_by_path(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as flow:
            flow.write("appId: com.app\n---\n- back\n")
        self.addCleanup(os.remove, flow.name)
        self.run_kw("run_flow", flow.name)
        with open(self.log, encoding="utf-8") as f:
            call = [c for c in map(json.loads, f) if c["tool"] == "run"][-1]["arguments"]
        self.assertEqual(call["files"], [os.path.abspath(flow.name)])

    def last_run(self):
        with open(self.log, encoding="utf-8") as f:
            return [c for c in map(json.loads, f) if c["tool"] == "run"][-1]["arguments"]

    def test_open_application_sends_permissions_only_when_given(self):
        self.run_kw("open_application", "com.app", permissions={"all": "deny"})
        self.assertEqual(self.steps(), [
            {"launchApp": {"appId": "com.app", "clearState": False, "stopApp": True,
                           "permissions": {"all": "deny"}}}])
        with self.assertRaisesRegex(ValueError, "'all' must be allow, deny or unset, not 'block'"):
            self.run_kw("open_application", "com.app", permissions={"all": "block"})

    def test_clear_kill_and_permissions_default_to_the_current_app(self):
        self.lib.app_id = "com.app"
        self.run_kw("clear_application_state")
        self.run_kw("kill_application", "com.other")
        self.run_kw("set_application_permissions", camera="allow", notifications="unset")
        self.assertEqual(self.steps(), [
            {"clearState": "com.app"}, {"killApp": "com.other"},
            {"setPermissions": {"appId": "com.app", "permissions": {"camera": "allow", "notifications": "unset"}}}])
        self.assertEqual(self.headers()[-1], 'appId: "com.app"')

    def test_permissions_fail_fast(self):
        with self.assertRaisesRegex(ValueError, "not 'grant'"):
            self.run_kw("set_application_permissions", "com.app", camera="grant")
        with self.assertRaisesRegex(ValueError, "No permissions given"):
            self.run_kw("set_application_permissions", "com.app")
        with self.assertRaisesRegex(ValueError, "No app_id given"):
            self.run_kw("clear_application_state")
        self.assertFalse(os.path.exists(self.log))  # nothing reached Maestro

    def test_run_flow_directory_is_sent_by_path_with_tags(self):
        with tempfile.TemporaryDirectory() as flows:
            self.run_kw("run_flow", flows, NAME="x", include_tags=["smoke"], exclude_tags=["slow"])
            self.assertEqual(self.last_run(), {
                "device_id": "emulator-5554", "dir": os.path.abspath(flows),
                "include_tags": ["smoke"], "exclude_tags": ["slow"], "env": {"NAME": "x"}})

    def test_run_flow_accepts_one_tag_as_a_string(self):
        with tempfile.TemporaryDirectory() as flows:
            self.run_kw("run_flow", flows, include_tags="smoke", exclude_tags="slow")
            self.assertEqual(self.last_run(), {
                "device_id": "emulator-5554", "dir": os.path.abspath(flows),
                "include_tags": ["smoke"], "exclude_tags": ["slow"]})

    def test_run_flow_reports_a_missing_flow_file_or_directory(self):
        for flow in ("flows/onboardng.yaml", "flows/missing.yml", "no/such/dir/"):
            with self.assertRaisesRegex(ValueError, "not found: " + flow):
                self.run_kw("run_flow", flow)
        self.assertFalse(os.path.exists(self.log))  # Maestro was never called
        self.run_kw("run_flow", "- runFlow: sub.yaml")  # one-line inline YAML is still YAML
        with open(self.log, encoding="utf-8") as f:
            sent = [c["arguments"]["yaml"] for c in map(json.loads, f) if "yaml" in c["arguments"]]
        self.assertTrue(sent[-1].endswith("---\n- runFlow: sub.yaml"), sent[-1])

    def test_long_waits_and_flow_runs_are_not_cut_off_by_the_client(self):
        with mock.patch.object(self.lib.mcp, "call_tool", wraps=self.lib.mcp.call_tool) as call:
            self.run_kw("wait_until_page_contains", "Log", timeout=timedelta(minutes=10))
            waits = [c.kwargs.get("timeout") for c in call.call_args_list if c.args[0] == "run"]
            self.assertGreaterEqual(min(waits), 600)
            with tempfile.TemporaryDirectory() as tmp:
                flow = os.path.join(tmp, "f.yaml")
                open(flow, "w").close()
                call.reset_mock()
                self.run_kw("run_flow", flow)
            self.assertGreaterEqual(call.call_args.kwargs.get("timeout"), 3600)

    def test_robot_reads_a_bare_swipe_duration_as_milliseconds(self):
        import inspect
        from robot.running import TypeInfo
        from MaestroLibrary.keywords._touch import TouchKeywords
        for name in ("swipe", "swipe_by_percent"):
            hint = inspect.signature(getattr(TouchKeywords, name)).parameters["duration"].annotation
            self.assertEqual(TypeInfo.from_type_hint(hint).convert("1000"), 1000)
            self.assertEqual(TypeInfo.from_type_hint(hint).convert("1.5s"), timedelta(seconds=1.5))

    def test_screenshot_without_an_image_fails_with_a_message(self):
        self.lib.platform, self.lib.device = "android", "emulator-5554"
        with mock.patch.object(self.lib.mcp, "call_tool", return_value=[{"type": "text", "text": "busy"}]):
            with self.assertRaisesRegex(AssertionError, "take_screenshot returned no image"):
                self.run_kw("capture_page_screenshot")

    def test_run_flow_tags_need_a_directory(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as flow:
            flow.write("appId: com.app\n---\n- back\n")
        self.addCleanup(os.remove, flow.name)
        with self.assertRaisesRegex(ValueError, "only apply to a flow directory"):
            self.run_kw("run_flow", flow.name, include_tags=["smoke"])
        with self.assertRaisesRegex(ValueError, "only apply to a flow directory"):
            self.run_kw("run_flow", "- back", exclude_tags=["slow"])
        self.assertFalse(os.path.exists(self.log))  # nothing reached Maestro

    def test_timeout_and_source(self):
        old = self.run_kw("set_maestro_timeout", timedelta(seconds=9))
        self.assertEqual((old, self.run_kw("get_maestro_timeout")), (timedelta(seconds=7), timedelta(seconds=9)))
        self.assertEqual(json.loads(self.run_kw("get_source")), SCREEN)

    def test_register_keyword_to_run_on_failure_returns_the_previous_one(self):
        self.assertEqual(self.run_kw("register_keyword_to_run_on_failure", "Log Source"), "Nothing")
        self.assertEqual(self.run_kw("register_keyword_to_run_on_failure", "Nothing"), "Log Source")
        self.assertIsNone(self.lib.run_on_failure_keyword)


class SnapshotKeywordsTest(KeywordTest):
    def test_page_checks_read_the_screen(self):
        self.run_kw("page_should_contain_text", "Log")
        self.run_kw("page_should_contain_element", "id=pin")
        with self.assertRaisesRegex(AssertionError, "should not have contained text 'Log'"):
            self.run_kw("page_should_not_contain_text", "Log", loglevel="NONE")

    def test_get_text_and_attributes_fill_in_defaults(self):
        self.assertEqual(self.run_kw("get_text", "regex=Assigned\\n\\d+"), "Assigned\n40")
        self.assertEqual(self.run_kw("get_element_attribute", "id=pin", "class"), "android.widget.EditText")
        self.assertIs(self.run_kw("get_element_attribute", "Log in", "enabled"), True)
        self.assertIs(self.run_kw("get_element_attribute", "Log in", "clickable"), False)

    def test_enabled_state_checks(self):
        self.run_kw("element_should_be_enabled", "Log in")
        self.run_kw("element_should_be_disabled", "id=pin")
        with self.assertRaisesRegex(AssertionError, "'id=pin' should be enabled"):
            self.run_kw("element_should_be_enabled", "id=pin", loglevel="NONE")


class DeviceKeywordsTest(KeywordTest):
    def test_location_and_travel(self):
        self.run_kw("set_location", 33.3152, 44.3661, altitude=10)
        self.run_kw("travel", "33.3152,44.3661", "33.316,44.367", speed=20)
        self.run_kw("travel", "1,2", "3,4")
        self.assertEqual(self.steps(), [
            {"setLocation": {"latitude": "33.3152", "longitude": "44.3661"}},
            {"travel": {"points": ["33.3152,44.3661", "33.316,44.367"], "speed": 20.0}},
            {"travel": {"points": ["1,2", "3,4"]}},
        ])
        with self.assertRaisesRegex(ValueError, "at least two points"):
            self.run_kw("travel", "1,2")

    def test_orientation(self):
        self.run_kw("landscape")
        self.run_kw("portrait")
        self.run_kw("set_orientation", "landscape right")
        self.run_kw("set_orientation", "UPSIDE_DOWN")
        self.assertEqual(self.steps(), [{"setOrientation": "LANDSCAPE_LEFT"}, {"setOrientation": "PORTRAIT"},
                                        {"setOrientation": "LANDSCAPE_RIGHT"}, {"setOrientation": "UPSIDE_DOWN"}])
        with self.assertRaisesRegex(ValueError, "Unknown orientation 'sideways'"):
            self.run_kw("set_orientation", "sideways")

    def test_airplane_and_dark_mode(self):
        self.run_kw("set_airplane_mode", True)
        self.run_kw("set_airplane_mode", False)
        self.run_kw("set_dark_mode", True)
        self.run_kw("set_dark_mode", False)
        self.assertEqual(self.steps(), [{"setAirplaneMode": "enabled"}, {"setAirplaneMode": "disabled"},
                                        {"setDarkMode": "enabled"}, {"setDarkMode": "disabled"}])

    def test_add_media_sends_absolute_forward_slash_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = os.path.join(tmp, "pic.png")
            open(image, "wb").close()
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                self.run_kw("add_media", "pic.png")
            finally:
                os.chdir(cwd)
            # The MCP process started inside tmp and holds it as its cwd; stop it so tmp can be removed.
            self.lib.mcp.close()
            self.assertEqual(self.steps(), [{"addMedia": [os.path.abspath(image).replace(os.sep, "/")]}])
            with self.assertRaisesRegex(ValueError, "does not exist: .*nope.png"):
                self.run_kw("add_media", os.path.join(tmp, "nope.png"))
        with self.assertRaisesRegex(ValueError, "at least one file"):
            self.run_kw("add_media")


class ScreenshotKeywordsTest(KeywordTest):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        outdir = mock.patch("MaestroLibrary.keywords._screenshot.BuiltIn")
        outdir.start().return_value.get_variable_value.return_value = self.tmp
        self.addCleanup(outdir.stop)

    def test_output_dir_outside_a_robot_run_is_the_working_directory(self):
        from robot.libraries.BuiltIn import RobotNotRunningError
        from MaestroLibrary.keywords._screenshot import output_dir
        with mock.patch("MaestroLibrary.keywords._screenshot.BuiltIn") as builtin:
            builtin.return_value.get_variable_value.side_effect = RobotNotRunningError("no context")
            self.assertEqual(output_dir(), os.getcwd())

    def test_capture_element_screenshot_crops_on_the_element(self):
        path = self.run_kw("capture_element_screenshot", "id=pin", "pin.png")
        base = os.path.join(self.tmp, "pin").replace(os.sep, "/")
        self.assertEqual(self.steps(), [{"takeScreenshot": {"path": base, "cropOn": {"id": "pin"}}}])
        self.assertEqual(path, os.path.join(self.tmp, "pin.png"))

    def test_screenshot_should_match_sends_absolute_path(self):
        reference = os.path.join(self.tmp, "ref.png")
        open(reference, "wb").close()
        self.run_kw("screenshot_should_match", reference, threshold=90, locator="Log in")
        self.run_kw("screenshot_should_match", reference)
        expected = reference.replace(os.sep, "/")
        self.assertEqual(self.steps(), [
            {"assertScreenshot": {"path": expected, "thresholdPercentage": "90", "cropOn": {"text": "Log\\ in"}}},
            {"assertScreenshot": {"path": expected, "thresholdPercentage": "95"}},
        ])

    def test_screenshot_should_match_needs_the_reference(self):
        with self.assertRaisesRegex(AssertionError, "Reference screenshot .*missing.png' does not exist"):
            self.run_kw("screenshot_should_match", os.path.join(self.tmp, "missing.png"))
        self.assertFalse(os.path.exists(self.log))  # Maestro was never called

    def test_screen_recording_start_stop_pull(self):
        self.lib.platform, self.lib.device, self.lib._adb = "android", "emulator-5554", "adb"
        with mock.patch("MaestroLibrary.keywords._screenshot.subprocess") as sp:
            sp.run.return_value.returncode = 0
            sp.Popen.return_value.poll.return_value = None  # still running
            self.run_kw("start_screen_recording")
            with self.assertRaisesRegex(AssertionError, "already running"):
                self.run_kw("start_screen_recording")
            path = self.run_kw("stop_screen_recording", "rec.mp4")
        popen = sp.Popen.call_args.args[0]
        self.assertEqual(popen[:7], ["adb", "-s", "emulator-5554", "shell", "screenrecord", "--time-limit", "180"])
        remote = popen[7]
        commands = [c.args[0] for c in sp.run.call_args_list]
        # Only this recording is interrupted: its device path is unique, other screenrecords keep running.
        self.assertIn(["adb", "-s", "emulator-5554", "shell", "pkill", "-INT", "-f", remote], commands)
        self.assertIn(["adb", "-s", "emulator-5554", "pull", remote, os.path.join(self.tmp, "rec.mp4")], commands)
        self.assertIn(["adb", "-s", "emulator-5554", "shell", "rm", "-f", remote], commands)
        self.assertEqual(path, os.path.join(self.tmp, "rec.mp4"))

    def test_start_after_a_recording_that_ended_is_not_blocked(self):
        self.lib.platform, self.lib.device, self.lib._adb = "android", "emulator-5554", "adb"
        with mock.patch("MaestroLibrary.keywords._screenshot.subprocess") as sp:
            sp.Popen.return_value.poll.return_value = 0  # the first recording has exited
            self.run_kw("start_screen_recording")
            self.run_kw("start_screen_recording")
        self.assertEqual(sp.Popen.call_count, 2)

    def test_failed_pull_keeps_the_device_file_and_names_it(self):
        self.lib.platform, self.lib.device, self.lib._adb = "android", "emulator-5554", "adb"
        with mock.patch("MaestroLibrary.keywords._screenshot.subprocess") as sp:
            sp.Popen.return_value.poll.return_value = None
            self.run_kw("start_screen_recording")
            sp.run.return_value.returncode = 1
            sp.run.return_value.stderr = "No space left on device"
            with self.assertRaisesRegex(AssertionError, "No space left on device") as cm:
                self.run_kw("stop_screen_recording", "rec.mp4")
        remote = sp.Popen.call_args.args[0][7]
        self.assertIn(remote, str(cm.exception))
        commands = [c.args[0] for c in sp.run.call_args_list]
        self.assertNotIn("rm", [arg for c in commands for arg in c], "the device file must be kept")

    def test_hung_adb_while_stopping_fails_with_a_message_and_keeps_the_device_file(self):
        self.lib.platform, self.lib.device, self.lib._adb = "android", "emulator-5554", "adb"
        with mock.patch("MaestroLibrary.keywords._screenshot.subprocess") as sp:
            sp.TimeoutExpired = subprocess.TimeoutExpired
            sp.Popen.return_value.poll.return_value = None
            self.run_kw("start_screen_recording")
            sp.run.side_effect = subprocess.TimeoutExpired("adb", 60)
            with self.assertRaisesRegex(AssertionError, "adb did not answer within 60 s") as cm:
                self.run_kw("stop_screen_recording", "rec.mp4")
        self.assertIn(sp.Popen.call_args.args[0][7], str(cm.exception))
        with self.assertRaisesRegex(AssertionError, "No screen recording is running"):
            self.run_kw("stop_screen_recording")

    def test_stop_without_start_and_non_android_fail_clearly(self):
        with self.assertRaisesRegex(AssertionError, "No screen recording is running"):
            self.run_kw("stop_screen_recording")
        self.lib.platform, self.lib.device, self.lib._xcrun = "ios", "SIM-1", ""
        with self.assertRaisesRegex(AssertionError, "needs xcrun"):
            self.run_kw("start_screen_recording")

    # WIP: the iOS recording runs simctl, from Apple's docs; not measured (no Mac).
    def ios_recording(self):
        self.lib.platform, self.lib.device, self.lib._xcrun = "ios", "SIM-1", "/usr/bin/xcrun"
        sp = mock.patch("MaestroLibrary.keywords._screenshot.subprocess")
        timer = mock.patch("MaestroLibrary.keywords._screenshot.threading.Timer")
        self.sp, self.timer = sp.start(), timer.start()
        self.addCleanup(sp.stop)
        self.addCleanup(timer.stop)
        self.sp.TimeoutExpired = subprocess.TimeoutExpired

    def test_ios_simulator_recording_wip(self):
        self.ios_recording()
        self.sp.Popen.return_value.poll.return_value = None
        self.run_kw("start_screen_recording", time_limit=timedelta(seconds=60))
        command = self.sp.Popen.call_args.args[0]
        self.assertEqual(command[:6], ["/usr/bin/xcrun", "simctl", "io", "SIM-1", "recordVideo", "--force"])
        self.assertEqual(self.timer.call_args.args[0], 60)  # simctl has no time limit of its own
        with open(command[6], "wb") as f:
            f.write(b"video")  # what simctl writes when interrupted
        path = self.run_kw("stop_screen_recording", "ios.mp4")
        self.sp.Popen.return_value.send_signal.assert_called_once()
        self.timer.return_value.cancel.assert_called_once()
        self.assertEqual(path, os.path.join(self.tmp, "ios.mp4"))
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.exists(command[6]))

    def test_ios_recorder_that_died_fails_stop_clearly(self):
        self.ios_recording()
        self.sp.Popen.return_value.poll.return_value = 1
        self.sp.Popen.return_value.returncode = 1
        self.run_kw("start_screen_recording")
        with self.assertRaisesRegex(AssertionError, r"recorder exited \(1\).*no video"):
            self.run_kw("stop_screen_recording")


class IOSTest(KeywordTest):
    def setUp(self):
        super().setUp()
        self.lib.platform, self.lib.device = "ios", "SIM-1"

    def test_android_only_keywords_fail_before_reaching_maestro(self):
        for name, args in [("execute_adb_shell", ["echo"]), ("go_back", []), ("set_airplane_mode", [True]),
                           ("press_key", ["Back"]), ("press_key", ["Power"]), ("press_key", ["Tab"]),
                           ("press_keycode", [4])]:
            with self.subTest(name, args=args), self.assertRaisesRegex(AssertionError, "needs an Android device"):
                self.run_kw(name, *args)
        self.assertFalse(os.path.exists(self.log))  # nothing reached Maestro

    # WIP: the iOS keywords below send what Maestro's docs describe; not run on iOS (no Mac).
    def test_ios_keywords_wip(self):
        self.run_kw("clear_keychain")
        self.run_kw("click_alert_button", "Don't Allow")
        self.run_kw("hide_keyboard", "Done")
        self.run_kw("hide_keyboard")
        self.assertEqual(self.steps(), ["clearKeychain", {"tapOn": {"text": "Don't\\ Allow"}},
                                        {"tapOn": {"text": "Done"}}, "hideKeyboard"])

    def test_keys_ios_has_still_work(self):
        self.run_kw("press_key", "Home")
        self.run_kw("press_keycode", 66)
        self.assertEqual(self.steps(), [{"pressKey": "Home"}, {"pressKey": "Enter"}])


if __name__ == "__main__":
    unittest.main()
