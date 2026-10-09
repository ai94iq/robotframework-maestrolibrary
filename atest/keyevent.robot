*** Settings ***
Documentation     Key event keywords, against Android Settings.
Resource          resource.resource
Test Setup        Open Application    ${SETTINGS}
Suite Teardown    Close All Applications


*** Test Cases ***
Press Keycode Back Leaves A Sub Screen
    Click Text    Network & internet    exact_match=True
    Wait Until Page Contains    Internet
    Press Keycode    4
    Wait Until Page Contains Element    Network & internet

Press Key Types Into The Search Field
    [Teardown]    Terminate Application    ${SEARCH_APP}
    Click Text    Search settings    exact_match=True
    Input Text Into Current Element    wifi
    Press Key    Backspace
    Element Text Should Be    id=com.google.android.settings.intelligence:id/open_search_view_edit_text    wif
    Press Key    Back

Unsupported Keycode Fails Fast
    Run Keyword And Expect Error    ValueError: Maestro cannot send keycode 999. Supported:*    Press Keycode    999

Press Home Leaves The App
    Press Key    Home
    Wait Until Page Does Not Contain Element    Network & internet
