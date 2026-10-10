# Handover

## State (2026-10-10)

- `main` is at the 0.5.0 release plus unreleased Studio work. Python floor 3.12 (CHANGELOG Unreleased > Changed).
- Run: `python -m MaestroLibrary.studio [--device ID] [--app APP_ID] [--max-size PX] [--video-encoder NAME]`; `pip install -e ".[studio]"` installs PySide6 6.12.0 and av 19.0.1.
- Code: `locators.py` (hit testing, locator choice), `studio.py` (`Session`, `main`), `stream.py` (`ScrcpyStream`), `studio_qt.py` (window and workers), `studio_icons.py` (Lucide 1.55.0).
- Threads: the UI; `ActionWorker` runs Maestro steps and screen reads in order (at most one read queued); a second `ActionWorker` sends Android touch steps (tap, long press, swipe, Back) with adb and does line edits; `StreamReader` decodes the scrcpy stream, keeping the newest frame.
- One `maestro mcp` process serves every device: a device switch points the library at the new device and restarts only the live view.

## Run

```
python -m pytest -q utest                                        # no device needed
python -m robot --dryrun --pythonpath src --output NONE --report NONE --log NONE atest
python -m bandit -q -c pyproject.toml -r src
```

## Verified

- Unit tests (171), coverage gate (85%; 91% now), bandit and the atest dry run pass at each Studio commit; pip-audit clean.
- On the phone (Samsung A70, Android 15) and a Pixel 9 emulator, 2026-10-10, in the real window:
  - End to end 18 of 18: tap, type, Back, Launch, right-click assert, swipe, Inspect, inspector Tap, element list, element boxes, Undo, Pause, Save. The saved test replays with robot (PASS).
  - Screenshot fallback without scrcpy: the state reads screenshots, the view refreshes after each step, steps still record.
  - Touch line confirmed 0.13 to 0.17 s after a click; device switch back to live in 0.7 s (emulator) and 2.2 s (phone).
  - Timings and the reasons behind each design choice: `plan.md`, Measured.

## Not verified yet

- Studio on Linux and macOS (CI runs its tests there) and on an iOS simulator.
- The first CI run with the Studio jobs on ubuntu, windows and macos (the ubuntu Qt packages are a best guess).

## Next

- Release 0.6.0 when the user says so; then raise the skill floors and fms-flutter-automation (python:3.14-alpine image) to it.
- Typing, assertions and Launch still run through Maestro (5 to 14 s); typing through adb is not measured yet.
