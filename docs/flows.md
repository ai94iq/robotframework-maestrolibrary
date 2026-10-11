# Converting between Maestro flows and Robot tests

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

## Robot tests to Maestro flows
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
