from typing import Literal

from robotlibcore import keyword

# Maestro's pressKey sends these only on Android (docs.maestro.dev, pressKey).
ANDROID_ONLY_KEYS = ("Back", "Power", "Tab")
# Android keycodes that Maestro's pressKey can send.
KEYCODES = {3: "Home", 4: "Back", 24: "Volume Up", 25: "Volume Down", 26: "Power", 61: "Tab",
            66: "Enter", 67: "Backspace", 82: "Lock"}
Key = Literal["Enter", "Backspace", "Home", "Back", "Lock", "Power", "Tab", "Volume Up", "Volume Down",
              "Escape", "Remote Dpad Up", "Remote Dpad Down", "Remote Dpad Left", "Remote Dpad Right",
              "Remote Dpad Center", "Remote Media Play Pause", "Remote Media Stop", "Remote Media Next",
              "Remote Media Previous", "Remote Media Rewind", "Remote Media Fast Forward"]


class KeyeventKeywords:
    def __init__(self, lib):
        self.lib = lib

    @keyword
    def press_key(self, key: Key):
        """Presses a device key by its Maestro name, for example ``Enter`` or ``Volume Up``.

        ``Back``, ``Power`` and ``Tab`` are Android only.
        """
        if key in ANDROID_ONLY_KEYS:
            self.lib.require_android(f"Press Key {key}")
        self.lib.run_commands({"pressKey": key})

    @keyword
    def press_keycode(self, keycode: int, metastate: int | None = None):
        """Presses an Android keycode, as in AppiumLibrary.

        Maestro sends only the keys in this table. Use `Press Key` for its own key names.
        | 3 Home | 4 Back | 24 Volume Up | 25 Volume Down | 26 Power | 61 Tab | 66 Enter | 67 Backspace | 82 Lock |
        `metastate` is not supported and must be left empty.
        """
        if metastate or keycode not in KEYCODES:
            raise ValueError(f"Maestro cannot send keycode {keycode}"
                             f"{' with metastate' if metastate else ''}. Supported: {KEYCODES}.")
        self.press_key(KEYCODES[keycode])
