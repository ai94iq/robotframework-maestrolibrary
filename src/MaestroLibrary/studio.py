"""Maestro Studio-style recorder: act on the live device screen and get Robot Framework lines.

    pip install "robotframework-maestrolibrary[studio]"
    python -m MaestroLibrary.studio [--device ID] [--app APP_ID] [--max-size PX] [--video-encoder NAME]

Do not run it while a Robot run uses the same device: Maestro allows one session per device.
"""
import argparse
import base64
import json
import sys
import threading

from .flow2robot import SEP, escape
from .locators import best_locator, element_at, parse_bounds, walk
from .recorder import MASKED_INPUT

GAP = "    # GAP: no unique locator, ask for a test id"
ELEMENT_KINDS = {"click": "click_element", "long_press": "long_press",
                 "wait_visible": "wait_until_page_contains_element",
                 "should_be_visible": "element_should_be_visible", "text_should_be": "element_text_should_be"}
SIMPLE_KINDS = {"back": "go_back", "hide_keyboard": "hide_keyboard", "screenshot": "capture_page_screenshot"}
KINDS = set(ELEMENT_KINDS) | set(SIMPLE_KINDS) | {"type", "swipe", "launch"}
# Touch steps Studio sends to an Android device with adb: the device reacts in about 0.2 s, against 2 to 7 s for
# Maestro, which waits for the screen to settle (measured on a phone). The recorded line is the same either way.
TOUCH_KINDS = {"click", "long_press", "swipe", "back"}
KEYWORD_NAMES = {"click_element": "Click Element", "long_press": "Long Press",
                 "wait_until_page_contains_element": "Wait Until Page Contains Element",
                 "element_should_be_visible": "Element Should Be Visible",
                 "element_text_should_be": "Element Text Should Be", "swipe_by_percent": "Swipe By Percent",
                 "go_back": "Go Back", "hide_keyboard": "Hide Keyboard",
                 "open_application": "Open Application", "capture_page_screenshot": "Capture Page Screenshot"}


def arg(value):
    """A recorded argument: every variable escaped, since device texts must never run as Robot code."""
    return escape(str(value), keep_variables=False)


def no_maestro_js(text):
    if "${" in text:
        raise ValueError("Maestro would evaluate ${...} in this text as JavaScript; leave out the ${.")
    return text


def pct(tree, x, y):
    return round(100 * x / tree["width"]), round(100 * y / tree["height"])


def locate(tree, x, y):
    """(locator, comment) for the element at device point x, y; a percent point and the GAP note without one."""
    element = element_at(tree["elements"], x, y)
    locator = best_locator(element, tree["elements"]) if element else None
    if locator:
        return locator, ""
    px, py = pct(tree, x, y)
    return f"point={px}%,{py}%", GAP


class Session:
    """Runs studio actions on the device through MaestroLibrary and records the matching Robot lines."""

    def __init__(self, lib, app_id=None, reader=None):
        self.lib, self.app_id, self.lines, self.recording = lib, app_id, [], True
        self.reader = reader              # a faster tree read (driver.DriverReader), or None for inspect_screen
        self.lock = threading.RLock()   # one Maestro session: one action at a time
        self._tree, self._last_locator = None, None

    def tree(self, fresh=False):
        """The current screen (nested and flat) and its size; read again after a step, or when `fresh`."""
        tree = self._tree
        if fresh or tree is None:
            screen = self._screen()                         # up to seconds on a phone: outside the lock
            elements = list(walk(screen))
            root = max((parse_bounds(e.get("b")) or (0, 0, 0, 0) for e in elements),
                       key=lambda b: b[2] * b[3], default=(0, 0, 0, 0))
            tree = {"screen": screen, "elements": elements, "width": root[2] or 1, "height": root[3] or 1,
                    "platform": getattr(self.lib, "platform", None)}
            with self.lock:
                self._tree = tree
        return tree

    def _screen(self):
        if not self.reader:
            return self.lib.screen()
        try:
            return self.reader.screen()
        except Exception:                 # the driver is not up yet, or moved: Maestro's own read still works
            return self.lib.screen()

    def _run(self, keyword, args, comment=""):
        self.lib.run_keyword(keyword, list(args))          # raises: nothing is recorded
        return self._record(keyword, args, comment)

    def _record(self, keyword, args, comment=""):
        self._tree = None                                   # the screen changed
        if not self.recording:
            return None
        line = SEP.join([KEYWORD_NAMES[keyword]] + [arg(a) for a in args]) + comment
        self.lines.append(line)
        return line

    def preview(self, kind, tree, x=None, y=None, x2=None, y2=None, text=None, secret=False):
        """The line `act` would most likely record, from `tree` and without touching the device or the lock.
        Shown while the step runs; the line `act` returns replaces it."""
        if kind == "type":
            return SEP.join(["Input Text Into Current Element", MASKED_INPUT if secret else arg(text)])
        if kind in ELEMENT_KINDS:
            locator, comment = locate(tree, x, y)
            args = [locator] + ([text] if kind == "text_should_be" else [])
            return SEP.join([KEYWORD_NAMES[ELEMENT_KINDS[kind]]] + [arg(a) for a in args]) + comment
        if kind == "swipe":
            return SEP.join(["Swipe By Percent"] + [str(n) for n in (*pct(tree, x, y), *pct(tree, x2, y2))])
        if kind == "launch":
            return SEP.join(["Open Application", arg(self.app_id or getattr(self.lib, "app_id", "") or "")])
        return KEYWORD_NAMES[SIMPLE_KINDS[kind]]

    def touch(self, kind):
        """Whether `kind` runs through adb here: an Android touch step with adb available."""
        return kind in TOUCH_KINDS and getattr(self.lib, "platform", None) == "android" and bool(self.lib.adb())

    def _adb_input(self, *args):
        # every argument is an int or a fixed word: adb joins them into one device shell line
        if self.lib.adb_shell("input", *(str(int(a)) if not isinstance(a, str) else a for a in args),
                              purpose="sending a touch step", check=True) is None:
            raise AssertionError("adb did not run the step on the device.")

    def _touch(self, kind, tree, x, y, x2, y2):
        """Runs a touch step with adb and records the line Maestro would replay, located on `tree` (the screen
        the user acted on)."""
        if kind == "back":
            self._adb_input("keyevent", "4")
            self._last_locator = None
            return self._record("go_back", [])
        if kind == "swipe":
            self._adb_input("swipe", x, y, x2, y2, 300)
            self._last_locator = None
            return self._record("swipe_by_percent", [*pct(tree, x, y), *pct(tree, x2, y2)])
        locator, comment = locate(tree, x, y)
        if kind == "click":
            self._adb_input("tap", x, y)
        else:
            self._adb_input("swipe", x, y, x, y, 800)          # a long press is a swipe that stays put
        self._last_locator = locator if kind == "click" else None
        return self._record(ELEMENT_KINDS[kind], [locator], comment)

    def act(self, kind, x=None, y=None, x2=None, y2=None, text=None, secret=False, tree=None):
        """Runs one action; returns its recorded line (None while recording is off).

        With `tree` (the screen the user acted on), an Android touch step goes through adb and is located on it."""
        if kind not in KINDS:
            raise ValueError(f"Unknown action {kind!r}.")
        if tree is not None and self.touch(kind):
            with self.lock:
                return self._touch(kind, tree, x, y, x2, y2)
        with self.lock:
            if kind == "type":
                return self._type(no_maestro_js(str(text)), secret)
            if kind in ELEMENT_KINDS:
                expected = [no_maestro_js(str(text))] if kind == "text_should_be" else []
                locator, comment = locate(self.tree(), x, y)
                line = self._run(ELEMENT_KINDS[kind], [locator] + expected, comment)
                self._last_locator = locator if kind == "click" else None
                return line
            self._last_locator = None
            if kind == "swipe":
                return self._run("swipe_by_percent", [*pct(self.tree(), x, y), *pct(self.tree(), x2, y2)])
            if kind == "launch":
                return self._run("open_application", [self.app_id or self.lib.app_id])
            if kind == "screenshot":      # the test takes it when it runs; here it would only leave a stray file
                return self._record(SIMPLE_KINDS[kind], [])
            return self._run(SIMPLE_KINDS[kind], [])

    def _type(self, text, secret):
        """Types into the focused field; right after a click, the click line becomes Input Text/Password."""
        if secret:
            try:
                self.lib.run_commands({"inputText": text}, log=False)  # never logged
            except Exception as err:                                   # nor echoed in an error
                raise AssertionError(str(err).replace(text, "***")) from None
        else:
            self.lib.run_keyword("input_text_into_current_element", [text])
        self._tree = None
        locator, self._last_locator = self._last_locator, None
        if not self.recording:
            return None
        shown = MASKED_INPUT if secret else arg(text)
        if locator and self.lines and self.lines[-1].startswith("Click Element"):
            self.lines[-1] = SEP.join(["Input Password" if secret else "Input Text", arg(locator), shown])
        else:
            self.lines.append(SEP.join(["Input Text Into Current Element", shown]))
        return self.lines[-1]

    def undo(self):
        with self.lock:
            if self.lines:
                self.lines.pop()

    def remove(self, index):
        """Removes recorded line `index` (the action on the device is not undone)."""
        with self.lock:
            if 0 <= index < len(self.lines):
                del self.lines[index]

    def clear(self):
        with self.lock:
            self.lines = []

    def robot(self, name):
        """The recorded lines as a Robot test file."""
        title = arg(name.strip() or "Recorded Test")
        title = "\\" + title if title.startswith("*") else title      # a leading * would start a section
        return "\n".join(["*** Settings ***", "Library    MaestroLibrary", "", "*** Test Cases ***", title]
                         + [SEP + line for line in self.lines]) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m MaestroLibrary.studio", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", help="Maestro device id; default: the first connected device")
    parser.add_argument("--app", help="app id to launch first (recorded as Open Application)")
    parser.add_argument("--max-size", type=int, default=1080, help="live view size, longest side in px (default 1080)")
    parser.add_argument("--video-encoder", help="device video encoder for the live view, if the default misbehaves "
                                                "(list them with: scrcpy --list-encoders)")
    # for packaged builds; a windowed .exe has no console, so the report can go to a file
    parser.add_argument("--self-check", nargs="?", const="-", metavar="FILE", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication

        from . import studio_qt
    except ImportError as err:
        print(f'Studio needs its extra: pip install "robotframework-maestrolibrary[studio]" ({err})', file=sys.stderr)
        return 2
    if args.self_check:
        return self_check(studio_qt, args.self_check)
    from . import MaestroLibrary
    from .driver import DriverReader
    from .stream import ScrcpyStream

    app = QApplication.instance() or QApplication(sys.argv[:1])
    if sys.platform == "win32":      # its own taskbar button and icon, not Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MaestroLibrary.Studio")
    app.setWindowIcon(studio_qt.app_icon())
    lib = MaestroLibrary(device=args.device, run_on_failure="Nothing", logcat=False)
    window = thread = touch_thread = reader = None
    try:
        device = lib.device_id()
        reader = DriverReader(lib) if lib.adb() else None
        session = Session(lib, args.app, reader=reader)
        worker = studio_qt.ActionWorker(session)
        thread = QThread()
        worker.moveToThread(thread)
        thread.start()
        touch = studio_qt.ActionWorker(session, follow=worker)
        touch_thread = QThread()
        touch.moveToThread(touch_thread)
        touch_thread.start()

        def screenshot():
            content = lib.mcp.call_tool("take_screenshot", {"device_id": lib.device_id()})
            data = next(c["data"] for c in content if c.get("type") == "image")
            return studio_qt.QImage.fromData(base64.b64decode(data))

        def live_view(device, platform):
            if platform != "android" or not lib.adb():
                return None
            return studio_qt.StreamReader(ScrcpyStream(lib.adb(), device, max_size=args.max_size,
                                                       video_encoder=args.video_encoder))

        window = studio_qt.MainWindow(session, worker, device_name=device, platform=lib.platform,
                                      devices=connected_devices(lib), live_view=live_view, touch=touch)
        worker.screenshot = screenshot
        window.resize(1480, 940)
        window.show()
        window.start_live()
        if args.app:
            window.submit("launch", {})
        worker.request_poll()
        return app.exec()
    finally:
        if window:
            window.stop_live()
        for running in (thread, touch_thread):
            if running:
                running.quit()
                running.wait(10000)
        if reader:
            reader.close()
        lib.mcp.close()


GPL_LIBS = ("enable-gpl", "libx264", "libx265", "enable-nonfree")


def self_check(studio_qt, out="-"):
    """Checks a build without a device: Qt, PyAV and grpcio load, FFmpeg decodes H.264, and which tools are found.
    Writes the report to `out` ("-" for stdout); returns 0 when the decoder works."""
    import importlib.resources

    import grpc
    from av._core import library_meta      # the only place PyAV exposes FFmpeg's license and configure line

    from .mcp import find_exe
    codec = library_meta["libavcodec"]
    sample = importlib.resources.files(__package__).joinpath("studio_sample.h264").read_bytes()
    decoder = studio_qt.FrameDecoder()
    frames = decoder.feed(sample) + decoder.flush()
    report = [f"ffmpeg license: {codec['license']}",
              f"ffmpeg gpl or nonfree parts: {[p for p in GPL_LIBS if p in codec['configuration']] or 'none'}",
              f"grpcio {grpc.__version__}",
              f"decoded {len(frames)} frames" + (f" of {frames[0].width()}x{frames[0].height()}" if frames else "")]
    report += [f"{tool}: {find_exe(tool) or 'missing'}" for tool in ("maestro", "adb", "scrcpy")]
    if out == "-":
        print("\n".join(report))
    else:
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(report) + "\n")
    return 0 if frames else 1


def connected_devices(lib):
    """The connected devices as {device_id, name, type} (for the device dropdown); empty when Maestro's list cannot
    be read. Maestro's type is "real", "emulator" or "simulator"."""
    try:
        content = lib.mcp.call_tool("list_devices", {})
        return [{"device_id": str(d["device_id"]), "name": str(d.get("name") or d["device_id"]),
                 "type": str(d.get("type", "")), "platform": str(d.get("platform", ""))} for d in json.loads(content[0]["text"])["devices"] if d.get("connected")]
    except (LookupError, TypeError, ValueError):
        return []


if __name__ == "__main__":
    sys.exit(main())
