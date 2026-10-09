*** Settings ***
Documentation     adb logcat per test and scrcpy mirroring. Needs an Android device with adb;
...               the mirroring test also needs scrcpy and a display.
Resource          resource.resource
Suite Teardown    Close All Applications


*** Test Cases ***
Logcat Streams While A Test Runs
    Open Application    ${SETTINGS}
    ${files}=    List Files In Directory    ${OUTPUT DIR}/logcat    *Logcat_Streams_While_A_Test_Runs.txt
    Length Should Be    ${files}    1

Logcat Of The Previous Test Was Kept
    ${files}=    List Files In Directory    ${OUTPUT DIR}/logcat    *Logcat_Streams_While_A_Test_Runs.txt
    ${size}=    Get File Size    ${OUTPUT DIR}/logcat/${files}[0]
    Should Be True    ${size} > 0

Screen Mirroring Shows The Device While Keywords Run
    [Tags]    scrcpy
    Start Screen Mirroring
    Swipe By Percent    50    70    50    30
    Run Keyword And Expect Error    *already running*    Start Screen Mirroring
    [Teardown]    Stop Screen Mirroring
