*** Settings ***
Documentation     Waiting keywords, against Android Settings.
Resource          resource.resource
Test Setup        Open Application    ${SETTINGS}
Suite Teardown    Close All Applications


*** Test Cases ***
Waits Pass When The Condition Holds
    Wait Until Element Is Visible    Network & internet
    Wait Until Page Contains    Network
    Wait Until Page Contains Element    regex=Network.*
    Wait Until Page Does Not Contain    No such thing    timeout=1s
    Wait Until Page Does Not Contain Element    id=no.such:id/thing    timeout=1s
    Wait For Animation To End

Wait Until Page Contains Waits For The Next Screen
    Click Text    Network & internet    exact_match=True
    Wait Until Page Contains    Internet    timeout=10s
    Go Back
    Wait Until Page Does Not Contain Element    text=Internet    timeout=10s

Waits Fail After The Timeout With The Default Or Custom Error
    Run Keyword And Expect Error    Element 'Nope' was not visible in 1 seconds.
    ...    Wait Until Element Is Visible    Nope    timeout=1s
    Run Keyword And Expect Error    Text 'Nope' did not appear in 2 seconds.
    ...    Wait Until Page Contains    Nope    timeout=2s
    Run Keyword And Expect Error    Custom message
    ...    Wait Until Page Does Not Contain    Network    timeout=1s    error=Custom message
