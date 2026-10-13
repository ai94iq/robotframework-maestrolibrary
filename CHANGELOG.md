# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions: [SemVer](https://semver.org/).

## Contents

- [Unreleased](#unreleased)
- [0.6.3](#063---2026-10-11) to [0.6.0](#060---2026-10-11)
- [0.5.0](#050---2026-10-10)
- [0.4.2](#042---2026-10-09) to [0.3.0](#030---2026-10-09)
- [0.2.0](#020---2026-10-08)
- [0.1.2](#012---2026-10-07) to [0.1.0](#010---2026-10-07)

## [Unreleased]

## [0.6.3] - 2026-10-11
### Changed
- iOS support is no longer marked WIP: it ran on an iOS simulator (element keys and locators,
  typing, `Kill Application`, the simulator's log stream, screen recording, `Clear Keychain`,
  `Hide Keyboard` with `key_name`), so the one-time "iOS support is WIP and untested" warning is
  gone. Not tested on iOS yet: `Click Alert Button`, `Hide Keyboard` without `key_name`, and
  screen mirroring.

## [0.6.2] - 2026-10-11
### Fixed
- iOS `Stop Screen Recording`: when `xcrun simctl io recordVideo` exits without a video, the failure
  message now ends with what simctl printed (`simctl said: ...`) instead of only its exit code. Found on
  the first iOS simulator run, where the recorder exited with 16 and said nothing.

## [0.6.1] - 2026-10-11
### Fixed
- Studio's device switcher now lists devices connected while it is open (an emulator started or a phone
  plugged in later): each idle poll checks `adb devices` and reads Maestro's device list again only when it
  changes.
- Studio's device pill keeps the device name next to its status dot when the state changes from
  connecting to live.

## [0.6.0] - 2026-10-11
### Added
- Studio: `python -m MaestroLibrary.studio` (the `studio` extra: PySide6, PyAV) shows the device
  screen live (scrcpy's H.264 stream) and records a Robot test while you act on it: click, type,
  drag, right-click assertions, control-bar steps; Inspect mode shows suggested locators and
  attributes. On Android, touch steps go through adb and are recorded in about 0.15 s, plain
  typing goes through adb in about 0.3 s instead of 4 s (other text and secrets still go through
  Maestro), and the element tree is read from Maestro's on-device driver (0.45 s against 2.2 s;
  `grpcio` joins the `studio` extra). A device switcher for several connected devices, a theme
  button (System, Light, Dark; remembered) and keyboard shortcuts.
- Studio desktop bundles on each GitHub release: Windows `.exe`, Linux `.tar.gz`, macOS `.dmg` (arm64 and
  Intel), built with PyInstaller and an LGPL FFmpeg that only decodes H.264 (no GPL parts; the build checks it).
  Unsigned for now. `find_exe` also looks where the installers put maestro and adb, for apps opened from Finder.
### Fixed
- `Capture Page Screenshot` and the other screenshot keywords work outside a Robot run (plain Python,
  Studio): they save to the working directory instead of failing with `RobotNotRunningError`.
### Changed
- Python 3.12 or newer is required (3.10 reached end of life on 2026-10-01; 3.12 is supported until
  2028-10).

## [0.5.0] - 2026-10-10
### Added
- `python -m MaestroLibrary.flow2robot flow.yaml` converts a Maestro flow, such as one recorded in
  Maestro Studio, to a Robot test; commands without a keyword become an inline `Run Flow`. Needs
  the `convert` extra (PyYAML).
- `record_flows=True` import argument: each test's Maestro commands are written to
  `flows/<n>-<test>.yaml`, a flow `maestro test` replays; `Input Password` is recorded as
  `${PASSWORD}`.

## [0.4.2] - 2026-10-09
### Changed
- The source is public on GitHub (https://github.com/ai94iq/robotframework-maestrolibrary); the PyPI page links to it, its issues and this
  changelog. CI and PyPI publishing run on GitHub Actions.

## [0.4.0] - 2026-10-09
### Added (iOS: WIP, untested; no Mac was available)
- iOS simulator log per test (`xcrun simctl spawn ... log stream`) in the same `logcat/` files.
- iOS simulator screen recording (`xcrun simctl io ... recordVideo`); Start Screen Mirroring is a
  no-op on iOS.
- `Clear Keychain` (iOS), `Click Alert Button`, `Hide Keyboard    key_name` on iOS.
- One warning when an iOS device is used, saying iOS support is WIP.
### Changed
- Go Back, Press Key Back/Power/Tab (and Press Keycode 4), Set Airplane Mode and Execute Adb Shell
  fail at once on iOS instead of reaching adb or passing without effect.

## [0.3.0] - 2026-10-09
### Added
- Logcat: every test's `adb logcat` is streamed to `logcat/<n>-<test>.txt` in the output
  directory and linked in the log (import argument `logcat`, on by default).
- `Start Screen Mirroring` / `Stop Screen Mirroring` and the `mirror` import argument: the
  Android screen in a scrcpy window.
### Changed
- adb is found by running `adb version`.
### Security
- `maestro`, `adb`, `scrcpy` and `taskkill` are looked up only in PATH's absolute directories.
  Windows (and `shutil.which` there) otherwise runs an exe from the working directory first, so
  an `adb.exe` in a checked-out test repository ran instead of the real one.
- A program found under the name `adb` or `scrcpy` is used only if its version output reads like
  the real tool (`adb version`, `scrcpy --version`), and `maestro` only if its MCP server names
  itself `maestro`; otherwise it is stopped and refused. This catches a wrong or impersonating
  binary, though a deliberate fake has already run once when it is checked.

## [0.2.0] - 2026-10-08
### Added
- App state: `Clear Application State`, `Kill Application`, `Set Application Permissions`, and
  `Open Application    permissions=...`.
- `Run Flow` on a directory of flows, with `include_tags` / `exclude_tags` (a list or one tag).
- Device: `Set Location`, `Travel`, `Landscape`, `Portrait`, `Set Orientation`,
  `Set Airplane Mode`, `Set Dark Mode`, `Add Media`.
- Visual: `Capture Element Screenshot` (PNG) and `Screenshot Should Match` (Maestro's
  assertScreenshot, whole screen or one element, with a threshold).
- `Start Screen Recording` / `Stop Screen Recording` (Android, adb screenrecord).
- README: where each `maestro` CLI subcommand and flow command is covered, or why not.
### Fixed
- A Maestro call that outlives the client's wait restarts the server instead of leaving it busy.
  Waits and scrolls get their own timeout plus a minute; Run Flow files and directories an hour.
- Swipe and Swipe By Percent read a bare number as milliseconds, like AppiumLibrary (it was seconds).
- Run Flow with a `.yaml`/`.yml` path or a directory that doesn't exist fails with "not found"
  instead of a YAML parse error.
- Stop Screen Recording stops only its own recording, and fails with a message when adb hangs.
### Changed
- Licence: MIT (was proprietary). The `Private :: Do Not Upload` classifier is gone.
- CI: every pipeline builds the package and runs `twine check --strict`; a version tag also
  uploads to PyPI when the `PYPI_TOKEN` variable is set, after the project registry upload.
### Notes
- `maestro mcp` reinstalls Maestro's driver app once per process (hard-coded in Maestro); the
  library keeps one process per run.

## [0.1.2] - 2026-10-07
### Security
- Minimum versions raised to the latest releases: robotframework 7.5, robotframework-pythonlibcore
  4.6.0; build backend setuptools 84 (past PYSEC-2026-3447). CI upgrades pip and setuptools
  before installing, and pins build >= 1.6.1 and twine >= 7.0.0 for publishing.

## [0.1.1] - 2026-10-07
### Fixed
- CI: pip-audit checks the package's declared dependencies, not the CI image's tools.
  0.1.0 was tagged but never published, because that check failed.

## [0.1.0] - 2026-10-07
### Added
- MaestroLibrary: Robot Framework keywords over `maestro mcp` (stdio), with AppiumLibrary's
  keyword names, arguments and `strategy=value` locators.
- Keyword groups: application management (including `Run Flow` and `Execute Adb Shell`),
  element (Should/Get on the settled screen; `Expect Element`/`Expect Text`), waiting, touch,
  key events (`Press Key`, `Press Keycode`), screenshots, run on failure.
- Import arguments: `timeout`, `run_on_failure`, `device`, `maestro`, `speed`.
- `Is Keyboard Shown`.
### Differences from Maestro's own behaviour
- `Open Application` waits for the app's window (Android, adb), like Appium's appWaitActivity.
- `Hide Keyboard` does nothing when no keyboard is shown; Maestro's Android hideKeyboard
  always sends Back.
