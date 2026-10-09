*** Settings ***
Documentation     Touch keywords, against Android Settings.
Resource          resource.resource
Test Setup        Open Application    ${SETTINGS}
Suite Teardown    Close All Applications


*** Variables ***
${BOTTOM}         regex=About (emulated device|phone)


*** Test Cases ***
Scroll Down And Up To Elements
    Scroll Down    ${BOTTOM}
    Element Should Be Visible    ${BOTTOM}
    Scroll Up    Network & internet
    Element Should Be Visible    Network & internet

Scroll Down Fails After Its Timeout
    Run Keyword And Expect Error    Element 'No such thing' was not found after scrolling down for 2 seconds.
    ...    Scroll Down    No such thing    timeout=2s

Swipe By Percent Moves The List
    Swipe By Percent    50    80    50    20
    Wait For Animation To End
    Page Should Not Contain Element    Network & internet

Swipe In Pixels
    Swipe    start_x=600    start_y=2200    end_x=600    end_y=800
    Wait For Animation To End
    Page Should Not Contain Element    Network & internet

Tap And Long Press
    Tap    Network & internet
    Wait Until Page Contains    Internet
    Go Back
    Tap    point=50%,50%    count=2
    Open Application    ${SETTINGS}
    Long Press    Network & internet
