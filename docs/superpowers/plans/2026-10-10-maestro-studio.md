# MaestroLibrary Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Copy this file to `robotframework-maestrolibrary/docs/superpowers/plans/2026-10-10-maestro-studio.md` as the first execution step.

**Goal:** `python -m MaestroLibrary.studio` opens a local page with the live device screen. You act on that screen (click, long-press, drag, type, toolbar) and every action runs on the device through MaestroLibrary while the matching Robot keyword line is recorded, ready to save as a `.robot` test.

**Architecture:** One stdlib HTTP server (`ThreadingHTTPServer`, 127.0.0.1 only) serves one HTML page. The live screen is scrcpy's raw H.264 stream (the scrcpy-server that ships with scrcpy), relayed as a chunked HTTP response and decoded in the browser with WebCodecs. Hit-testing uses Maestro's `inspect_screen` tree, and actions run through `MaestroLibrary.run_keyword`, so the recorded line is exactly what ran. No new dependencies.

**Tech Stack:** Python 3.10+ stdlib, MaestroLibrary (`run_keyword`, `elements()`, `locators.matches/to_selector/walk`, `flow2robot.escape`), scrcpy 5.0 server over adb, browser WebCodecs `VideoDecoder` (Chrome/Edge), vanilla JS.

**Spec:** the user's answers in this session:
- live device screen with a step recorder, like Maestro Studio
- clicking runs the action and appends the line
- the user never types Robot; they act on the device and the keywords are written for them
- it ships in the library

Maestro Studio (docs.maestro.dev) works by right-clicking an element, which offers a command menu and appends that command, then running step by step. Google Artemis is a natural-language AI driver, a different model; it is out of scope.

Appium Inspector (Apache-2.0, Electron; docs 2025.8) contributes several ideas:
- the screenshot panel's two modes: **Element Mode** (hover highlights, click selects) and **Coordinates Mode** (click and swipe act on the device)
- **Element Handles** toggle
- the **Source** tree linked to the screen
- the **Selected Element** panel, with action buttons (Tap, Send/Clear text), **Suggested Locators** and **Element Attributes**
- the **Recorder** with a header **Toggle Recorder**, plus Copy and Clear (Clear does not change the recording state)

Its screen is static between refreshes unless you set up MJPEG. Ours is live through scrcpy, which is the gap this tool fills. Its recorder outputs Appium client code; ours outputs MaestroLibrary Robot lines.

## Measured on the phone (Samsung A70, Android 15, 1080x2400), 2026-10-10

| Source | Time per frame | Notes |
|---|---|---|
| MCP `take_screenshot` | 2.3 s | JPEG, 900x2000 |
| `adb exec-out screencap -p` | 2.2 s | PNG |
| `adb exec-out screencap` (raw) | 0.8-1.0 s | 10 MB per frame |
| MCP `inspect_screen` | 0.36 s | gives bounds in device pixels, e.g. `[0,2274][1080,2400]` |
| scrcpy-server 5.0 raw stream (Task 3 spike) | live | `app_process / com.genymobile.scrcpy.Server 5.0 tunnel_forward=true audio=false control=false raw_stream=true video_codec=h264 max_size=1080`; first bytes after ~1.5-1.8 s (adb accepts the forward before the server listens, so wait for bytes); NAL 7, 8, 5 then 1; codec avc1.42800a; the server exits with the adb shell |

None of the screenshot sources is fast enough to feel live, so the plan uses scrcpy's stream. `scrcpy-server` sits next to `scrcpy.exe` (here `C:\adb\scrcpy-server`), and `SCRCPY_SERVER_PATH` overrides it.

## Global Constraints

- Python floor: `requires-python = ">=3.10"`. No f-strings with backslashes inside `{}`, and no 3.11+ stdlib features.
- No new runtime or optional dependency.
- The server binds `127.0.0.1` only. Every POST must carry the per-run token from the page URL (`?t=<token>`); otherwise it returns 403 (CSRF guard).
- Only one Maestro session per device: Studio must not run while a Robot run is using the device. Docs and the startup message say so.
- Secrets: text typed with "secret" on is recorded as `${PASSWORD}` and is never logged or echoed.
- Plain ASCII in code, docs and commits. Commit format: `robotframework-maestrolibrary: <type>: <title>`, with a body that says what was verified.
- Checks before every commit: `python -m pytest -q utest`, `python -m coverage run --branch --source=src/MaestroLibrary -m pytest -q utest && python -m coverage report --fail-under=85`, `python -m bandit -q -c pyproject.toml -r src`, `python -m robot --dryrun --pythonpath src --output NONE --report NONE --log NONE atest`.

## Review Focus

1. **Element with no unique locator** (Flutter rows, icons): record `point=x%,y%` with a `# GAP` comment rather than a wrong match. Test in Task 2.
2. **Click on blank space, or between element boxes**: pick the smallest locatable element under the point. If there is none, record a point tap. Test in Task 2.
3. **The screen changes between the hit test and the click** (animation, navigation): the tree is refreshed after every action and before a hit test that is more than 1 s old. Test in Task 3 (stale tree refresh).
4. **A keyword fails on the device** (element gone): nothing is recorded, and the error is shown in the page. Test in Task 3.
5. **The stream drops** (device unplugged, or scrcpy is missing): the page shows "no live view" and falls back to a Maestro screenshot after each action. Recording keeps working. Test in Task 4 (stream unavailable gives 503, and the page falls back).

The Task 3 spike settles one open question, which must not be assumed: the exact scrcpy-server arguments for a raw H.264 stream on scrcpy 5.0.

## Security (RCE and exploit review)

This adds no new libraries. If one ever becomes necessary, it starts at the latest stable release, checked live with `pip index versions <pkg>`, and goes through `pip-audit`.

Threat model:
- a local HTTP server that any web page in the user's browser can reach
- device content (app texts and ids) under an app author's control
- a saved `.robot` file that is executed later

Each risk below is covered in the code, with a test in the task that owns that code.

| # | Risk | Guard | Test (task) |
|---|---|---|---|
| S1 | **CSRF / cross-site reads**: another page calls `127.0.0.1:8787` | Per-run token (`secrets.token_urlsafe(32)`) required on **every** endpoint: `?t=` for `/` and the `X-Token` header for all others (the page's fetches send it), compared with `hmac.compare_digest`. A missing or wrong token gets 403. | T4 |
| S2 | **DNS rebinding**: an evil domain resolving to 127.0.0.1 | Accept only `Host` in {`127.0.0.1:<port>`, `localhost:<port>`}; otherwise 403. The token also blocks it. | T4 |
| S3 | **Arbitrary keyword or command execution from a request** | The client sends a `kind` only. The keyword name comes from a server-side dict, and an unknown `kind` gets 400. Client strings never become a keyword name, a file path other than `/save`'s, or a process argument. | T2, T4 |
| S4 | **Remote shell injection on the device**: `adb shell` joins its arguments into one device shell command line | Validate everything placed after `adb shell`: scrcpy version `^\d+(\.\d+)*$`, `max_size` int, device serial `^[\w.:-]+$`. Refuse otherwise. No `shell=True` anywhere. | T3 |
| S5 | **Robot code injection on replay**: device text such as `${{__import__('os').system('...')}}` becomes a locator or expected text, and Robot evaluates `${{ }}` as Python when the saved test runs | Studio escapes every variable start in recorded arguments (`$ @ & %` followed by `{`, giving `\${`). Only the `${PASSWORD}` placeholder it inserts itself stays raw. Also tighten `flow2robot.escape`: keep only plain `${NAME}` (`\w+`) unescaped, and escape `${{`, `@{`, `&{`, `%{` and the rest. | T2 (Studio), T2 extra test for flow2robot |
| S6 | **Robot file structure injection**: text with a newline and `*** Settings ***` | `escape()` turns newlines into `\n` and escapes a leading `#` and spaces. Test that a device text with `\n*** Settings ***\nLibrary  OperatingSystem` stays on one line. | T2 |
| S7 | **Path traversal and arbitrary write via `/save`** | `realpath` inside `realpath(cwd) + os.sep` (symlinks resolved), `.robot` extension required, no NUL bytes, the file is written as UTF-8 text. Otherwise 400. | T4 |
| S8 | **XSS in the page**: device texts rendered in the source tree, element panel and recorder | Use `textContent` and `createElement` only, never `innerHTML` or `insertAdjacentHTML` with data. CSP with a per-run nonce: `default-src 'none'; script-src 'nonce-X'; style-src 'nonce-X'; connect-src 'self'; img-src 'self' blob: data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`. Also `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. | T4 (headers), T5 (grep) |
| S9 | **Request DoS**: a huge body or slowloris | Reject `Content-Length` over 64 KiB with 413. Request socket timeout 30 s. JSON parsed with `json.loads` only. | T4 |
| S10 | **Secret leakage**: secret typing logged or echoed | The secret path calls `lib.run_commands({"inputText": text}, log=False)`. It is never in `lines`, the HTTP response or stdout (`${PASSWORD}` is shown instead). | T2 |
| S11 | **Maestro JS evaluation**: Maestro evaluates `${...}` in flow strings as JavaScript | Typed text and expected texts that contain `${` are refused by `/act` with 400 ("Maestro would evaluate it"). The user can still record them by hand in a resource. | T2 |
| S12 | **Exposure beyond localhost** | Bind `127.0.0.1` only. No `--host` option. | T4 |

Task 6 adds a final security pass:
- `bandit -r src` must be clean.
- `pip-audit` must pass.
- Grep the diff for `shell=True|eval\(|exec\(|innerHTML|insertAdjacentHTML|pickle|yaml\.load\(|os\.system|subprocess\..*\+`. Each hit is justified or removed.
- Re-read every request handler against S1 to S12.

## Platforms (Windows, Linux, macOS)

- **scrcpy-server lookup (`stream.server_file`):** `SCRCPY_SERVER_PATH` first, then these candidates, taking the first that exists:
  - next to the scrcpy executable (Windows zip, Linux static release)
  - `<prefix>/share/scrcpy/scrcpy-server`, where `<prefix>` is the executable's `../` (apt, `/usr/local` builds, Homebrew `$(brew --prefix)`)
  - `/usr/share/scrcpy/scrcpy-server`
  - `/usr/local/share/scrcpy/scrcpy-server`
  - `/opt/homebrew/share/scrcpy/scrcpy-server`

  If none exists, raise `RuntimeError` naming `SCRCPY_SERVER_PATH`.
- **adb:** reuse `MaestroLibrary.adb()`, which already resolves and verifies adb on every OS.
- **iOS simulator (macOS):** there is no scrcpy for iOS, so the live view is the screenshot fallback (MCP `take_screenshot` works for simulators), with the status line "live view is Android only". Back is disabled when `lib.platform == "ios"`. The library's iOS support is already marked WIP, and the docs must say so.
- **Process stop:** `Popen.terminate()` on the local `adb shell` process. Ending the adb shell ends the remote server on current adb; Step 1 of Task 3 checks this with `adb shell pidof app_process` after stop. If the process survives, kill the remote pid.
- **Browser:** WebCodecs H.264 decoding works in Chrome, Edge, Firefox 130+ and Safari 16.4+ on all three OSes. Anything else gets the fallback with the reason shown. `webbrowser.open` opens the default browser everywhere.
- **Paths:** only `os.path`. `/save` checks with `realpath` plus `os.sep`.
- **CI:** add an `os: [ubuntu-latest, windows-latest, macos-latest]` matrix for the unit-test job in `.github/workflows/ci.yml` (the Task 6 edit), so studio, stream and locator tests run on all three.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/MaestroLibrary/locators.py` (modify) | `best_locator(element, elements)`, `element_at(elements, x, y)`, `parse_bounds(b)` |
| `src/MaestroLibrary/stream.py` (create) | `ScrcpyStream`: push the server, forward the socket, start it, yield the raw H.264 bytes, stop |
| `src/MaestroLibrary/studio.py` (create) | `Session` (actions to keyword runs and recorded lines, typing merge, undo, `.robot` text), HTTP handler, CLI `main()` |
| `src/MaestroLibrary/studio.html` (create) | The page: video canvas, overlay, context menu, toolbar, recorder panel |
| `pyproject.toml` (modify) | package-data `studio.html` |
| `utest/test_studio.py` (create) | Locator, hit-test, Session and HTTP tests (fake MCP) |
| `README.md`, `CHANGELOG.md`, skill `SKILL.md` (modify) | docs |

---

### Task 1: Hit testing and best locator

**Files:**
- Modify: `src/MaestroLibrary/locators.py` (append)
- Test: `utest/test_studio.py`

**Interfaces:**
- Produces:
  - `parse_bounds(b: str) -> tuple[int, int, int, int] | None`
  - `element_at(elements: list[dict], x: int, y: int) -> dict | None`, which takes the flattened list
  - `best_locator(element: dict, elements: list[dict]) -> str | None`, which returns a locator matching exactly one element, or None

- [ ] **Step 1: Write the failing tests**

```python
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from MaestroLibrary.locators import best_locator, element_at, parse_bounds

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

    def test_element_at_prefers_smallest_locatable(self):
        self.assertEqual(element_at(SCREEN, 90, 500)["txt"], "Apps")      # icon has nothing locatable
        self.assertEqual(element_at(SCREEN, 500, 200)["rid"], "com.app:id/search")
        self.assertIsNone(element_at(SCREEN, 500, 2300))                    # only the root

    def test_best_locator_unique_or_none(self):
        self.assertEqual(best_locator(SCREEN[1], SCREEN), "id=com.app:id/search")
        self.assertIsNone(best_locator(SCREEN[2], SCREEN))                  # "Apps" twice
        self.assertEqual(best_locator(SCREEN[5], SCREEN), "text=Battery\n79%")

    def test_candidates_carry_match_counts(self):
        from MaestroLibrary.locators import locator_candidates
        self.assertEqual(locator_candidates(SCREEN[2], SCREEN), [("text=Apps", 2)])
        self.assertEqual(locator_candidates(SCREEN[1], SCREEN), [("id=com.app:id/search", 1), ("text=Search", 1)])
```

- [ ] **Step 2: Run it and check it fails**

Run `python -m pytest -q utest/test_studio.py`. Expected: ImportError on `best_locator`.

- [ ] **Step 3: Implement** (append to `locators.py`)

```python
LOCATABLE = ("rid", "txt", "a11y", "hint")


def parse_bounds(b):
    """Returns (x1, y1, x2, y2) from an inspect_screen bounds string such as ``[0,0][1080,2400]``."""
    found = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b or "")
    return tuple(int(n) for n in found.groups()) if found else None


def element_at(elements, x, y):
    """The smallest element at device point (x, y) that has something a locator can use."""
    hits = []
    for element in elements:
        box = parse_bounds(element.get("b"))
        if box and box[0] <= x < box[2] and box[1] <= y < box[3] and any(element.get(k) for k in LOCATABLE):
            hits.append(((box[2] - box[0]) * (box[3] - box[1]), element))
    return min(hits, key=lambda h: h[0])[1] if hits else None


def locator_candidates(element, elements):
    """[(locator, match count)] for id= then text= (text, content-desc, hint), as the Inspector panel lists them."""
    candidates = ([f"id={element['rid']}"] if element.get("rid") else []) + \
        [f"text={element[k]}" for k in ("txt", "a11y", "hint") if element.get(k)]
    return [(c, sum(matches(e, to_selector(c)) for e in elements)) for c in dict.fromkeys(candidates)]


def best_locator(element, elements):
    """The first candidate that matches exactly one element, or None."""
    return next((c for c, count in locator_candidates(element, elements) if count == 1), None)
```

- [ ] **Step 4: Run the tests and check they pass**

Run `python -m pytest -q utest/test_studio.py`. Expected: 3 passed.

- [ ] **Step 5: Commit** with the message `robotframework-maestrolibrary: feat: hit testing and unique locator choice for studio`.

---

### Task 2: Session: actions to keyword runs and recorded lines

**Files:**
- Create: `src/MaestroLibrary/studio.py` (Session part)
- Test: `utest/test_studio.py`

**Interfaces:**
- Consumes: Task 1 functions; `MaestroLibrary.run_keyword(name, args)`, `MaestroLibrary.elements()`, `MaestroLibrary.app_id`, and `flow2robot.escape(arg)`.
- Produces:
  - `class Session(lib, app_id=None)`
  - `Session.tree() -> dict`, which returns `{"elements": [...], "width": int, "height": int}`, refreshes when older than 1 s, and takes width and height from the root bounds
  - `Session.act(kind: str, x=None, y=None, x2=None, y2=None, text=None, secret=False) -> str`, which returns the recorded line or raises `AssertionError` (in that case nothing is recorded)
  - `Session.undo() -> None`
  - `Session.robot(name: str) -> str`
  - `kind` values: `click`, `long_press`, `type`, `wait_visible`, `should_be_visible`, `text_should_be`, `swipe`, `back`, `hide_keyboard`, `launch`, `screenshot`.

- [ ] **Step 1: Write the failing tests** (append to `utest/test_studio.py`)

```python
from unittest import mock
from MaestroLibrary.studio import Session

class FakeLib:
    def __init__(self, elements):
        self._elements, self.ran, self.app_id, self.fail = elements, [], "com.app", None
    def elements(self):
        return self._elements
    def run_keyword(self, name, args, kwargs=None):
        if self.fail:
            raise AssertionError(self.fail)
        self.ran.append((name, list(args)))

class SessionTest(unittest.TestCase):
    def setUp(self):
        self.lib = FakeLib(SCREEN)
        self.s = Session(self.lib)

    def test_click_runs_and_records(self):
        self.assertEqual(self.s.act("click", 500, 200), "Click Element    id\\=com.app:id/search")
        self.assertEqual(self.lib.ran, [("click_element", ["id=com.app:id/search"])])

    def test_no_unique_locator_records_point_with_gap(self):
        line = self.s.act("click", 540, 500)
        self.assertEqual(line, "Click Element    point\\=50%,21%    # GAP: no unique locator, ask for a test id")

    def test_typing_after_click_merges_into_input_text(self):
        self.s.act("click", 500, 200)
        self.s.act("type", text="wifi")
        self.assertEqual(self.s.lines, ["Input Text    id\\=com.app:id/search    wifi"])
        self.assertEqual(self.lib.ran[-1], ("input_text_into_current_element", ["wifi"]))

    def test_secret_typing_records_password_variable(self):
        self.s.act("click", 500, 200)
        self.s.act("type", text="hunter2", secret=True)
        self.assertEqual(self.s.lines, ["Input Password    id\\=com.app:id/search    ${PASSWORD}"])

    def test_failure_records_nothing(self):
        self.lib.fail = "Element not found"
        with self.assertRaisesRegex(AssertionError, "not found"):
            self.s.act("click", 500, 200)
        self.assertEqual(self.s.lines, [])

    def test_swipe_and_toolbar(self):
        self.s.act("swipe", 540, 1800, 540, 600)
        self.s.act("back")
        self.assertEqual(self.s.lines, ["Swipe By Percent    50    75    50    25", "Go Back"])

    def test_stale_tree_refreshes(self):
        calls = []
        self.lib.elements = lambda: calls.append(1) or SCREEN
        with mock.patch("MaestroLibrary.studio.time.monotonic", side_effect=[0, 0, 0.5, 5, 5]):
            self.s.tree(); self.s.tree(); self.s.tree()    # fresh, 0.5 s old, 5 s old
        self.assertEqual(len(calls), 2)

    def test_undo_and_robot_file(self):
        self.s.act("back"); self.s.act("hide_keyboard"); self.s.undo()
        self.assertEqual(self.s.robot("My Test"),
                         "*** Settings ***\nLibrary    MaestroLibrary\n\n*** Test Cases ***\nMy Test\n    Go Back\n")
```


- [ ] **Step 2: Run it and check it fails** (ImportError on `Session`).

- [ ] **Step 3: Implement** (`src/MaestroLibrary/studio.py`)

```python
"""Maestro Studio-style recorder: act on the live device screen and get Robot Framework lines.

    python -m MaestroLibrary.studio [--device ID] [--app APP_ID] [--port N]

Do not run it while a Robot run uses the same device: Maestro allows one session per device.
"""
import threading
import time

from .flow2robot import SEP, escape
from .locators import best_locator, element_at, parse_bounds

TREE_MAX_AGE_S = 1.0
SECRET = "${PASSWORD}"
GAP = "    # GAP: no unique locator, ask for a test id"
KEYWORD_NAMES = {"click_element": "Click Element", "long_press": "Long Press",
                 "input_text": "Input Text", "input_password": "Input Password",
                 "wait_until_page_contains_element": "Wait Until Page Contains Element",
                 "element_should_be_visible": "Element Should Be Visible",
                 "element_text_should_be": "Element Text Should Be", "swipe_by_percent": "Swipe By Percent",
                 "go_back": "Go Back", "hide_keyboard": "Hide Keyboard",
                 "open_application": "Open Application", "capture_page_screenshot": "Capture Page Screenshot"}


class Session:
    def __init__(self, lib, app_id=None):
        self.lib, self.app_id, self.lines, self.recording = lib, app_id, [], True
        self.lock = threading.Lock()   # one Maestro session: one action at a time
        self._tree, self._at, self._last_locator = None, None, None

    def tree(self):
        if self._tree is None or time.monotonic() - self._at > TREE_MAX_AGE_S:
            elements = self.lib.elements()
            root = max((parse_bounds(e.get("b")) or (0, 0, 0, 0) for e in elements), key=lambda b: b[2] * b[3])
            self._tree = {"elements": elements, "width": root[2], "height": root[3]}
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

    def _run(self, keyword, args, shown=None, comment=""):
        self.lib.run_keyword(keyword, list(args))          # raises: nothing recorded
        self._tree = None                                   # the screen changed
        if not self.recording:
            return None
        line = SEP.join([KEYWORD_NAMES[keyword]] + [escape(str(a)) for a in (shown or args)]) + comment
        self.lines.append(line)
        return line

    def act(self, kind, x=None, y=None, x2=None, y2=None, text=None, secret=False):
        with self.lock:
            if kind == "type":
                return self._type(text, secret)
            if kind in ("click", "long_press", "wait_visible", "should_be_visible", "text_should_be"):
                locator, comment = self._locate(x, y)
                keyword = {"click": "click_element", "long_press": "long_press",
                           "wait_visible": "wait_until_page_contains_element",
                           "should_be_visible": "element_should_be_visible",
                           "text_should_be": "element_text_should_be"}[kind]
                args = [locator] + ([text] if kind == "text_should_be" else [])
                line = self._run(keyword, args, comment=comment)
                self._last_locator = locator if kind == "click" else None
                return line
            self._last_locator = None
            if kind == "swipe":
                return self._run("swipe_by_percent", [*self._pct(x, y), *self._pct(x2, y2)])
            if kind == "launch":
                return self._run("open_application", [self.app_id or self.lib.app_id])
            simple = {"back": "go_back", "hide_keyboard": "hide_keyboard", "screenshot": "capture_page_screenshot"}
            return self._run(simple[kind], [])

    def _type(self, text, secret):
        """Types into the focused field; right after a click, the click line becomes Input Text/Password."""
        if "${" in text:
            raise ValueError("Maestro would evaluate ${...} as JavaScript; type it without ${.")
        if secret:
            self.lib.run_commands({"inputText": text}, log=False)      # never logged
        else:
            self.lib.run_keyword("input_text_into_current_element", [text])
        self._tree = None
        if not self.recording:
            self._last_locator = None
            return None
        shown = SECRET if secret else text
        if self._last_locator and self.lines and self.lines[-1].startswith("Click Element"):
            keyword = "Input Password" if secret else "Input Text"
            self.lines[-1] = SEP.join([keyword, escape(self._last_locator), escape(shown)])
        else:
            self.lines.append(SEP.join(["Input Text Into Current Element", escape(shown)]))
        self._last_locator = None
        return self.lines[-1]

    def undo(self):
        with self.lock:
            if self.lines:
                self.lines.pop()

    def robot(self, name):
        return "\n".join(["*** Settings ***", "Library    MaestroLibrary", "", "*** Test Cases ***", name]
                         + [SEP + line for line in self.lines]) + "\n"
```


- [ ] **Step 4: Run the tests and check they pass.**
- [ ] **Step 5: Commit** with the message `robotframework-maestrolibrary: feat: studio session records actions as robot lines`.

---

### Task 3: Live stream from scrcpy-server

**Files:**
- Create: `src/MaestroLibrary/stream.py`
- Test: `utest/test_studio.py`

**Interfaces:**
- Consumes: `android.verified_exe` / `MaestroLibrary.adb()` for the adb path; `scrcpy` on PATH (or `SCRCPY_SERVER_PATH`).
- Produces: `class ScrcpyStream(adb: str, device: str, max_size: int = 1080)`, with:
  - `start() -> None`, which raises `RuntimeError` with the reason
  - `read(n=65536) -> bytes`, which returns raw Annex-B H.264, or `b""` at the end
  - `stop() -> None`

- [ ] **Step 1: Spike on the phone (measure, do not assume).** Run the server by hand and save 3 s of the stream:

```bash
SERVER="${SCRCPY_SERVER_PATH:-$(dirname "$(command -v scrcpy)")/scrcpy-server}"
adb push "$SERVER" /data/local/tmp/scrcpy-server.jar
adb forward tcp:27183 localabstract:scrcpy
adb shell CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / com.genymobile.scrcpy.Server 3.3.1 \
    tunnel_forward=true audio=false control=false raw_stream=true video_codec=h264 max_size=1080 &
python -c "import socket,time;s=socket.create_connection(('127.0.0.1',27183));t=time.time();d=b''
while time.time()-t<3: d+=s.recv(65536)
open('s.h264','wb').write(d);print(len(d), d[:5].hex())"
```

The version argument must equal the installed server's version. Get it from `scrcpy --version` (here `5.0`), not from the example's `3.3.1`. Expected: the stream starts with `00000001` and NAL type 7 (SPS, byte `67`). Write down the exact working arguments in the plan's measured table. If `raw_stream` is refused, read the server's usage error and adjust. Do not code until the spike works.

- [ ] **Step 2: Write the failing test.** Patch `subprocess.run`, `subprocess.Popen` and `socket.create_connection`, and assert the exact command lists from Step 1, including that `stop()` removes the forward.

```python
class StreamTest(unittest.TestCase):
    def test_start_pushes_forwards_and_launches(self):
        from MaestroLibrary import stream
        with mock.patch.object(stream.subprocess, "run") as run, \
             mock.patch.object(stream.subprocess, "Popen") as popen, \
             mock.patch.object(stream.socket, "create_connection") as conn, \
             mock.patch.object(stream, "server_file", return_value=("/x/scrcpy-server", "5.0")):
            s = stream.ScrcpyStream("adb", "SER", port=27183)
            s.start()
            cmds = [c.args[0] for c in run.call_args_list]
            self.assertIn(["adb", "-s", "SER", "push", "/x/scrcpy-server", "/data/local/tmp/scrcpy-server.jar"], cmds)
            self.assertIn(["adb", "-s", "SER", "forward", "tcp:27183", "localabstract:scrcpy"], cmds)
            self.assertIn("raw_stream=true", popen.call_args.args[0])
            s.stop()
            self.assertIn(["adb", "-s", "SER", "forward", "--remove", "tcp:27183"],
                          [c.args[0] for c in run.call_args_list])
```

- [ ] **Step 3: Implement `stream.py`** with the arguments measured in Step 1:

```python
"""Raw H.264 screen stream from scrcpy-server (shipped with scrcpy), for the studio page."""
import os
import shutil
import socket
import subprocess
import time

REMOTE = "/data/local/tmp/scrcpy-server.jar"


def server_file():
    """(path to scrcpy-server, scrcpy version) on Windows, Linux and macOS; SCRCPY_SERVER_PATH wins."""
    scrcpy = shutil.which("scrcpy")
    if not scrcpy:
        raise RuntimeError("scrcpy is not on PATH; the live view needs it (the recorder still works).")
    here = os.path.dirname(os.path.realpath(scrcpy))
    candidates = [os.environ.get("SCRCPY_SERVER_PATH"), os.path.join(here, "scrcpy-server"),
                  os.path.join(here, "..", "share", "scrcpy", "scrcpy-server"),
                  "/usr/share/scrcpy/scrcpy-server", "/usr/local/share/scrcpy/scrcpy-server",
                  "/opt/homebrew/share/scrcpy/scrcpy-server"]
    path = next((c for c in candidates if c and os.path.isfile(c)), None)
    if not path:
        raise RuntimeError("scrcpy-server not found; set SCRCPY_SERVER_PATH to the file.")
    version = subprocess.run([scrcpy, "--version"], capture_output=True, text=True, timeout=10).stdout.split()[1]
    return path, version


class ScrcpyStream:
    def __init__(self, adb, device, port=27183, max_size=1080):
        self.adb, self.device, self.port, self.max_size = adb, device, port, max_size
        self._proc = self._sock = None

    def _adb(self, *args):
        return subprocess.run([self.adb, "-s", self.device, *args], capture_output=True, timeout=30, check=True)

    def start(self):
        path, version = server_file()
        self._adb("push", path, REMOTE)
        self._adb("forward", f"tcp:{self.port}", "localabstract:scrcpy")
        self._proc = subprocess.Popen(
            [self.adb, "-s", self.device, "shell", f"CLASSPATH={REMOTE}", "app_process", "/",
             "com.genymobile.scrcpy.Server", version, "tunnel_forward=true", "audio=false",
             "control=false", "raw_stream=true", "video_codec=h264", f"max_size={self.max_size}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):                      # the server needs a moment to listen
            try:
                self._sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
                return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError("scrcpy-server did not start on the device.")

    def read(self, n=65536):
        return self._sock.recv(n) if self._sock else b""

    def stop(self):
        if self._sock:
            self._sock.close()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        try:
            self._adb("forward", "--remove", f"tcp:{self.port}")
        except (subprocess.SubprocessError, OSError):
            pass
        self._proc = self._sock = None
```

Check bandit. B404 and B603 are already skipped in pyproject. If `shutil.which` plus a subprocess call raises B607, use `verified_exe` from `mcp.py` the way `Mirror` does instead (`android.py:102`).

- [ ] **Step 4: Run the tests and check they pass**, then repeat the Step 1 device check through the class: `ScrcpyStream(adb, serial).start()`, read for 3 s, and check that the stream starts with `00000001` and contains `67`.
- [ ] **Step 5: Commit** with the message `robotframework-maestrolibrary: feat: raw scrcpy h264 stream for the studio live view`.

---

### Task 4: HTTP server, token, CLI

**Files:**
- Modify: `src/MaestroLibrary/studio.py` (append the handler and `main`)
- Modify: `pyproject.toml` (change `MaestroLibrary = ["py.typed"]` to `["py.typed", "studio.html"]`)
- Test: `utest/test_studio.py`

**Interfaces:**
- Consumes: `Session` (Task 2), `ScrcpyStream` (Task 3).
- Produces HTTP endpoints. The page's JS uses exactly these:
  - `GET /?t=TOKEN` returns studio.html.
  - `GET /tree` returns the `Session.tree()` JSON.
  - `GET /inspect?x&y` returns `{"element": {...attributes}, "locators": [[locator, count], ...]}` from `element_at` and `locator_candidates`, or `{"element": null}`. This drives the Selected Element panel.
  - `POST /record {"on": bool}` sets the Toggle Recorder state: `Session.recording`, default on. When it is off, actions still run on the device and `act` returns `{"line": null}`.
  - `POST /clear` empties the lines without changing the recording state, as in Appium Inspector.
  - `GET /stream` returns raw H.264 as `application/octet-stream`, or 503 with the reason as text.
  - `GET /screenshot` returns a JPEG, the Maestro fallback.
  - `POST /act` takes a JSON body of `Session.act` kwargs and returns `{"line"}` or `{"error"}` with 409.
  - `POST /undo`
  - `GET /robot?name=N` returns the text.
  - `POST /save` takes `{"path", "name"}`. The path must be relative and inside the cwd, otherwise 400.
  - Every POST needs header `X-Token: TOKEN`, otherwise 403.

- [ ] **Step 1: Write the failing tests.** Start the server on port 0 in a thread, with a `FakeLib` and with `stream=None` (no device), then:
  - `GET /?t=<token>` returns 200 and contains `<canvas`.
  - `POST /act` without the token returns 403.
  - `POST /act {"kind":"back"}` with the token returns 200 with `{"line":"Go Back"}`.
  - `GET /stream` with no stream returns 503.
  - `POST /save {"path":"../x.robot"}` returns 400.
  - `POST /save {"path":"t.robot","name":"T"}` writes the file inside a temp cwd.

```python
import http.client, json, tempfile, threading
from MaestroLibrary.studio import make_server

class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        cwd = os.getcwd(); os.chdir(self.tmp.name); self.addCleanup(os.chdir, cwd)
        self.server, self.token = make_server(Session(FakeLib(SCREEN)), stream_factory=None, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

    def req(self, method, path, body=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"X-Token": self.token} if token else {})
        r = c.getresponse(); return r.status, r.read()

    def test_endpoints(self):
        self.assertEqual(self.req("GET", f"/?t={self.token}")[0], 200)
        self.assertEqual(self.req("POST", "/act", {"kind": "back"}, token=False)[0], 403)
        self.assertEqual(json.loads(self.req("POST", "/act", {"kind": "back"})[1]), {"line": "Go Back"})
        self.assertEqual(self.req("GET", "/stream")[0], 503)
        self.assertEqual(self.req("POST", "/save", {"path": "../x.robot", "name": "T"})[0], 400)
        self.assertEqual(self.req("POST", "/save", {"path": "t.robot", "name": "T"})[0], 200)
        self.assertTrue(os.path.isfile("t.robot"))
        insp = json.loads(self.req("GET", "/inspect?x=500&y=200")[1])
        self.assertEqual(insp["locators"], [["id=com.app:id/search", 1], ["text=Search", 1]])
        self.req("POST", "/record", {"on": False})
        self.assertEqual(json.loads(self.req("POST", "/act", {"kind": "back"})[1]), {"line": None})
        self.req("POST", "/clear")
        self.assertIn(b"*** Test Cases ***\nT\n", self.req("GET", "/robot?name=T")[1])
```

Security tests for Task 4, in the same class:
- **S1:** with no `X-Token`, `GET /tree` returns 403, and `GET /` with no `?t=` returns 403.
- **S2:** with `Host: evil.example`, `GET /?t=...` returns 403.
- **S9:** a `Content-Length` of 100000 returns 413.
- **S3:** `{"kind": "__import__"}` and `{"kind": "click", "x": "1;rm"}` both return 400.
- **S8:** the `GET /` response has a `Content-Security-Policy` containing `default-src 'none'` and `frame-ancestors 'none'`, plus `X-Content-Type-Options: nosniff`.

Security tests for Task 2:
- **S5:** an element with `txt` `${{__import__('os').getcwd()}}` gives the locator line `Click Element    text\=\${{__import__('os').getcwd()}}`.
- **S6:** typed text `a\n*** Settings ***` gives one line, containing `\n`.
- **S10:** with secret typing, the line holds `${PASSWORD}` and the fake lib's recorded call is `run_commands(..., log=False)`.
- **S11:** `act("type", text="${1+1}")` raises `ValueError`.
- **flow2robot:** `escape("${{1}}")` returns `\${{1}}`, and `escape("${USER}")` returns `${USER}`.

Also add this to the Task 2 tests: `self.s.recording = False; self.assertIsNone(self.s.act("back")); self.assertEqual(self.s.lines, []); self.assertEqual(self.lib.ran, [("go_back", [])])`.

- [ ] **Step 2: Run it and check it fails.**
- [ ] **Step 3: Implement** `make_server(session, stream_factory, port) -> (ThreadingHTTPServer, token)` and `main()`:
  - Token: `secrets.token_urlsafe(16)`.
  - Bind to `("127.0.0.1", port)`.
  - `/stream` calls `stream_factory()`, which returns a started `ScrcpyStream` or raises `RuntimeError`, giving a 503 with the message. Only one stream at a time: stop the previous one. Loop `read()`, then `wfile.write()`, until either side closes, and `stop()` in `finally`.
  - `/screenshot` calls `lib.mcp.call_tool("take_screenshot", ...)` under `session.lock`.
  - `/save` resolves `os.path.realpath(path)` and requires it to start with `os.path.realpath(os.getcwd()) + os.sep` and end with `.robot`.
  - `main()`:
    - argparse `--device`, `--app`, `--port` (default 8787)
    - builds `MaestroLibrary(device=..., run_on_failure="Nothing", logcat=False)`
    - when `--app` is given, opens the app and records that as the first line
    - prints the URL and the one-session warning, then calls `webbrowser.open(url)`
    - closes `lib.mcp` on Ctrl+C
  - Add `if __name__ == "__main__": main()`.
- [ ] **Step 4: Run the tests and check they pass**, then run the four global checks.
- [ ] **Step 5: Commit** with the message `robotframework-maestrolibrary: feat: studio http server with token guard and cli`.

---

### Task 5: The page (studio.html)

**Files:**
- Create: `src/MaestroLibrary/studio.html`

**Interfaces:**
- Consumes: Task 4 endpoints. The token is read from `location.search` and sent as `X-Token`.

Inspector features (from Appium Inspector):
- A mode switch above the screen:
  - **Act** (Coordinates Mode): click, drag and type run on the device and are recorded (the table below).
  - **Inspect** (Element Mode): hover highlights, and a click selects without touching the device.
- An **Elements** toggle that outlines every locatable element.
- A collapsible **Source** tree from `/tree`. Selecting a row highlights the element on screen, and the reverse.
- A **Selected Element** panel, from `/inspect`:
  - the suggested locators with match counts, unique ones marked and click to copy
  - the attributes table
  - action buttons Tap, Type, Wait visible, Should be visible, Text should be, which run and record through `/act` at the element's center
- In the recorder header: **Record** toggle, **Copy**, **Clear**, **Undo**, test name, and **Save**.

Layout: the left side is the device (a `<canvas id="screen">`, with an overlay canvas on top for the hovered element box and its suggested locator). The right side is the recorder: an ordered list of lines (read only), with Undo, Copy, test name field, Save path field, and Save. A toolbar above holds Launch app, Back, Hide keyboard, Screenshot, a Secret toggle, and the live/fallback status.

Behavior:

| Your action on the screen | Request | Recorded |
|---|---|---|
| left click | `act {kind:"click", x, y}` | Click Element |
| right click | context menu: Long press, Wait until visible, Should be visible, Text should be (prefilled from the element's text, editable), then `act` | that keyword |
| drag over 30 px | `act {kind:"swipe", x, y, x2, y2}` | Swipe By Percent |
| typing while the screen has focus | buffer, then on Enter or a click elsewhere `act {kind:"type", text, secret}` | Input Text (merged with the click) |
| toolbar buttons | `act {kind:"back"}` and the others | Go Back and the others |

Device coordinates: `x = Math.round(ev.offsetX / canvas.clientWidth * tree.width)`, with the same for y. Fetch `GET /tree` after each act, for hover boxes and the hover locator preview. The preview runs the same `element_at`/`best_locator` logic on the server. Add `GET /locate?x&y` to Task 4 only if hover needs it. Otherwise draw boxes from the tree client side and let click do the authoritative choice.

Live view (WebCodecs):

```js
const dec = new VideoDecoder({output: f => { ctx.drawImage(f, 0, 0, cv.width, cv.height); f.close(); },
                              error: e => fallback(String(e))});
let configured = false, pending = [], buf = new Uint8Array(0), ts = 0;
function nalUnits(bytes) {               // split Annex-B on 00 00 01 / 00 00 00 01, keep start codes
  const out = []; let s = -1;
  for (let i = 0; i + 3 < bytes.length; i++)
    if (bytes[i] === 0 && bytes[i+1] === 0 && (bytes[i+2] === 1 || (bytes[i+2] === 0 && bytes[i+3] === 1))) {
      if (s >= 0) out.push(bytes.subarray(s, i)); s = i; i += 2; }
  return {units: out, rest: s >= 0 ? bytes.subarray(s) : bytes};
}
function onNal(u) {
  const off = u[2] === 1 ? 3 : 4, type = u[off] & 31;
  if (type === 7 && !configured) {
    const codec = 'avc1.' + [u[off+1], u[off+2], u[off+3]].map(b => b.toString(16).padStart(2, '0')).join('');
    dec.configure({codec, optimizeForLatency: true}); configured = true;   // no description = Annex-B input
  }
  pending.push(u);
  if (type === 1 || type === 5) {
    if (!configured) { pending = []; return; }
    const data = new Uint8Array(pending.reduce((n, p) => n + p.length, 0));
    let o = 0; for (const p of pending) { data.set(p, o); o += p.length; }
    dec.decode(new EncodedVideoChunk({type: type === 5 ? 'key' : 'delta', timestamp: ts++, data}));
    pending = [];
  }
}
async function live() {
  if (!('VideoDecoder' in window)) return fallback('this browser has no WebCodecs; use Chrome or Edge');
  const r = await fetch('/stream');
  if (!r.ok) return fallback(await r.text());
  const reader = r.body.getReader();
  for (;;) {
    const {value, done} = await reader.read(); if (done) return fallback('stream ended');
    const joined = new Uint8Array(buf.length + value.length); joined.set(buf); joined.set(value, buf.length);
    const {units, rest} = nalUnits(joined); units.forEach(onNal); buf = rest.slice();
  }
}
```

`fallback(reason)` shows the reason in the status bar and, after each act, loads `/screenshot` into the canvas.

- [ ] **Step 0: Design with the impeccable skill.** Invoke `impeccable` (plugin marketplace `impeccable`, v4.5.0) in **Operate** mode for the page.
  - Run its setup launcher (`scripts/impeccable context --target src/MaestroLibrary/studio.html`; on Windows without `sh`, use `impeccable.cmd`), then read its `reference/new-work.md` and `reference/craft-floor.md` before writing UI.
  - The page is a tool: scanability, a clear device/recorder split, keyboard focus states, an obvious live/fallback status, readable monospace Robot lines, light and dark themes, and no decoration that competes with the device screen.
  - Constraints that override any skill suggestion:
    - one self-contained HTML file
    - no external fonts, CDNs or network requests: it must work offline on a locked-down machine
    - plain ASCII in copy
  - Do not run impeccable's agents (asset-producer, finish-reviewer and the others) without explicit approval, per the global rule.
- [ ] **Step 1: Write the page** (about 200 to 300 lines: the HTML, the CSS from Step 0, and the JS above plus the input handling from the table).
- [ ] **Step 2: Device test (manual, on the phone).**
  - Run `python -m MaestroLibrary.studio --app com.android.settings`. The page opens and the screen is live (move the phone's screen by hand and watch it follow).
  - Then:
    - click the search bar, type `wifi` and press Enter
    - press Back twice
    - right-click "Apps" and choose Should be visible
    - drag up
    - save as `studio_check.robot`
  - Expected lines:
    - `Open Application    com.android.settings`
    - `Input Text    id_regex...` (dots in an id make it `id_regex`)
    - `Go Back` twice
    - `Element Should Be Visible ...`
    - `Swipe By Percent ...`
- [ ] **Step 3: Replay.** Run `robot --pythonpath src -d <scratch> studio_check.robot` with Studio stopped. Expected: PASS.
- [ ] **Step 4: Fallback check.** Rename scrcpy temporarily, or set `SCRCPY_SERVER_PATH` to a missing file. The page shows the reason, actions still record, and the screenshot refreshes after each act.
- [ ] **Step 5: Commit** with the message `robotframework-maestrolibrary: feat: studio page with live screen and step recorder`.

---

### Task 6: Docs, skill, release

**Files:**
- Modify: `README.md` (new section "Studio: record a test on the live device" after the converter section), `CHANGELOG.md` (Unreleased, Added)
- Modify: `~/claude-skills` and `D:\Docs\rhd\automation\claude-skills`, in `robot-maestro-automation/SKILL.md` (one line under the explore section: Studio for recording, which still needs the locators moved into `<area>_screen.resource` and the GAP lines filed as testability asks)

- [ ] **Step 1:** Write the README section (the command, what each gesture records, the token, the one-session rule, Chrome or Edge for the live view, the fallback) and the CHANGELOG entry.
- [ ] **Step 2:** Make the skill edit in both copies, and run `./check.sh` in each.
- [ ] **Step 2b:** CI matrix: in `.github/workflows/ci.yml`, run the unit tests on `ubuntu-latest`, `windows-latest` and `macos-latest`. Keep the publish and audit steps on ubuntu only.
- [ ] **Step 3:** Run the full global checks, plus `python -m pip wheel --no-deps -w <scratch> .`, and check the wheel contains `studio.html`, `studio.py` and `stream.py`.
- [ ] **Step 4:** Commit and push the library, the skills (develop) and the mirror (main).
- [ ] **Step 5:** Release only on the user's word: version 0.6.0, CHANGELOG dated, tag `v0.6.0`.

---

## Verification (end to end)

1. Unit and HTTP tests: `python -m pytest -q utest` (fake MCP, no device).
2. Coverage gate at 85% or more, bandit clean, atest dry run against `src`.
3. Phone:
   - The live view follows the device.
   - The Task 5 recording session produces the expected lines.
   - The saved `.robot` passes under `robot`.
   - The fallback works without scrcpy.
4. Wheel contents include `studio.html`.

## Execution

Native (I implement in this session) is recommended. The tasks are sequential and share interfaces, and Task 3 needs a live device spike before any code. A final reviewer subagent runs only if you approve it, on Sonnet per your rule.
