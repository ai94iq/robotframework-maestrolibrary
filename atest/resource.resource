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
# Settings' search field and the label that opens it. Stock emulator images use Google's search
# package; other builds (a Lineage or Samsung phone) use android:id/search_src_text and
# "Search Settings". Override both for such a device.
${SEARCH}         id=com.google.android.settings.intelligence:id/open_search_view_edit_text
${SEARCH_ENTRY}    Search settings
