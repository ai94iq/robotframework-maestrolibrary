# MaestroLibrary Studio Implementation Plan (revision 2: native Qt)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Replace `robotframework-maestrolibrary/docs/superpowers/plans/2026-10-10-maestro-studio.md` with this file as the first execution step.

## Context

The goal is a Maestro Studio / Appium Inspector-style recorder that writes MaestroLibrary Robot lines while you act on a live device screen. Revision 1 built it as a local web page:

| Revision 1 work | Commit | Status |
|---|---|---|
| hit testing and locators | `e8eead1` | done |
| Session | `ae8ee8b` | done |
| scrcpy stream | `afc6226`, `fd2c65d` | done |
| HTTP server | `9928456` | done |
| HTML page | not committed | the page ran live in Edge |

The user then asked whether plain HTML is the right frontend, compared the options, and chose **native Qt (PySide6)**. This revision:
- keeps the Qt-independent core (locators, Session, ScrcpyStream)
- replaces the HTTP server and the HTML page with a PySide6 window

**Goal:** `python -m MaestroLibrary.studio` opens a native window with the live device screen. You act on it (click, long-press, drag, type, toolbar) and every action runs on the device through MaestroLibrary while the matching Robot line is recorded, ready to save as a `.robot` test.

**Architecture:**
- A PySide6 `QMainWindow`.
- **Live view:** a reader thread pulls scrcpy's raw H.264 from `ScrcpyStream` and decodes it. The decoder is Qt's own FFmpeg backend if the Task 4 spike proves it works, otherwise PyAV. Frames go to a `DeviceView` widget as `QImage` through a signal.
- **Actions:** they run one at a time, in order, on a worker thread through `Session.act`, so the UI never blocks. Results come back as signals.
- **Hit testing:** reuses `locators.element_at`/`locator_candidates`, plus `lib.screen()` for a real source tree.

**Tech Stack:** Python, MaestroLibrary core (done), PySide6 6.12.0 (LGPL-3.0, optional extra), possibly PyAV 19.0.1 (BSD); Python 3.12+, scrcpy 5.0 server over adb.

**Spec** (the user's words this session):
- a live device screen with a step recorder, like Maestro Studio
- clicking runs the action and appends the line
- you never type Robot; the keywords are written for you
- it ships in the library
- the UI goes through impeccable
- it runs on Windows, Linux and macOS
- new libraries at their latest versions
- the code is checked for RCEs and exploits
- the frontend is native Qt (PySide6)

UI ideas taken from Appium Inspector:
- Element Mode / Coordinates Mode (named Inspect / Act here)
- the Element Handles toggle
- the Source tree
- the Selected Element panel (suggested locators with match counts, attributes, actions)
- the Recorder with Toggle, Copy and Clear

From Maestro Studio: right-click an element to get a command menu.

## Measured on the phone (Samsung A70, Android 15, 1080x2400), 2026-10-10

| Source | Result |
|---|---|
| MCP `take_screenshot` | 2.3 s per frame (too slow for live) |
| `adb screencap` | 0.8 to 2.2 s per frame |
| MCP `inspect_screen` | 0.36 s; bounds are in device pixels |
| scrcpy-server 5.0 raw stream (`ScrcpyStream`, done) | live; first bytes after 1.5 to 1.8 s; NAL 7, 8, 5 then 1; `avc1.42800a`; the server exits with the adb shell |
| Task 4 decoder spike | Qt FFmpeg (`QMediaPlayer.setSourceDevice` on a live pipe): 2 frames in 15 s, then stalls; rejected. PyAV 19.0.1 `CodecContext("h264")`: 30.4 fps over 12 s while swiping, first frame 0.1 s after stream start, frame to QImage 1.6 ms avg (3.5 ms max); chosen. Frames are 486x1080 at max_size=1080 |
| Revision 1 page in headless Edge | live view reached "Live"; it exposed a dropped-step bug, which taught us that actions must queue (the Qt worker queues them) |

## Global Constraints

- **New dependencies**, only in an optional `studio` extra, at their latest versions, checked live:
  - `PySide6>=6.12.0`
  - `av>=19.0.1`, only if the Task 4 spike needs it (no Python marker needed, since the floor is 3.12)
  - Re-check with `pip index versions` at execution time.
  - Core install stays dependency-free. `pip-audit` covers the extra.
- **Python floor: 3.12** (the user's choice). 3.10 reached EOL on 2026-10-01, 3.11's EOL is 2027-10, and 3.12's is 2028-10. 3.12 also matches PyAV 19's floor, so no special case is needed. CI tests 3.12 and 3.14. The dependency floors are already at the latest releases (robotframework 7.5, robotframework-pythonlibcore 4.6.0, PyYAML 6.0.3, checked live 2026-10-10).
- **Progress tracking:** the library repo gets `plan.md` (status per task, with a checkbox list mirroring this plan) and `handover.md` (current state, what is verified and what is not, next step, how to run Studio). Update both at the end of every task, in that task's commit. Lean, facts only.
- **Installing into the user's Python** (3.14): `pip install "PySide6==<latest>"` and, if needed, `"av==<latest>"`. This is covered by approving this plan, per the rule to ask before installing.
- **Lazy import:** `import MaestroLibrary` never imports Qt. Only `python -m MaestroLibrary.studio` does, and a missing extra prints `pip install "robotframework-maestrolibrary[studio]"`.
- **One Maestro session per device:** Studio must not run during a Robot run on that device. The window title and status bar say so.
- Plain ASCII in code, docs and commits. Commit format: `robotframework-maestrolibrary: <type>: <title>`, with a body that says what was verified.
- **Checks before every commit:**
  - `python -m pytest -q utest`. Qt tests run with `QT_QPA_PLATFORM=offscreen` and skip cleanly when PySide6 is missing.
  - The coverage gate at 85%.
  - `bandit -q -c pyproject.toml -r src`.
  - The atest dry run against `src`.

## Security (RCE and exploit review), updated for a native app

| # | Risk | Guard | Test |
|---|---|---|---|
| S3 | **Arbitrary keyword execution**: action kinds outside the known set | `Session.act` accepts only `KINDS`; the UI sends fixed kinds (done) | done (`test_unknown_kind_is_refused`) |
| S4 | **Remote shell injection via `adb shell` arguments** | serial, version and max_size validated; scrcpy from PATH only (done) | done |
| S5 | **Robot code injection on replay** (device text such as `${{...}}`) | every recorded argument escapes all variable syntax (done) | done |
| S6 | **Section injection** through newlines | escaped (done) | done |
| S7 | **Overwriting arbitrary files** | Save uses `QFileDialog.getSaveFileName` (the user picks the path) and forces a `.robot` suffix; no path comes from device data | Task 6 |
| S8 | **Qt rich-text injection**: QLabel and friends auto-detect HTML, so device text like `<img src=...>` or `<a href=file:...>` would render as HTML | Every widget that shows device data uses `Qt.PlainText`. Use `QTableWidgetItem` and `QTreeWidgetItem` (always plain), `setOpenExternalLinks(False)`, and never `setHtml`, `QTextBrowser` or tooltips built with HTML. A test feeds `<b>x</b><img src=x>` and asserts that `label.text()` stays literal and `textFormat() == PlainText`. | Task 6 |
| S10 | **Secret leakage** | Secret typing goes through `run_commands(log=False)` and is scrubbed from errors (done). The typing overlay shows `*`. The status bar never shows the text. | done + Task 6 |
| S11 | **Maestro JS evaluation** | `${` refused (done); the UI shows the refusal message | done |
| S13 | **Decoder memory**: hostile or garbage stream bytes | Only our own scrcpy-server on the user's device feeds the decoder. Frames over 8192 px per side are dropped. Decode errors stop the live view and fall back to screenshots, without a crash. | Task 4 |
| S14 | **Dependency supply chain** | Exact latest versions verified live. `pip-audit -r` on the extra in CI. No other new packages. | Task 7 |

S1, S2, S9 and S12 belonged to the HTTP server and go away with it, since there is no listening socket any more. The only socket is the adb forward to the device on 127.0.0.1, which adb owns.

Final security pass (Task 7):
- bandit clean
- pip-audit clean (core and the `studio` extra)
- grep of the diff for `shell=True|eval\(|exec\(|setHtml|QTextBrowser|RichText|pickle|os\.system|setOpenExternalLinks\(True`, with each hit justified or removed
- re-read every slot that touches device data against S5, S6 and S8

## Platforms (Windows, Linux, macOS)

- **scrcpy-server lookup:** done (`stream.server_file`, PATH-only scrcpy).
- **Qt platform plugins:** PySide6 wheels ship Windows, macOS (arm64 and x86_64) and Linux (xcb and wayland) builds. On Linux, document the system libraries Qt's xcb plugin needs (`libxcb-cursor0` on Debian/Ubuntu).
- **Theme:** the Fusion style with a palette that follows the system (`QGuiApplication.styleHints().colorScheme()`, Qt 6.5+), so it looks the same on all three OSes.
- **iOS simulator (macOS):** no scrcpy, so the view refreshes a Maestro screenshot after each step, Back is disabled, and the status says "Live view is Android only".
- **CI:** an `ubuntu-latest`, `windows-latest` and `macos-latest` matrix for unit tests with `.[studio,convert]` and `QT_QPA_PLATFORM=offscreen`. On ubuntu, `apt-get install -y libegl1 libxkbcommon0`, or whatever the offscreen plugin needs, verified in the first CI run.

## File Structure (the end state)

| File | Responsibility |
|---|---|
| `src/MaestroLibrary/locators.py` | done: `parse_bounds`, `element_at`, `locator_candidates`, `best_locator` |
| `src/MaestroLibrary/stream.py` | done: `ScrcpyStream`, `server_file` |
| `src/MaestroLibrary/studio.py` | `Session` (done) plus `main()`. Remove the HTTP server (`make_server`, `act_kwargs`, `Handler`, HEADERS/CSP). `main()` checks the Python version and that PySide6 imports, then starts the Qt app. |
| `src/MaestroLibrary/studio_qt.py` (new) | `MainWindow`, `DeviceView`, `ActionWorker`, `StreamReader` (decoding), `source_tree(screen)` |
| `src/MaestroLibrary/studio.html` | deleted |
| `pyproject.toml` | package data back to `["py.typed"]`; `studio` extra |
| `utest/test_studio.py` | keep the Locator, Session, Stream and Escape tests; delete HttpTest; rewrite MainTest |
| `utest/test_studio_qt.py` (new) | offscreen Qt tests: widget behavior, the S8 plain text test, the decoder with a fixture |
| `utest/fixtures/screen.h264` (new, if needed) | a few KB of real H.264 for the decoder test (Task 4 decides its source) |

---

### Task 3b: Raise the Python floor to 3.12, and start progress tracking

- [ ] **Step 1:** In `pyproject.toml`, set `requires-python = ">=3.12"`. In `.github/workflows/ci.yml`, change the matrix to `python: ['3.12', '3.14']` and update its comment.
  - Grep for `3.10` and `3.11` in the repo (README requirements, docs) and update them.
  - Remove anything kept only for 3.10/3.11. For example, the `if: matrix.python != '3.10'` guard on the pip-audit step (tomllib is in 3.11+) can go.
- [ ] **Step 2:** Add to CHANGELOG under Unreleased > Changed: "Python 3.12 or newer is required (3.10 reached end of life on 2026-10-01)."
- [ ] **Step 3:** Create `plan.md`, with the goal, a link to `docs/superpowers/plans/2026-10-10-maestro-studio.md`, and a task checklist with Tasks 1 to 4 marked done or open, plus the measured facts. Create `handover.md`, with the state, how to run the tests and Studio, what is verified (with dates), what is unverified, and the next step.
- [ ] **Step 4:** Run the checks, then commit with `chore: require python 3.12 and track studio progress`.
- [ ] **Step 5:** In `fms-flutter-automation`, update the CI image from `python:3.11-alpine` to the latest, `python:3.14-alpine` (check Docker Hub tags live). Check that each job's commands still work by running its dry-run job locally on 3.14. Commit on develop with `chore: ci image python 3.14 for maestrolibrary 0.6`, and push only after 0.6.0 is released on PyPI, so CI resolves it.
- [ ] **Step 6:** In both skill copies, check the scaffold's CI template image and `requirements` (`assets/scaffold/scaffold.py`), raise them to the latest Python image if they are lower, and run `./check.sh`. This is committed with Task 7.

### Task 4: Remove the HTTP layer, and the video decoder spike

- [ ] **Step 1: Remove the web layer.**
  - Delete `make_server`, `act_kwargs`, `MAX_BODY`, `COORDS`, `ACT_FIELDS`, `PAGE`, `HEADERS` and their imports from `studio.py`.
  - Delete `studio.html` and revert its package-data entry.
  - Delete `HttpTest`. Keep `MainTest`, which Task 6 rewrites.
  - Discard the uncommitted page changes (`git checkout -- src/MaestroLibrary/studio.html`) before deleting the file.
  - Run the checks and commit with `refactor: drop the studio web layer for the native qt window`.
- [ ] **Step 2: Install PySide6.** Run `pip index versions PySide6` (expect 6.12.0 or newer), then `python -m pip install "PySide6==<latest>"`.
- [ ] **Step 3: Spike the decoder with Qt alone, measuring rather than assuming.** In a scratch script, feed `ScrcpyStream` bytes into a `QBuffer` or a custom sequential `QIODevice` subclass, and play it with `QMediaPlayer.setSourceDevice(device, QUrl("stream.h264"))` into a `QVideoSink`. Count frames per second and the latency (tap the phone's screen and watch the window).
  - **Accept the Qt route** if it reaches 15 fps or more, with latency under 400 ms, and follows screen changes for 60 s.
  - **Otherwise use PyAV:** run `pip index versions av` (expect 19.0.1 or newer), install it, then use `codec = av.CodecContext.create("h264", "r")`. For each chunk, loop `for packet in codec.parse(chunk): for frame in codec.decode(packet):` and call `frame.reformat(format="rgb24")`, then build `QImage(bytes(plane), w, h, plane.line_size, QImage.Format.Format_RGB888).copy()`. Measure the same numbers.
  - Write the result and the chosen route into the plan's measured table.
- [ ] **Step 4: Write the decoder test.** First try encoding a synthetic fixture in-test with the chosen library (PyAV `h264` encoder, if its wheels include an encoder). If that isn't possible, save 2 s of the phone's Settings screen as `utest/fixtures/screen.h264`; it holds no personal data, which you should check by viewing a frame. The test asserts that the decoder yields at least one 1080-wide `QImage`, and that 1 MB of random bytes yields no frame and no exception (S13).
- [ ] **Step 5: Implement `StreamReader(QThread)` in `studio_qt.py`.** It does this:
  - `run()` loops `stream.read()` into the decoder.
  - Each decoded frame is emitted as `frame(QImage)`.
  - Frames larger than 8192 px per side are dropped.
  - A decoder error or the end of the stream emits `failed(str)`.
  - `stop()` calls `stream.stop()` and waits.

  Run the tests and commit with `feat: decode the scrcpy stream into qt frames`.

### Task 5: Action worker and source tree

**Interfaces:**
- `ActionWorker(QObject)` lives on a `QThread` and has:
  - a `submit(kind: str, **kw)` slot, which queues steps in order (one Maestro session)
  - signals `recorded(object)` (the line, or None), `failed(str)`, `busy(bool)` and `tree(dict)` (a fresh `Session.tree()` after each step)
- `source_tree(screen: list[dict]) -> list[tuple[int, dict]]` returns (depth, element) pairs from `lib.screen()`'s nested tree, using `walk` with depth. `DeviceView` and the source panel use it.

- [ ] **Step 1: Write the failing tests** (offscreen; `FakeLib` from `test_studio.py`):
  - Submitting `back` then `hide_keyboard` emits `recorded` twice, in order, and `lib.ran` has `go_back` before `hide_keyboard`.
  - A failing keyword emits `failed("Element not found")`, and `Session.lines` stays empty.
  - `submit("type", text="${1}")` emits the `failed` message that mentions JavaScript.
  - `source_tree` on a nested sample returns the right depths.
  - Use `QSignalSpy` and `QTest.qWait` (both in PySide6), so no pytest-qt dependency is needed.
- [ ] **Step 2: Implement it.** The worker's slot runs `session.act(kind, **kw)` in a try block, emits `recorded`, and catches `ValueError` and `Exception` (as `failed(str(err))`). `busy` is emitted around each step.
- [ ] **Step 3: Commit** with `feat: studio action worker runs steps in order off the ui thread`.

### Task 6: The window (impeccable, Operate mode)

**Design** (impeccable is not installed as a skill here; its launcher would download a binary, so apply its references directly: `mode-operate.md`, `craft-floor.md`, `new-work.md`):
- **Shell:** the main toolbar carries:
  - the product name
  - the device and its live/screenshot status
  - the mode switch (Act / Inspect, exclusive QActions)
  - the Elements toggle
  - Launch, Back, Keyboard, Screenshot
  - Secret
- **Work areas** (a `QSplitter`, three panes):
  1. `DeviceView`: frames scaled to fit, the overlay boxes, the hover highlight, and a typing overlay
  2. **Inspector**: a Source `QTreeWidget` with real hierarchy, and a Selected Element panel with locators (table: locator, matches, unique badge, copy on double-click), attributes (table) and action buttons
  3. **Recorder**: a `QListWidget` of numbered lines in the system monospace font. GAP lines use the warning color. The header has Record, Undo, Clear and Copy, with Save at the bottom.
- **Palette:** a committed one for the shell (deep blue toolbar), a record red, OK green and warning amber, in light and dark variants that follow the system scheme.
- **Signature move:** each recorded step briefly outlines the device frame in record red while the new line slides in with a short fade. Only one animated moment; respect `QStyleHints` and reduced motion where available.
- **Icons:** drawn with QPainter paths in a single stroke weight, in a small `icons()` helper. No emoji, no Unicode glyph icons.
- **States:** keyboard focus rings; busy (the toolbar actions are not disabled; steps queue, and the status shows "Running 2 steps"); error (the status bar in record red names the problem and the recovery); empty recorder text; and an empty selected-element panel.

**Behavior** (same as revision 1):

| Input on the DeviceView | Result |
|---|---|
| left click | `click` |
| drag over 30 px | `swipe` |
| right click | menu: Long press, Wait until visible, Should be visible, Text should be (an inline `QLineEdit`, prefilled from the element's text) |
| typing | buffered; Enter sends; Esc cancels |
| Inspect mode | hover highlights; a click selects only |

Coordinates map from widget pixels through the frame rectangle to device pixels (`tree.width/height`).

- [ ] **Step 1: Write the failing tests** (`utest/test_studio_qt.py`, offscreen, `FakeLib`, a fake frame `QImage(1080, 2400)`):
  - Clicking the device view at the widget point for (500, 200) submits `click` with x=500, y=200 (the mapping is right at a non-1:1 widget size).
  - A drag submits `swipe`.
  - Typing `wifi` then Enter submits `type`. With Secret on, the overlay text is `****`.
  - Inspect mode: a click submits nothing and fills the locators table, with "unique" for `id=com.app:id/search`.
  - **S8:** an element with `txt` `<b>x</b><img src=x>` shows in the source tree, the attributes table and the hover label as that literal text, and every QLabel showing device text has `textFormat() == Qt.PlainText`.
  - Save: patch `QFileDialog.getSaveFileName` to return `tmp/t` and assert that `tmp/t.robot` is written (the `.robot` suffix is forced).
  - Undo, Clear and Record each change `Session` as expected.
- [ ] **Step 2: Implement `MainWindow` and `DeviceView`.**
- [ ] **Step 3: Rewrite `main()`.** It:
  - parses arguments: `--device`, `--app`, `--max-size 1080`
  - checks that PySide6 imports (and PyAV, if that route is chosen)
  - creates the `QApplication` with the Fusion style and palette
  - creates `MaestroLibrary(run_on_failure="Nothing", logcat=False)` and resolves the device
  - starts `StreamReader` on Android, or uses screenshots on iOS or when it fails
  - closes the MCP connection and the stream on exit

  Rewrite `MainTest` so it patches `MaestroLibrary`, `QApplication.exec` and `StreamReader`.
- [ ] **Step 4: Device end to end (automated against the phone).** A scratch script starts the real window (offscreen is fine) against the phone, waits for the first live frame, then drives `DeviceView` with `QTest`:
  - click the search bar, type `wifi` and press Enter
  - press Back twice
  - right-click "Apps" and choose Should be visible
  - drag up
  - in Inspect mode, click Apps and check the locators
  - save as `studio_check.robot`

  The expected recorder lines are `Open Application`, `Input Text    id...`, `Go Back` twice, `Element Should Be Visible ...` and `Swipe By Percent ...`. Grab the window to a PNG at the start, after typing and in Inspect mode, and review the screenshots once against the craft floor, light and dark. Fix everything found in one batch and confirm with one more round.
- [ ] **Step 5: Replay.** With Studio closed, run `robot --pythonpath src studio_check.robot`. Expected: PASS.
- [ ] **Step 6: Fallback.** Run with `SCRCPY_SERVER_PATH` set to a missing file. The status shows the reason, screenshots refresh after each step, and recording still works.
- [ ] **Step 7: Commit** with `feat: native qt studio window with live screen and recorder`.

### Task 7: Docs, skill, CI, security pass

- [ ] **Step 1:** Add a README section, "Studio: record a test on a live device", covering:
  - `pip install "robotframework-maestrolibrary[studio]"` and `python -m MaestroLibrary.studio --app <id>`
  - what each gesture records, the one-session rule, and the iOS fallback
  - the Linux system libraries Qt needs

  Add a CHANGELOG entry under Unreleased > Added.
- [ ] **Step 2:** Add a skill line in both copies of `robot-maestro-automation/SKILL.md` (Studio for recording; move its locators into `<area>_screen.resource`; file the GAP lines as testability asks), and run `./check.sh` in both.
- [ ] **Step 3:** Update `.github/workflows/ci.yml`: the OS matrix for unit tests with `.[studio,convert]` and `QT_QPA_PLATFORM=offscreen`, `pip-audit` over the studio extra's requirements, and the ubuntu Qt system libraries.
- [ ] **Step 4:** The security pass listed above.
- [ ] **Step 5:** Run the full checks, plus a wheel build check: `studio_qt.py` is present, `studio.html` is absent, and the metadata has `Provides-Extra: studio`.
- [ ] **Step 6:** Update `plan.md` and `handover.md`, then commit and push the library (main), the skills (develop) and the mirror (main). Watch the first CI run on all three OSes; if `gh` is unavailable, ask the user to check it.
- [ ] **Step 7:** Release only on the user's word: 0.6.0 and tag `v0.6.0`.

## Verification (end to end)

1. `python -m pytest -q utest` (fake MCP, offscreen Qt): all pass, coverage 85% or more, bandit and pip-audit clean, atest dry run OK.
2. Phone:
   - The window shows a live screen within about 2 s.
   - The Task 6 Step 4 script records the expected lines.
   - The saved `.robot` passes under `robot`.
   - The fallback works without scrcpy.
3. CI is green on ubuntu, windows and macos.
4. The wheel has the `studio` extra and no HTML.

## Execution

Native: I implement in this session. Each task is sequential and depends on the previous one's interfaces, and the device spikes need the phone. A final reviewer subagent runs only with your explicit approval, on Sonnet, per your rule.
