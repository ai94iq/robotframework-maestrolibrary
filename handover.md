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

- Studio on Linux and macOS (CI runs its tests there) and on an iOS simulator.
- The first CI run with the Studio jobs on ubuntu, windows and macos (the ubuntu Qt packages are a best guess).

## Next

- Release 0.6.0 when the user says so; then raise the skill floors and fms-flutter-automation (python:3.14-alpine image) to it.
- Typing, assertions and Launch still run through Maestro (5 to 14 s); typing through adb is not measured yet.
