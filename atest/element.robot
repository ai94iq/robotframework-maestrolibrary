*** Settings ***
Documentation     Element keywords, against Android Settings and its search field.
Resource          resource.resource
Test Setup        Open Application    ${SETTINGS}
Suite Teardown    Close All Applications


*** Variables ***
${SEARCH}         id=com.google.android.settings.intelligence:id/open_search_view_edit_text


*** Test Cases ***
Page Text And Element Checks
    Page Should Contain Text    Network
    Page Should Not Contain Text    No such thing here
    Page Should Contain Element    text=Network & internet
    Page Should Not Contain Element    id=no.such:id/thing
    Element Should Be Visible    Network & internet
    Text Should Be Visible    Network &
    Text Should Be Visible    Network & internet    exact_match=True

Snapshot Checks Fail Without Waiting And Name The Locator
    Run Keyword And Expect Error    Page should have contained element 'text=Nope' but did not.
    ...    Page Should Contain Element    text=Nope    loglevel=NONE
    Run Keyword And Expect Error    Text 'Network' should be visible but did not.
    ...    Text Should Be Visible    Network    exact_match=True    loglevel=NONE

Unsupported Locator Fails Fast
    Run Keyword And Expect Error    *not supported by Maestro*    Click Element    //android.widget.Button

Get Text And Text Assertions
    ${text}=    Get Text    regex=Network.*
    Should Be Equal    ${text}    Network & internet
    Element Text Should Be    regex=Network.*    Network & internet
    Element Should Contain Text    regex=Network.*    internet
    Element Should Not Contain Text    regex=Network.*    Bluetooth
    @{all}=    Get Text    regex=.*    first_only=False
    Should Contain    ${all}    Network & internet

Get Element Attribute And Enabled State
    ${enabled}=    Get Element Attribute    Network & internet    enabled
    Should Be True    ${enabled}
    ${class}=    Get Element Attribute    Network & internet    class
    Should Be Equal    ${class}    android.widget.TextView
    Element Should Be Enabled    Network & internet
    Run Keyword And Expect Error    Element 'Network & internet' should be disabled but did not.
    ...    Element Should Be Disabled    Network & internet

Type, Read Back And Clear Text
    [Teardown]    Terminate Application    ${SEARCH_APP}
    Click Text    Search settings    exact_match=True
    Input Text    ${SEARCH}    wifi
    Element Text Should Be    ${SEARCH}    wifi
    Input Text Into Current Element    \ calling
    Element Text Should Be    ${SEARCH}    wifi calling
    Clear Text    ${SEARCH}
    Page Should Not Contain Text    wifi calling
    Input Password    ${SEARCH}    secret
    Hide Keyboard
    Go Back

Expect Element And Expect Text
    Expect Element    Network & internet    visible
    Expect Element    Network & internet    enabled
    Expect Text    No such thing    not visible    timeout=1s
    Run Keyword And Expect Error    Element 'Nope' was not visible.
    ...    Expect Element    Nope    visible    timeout=1s

Click Element Navigates
    Click Element    Network & internet
    Expect Text    Internet    visible
    Go Back

Scroll Element Into View
    Scroll Element Into View    regex=About (emulated device|phone)
    Element Should Be Visible    regex=About (emulated device|phone)

Hide Keyboard Without A Keyboard Stays In The App
    Hide Keyboard
    Expect Element    Network & internet    visible

Is Keyboard Shown Follows The Keyboard
    Click Text    Search settings    exact_match=True
    ${shown}=    Is Keyboard Shown
    Should Be True    ${shown}
    Hide Keyboard
    ${shown}=    Is Keyboard Shown
    Should Not Be True    ${shown}
    [Teardown]    Terminate Application    ${SEARCH_APP}
