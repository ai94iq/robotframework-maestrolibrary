# Studio: record a test on a live device

```
pip install "robotframework-maestrolibrary[studio]"      # PySide6, PyAV and grpcio
python -m MaestroLibrary.studio --app com.android.vending
```
Or, without Python, download the Windows `.exe`, Linux `.tar.gz` or macOS `.dmg` from the
[GitHub release](https://github.com/ai94iq/robotframework-maestrolibrary/releases) (unsigned for now; the release text
says how to open them). Maestro, adb and scrcpy are still needed on the machine.

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
- On Android with adb, taps, long presses, swipes, Back and plain typing (letters, digits, spaces
  and `. , _ @ : + = / -`) go to the device with `adb shell input` and are recorded at once. Other
  text and secrets go through Maestro, as do assertions and Launch, which waits for the screen to
  settle. The recorded line is the same either way, and the locator is checked when the test runs.
  Measured on an Android 15 phone: the line is recorded 0.13 to 0.17 s after a click and the screen
  changes 0.33 to 0.43 s after it (a Maestro tap took 4 to 7 s); typing takes about 0.3 s against
  4 s through Maestro.
- On Android, the element tree is read from Maestro's on-device driver (its gRPC `viewHierarchy`,
  through an adb forward): 0.45 s on an Android 15 phone against 2.2 s for MCP's `inspect_screen`,
  which stays the fallback.
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
