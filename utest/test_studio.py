import os
import sys
import tempfile
import unittest
from unittest import mock

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


class FakeLib:
    def __init__(self, elements):
        self._elements, self.ran, self.app_id, self.fail = elements, [], "com.app", None
        self.device, self.platform, self.device_switches = "SER", "android", []
        self.adb_path, self.shell = None, []

    def adb(self):
        return self.adb_path

    def adb_shell(self, *args, purpose):
        self.shell.append(args)
        return ""

    def device_id(self):
        if self.platform is None:              # set to None by a device switch: resolve it again
            if self.device == "GONE":
                raise RuntimeError("Device 'GONE' is not connected.")
            self.device_switches.append(self.device)
            self.platform = "android"
        return self.device

    def screen(self):
        return self._elements

    def run_keyword(self, name, args, kwargs=None):
        if self.fail:
            raise AssertionError(self.fail)
        self.ran.append((name, list(args)))

    def run_commands(self, *commands, app_id=None, log=True):
        self.ran.append(("run_commands", list(commands), log))


class SessionTest(unittest.TestCase):
    def setUp(self):
        from MaestroLibrary.studio import Session
        self.lib = FakeLib(SCREEN)
        self.s = Session(self.lib)

    def test_click_runs_and_records(self):
        self.assertEqual(self.s.act("click", 500, 200), r"Click Element    id\=com.app:id/search")
        self.assertEqual(self.lib.ran, [("click_element", ["id=com.app:id/search"])])

    def test_no_unique_locator_records_point_with_gap(self):
        self.assertEqual(self.s.act("click", 540, 500),
                         r"Click Element    point\=50%,21%    # GAP: no unique locator, ask for a test id")
        self.assertEqual(self.lib.ran, [("click_element", ["point=50%,21%"])])

    def test_preview_matches_the_recorded_line(self):
        for kind, kw in (("click", {"x": 500, "y": 200}), ("click", {"x": 540, "y": 500}), ("back", {}),
                         ("swipe", {"x": 540, "y": 1800, "x2": 540, "y2": 600}),
                         ("text_should_be", {"x": 500, "y": 200, "text": "Search @{x}"})):
            planned = self.s.preview(kind, self.s.tree(), **kw)
            self.assertEqual(planned, self.s.act(kind, **kw))
        self.assertEqual(self.s.preview("type", self.s.tree(), text="pw", secret=True),
                         "Input Text Into Current Element    ${PASSWORD}")

    def test_android_touch_steps_go_through_adb_with_the_same_lines(self):
        maestro = [self.s.act(k, **kw) for k, kw in (("click", {"x": 500, "y": 200}), ("back", {}),
                                                      ("swipe", {"x": 540, "y": 1800, "x2": 540, "y2": 600}),
                                                      ("long_press", {"x": 500, "y": 200}))]
        self.lib.adb_path, self.lib.ran = "adb", []
        tree = self.s.tree()
        fast = [self.s.act(k, tree=tree, **kw) for k, kw in (("click", {"x": 500.4, "y": 200}), ("back", {}),
                                                               ("swipe", {"x": 540, "y": 1800, "x2": 540, "y2": 600}),
                                                               ("long_press", {"x": 500, "y": 200}))]
        self.assertEqual(fast, maestro)
        self.assertEqual(self.lib.ran, [])                      # no Maestro call
        self.assertEqual(self.lib.shell, [("input", "tap", "500", "200"), ("input", "keyevent", "4"),
                                          ("input", "swipe", "540", "1800", "540", "600", "300"),
                                          ("input", "swipe", "500", "200", "500", "200", "800")])

    def test_typing_after_an_adb_click_merges_into_input_text(self):
        self.lib.adb_path = "adb"
        self.s.act("click", 500, 200, tree=self.s.tree())
        self.s.act("type", text="wifi")
        self.assertEqual(self.s.lines, [r"Input Text    id\=com.app:id/search    wifi"])

    def test_without_adb_touch_steps_use_maestro(self):
        self.s.act("click", 500, 200, tree=self.s.tree())
        self.assertEqual(self.lib.ran, [("click_element", ["id=com.app:id/search"])])

    def test_screenshot_is_recorded_without_running(self):
        self.assertEqual(self.s.act("screenshot"), "Capture Page Screenshot")
        self.assertEqual(self.lib.ran, [])

    def test_blank_space_records_point(self):
        self.assertTrue(self.s.act("click", 500, 2300).startswith(r"Click Element    point\=46%,96%"))

    def test_typing_after_click_merges_into_input_text(self):
        self.s.act("click", 500, 200)
        self.s.act("type", text="wifi")
        self.assertEqual(self.s.lines, [r"Input Text    id\=com.app:id/search    wifi"])
        self.assertEqual(self.lib.ran[-1], ("input_text_into_current_element", ["wifi"]))

    def test_typing_without_click_types_into_current_element(self):
        self.s.act("back")
        self.s.act("type", text="wifi")
        self.assertEqual(self.s.lines, ["Go Back", "Input Text Into Current Element    wifi"])

    def test_secret_typing_is_never_logged_or_recorded(self):
        self.s.act("click", 500, 200)
        line = self.s.act("type", text="hunter2", secret=True)
        self.assertEqual(self.s.lines, [r"Input Password    id\=com.app:id/search    ${PASSWORD}"])
        self.assertEqual(self.lib.ran[-1], ("run_commands", [{"inputText": "hunter2"}], False))
        self.assertNotIn("hunter2", line)

    def test_secret_is_scrubbed_from_device_errors(self):
        def fail(*commands, **kwargs):
            raise RuntimeError("could not type hunter2")
        self.lib.run_commands = fail
        with self.assertRaises(AssertionError) as caught:
            self.s.act("type", text="hunter2", secret=True)
        self.assertEqual(str(caught.exception), "could not type ***")

    def test_maestro_js_in_typed_text_is_refused(self):
        with self.assertRaisesRegex(ValueError, "JavaScript"):
            self.s.act("type", text="${1+1}")
        with self.assertRaisesRegex(ValueError, "JavaScript"):
            self.s.act("text_should_be", 500, 200, text="${output.x}")
        self.assertEqual(self.lib.ran, [])

    def test_device_text_cannot_inject_robot_code(self):
        from MaestroLibrary.studio import Session
        evil = [{"b": "[0,0][1080,2400]"}, {"b": "[0,0][100,100]", "txt": "${{__import__('os').getcwd()}}"}]
        line = Session(FakeLib(evil)).act("click", 50, 50)
        self.assertEqual(line, r"Click Element    text\=\${{__import__('os').getcwd()}}")

    def test_newlines_cannot_add_robot_sections(self):
        self.s.act("type", text="a\n*** Settings ***\nLibrary  OperatingSystem")
        self.assertEqual(self.s.robot("T").count("\n"), 6)
        self.assertEqual(self.s.lines,
                         [r"Input Text Into Current Element    a\n*** Settings ***\nLibrary \ OperatingSystem"])

    def test_failure_records_nothing(self):
        self.lib.fail = "Element not found"
        with self.assertRaisesRegex(AssertionError, "not found"):
            self.s.act("click", 500, 200)
        self.assertEqual(self.s.lines, [])

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            self.s.act("__import__")
        self.assertEqual(self.lib.ran, [])

    def test_swipe_toolbar_and_assertions(self):
        self.s.act("swipe", 540, 1800, 540, 600)
        self.s.act("back")
        self.s.act("text_should_be", 500, 200, text="Search")
        self.assertEqual(self.s.lines, ["Swipe By Percent    50    75    50    25", "Go Back",
                                        r"Element Text Should Be    id\=com.app:id/search    Search"])

    def test_launch_uses_app_id(self):
        self.assertEqual(self.s.act("launch"), "Open Application    com.app")

    def test_recording_off_runs_but_records_nothing(self):
        self.s.recording = False
        self.assertIsNone(self.s.act("back"))
        self.assertEqual(self.s.lines, [])
        self.assertEqual(self.lib.ran, [("go_back", [])])

    def test_tree_is_read_again_only_after_a_step_or_when_fresh(self):
        calls = []
        self.lib.screen = lambda: calls.append(1) or SCREEN
        self.s.tree(); self.s.tree()                     # cached: Maestro's settle wait costs seconds
        self.assertEqual(len(calls), 1)
        self.s.act("back"); self.s.tree()                # a step changed the screen
        self.s.tree(fresh=True)                          # the window's poll
        self.assertEqual(len(calls), 3)

    def test_undo_clear_and_robot_file(self):
        self.s.act("back"); self.s.act("hide_keyboard"); self.s.undo()
        self.assertEqual(self.s.robot("My Test"),
                         "*** Settings ***\nLibrary    MaestroLibrary\n\n*** Test Cases ***\nMy Test\n    Go Back\n")
        self.s.clear()
        self.assertEqual(self.s.lines, [])


class StreamTest(unittest.TestCase):
    def test_start_pushes_forwards_launches_and_stop_cleans_up(self):
        from MaestroLibrary import stream
        sock = mock.Mock()
        sock.recv.side_effect = [b"", b"\0\0\0\1\x67"]           # the first connect is closed: not ready yet
        with mock.patch.object(stream.subprocess, "run") as run, \
                mock.patch.object(stream.subprocess, "Popen") as popen, \
                mock.patch.object(stream.socket, "create_connection", return_value=sock), \
                mock.patch.object(stream.time, "sleep"), \
                mock.patch.object(stream, "server_file", return_value=("/x/scrcpy-server", "5.0")):
            run.return_value.stdout = b"40123\n"                    # adb forward tcp:0 prints the port it chose
            s = stream.ScrcpyStream("adb", "SER")
            s.start()
            cmds = [c.args[0] for c in run.call_args_list]
            self.assertIn(["adb", "-s", "SER", "push", "/x/scrcpy-server", "/data/local/tmp/scrcpy-server.jar"], cmds)
            self.assertIn(["adb", "-s", "SER", "forward", "tcp:0", f"localabstract:scrcpy_{s.scid}"], cmds)
            self.assertRegex(s.scid, r"^[0-9a-f]{8}$")
            self.assertEqual(s.port, 40123)
            launched = popen.call_args.args[0]
            self.assertEqual(launched[:10], ["adb", "-s", "SER", "shell", "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
                                             "app_process", "/", "com.genymobile.scrcpy.Server", "5.0", f"scid={s.scid}"])
            self.assertIn("raw_stream=true", launched)
            self.assertFalse(any(a.startswith("video_encoder=") for a in launched))
            self.assertEqual(s.read(), b"\0\0\0\1\x67")             # the probe's bytes are not lost
            s.stop()
            self.assertIn(["adb", "-s", "SER", "forward", "--remove", "tcp:40123"],
                          [c.args[0] for c in run.call_args_list])
            self.assertNotEqual(stream.ScrcpyStream("adb", "SER").scid, s.scid)
            sock.recv.side_effect = [b"\0\0\0\1\x67"]
            stream.ScrcpyStream("adb", "SER", video_encoder="OMX.qcom.video.encoder.avc").start()
            self.assertIn("video_encoder=OMX.qcom.video.encoder.avc", popen.call_args.args[0])

    def test_shell_arguments_are_validated(self):
        from MaestroLibrary import stream
        with self.assertRaisesRegex(ValueError, "device"):
            stream.ScrcpyStream("adb", "SER;reboot")
        with self.assertRaisesRegex(ValueError, "max_size"):
            stream.ScrcpyStream("adb", "SER", max_size="1080;reboot")
        with self.assertRaisesRegex(ValueError, "encoder"):
            stream.ScrcpyStream("adb", "SER", video_encoder="OMX.x;reboot")
        with mock.patch.object(stream, "server_file", return_value=("/x/s", "5.0;reboot")), \
                mock.patch.object(stream.subprocess, "run"), mock.patch.object(stream.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "version"):
                stream.ScrcpyStream("adb", "SER").start()
            popen.assert_not_called()

    def test_server_file_lookup(self):
        from MaestroLibrary import stream
        with mock.patch.object(stream, "find_exe", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "scrcpy is not on PATH"):
                stream.server_file()
        with tempfile.TemporaryDirectory() as tmp:
            exe, server = os.path.join(tmp, "scrcpy"), os.path.join(tmp, "scrcpy-server")
            open(server, "w").close()
            answer = mock.Mock(stdout="scrcpy 5.0 <https://github.com/Genymobile/scrcpy>\n")
            with mock.patch.object(stream, "find_exe", return_value=exe), \
                    mock.patch.object(stream.subprocess, "run", return_value=answer), \
                    mock.patch.dict(os.environ, {"SCRCPY_SERVER_PATH": ""}):
                found, version = stream.server_file()
                self.assertEqual((os.path.realpath(found), version), (os.path.realpath(server), "5.0"))   # macOS: /var is /private/var
                answer.stdout = "fake 1.0"
                with self.assertRaisesRegex(RuntimeError, "does not answer like scrcpy"):
                    stream.server_file()
                answer.stdout = "scrcpy 5.0 <https://github.com/Genymobile/scrcpy>\n"
                os.remove(server)
                with self.assertRaisesRegex(RuntimeError, "SCRCPY_SERVER_PATH"):
                    stream.server_file()


class EscapeTest(unittest.TestCase):
    def test_flow2robot_keeps_only_plain_variables(self):
        from MaestroLibrary.flow2robot import escape
        self.assertEqual(escape("${USER}"), "${USER}")
        self.assertEqual(escape("${{1}}"), r"\${{1}}")
        self.assertEqual(escape("%{HOME}"), r"\%{HOME}")
        self.assertEqual(escape("@{x} &{y}"), r"\@{x} \&{y}")
        self.assertEqual(escape("${USER}", keep_variables=False), r"\${USER}")


if __name__ == "__main__":
    unittest.main()
