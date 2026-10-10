# Handover

## State (2026-10-10)

- `main` is at the 0.5.0 release plus unreleased Studio work, pushed; no tag yet (the user says when). Python floor 3.12.
- Run: `python -m MaestroLibrary.studio [--device ID] [--app APP_ID] [--max-size PX] [--video-encoder NAME]`; `pip install -e ".[studio]"` installs PySide6 6.12.0, av 19.0.1 and grpcio 1.84.0. `--self-check [FILE]` checks a build without a device.
- Code: `locators.py` (hit testing, locator choice), `studio.py` (`Session`, `main`, `self_check`), `stream.py` (`ScrcpyStream`), `driver.py` (`DriverReader`), `studio_qt.py` (window and workers), `studio_icons.py` (Lucide 1.55.0); `packaging/` builds the desktop bundles.
- Threads: the UI; `ActionWorker` runs Maestro steps and screen reads in order (at most one read queued); a second `ActionWorker` sends Android touch steps (tap, long press, swipe, Back) with adb (a failed adb call records nothing) and does line edits; steps change worker only when the other is idle; `StreamReader` decodes the scrcpy stream, keeping the newest frame. The MCP client takes one call at a time.
- Android tree reads go to Maestro's driver over gRPC (`DriverReader`, an adb forward to device port 7001) and fall back to MCP `inspect_screen`.
- One `maestro mcp` process serves every device: a device switch points the library at the new device and restarts only the live view.
- Tools are found on PATH, then in the installers' folders (`~/.maestro/bin`, Android SDK `platform-tools`, Homebrew); never the working directory.
- Desktop bundles: CI's `bundles` job builds and self-checks Windows `.exe`, Linux `.tar.gz` and macOS `.dmg` (arm64, Intel) on every run; `release-bundles` attaches them with `SHA256SUMS` on a `vX.Y.Z` tag. Unsigned.

## Run

```
python -m pytest -q utest                                        # no device needed
python -m robot --dryrun --pythonpath src --output NONE --report NONE --log NONE atest
python -m bandit -q -c pyproject.toml -r src
```

## Verified

- Unit tests (185), coverage gate (85%; 91% now), bandit and the atest dry run pass at each commit; pip-audit clean; every dependency, tool and action at its latest release (checked 2026-10-10).
- On the phone (Samsung A70, Android 15) and a Pixel 9 emulator, 2026-10-10, in the real window:
  - End to end 18 of 18: tap, type, Back, Launch, right-click assert, swipe, Inspect, inspector Tap, element list, element boxes, Undo, Pause, Save. The saved test replays with robot (PASS).
  - Screenshot fallback without scrcpy: the state reads screenshots, the view refreshes after each step, steps still record.
  - Touch line confirmed 0.13 to 0.17 s after a click; device switch back to live in 0.7 s (emulator) and 2.2 s (phone); Elements show a new screen 0.17 to 1.60 s after a tap.
- Linux bundle in WSL against the phone over adb Wi-Fi (details in `plan.md`, Measured); Linux and macOS arm64 bundles built and self-checked in CI.
- impeccable detect on an HTML copy of the window, light and dark: no findings.

## Not verified yet

- The Windows bundle (first CI run failed; fix `ede0d9e` not seen) and the macOS Intel bundle; the Windows `.exe` on this PC.
- Studio on a real macOS desktop and on an iOS simulator (no Mac here).
- The tree-read speed-ups after the code review fixes were measured before them; the end-to-end run was not repeated after `dde9ed4` (the user had Studio open on the phone).

## Next

- Read the CI result of `ede0d9e` (the unauthenticated GitHub API limit was used up; `! gh auth login` avoids it).
- Run the Windows `.exe` from CI against the phone; repeat the 18-check end to end after the review fixes.
- `~/claude-skills`: commit `7008a8f` waits for the VPN to push (the D: mirror is pushed).
- iOS check, then fms-flutter-automation; release 0.6.0 only when the user says so, then raise the skill floors.
- Typing, assertions and Launch still run through Maestro (5 to 14 s); typing through adb is not measured yet.
