# Android logs and mirroring

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
