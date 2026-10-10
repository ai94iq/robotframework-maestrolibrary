"""Maestro Studio-style recorder: act on the live device screen and get Robot Framework lines.

    python -m MaestroLibrary.studio [--device ID] [--app APP_ID]

Do not run it while a Robot run uses the same device: Maestro allows one session per device.
"""
import threading
import time

from .flow2robot import SEP, escape
from .locators import best_locator, element_at, parse_bounds
from .recorder import MASKED_INPUT

TREE_MAX_AGE_S = 1.0
GAP = "    # GAP: no unique locator, ask for a test id"
ELEMENT_KINDS = {"click": "click_element", "long_press": "long_press",
                 "wait_visible": "wait_until_page_contains_element",
                 "should_be_visible": "element_should_be_visible", "text_should_be": "element_text_should_be"}
SIMPLE_KINDS = {"back": "go_back", "hide_keyboard": "hide_keyboard", "screenshot": "capture_page_screenshot"}
KINDS = set(ELEMENT_KINDS) | set(SIMPLE_KINDS) | {"type", "swipe", "launch"}
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


class Session:
    """Runs studio actions on the device through MaestroLibrary and records the matching Robot lines."""

    def __init__(self, lib, app_id=None):
        self.lib, self.app_id, self.lines, self.recording = lib, app_id, [], True
        self.lock = threading.RLock()   # one Maestro session: one action at a time
        self._tree, self._at, self._last_locator = None, 0.0, None

    def tree(self):
        """The current screen's flat element list and size, fetched again when older than a second."""
        with self.lock:
            if self._tree is None or time.monotonic() - self._at > TREE_MAX_AGE_S:
                elements = self.lib.elements()
                root = max((parse_bounds(e.get("b")) or (0, 0, 0, 0) for e in elements),
                           key=lambda b: b[2] * b[3], default=(0, 0, 0, 0))
                self._tree = {"elements": elements, "width": root[2] or 1, "height": root[3] or 1,
                              "platform": getattr(self.lib, "platform", None)}
                self._at = time.monotonic()
            return self._tree

    def _pct(self, x, y):
        t = self.tree()
        return round(100 * x / t["width"]), round(100 * y / t["height"])

    def _locate(self, x, y):
        t = self.tree()
        element = element_at(t["elements"], x, y)
        locator = best_locator(element, t["elements"]) if element else None
        if locator:
            return locator, ""
        px, py = self._pct(x, y)
        return f"point={px}%,{py}%", GAP

    def _run(self, keyword, args, comment=""):
        self.lib.run_keyword(keyword, list(args))          # raises: nothing is recorded
        self._tree = None                                   # the screen changed
        if not self.recording:
            return None
        line = SEP.join([KEYWORD_NAMES[keyword]] + [arg(a) for a in args]) + comment
        self.lines.append(line)
        return line

    def act(self, kind, x=None, y=None, x2=None, y2=None, text=None, secret=False):
        """Runs one action; returns its recorded line (None while recording is off)."""
        if kind not in KINDS:
            raise ValueError(f"Unknown action {kind!r}.")
        with self.lock:
            if kind == "type":
                return self._type(no_maestro_js(str(text)), secret)
            if kind in ELEMENT_KINDS:
                expected = [no_maestro_js(str(text))] if kind == "text_should_be" else []
                locator, comment = self._locate(x, y)
                line = self._run(ELEMENT_KINDS[kind], [locator] + expected, comment)
                self._last_locator = locator if kind == "click" else None
                return line
            self._last_locator = None
            if kind == "swipe":
                return self._run("swipe_by_percent", [*self._pct(x, y), *self._pct(x2, y2)])
            if kind == "launch":
                return self._run("open_application", [self.app_id or self.lib.app_id])
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

    def clear(self):
        with self.lock:
            self.lines = []

    def robot(self, name):
        """The recorded lines as a Robot test file."""
        title = arg(name.strip() or "Recorded Test")
        title = "\\" + title if title.startswith("*") else title      # a leading * would start a section
        return "\n".join(["*** Settings ***", "Library    MaestroLibrary", "", "*** Test Cases ***", title]
                         + [SEP + line for line in self.lines]) + "\n"
