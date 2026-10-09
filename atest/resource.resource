*** Settings ***
Library           OperatingSystem
Library           MaestroLibrary    device=${DEVICE}    speed=${SPEED}


*** Variables ***
${DEVICE}         ${None}
# Pause before each Maestro command; the emulator stopped answering twice in long runs.
${SPEED}          0.3s
${SETTINGS}       com.android.settings
# Settings search runs in its own package and outlives a Settings restart.
${SEARCH_APP}     com.google.android.settings.intelligence
# Settings is a system app whose permissions can't change. Permission tests use Chrome, which ships on
# stock emulator images and has CAMERA not granted by default. Override with
# --variable PERMISSION_APP:<package> for another installed app; the tests skip when it is missing.
${PERMISSION_APP}    com.android.chrome
