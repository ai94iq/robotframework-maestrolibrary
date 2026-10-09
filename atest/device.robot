*** Settings ***
Documentation     Device state keywords on the emulator. Every test puts back what it changes.
...               Airplane mode is unit-tested only: it cuts the emulator's network.
Resource          resource.resource
Suite Setup       Open Application    ${SETTINGS}
Suite Teardown    Close All Applications


*** Variables ***
${MEDIA}          maestro-atest.png


*** Test Cases ***
Landscape And Portrait Rotate The Screen
    Landscape
    Rotation Should Be    1
    Portrait
    Rotation Should Be    0
    [Teardown]    Portrait

Set Orientation Takes Readable Names
    Set Orientation    landscape right
    Rotation Should Be    3
    [Teardown]    Portrait

Set Dark Mode Switches The Night Theme
    Set Dark Mode    True
    ${night}=    Execute Adb Shell    cmd    uimode    night
    Should Contain    ${night}    yes
    Set Dark Mode    False
    ${night}=    Execute Adb Shell    cmd    uimode    night
    Should Contain    ${night}    no
    [Teardown]    Set Dark Mode    False

Set Location Mocks The Device Location
    Set Location    33.3152    44.3661
    ${dump}=    Execute Adb Shell    dumpsys    location
    Should Contain    ${dump}    33.315200,44.366100

Travel Ends At The Last Point
    Travel    33.3152,44.3661    33.3160,44.3670    speed=100
    ${dump}=    Execute Adb Shell    dumpsys    location
    Should Contain    ${dump}    33.316000,44.367000

Add Media Puts The File In The Gallery
    Add Media    ${CURDIR}/media/${MEDIA}
    ${rows}=    Execute Adb Shell    content query --uri content://media/external/images/media --projection _display_name
    Should Contain    ${rows}    ${MEDIA}
    [Teardown]    Execute Adb Shell    content delete --uri content://media/external/images/media --where "_display_name='${MEDIA}'"


*** Keywords ***
Rotation Should Be
    [Arguments]    ${expected}
    ${rotation}=    Execute Adb Shell    settings    get    system    user_rotation
    Should Be Equal    ${rotation.strip()}    ${expected}
