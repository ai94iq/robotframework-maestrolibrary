*** Settings ***
Documentation     Element screenshots, visual checks and screen recording, against Android Settings.
Resource          resource.resource
Suite Setup       Open Application    ${SETTINGS}
Suite Teardown    Close All Applications


*** Test Cases ***
Capture Element Screenshot Saves A PNG
    ${path}=    Capture Element Screenshot    regex=Network.*    network.png
    File Should Exist    ${path}
    Should End With    ${path}    network.png

Screenshot Should Match Its Own Reference
    ${reference}=    Capture Element Screenshot    regex=Network.*    reference.png
    Screenshot Should Match    ${reference}    locator=regex=Network.*

Screenshot Should Match Fails On A Different Size
    ${reference}=    Capture Element Screenshot    regex=Network.*    small.png
    Run Keyword And Expect Error    *size mismatch*    Screenshot Should Match    ${reference}

Screen Recording Produces A Video
    Start Screen Recording
    Swipe By Percent    50    70    50    30
    Sleep    3s    reason=screenrecord needs a few frames
    ${video}=    Stop Screen Recording    settings.mp4
    ${size}=    Get File Size    ${video}
    Should Be True    ${size} > 0
