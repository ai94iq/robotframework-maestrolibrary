# robotframework-maestrolibrary

Robot Framework keywords for mobile apps, driven by [Maestro](https://maestro.dev).
If you know [AppiumLibrary](https://github.com/serhatbolsu/robotframework-appiumlibrary),
you already know the keyword names, the arguments and the `strategy=value` locators.
There's no Appium server and no capabilities to manage. Maestro waits for the UI on every action.

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [Example](#example)
- [Locators](#locators)
- [Coming from AppiumLibrary](#coming-from-appiumlibrary)
- [Android logs and mirroring](#android-logs-and-mirroring)
- [iOS](#ios)
- [Converting between Maestro flows and Robot tests](#converting-between-maestro-flows-and-robot-tests)
- [Studio: record a test on a live device](#studio-record-a-test-on-a-live-device)
- [Maestro CLI coverage](#maestro-cli-coverage)
- [Development](#development)

## Requirements
- Python 3.12 or newer
- Maestro CLI on PATH (`maestro --version`) and Java 17+
- A running Android emulator or connected Android device, or an iOS simulator on a Mac (see iOS)
- Android: `adb` (platform-tools) on PATH. `Open Application` uses it to wait for the app's
  window; `Execute Adb Shell`, screen recording and the logcat files need it. Without it, Open
  Application warns and returns as soon as Maestro does.
- Optional, for screen mirroring and Studio's live view: [scrcpy](https://github.com/Genymobile/scrcpy)
  on PATH and a display.
- `maestro`, `adb` and `scrcpy` are taken only from PATH's absolute folders, never the working
  folder, and only if they answer like the real tool (`adb version`, `scrcpy --version`, and
  Maestro's MCP server naming itself `maestro`). Anything else is stopped and refused.

## Install
```
pip install robotframework-maestrolibrary
```
For development: `pip install -e .`

Bugs and ideas: [issues](https://github.com/ai94iq/robotframework-maestrolibrary/issues). Releases: a `vX.Y.Z` tag matching `__version__` publishes
to PyPI from GitHub Actions ([docs/distribution.md](docs/distribution.md)). MIT: see LICENSE.

## Example
```robotframework
*** Settings ***
Library    MaestroLibrary    timeout=10s

*** Test Cases ***
Search Settings
    Open Application    com.android.settings
    Click Text    Search settings    exact_match=True
    Input Text    id=com.google.android.settings.intelligence:id/open_search_view_edit_text    wifi
    Wait Until Page Contains    Wi-Fi
    [Teardown]    Close All Applications
```

## Locators
`text=`, `accessibility_id=`, `id=` (literal, whole value), `regex=`, `id_regex=`
(Maestro regular expressions), `point=50%,50%`. A bare value means text. Flutter apps
get ids from `Semantics(identifier: ...)`. xpath, class, android, ios, predicate, chain,
css, name and identifier fail with a clear message.

## Coming from AppiumLibrary
Same names and arguments: Close/Activate/Terminate Application, Close All
Applications, Go Back, Go To Url, Get Source, Log Source, Execute Adb Shell, Click
Element, Click Text, Input Text, Input Password, Input Text Into Current Element, Clear
Text, Hide Keyboard, Page Should (Not) Contain Text/Element, Element Should Be
Visible/Enabled/Disabled, Text Should Be Visible, Element Text Should Be, Element Should
(Not) Contain Text, Get Text, Get Element Attribute, Scroll Element Into View, Expect
Element, Expect Text, the five Wait Until keywords, Swipe, Swipe By Percent, Scroll
Down/Up, Tap, Long Press, Press Keycode, Capture Page Screenshot, Register Keyword To Run
On Failure, Set Location, Landscape, Portrait, Click Alert Button (iOS: not tested yet).

Differences:
- `Open Application    <app id>    clear_state=False    stop_app=True`: no remote URL or
  capabilities. Like Appium, it returns once the app has window focus.
- Set/Get Appium Timeout become Set/Get Maestro Timeout.
- Press Keycode supports the keycodes that Maestro can send. `Press Key` takes Maestro key names.
- Should/Get keywords check the settled screen once. Wait/Expect keywords and every action wait.
- Screenshots are JPEG (`maestro-screenshot-<n>.jpg`, or `EMBED`).
- Swipe `duration` takes a time (`300ms`); a bare number is milliseconds, as in AppiumLibrary.
- `speed=0.5s` (import argument) pauses before every Maestro command, like SeleniumLibrary's
  speed. Use it when a slow or overloaded emulator stops responding.
- Start Screen Recording takes `time_limit` (AppiumLibrary: `timeLimit`), 3 minutes by default.
  Stop Screen Recording saves `filename` as given (AppiumLibrary appends `.mp4`). Both are
  Android only (adb `screenrecord`): Maestro ends its own recording with each flow, and every
  keyword is its own flow. Put Stop in a teardown.
- Set Location ignores `altitude`.

Maestro-only keywords:
- `Run Flow`: a YAML file, inline commands, or a directory of flows with `include_tags` /
  `exclude_tags`, plus env variables.
- App state: `Clear Application State`, `Kill Application` (the system killing a background app),
  `Set Application Permissions` (`camera=deny`, `all=allow`), `Open Application    permissions=...`.
- Device: `Travel` (move the location along points), `Set Orientation`, `Set Airplane Mode`,
  `Set Dark Mode`, `Add Media` (put images or videos in the gallery).
- Visual: `Capture Element Screenshot` (PNG), `Screenshot Should Match` (compare with a reference
  PNG, whole screen or one element, with a threshold).
- `Wait For Animation To End`, `Is Keyboard Shown`.
- Android: `Start Screen Mirroring` / `Stop Screen Mirroring` (scrcpy).

Not ported: webview contexts, xpath, multiple app aliases, touch id, WebElement keywords,
Drag And Drop, Flick, sleep-between-wait-loop settings, and the iOS keywords Lock, Input Value and
Tap With Number Of Taps.

## Android logs and mirroring
On Android, every test's `adb logcat` is streamed to `logcat/<n>-<test>.txt` in the output
directory and linked in the log, so a crash's log survives the device's small ring buffers
(`logcat=False` turns it off). `Start Screen Mirroring` / `Stop Screen Mirroring`, or `mirror=True`
for the whole run, show the device in a scrcpy window. Import arguments, a full suite and the run
commands: [docs/logs-and-mirroring.md](https://github.com/ai94iq/robotframework-maestrolibrary/blob/main/docs/logs-and-mirroring.md).

## iOS
Maestro 2.11.0 drives iOS **simulators only** (macOS with Xcode); it fails physical iPhones with
"Physical iOS devices are not yet supported".

Measured on an iPhone simulator (two runs on 2026-10-11):
- element keys match Android: Flutter text in `a11y`, Semantics ids in `rid`; text and `id=`
  locators work;
- the per-test log files stream the simulator's log (`xcrun simctl spawn <udid> log stream`),
  the app's lines included;
- `Start/Stop Screen Recording` (`xcrun simctl io <udid> recordVideo`) saves an MP4;
- `Kill Application`, `Clear Keychain` and `Hide Keyboard    key_name=Done` work;
- `xcrun` is checked like adb (`xcrun --version` must answer `xcrun version <n>`) and accepted.

Android only, failing at once on iOS (from Maestro's docs): `Go Back` (iOS has no back button),
`Press Key` Back / Power / Tab and `Press Keycode 4`, `Set Airplane Mode` (simulators have none),
`Execute Adb Shell`, `Is Keyboard Shown`.

Not tested on iOS yet: `Click Alert Button` (no alert appeared), `Hide Keyboard` without
`key_name`, `Start Screen Mirroring` (the Simulator window already shows the screen), permission
names for `Set Application Permissions`, and which attributes `Get Element Attribute` sees.

## Converting between Maestro flows and Robot tests
Record a flow in Maestro Studio, save its YAML, and convert it to a Robot test:
```
pip install "robotframework-maestrolibrary[convert]"
python -m MaestroLibrary.flow2robot settings_search.yaml > settings_search.robot
```
The other way, `record_flows=True` writes every Maestro command a test sends to
`flows/<n>-<test>.yaml`. A worked example and what converts to what:
[docs/flows.md](https://github.com/ai94iq/robotframework-maestrolibrary/blob/main/docs/flows.md).

## Studio: record a test on a live device
```
pip install "robotframework-maestrolibrary[studio]"      # PySide6, PyAV and grpcio
python -m MaestroLibrary.studio --app com.android.vending
```
Or, without Python, download the Windows `.exe`, Linux `.tar.gz` or macOS `.dmg` from the
[GitHub release](https://github.com/ai94iq/robotframework-maestrolibrary/releases) (unsigned for now; the release text
says how to open them). Maestro, adb and scrcpy are still needed on the machine.

A window shows the device screen live; every action you take on it runs on the device while the
matching Robot line is recorded. What each action records, Inspect mode, shortcuts and platform
notes: [docs/studio.md](https://github.com/ai94iq/robotframework-maestrolibrary/blob/main/docs/studio.md).

## Maestro CLI coverage
The library talks to `maestro mcp`. Which other `maestro` subcommands map to which keywords, the
flow commands reachable only through `Run Flow`, and how to share the server with a coding agent:
[docs/maestro-cli.md](https://github.com/ai94iq/robotframework-maestrolibrary/blob/main/docs/maestro-cli.md).

## Development
```
python -m unittest discover -s utest                        # no device needed
robot --pythonpath src -d results atest                     # needs a running Android emulator
python -m robot.libdoc --pythonpath src MaestroLibrary results/MaestroLibrary.html
```
