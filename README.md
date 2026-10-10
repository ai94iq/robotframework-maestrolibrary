# robotframework-maestrolibrary

Robot Framework keywords for mobile apps, driven by [Maestro](https://maestro.dev).
If you know [AppiumLibrary](https://github.com/serhatbolsu/robotframework-appiumlibrary),
you already know the keyword names, the arguments and the `strategy=value` locators.
There's no Appium server and no capabilities to manage. Maestro waits for the UI on every action.

## Requirements
- Python 3.12 or newer
- Maestro CLI on PATH (`maestro --version`) and Java 17+
- A running Android emulator or connected Android device, or an iOS simulator on a Mac (WIP, see iOS)
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
to PyPI from GitHub Actions (docs/distribution.md). MIT: see LICENSE.

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
On Failure, Set Location, Landscape, Portrait, Click Alert Button (iOS: WIP).

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
Logcat: on Android, every test's `adb logcat` is streamed to `logcat/<n>-<test>.txt` in the
output directory and linked in the log, so a crash's log survives the device's small ring
buffers. Suite setup and teardown get a file named after the suite. Needs adb; turn it off with
`logcat=False`.

Mirroring: `Start Screen Mirroring` shows the device screen in a scrcpy window on this computer,
and `Stop Screen Mirroring` closes it (a no-op when nothing runs, so it fits a teardown).
`mirror=True` opens it for the whole run instead. The window is view only; `control=True` lets
the mouse and keyboard through. Extra arguments go to scrcpy as given, for example
`--max-size=1024` or `--record=run.mp4` for a recording longer than `Start Screen Recording`'s
3 minutes.

Import arguments, set once in a shared resource file:

```robotframework
*** Settings ***
Documentation     common.resource: the library and its settings, for every suite.
Library           MaestroLibrary    timeout=10s    device=${DEVICE}    logcat=${LOGCAT}    mirror=${MIRROR}

*** Variables ***
${DEVICE}         ${None}     # the first connected device
${LOGCAT}         ${True}     # logcat/<n>-<test>.txt per test
${MIRROR}         ${False}    # a scrcpy window for the whole run
```

A suite that uses it, with mirroring and a recording for one test:

```robotframework
*** Settings ***
Resource          common.resource
Suite Setup       Open Application    com.example.app
Suite Teardown    Close All Applications

*** Test Cases ***
Login Works
    Input Text    id=username    demo
    Input Password    id=password    ${PASSWORD}
    Click Element    text=Log in
    Wait Until Page Contains    Welcome

Checkout While Watching
    [Setup]    Start Screen Mirroring    --max-size=1024    --always-on-top
    Start Screen Recording    time_limit=60s
    Click Element    text=Checkout
    Wait Until Page Contains    Order placed
    [Teardown]    Run Keywords    Stop Screen Recording    checkout.mp4
    ...           AND    Stop Screen Mirroring
```

```
robot -d results tests/                                      # logcat on, no window
robot -d results --variable MIRROR:True tests/               # watch the whole run
robot -d results --variable DEVICE:emulator-5554 --variable LOGCAT:False tests/
```
After a crash, open the test in `log.html` and follow its `logcat` link, or read
`results/logcat/<n>-<suite>.<test>.txt`.

## iOS (WIP, needs testing)
Nothing here has run on iOS yet: there was no Mac to test on. Maestro 2.11.0 drives iOS
**simulators only** (macOS with Xcode); it fails physical iPhones with "Physical iOS devices are
not yet supported". Using an iOS device logs one warning that iOS support is WIP.

Android only, failing at once on iOS (from Maestro's docs): `Go Back` (iOS has no back button),
`Press Key` Back / Power / Tab and `Press Keycode 4`, `Set Airplane Mode` (simulators have none),
`Execute Adb Shell`, `Is Keyboard Shown`.

WIP, written from Maestro's and Apple's docs, needs testing on a simulator:
- the per-test log files stream the simulator's log (`xcrun simctl spawn <udid> log stream`);
- `Start/Stop Screen Recording` uses `xcrun simctl io <udid> recordVideo`;
- `Start Screen Mirroring` does nothing (the Simulator window shows the screen);
- `Clear Keychain`, `Click Alert Button`, `Hide Keyboard    key_name=Done`;
- `xcrun` is checked like adb (`xcrun --version` must answer `xcrun version <n>`).

Not checked on iOS yet: Kill Application, permission names for `Set Application Permissions`,
which attributes `Get Element Attribute` sees, and how `id=` matches.

## Converting between Maestro flows and Robot tests
Record a flow in Maestro Studio, save its YAML, and convert it to a Robot test:
```
pip install "robotframework-maestrolibrary[convert]"
python -m MaestroLibrary.flow2robot settings_search.yaml > settings_search.robot
```
A Studio flow such as
```yaml
appId: com.android.settings
---
- launchApp
- assertVisible: "Search Settings"
- tapOn:
    text: "Apps"
    index: 0
- back
- tapOn:
    id: "com.android.settings:id/search_action_bar"
- inputText: "wifi"
- takeScreenshot: search
- hideKeyboard
- back
- stopApp
```
becomes
```robotframework
*** Settings ***
Library    MaestroLibrary

*** Test Cases ***
Settings Search
    Open Application    com.android.settings
    Wait Until Page Contains Element    text\=Search Settings
    Run Flow    - {tapOn: {text: Apps, index: 0}}
    Go Back
    Input Text    id_regex\=com.android.settings:id/search_action_bar    wifi
    Capture Page Screenshot    search.jpg
    Hide Keyboard
    Go Back
    Terminate Application    com.android.settings
```
(`\=` keeps Robot from reading `id=...` as a named argument.)

Commands with a keyword become that keyword (`tapOn` then `inputText` becomes one `Input Text`);
the rest, such as a selector with `index`, become an inline `Run Flow` line. Maestro matches text
as a regular expression, so a value with regex characters (an id with dots, too) comes out as
`regex=` or `id_regex=`, which keeps its meaning. Move the locators
into variables before the test joins a suite.

### Robot tests to Maestro flows
A Robot test is only a flow once it runs: variables, loops and user keywords resolve at run time.
So the library records instead of converting. With `record_flows=True`, every Maestro command a
test sends goes to `flows/<n>-<test>.yaml` in the output directory, linked in the log:
```
robot -v RECORD:True -d results tests/      # Library  MaestroLibrary  record_flows=${RECORD}
maestro test -e PASSWORD=... results/flows/1-Log_In.yaml
```
Loops come out unrolled and `Run Flow` lines are kept; `Input Password` is recorded as
`${PASSWORD}`. Snapshot checks (`Page Should Contain Element`, `Get Text`, ...), screenshots, adb
and Python steps are not Maestro commands, so they are not in the flow; waiting checks such as
`Wait Until Page Contains Element` are (`extendedWaitUntil`).

## Studio: record a test on a live device
```
pip install "robotframework-maestrolibrary[studio]"      # PySide6 and PyAV
python -m MaestroLibrary.studio --app com.android.vending
```
A window shows the device screen live, and every action you take on it runs on the device while
the matching Robot line is recorded:

| On the screen | Recorded |
|---|---|
| click | `Click Element` with the first unique locator (`id=`, then `text=`), or `point=` and a GAP comment |
| type, then Enter | merged into the click before it: `Input Text` (`Input Password` with `${PASSWORD}` when Secret is on) |
| drag | `Swipe By Percent` |
| right-click | `Long Press`, `Wait Until Page Contains Element`, `Element Should Be Visible`, `Element Text Should Be` |
| control bar under the screen | `Open Application`, `Go Back`, `Hide Keyboard`, `Capture Page Screenshot` |

Inspect mode selects instead of acting: the element's suggested locators (with how many elements
each matches), its attributes and the source tree. Undo, Clear, Copy and Save work on the recorded
lines; Record pauses recording while actions still run. Move the locators into variables and file
the GAP lines as test id requests before the test joins a suite.

- The live view needs scrcpy on PATH and an Android device; it streams the device's hardware H.264
  encoder at up to 1080 px (`--max-size`; `--video-encoder` picks another encoder from
  `scrcpy --list-encoders`). Without it, or on an iOS simulator, the view refreshes with a
  screenshot after each step.
- On Android with adb, taps, long presses, swipes and Back go to the device with `adb shell input`
  and are recorded at once; typing, assertions and Launch run through Maestro, which waits for the
  screen to settle. The recorded line is the same either way, and the locator is checked when the
  test runs. Measured on an Android 15 phone: the line is recorded 0.13 to 0.17 s after a click and
  the screen changes 0.33 to 0.43 s after it (a Maestro tap took 4 to 7 s).
- With several devices connected, the device box in the toolbar lists them (phones and emulators
  marked apart); picking one moves Studio to it in place and keeps the recorded lines.
- The theme button in the toolbar cycles System, Light and Dark; the choice is remembered between
  runs.
- Shortcuts: `Ctrl+1` Act, `Ctrl+2` Inspect, `Ctrl+Z` undo, `Ctrl+S` save, `Delete` removes the
  selected recorded line.
- Keep Robot runs off the device while Studio is open: Maestro allows one session per device.
- Linux needs Qt's system libraries (Debian/Ubuntu: `libxcb-cursor0`); Windows and macOS need
  nothing extra.
- Device text is shown as plain text, and recorded arguments escape Robot variable syntax, so an
  app cannot inject code into the saved test.

## Maestro CLI coverage
The library talks to `maestro mcp`. What the other `maestro` subcommands do, and where it lives here:

| `maestro` | Here |
|---|---|
| `test` (flows, tags, `-e`) | `Run Flow` |
| `print-hierarchy`, `query` | `Get Source`, `Get Text`, `Get Element Attribute`, the Should keywords |
| `list-devices` | the `device` import argument; the first connected device by default |
| `record` | `Start/Stop Screen Recording` |
| `check-syntax` | `Run Flow` fails with Maestro's parse error and its line |
| `start-device` | not a test step: boot the emulator before the run, e.g. `maestro start-device --platform android` in CI |
| `studio`, `chat`, `driver`, `cloud`, `login`, ... | interactive or Maestro Cloud tools, not used |

Flow commands without a keyword, still reachable with `Run Flow`: the AI assertions (need a
Maestro Cloud key), `inputRandom*`, clipboard commands (the copied text stays inside one flow),
`repeat`/`retry` (use Robot's FOR and `Wait Until Keyword Succeeds`), `runScript`/`evalScript`,
`toggleAirplaneMode`, `assertDarkMode`/`assertLightMode`, `clearKeychain` (iOS), `doubleTapOn`.

Each `maestro mcp` process reinstalls Maestro's driver app on the device once, when it first
connects (Maestro hard-codes it). The library keeps one process for the whole run.

Tip: to let a coding agent look at the app while you write tests, register the same server with
it, e.g. `claude mcp add maestro -- maestro mcp` for Claude Code. It opens its own session on
the device, so keep it idle while a Robot run is going.

## Development
```
python -m unittest discover -s utest                        # no device needed
robot --pythonpath src -d results atest                     # needs a running Android emulator
python -m robot.libdoc --pythonpath src MaestroLibrary results/MaestroLibrary.html
```
