# Handover

## State (2026-10-10)

- `main` is at the 0.5.0 release plus unreleased Studio work. The Studio core is done: `locators.py` (hit testing, locator choice), `studio.Session` and `stream.ScrcpyStream`.
- `studio.py` still holds revision 1's HTTP server (`make_server`) and `studio.html` still ships. Task 4 removes both for the Qt window.
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

## Not verified yet

- The Qt window, the decoding route (Qt FFmpeg or PyAV), Linux and macOS, and an iOS simulator.

## Next

- Task 4 in `plan.md`: remove the web layer, install PySide6 (latest, checked live), and spike decoding.
