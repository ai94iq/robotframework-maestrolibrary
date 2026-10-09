import os

from robotlibcore import keyword

ORIENTATIONS = ("PORTRAIT", "LANDSCAPE_LEFT", "LANDSCAPE_RIGHT", "UPSIDE_DOWN")


def maestro_path(path):
    """`path` as Maestro needs it: absolute, with forward slashes (also on Windows)."""
    return os.path.abspath(path).replace(os.sep, "/")


class DeviceKeywords:
    def __init__(self, lib):
        self.lib = lib

    @keyword
    def set_location(self, latitude: float, longitude: float, altitude: float | None = None):
        """Sets the device's location (a mock location on Android).

        `altitude` is accepted for AppiumLibrary compatibility and ignored: Maestro sets only
        latitude and longitude.

        | `Set Location` | 33.3152 | 44.3661 |
        """
        self.lib.run_commands({"setLocation": {"latitude": str(latitude), "longitude": str(longitude)}})

    @keyword
    def travel(self, *points: str, speed: float | None = None):
        """Moves the device's location through `points` (``latitude,longitude``) at `speed` metres per
        second, or Maestro's default speed.

        | `Travel` | 33.3152,44.3661 | 33.3200,44.3700 | speed=20 |
        """
        if len(points) < 2:
            raise ValueError("Travel needs at least two points.")
        command = {"points": list(points)}
        if speed is not None:
            command["speed"] = speed
        self.lib.run_commands({"travel": command})

    @keyword
    def landscape(self):
        """Rotates the device to landscape (``LANDSCAPE_LEFT``)."""
        self.set_orientation("LANDSCAPE_LEFT")

    @keyword
    def portrait(self):
        """Rotates the device to portrait."""
        self.set_orientation("PORTRAIT")

    @keyword
    def set_orientation(self, orientation: str):
        """Rotates the device: ``PORTRAIT``, ``LANDSCAPE_LEFT``, ``LANDSCAPE_RIGHT`` or ``UPSIDE_DOWN``
        (case and spaces don't matter).

        | `Set Orientation` | landscape right |
        """
        value = orientation.strip().upper().replace(" ", "_")
        if value not in ORIENTATIONS:
            raise ValueError(f"Unknown orientation '{orientation}'. Use one of: {', '.join(ORIENTATIONS)}.")
        self.lib.run_commands({"setOrientation": value})

    @keyword
    def set_airplane_mode(self, enabled: bool):
        """Turns airplane mode on or off. With it on, the device has no network.

        Android only: iOS simulators have no airplane mode, and Maestro would pass without effect.

        | `Set Airplane Mode` | True |
        """
        self.lib.require_android("Set Airplane Mode (iOS simulators have none)")
        self.lib.run_commands({"setAirplaneMode": "enabled" if enabled else "disabled"})

    @keyword
    def set_dark_mode(self, enabled: bool):
        """Turns the system dark theme on or off.

        | `Set Dark Mode` | True |
        """
        self.lib.run_commands({"setDarkMode": "enabled" if enabled else "disabled"})

    @keyword
    def add_media(self, *paths: str):
        """Adds image or video files to the device's gallery, for tests that pick or upload media.
        On Android they land in ``Pictures/`` under their own file names.

        | `Add Media` | ${CURDIR}/data/receipt.png |
        """
        if not paths:
            raise ValueError("Add Media needs at least one file.")
        missing = [path for path in paths if not os.path.isfile(path)]
        if missing:
            raise ValueError(f"Media file does not exist: {', '.join(missing)}")
        self.lib.run_commands({"addMedia": [maestro_path(path) for path in paths]})
