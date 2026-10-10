# Handover

## State (2026-10-10)

- `main` is at the 0.5.0 release plus unreleased Studio work. The Studio core is done: `locators.py` (hit testing, locator choice), `studio.Session` and `stream.ScrcpyStream`.
- The web layer is gone. `studio_qt.py` has `FrameDecoder` (PyAV H.264 to QImage) and `StreamReader` (QThread). `ActionWorker` runs steps in order on its own thread (Task 5). The window and `main()` come next (Task 6), so `python -m MaestroLibrary.studio` does nothing yet.
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

- The Qt window, Linux and macOS (the CI matrix comes in Task 7), and an iOS simulator.

## Next

- Task 6 in `plan.md`: the Qt window (impeccable Operate mode), `main()`, then the device end-to-end run.
