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

    def elements(self):
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

    def test_stale_tree_refreshes(self):
        calls = []
        self.lib.elements = lambda: calls.append(1) or SCREEN
        with mock.patch("MaestroLibrary.studio.time.monotonic", side_effect=[0, 0.5, 5, 5]):
            self.s.tree(); self.s.tree(); self.s.tree()    # fetched at 0; 0.5 s old: kept; 5 s old: fetched
        self.assertEqual(len(calls), 2)

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
            s = stream.ScrcpyStream("adb", "SER", port=27183)
            s.start()
            cmds = [c.args[0] for c in run.call_args_list]
            self.assertIn(["adb", "-s", "SER", "push", "/x/scrcpy-server", "/data/local/tmp/scrcpy-server.jar"], cmds)
            self.assertIn(["adb", "-s", "SER", "forward", "tcp:27183", "localabstract:scrcpy"], cmds)
            launched = popen.call_args.args[0]
            self.assertEqual(launched[:9], ["adb", "-s", "SER", "shell", "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
                                            "app_process", "/", "com.genymobile.scrcpy.Server", "5.0"])
            self.assertIn("raw_stream=true", launched)
            self.assertEqual(s.read(), b"\0\0\0\1\x67")           # the probe's bytes are not lost
            s.stop()
            self.assertIn(["adb", "-s", "SER", "forward", "--remove", "tcp:27183"],
                          [c.args[0] for c in run.call_args_list])

    def test_shell_arguments_are_validated(self):
        from MaestroLibrary import stream
        with self.assertRaisesRegex(ValueError, "device"):
            stream.ScrcpyStream("adb", "SER;reboot")
        with self.assertRaisesRegex(ValueError, "max_size"):
            stream.ScrcpyStream("adb", "SER", max_size="1080;reboot")
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
                self.assertEqual(stream.server_file(), (server, "5.0"))
                answer.stdout = "fake 1.0"
                with self.assertRaisesRegex(RuntimeError, "does not answer like scrcpy"):
                    stream.server_file()
                answer.stdout = "scrcpy 5.0 <https://github.com/Genymobile/scrcpy>\n"
                os.remove(server)
                with self.assertRaisesRegex(RuntimeError, "SCRCPY_SERVER_PATH"):
                    stream.server_file()


class HttpTest(unittest.TestCase):
    def setUp(self):
        import threading
        from MaestroLibrary.studio import Session, make_server
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, cwd)
        self.lib = FakeLib(SCREEN)
        self.server, self.token = make_server(Session(self.lib), stream_factory=None,
                                              screenshot=lambda: b"\xff\xd8jpeg", port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def req(self, method, path, body=None, token=True, headers=None):
        import http.client
        import json
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request(method, path, json.dumps(body) if body is not None else None,
                     {**({"X-Token": self.token} if token else {}), **(headers or {})})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data, response

    def json(self, *args, **kwargs):
        import json
        return json.loads(self.req(*args, **kwargs)[1])

    def test_page_and_actions(self):
        status, page, _ = self.req("GET", f"/?t={self.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"<canvas", page)
        self.assertEqual(self.json("POST", "/act", {"kind": "back"}), {"line": "Go Back"})
        self.assertEqual(self.req("GET", "/stream")[0], 503)
        self.assertEqual(self.req("GET", "/screenshot")[1], b"\xff\xd8jpeg")
        self.assertEqual(self.json("GET", "/inspect?x=500&y=200")["locators"],
                         [["id=com.app:id/search", 1], ["text=Search", 1]])
        self.assertEqual(self.json("GET", "/inspect?x=500&y=2300"), {"element": None, "locators": []})
        self.assertEqual(self.json("GET", "/tree")["width"], 1080)

    def test_record_toggle_undo_clear_and_robot(self):
        self.req("POST", "/act", {"kind": "back"})
        self.req("POST", "/act", {"kind": "hide_keyboard"})
        self.req("POST", "/undo")
        self.assertIn(b"My Test\n    Go Back\n", self.req("GET", "/robot?name=My%20Test")[1])
        self.req("POST", "/record", {"on": False})
        self.assertEqual(self.json("POST", "/act", {"kind": "back"}), {"line": None})
        self.req("POST", "/clear")
        self.assertTrue(self.req("GET", "/robot?name=T")[1].endswith(b"*** Test Cases ***\nT\n"))

    def test_device_failure_is_409_and_records_nothing(self):
        self.lib.fail = "Element not found"
        status, body, _ = self.req("POST", "/act", {"kind": "click", "x": 500, "y": 200})
        self.assertEqual(status, 409)
        self.assertIn(b"Element not found", body)

    def test_save_only_robot_files_inside_cwd(self):
        self.req("POST", "/act", {"kind": "back"})
        self.assertEqual(self.req("POST", "/save", {"path": "t.robot", "name": "T"})[0], 200)
        with open("t.robot", encoding="utf-8") as f:
            self.assertIn("    Go Back", f.read())
        for bad in ("../x.robot", os.path.abspath("../y.robot"), "t.py", "a\0.robot", 5):
            self.assertEqual(self.req("POST", "/save", {"path": bad, "name": "T"})[0], 400, bad)

    def test_token_is_required_everywhere(self):                                     # S1
        self.assertEqual(self.req("GET", "/", token=False)[0], 403)
        self.assertEqual(self.req("GET", "/?t=wrong", token=False)[0], 403)
        for method, path in (("GET", "/tree"), ("GET", "/stream"), ("GET", "/screenshot"),
                             ("GET", "/robot?name=T"), ("GET", "/inspect?x=1&y=1"), ("POST", "/act")):
            self.assertEqual(self.req(method, path, {"kind": "back"}, token=False)[0], 403, path)
        self.assertEqual(self.lib.ran, [])

    def test_foreign_host_is_refused(self):                                          # S2
        self.assertEqual(self.req("GET", f"/?t={self.token}", token=False, headers={"Host": "evil.example"})[0], 403)

    def test_bad_input_is_400(self):                                                 # S3
        for body in ({"kind": "__import__"}, {"kind": "click", "x": "1;rm", "y": 1}, {"kind": "click", "x": True, "y": 1},
                     {"kind": "type", "text": 5}, {"kind": "back", "extra": 1}, ["back"]):
            self.assertEqual(self.req("POST", "/act", body)[0], 400, body)
        self.assertEqual(self.lib.ran, [])

    def test_big_body_is_413(self):                                                  # S9
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.putrequest("POST", "/act")
        conn.putheader("X-Token", self.token)
        conn.putheader("Content-Length", "100000")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()

    def test_security_headers(self):                                                 # S8
        response = self.req("GET", f"/?t={self.token}", token=False)[2]
        csp = response.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.getheader("Cache-Control"), "no-store")


class MainTest(unittest.TestCase):
    def test_main_launches_serves_and_closes_maestro(self):
        import MaestroLibrary
        from MaestroLibrary import studio
        lib = FakeLib(SCREEN)
        lib.device_id, lib.mcp, lib.platform = (lambda: "SER"), mock.Mock(), "android"
        server = mock.Mock(server_port=8787)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(MaestroLibrary, "MaestroLibrary", return_value=lib), \
                mock.patch.object(studio, "make_server", return_value=(server, "TOKEN")) as make, \
                mock.patch.object(studio.webbrowser, "open") as browser, mock.patch("builtins.print"):
            self.assertEqual(studio.main(["--app", "com.app"]), 0)
        browser.assert_called_once_with("http://127.0.0.1:8787/?t=TOKEN")
        self.assertEqual(lib.ran, [("open_application", ["com.app"])])
        server.server_close.assert_called_once()
        lib.mcp.close.assert_called_once()
        session, stream_factory, screenshot, port = make.call_args.args
        self.assertEqual(port, 8787)
        lib.platform = "ios"
        with self.assertRaisesRegex(RuntimeError, "Android only"):
            stream_factory()
        lib.mcp.call_tool.return_value = [{"type": "image", "data": "/9g="}]
        self.assertEqual(screenshot(), b"\xff\xd8")


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
