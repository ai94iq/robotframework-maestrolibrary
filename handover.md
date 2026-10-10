# Handover

## State (2026-10-10)

- `main` is at the 0.5.0 release plus unreleased Studio work. The Studio core is done: `locators.py` (hit testing, locator choice), `studio.Session` and `stream.ScrcpyStream`.
- The web layer is gone. `studio_qt.py` has `FrameDecoder` (PyAV H.264 to QImage) and `StreamReader` (QThread). `ActionWorker` runs steps in order on its own thread. `studio_qt.MainWindow` is the window; `python -m MaestroLibrary.studio --app <id>` runs it (`--max-size`, default 1080; `--video-encoder`).
- `pip install -e ".[studio]"` installs PySide6 6.12.0 and av 19.0.1.
- Python floor 3.12 (CHANGELOG Unreleased > Changed).

## Run

```
python -m pytest -q utest                                        # no device needed
python -m robot --dryrun --pythonpath src --output NONE --report NONE --log NONE atest
python -m bandit -q -c pyproject.toml -r src
```

## Verified

- Unit tests, coverage gate (85%), bandit and the atest dry run pass at each Studio commit.
- On the phone (Samsung A70, Android 15), 2026-10-10:
  - `ScrcpyStream` is ready in 1.8 s, streams H.264, and leaves no server after `stop()`.
  - The revision 1 page showed the live view in Edge.
  - PyAV decodes the live stream at 30 fps. Qt's own decoder stalls after the first frame.

## Not verified yet

- Studio on Linux and macOS (CI runs its tests there), an iOS simulator, and the e2e replay and fallback runs.

## Next

- UI: Lucide 1.55.0 icons, segmented mode control, cards with shadows, a floating device control bar, one title style for both panes, a click-to-cycle theme button (system, light, dark), menus and tooltips drawn as one rounded surface, 150 ms tooltips, and a device dropdown in the pill when several devices are connected (real devices and emulators get their own icons; switching moves the same window and Maestro process to that device), steps shown as pending lines while Maestro runs them; Android touch steps go through adb and record in about 0.15 s. End to end on the phone (2026-10-10): 18 of 18 checks pass in the real window, the saved test replays, the screenshot fallback works. Waiting for the user's look.
- Then one device batch: end to end, replay, fallback.

- Device runs at the end: end to end (make the harness read element positions from the window's own tree, not Maestro on the UI thread), replay of the saved test, fallback without scrcpy.
- Check the first CI run on ubuntu, windows and macos (the ubuntu Qt packages are a best guess).
- Release 0.6.0 when the user says so; then raise the skill floors and fms-flutter-automation (python:3.14-alpine image) to it.
