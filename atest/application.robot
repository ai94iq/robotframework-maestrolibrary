*** Settings ***
Documentation     Application management, screenshots and run-on-failure, against Android Settings.
Resource          resource.resource
Suite Teardown    Close All Applications


*** Test Cases ***
Open, Run Flow, Go Back And Close
    Open Application    ${SETTINGS}    clear_state=False
    Run Flow    - assertVisible: "Network.*"
    Run Flow    - tapOn: "Network.*"
    Go Back
    Run Flow    - assertVisible: "Network.*"
    Close Application

Run Flow From A File With Env
    Open Application    ${SETTINGS}
    Run Flow    ${CURDIR}/flows/assert_text.yaml    TEXT=Network.*

Run Flow From A File Resolves Relative Subflows
    Open Application    ${SETTINGS}
    Run Flow    ${CURDIR}/flows/calls_subflow.yaml    TEXT=Network.*

Failure Message Is Maestro's Reason And A Screenshot Is Taken
    Open Application    ${SETTINGS}
    ${old}=    Register Keyword To Run On Failure    Capture Page Screenshot
    Run Keyword And Expect Error    Assertion is false: "No such thing" is visible
    ...    Run Flow    - assertVisible: "No such thing"
    Register Keyword To Run On Failure    ${old}

Capture Page Screenshot Saves A File
    ${path}=    Capture Page Screenshot
    File Should Exist    ${path}
    ${none}=    Capture Page Screenshot    EMBED
    Should Be Equal    ${none}    ${None}

Get Source Has The Screen
    Open Application    ${SETTINGS}
    ${source}=    Get Source
    Should Contain    ${source}    Network

Execute Adb Shell
    ${out}=    Execute Adb Shell    echo    hello
    Should Be Equal    ${out.strip()}    hello

Clear Application State Stops And Wipes The App
    Open Application    ${SETTINGS}
    Clear Application State
    Run Keyword And Expect Error    adb shell pidof failed (1)*    Execute Adb Shell    pidof    ${SETTINGS}

Kill Application Stops A Background App
    Open Application    ${SETTINGS}
    ${pid}=    Execute Adb Shell    pidof    ${SETTINGS}
    Should Not Be Empty    ${pid.strip()}
    Execute Adb Shell    input    keyevent    KEYCODE_HOME
    # Measured: killApp within about 0.5 s of HOME does nothing, 1 s or more after it kills the app.
    Sleep    2s
    Kill Application    ${SETTINGS}
    Run Keyword And Expect Error    adb shell pidof failed (1)*    Execute Adb Shell    pidof    ${SETTINGS}

Kill Application Leaves A Foreground App Running
    Open Application    ${SETTINGS}
    Kill Application    ${SETTINGS}
    ${pid}=    Execute Adb Shell    pidof    ${SETTINGS}
    Should Not Be Empty    ${pid.strip()}

Open Application With Permissions Grants Them
    [Setup]    Skip Unless Permission App Is Installed
    [Teardown]    Restore Permission App
    Open Application    ${PERMISSION_APP}    permissions={'camera': 'allow'}
    Camera Permission Should Be    true

Set Application Permissions Round Trip
    [Setup]    Skip Unless Permission App Is Installed
    [Teardown]    Restore Permission App
    Set Application Permissions    ${PERMISSION_APP}    camera=allow
    Camera Permission Should Be    true
    Set Application Permissions    ${PERMISSION_APP}    camera=deny
    Camera Permission Should Be    false
    Set Application Permissions    ${PERMISSION_APP}    camera=allow
    Camera Permission Should Be    true
    Set Application Permissions    ${PERMISSION_APP}    camera=unset
    Camera Permission Should Be    false

Run Flow On A Directory Runs Only The Included Tags
    Open Application    ${SETTINGS}
    Run Flow    ${CURDIR}/flows/dir    include_tags=smoke

Timeout Can Be Changed
    ${old}=    Set Maestro Timeout    10s
    ${now}=    Get Maestro Timeout
    Should Be Equal As Numbers    ${now.total_seconds()}    10
    Set Maestro Timeout    ${old}

*** Keywords ***
Skip Unless Permission App Is Installed
    ${installed}=    Run Keyword And Return Status    Execute Adb Shell    pm    path    ${PERMISSION_APP}
    Skip If    not ${installed}    ${PERMISSION_APP} is not installed. Set PERMISSION_APP to an installed app with a CAMERA permission.

Camera Permission Should Be
    [Arguments]    ${granted}
    ${out}=    Execute Adb Shell    dumpsys    package    ${PERMISSION_APP}
    Should Contain    ${out}    android.permission.CAMERA: granted=${granted}

Restore Permission App
    ${installed}=    Run Keyword And Return Status    Execute Adb Shell    pm    path    ${PERMISSION_APP}
    # Restores to unset, not the prior grant: on a device that already granted CAMERA this revokes it.
    Run Keyword If    ${installed}    Set Application Permissions    ${PERMISSION_APP}    camera=unset
    Close Application
