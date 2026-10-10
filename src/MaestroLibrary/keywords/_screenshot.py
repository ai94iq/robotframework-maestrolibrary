import base64
import itertools
import os
import pathlib
import signal
import subprocess
import threading
from datetime import timedelta

from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn, RobotNotRunningError
from robotlibcore import keyword

from ..locators import to_selector
from ..mcp import MaestroError
from ._device import maestro_path

EMBED = "EMBED"
ADB_TIMEOUT_S = 60


def output_dir():
    """Robot's output directory; the working directory outside a Robot run (Studio, plain Python)."""
    try:
        return BuiltIn().get_variable_value("${OUTPUT DIR}", os.getcwd())
    except RobotNotRunningError:
        return os.getcwd()


def output_path(filename):
    path = os.path.join(output_dir(), filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def log_link(path, label):
    """Logs a link to `path`; `label` is HTML in which ``{src}`` is replaced by the link target."""
    outdir = output_dir()
    try:
        src = os.path.relpath(path, outdir).replace(os.sep, "/")
    except ValueError:  # Windows: path and output dir are on different drives
        src = pathlib.Path(path).resolve().as_uri()
    logger.info(f'<a href="{src}">{label.format(src=src)}</a>', html=True)


class ScreenshotKeywords:
    def __init__(self, lib):
        self.lib = lib
        self._index = itertools.count(1)
        self._recording = None
        self._remote = None
        self._ios_video = self._timer = None

    @keyword
    def capture_page_screenshot(self, filename: str | None = None) -> str | None:
        """Takes a screenshot of the device screen and shows it in the log.

        Maestro returns JPEG data, whatever the `filename` extension. Without a `filename`, the file is saved as
        ``maestro-screenshot-<n>.jpg`` in the output directory. With ``filename=EMBED``,
        the image goes into log.html and nothing is written to disk.
        Returns the file path, or None when embedded.
        """
        content = self.lib.mcp.call_tool("take_screenshot", {"device_id": self.lib.device_id()})
        data = next((c["data"] for c in content if c.get("type") == "image"), None)
        if data is None:
            raise MaestroError("Maestro's take_screenshot returned no image.")
        if filename and filename.upper() == EMBED:
            logger.info(f'<img src="data:image/jpeg;base64,{data}" width="400">', html=True)
            return None
        path = output_path(filename or f"maestro-screenshot-{next(self._index)}.jpg")
        with open(path, "wb") as file:
            file.write(base64.b64decode(data))
        log_link(path, '<img src="{src}" width="400">')
        return path

    @keyword
    def capture_element_screenshot(self, locator: str, filename: str | None = None) -> str:
        """Takes a PNG screenshot of the element matching `locator` and shows it in the log.

        Without a `filename`, the file is saved as ``maestro-element-<n>.png`` in the output
        directory. Returns the file path. Use it to make references for `Screenshot Should Match`.

        | ${path}= | `Capture Element Screenshot` | id=logo | logo.png |
        """
        path = output_path(filename or f"maestro-element-{next(self._index)}.png")
        base = path[:-4] if path.lower().endswith(".png") else path
        # Maestro appends ".png" to the path it is given.
        self.lib.run_commands({"takeScreenshot": {"path": maestro_path(base), "cropOn": to_selector(locator)}})
        path = base + ".png"
        log_link(path, '<img src="{src}" width="400">')
        return path

    @keyword
    def screenshot_should_match(self, reference: str, threshold: float = 95, locator: str | None = None):
        """Fails unless the screen, or the element matching `locator`, matches the PNG `reference` by at
        least `threshold` percent. The images must have the same size, so make an element reference with
        `Capture Element Screenshot` on the same device.

        | `Screenshot Should Match` | ${CURDIR}/refs/logo.png | locator=id=logo |
        """
        if not os.path.isfile(reference):
            raise AssertionError(f"Reference screenshot '{reference}' does not exist.")
        command = {"path": maestro_path(reference), "thresholdPercentage": f"{threshold:g}"}
        if locator:
            command["cropOn"] = to_selector(locator)
        try:
            self.lib.run_commands({"assertScreenshot": command})
        except MaestroError as err:
            raise AssertionError(str(err)) from None

    @keyword
    def start_screen_recording(self, time_limit: timedelta = timedelta(minutes=3)):
        """Starts recording the screen. Android: adb ``screenrecord``. iOS simulator: ``xcrun simctl
        io recordVideo`` (WIP, needs testing on an iOS simulator).

        ``time_limit`` is how long the recording may run (AppiumLibrary: ``timeLimit``). It
        defaults to 3 minutes, Android's maximum. Stop it and get the video with
        `Stop Screen Recording`. Put `Stop Screen Recording` in a Test Teardown so a failing
        test still stops it.

        | `Start Screen Recording` | time_limit=60s |

        (Maestro's own recording ends with each flow, and every keyword is its own flow.)
        """
        self.lib.device_id()
        if self.lib.platform != "android":
            return self._start_ios_recording(time_limit)
        adb = self._require_adb()
        if self._recording:
            if self._recording.poll() is None:
                raise AssertionError("A screen recording is already running. Stop it with Stop Screen Recording.")
            logger.warn(f"A previous screen recording had already ended, and its file {self._remote} "
                        "was left on the device.")
            self._recording = None
        self._remote = f"/sdcard/maestro-recording-{os.getpid()}-{next(self._index)}.mp4"
        self._recording = subprocess.Popen(
            [adb, "-s", self.lib.device, "shell", "screenrecord", "--time-limit",
             str(int(time_limit.total_seconds())), self._remote],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @keyword
    def stop_screen_recording(self, filename: str | None = None) -> str:
        """Stops the recording started with `Start Screen Recording`, saves it as an mp4 in the output
        directory (``maestro-recording-<n>.mp4`` without a `filename`), links it in the log and returns
        its path. ``filename`` is used as given (AppiumLibrary appends ``.mp4``).

        | ${video}= | `Stop Screen Recording` | login.mp4 |
        """
        if not self._recording:
            raise AssertionError("No screen recording is running. Start one with Start Screen Recording.")
        if self._ios_video:
            return self._stop_ios_recording(filename)
        adb = self._require_adb()
        device, remote, recording = self.lib.device, self._remote, self._recording
        self._recording = self._remote = None
        path = output_path(filename or f"maestro-recording-{next(self._index)}.mp4")
        try:
            # screenrecord writes a playable file only when it is interrupted, not killed. Matching
            # its unique file path leaves other screenrecord processes on the device alone.
            subprocess.run([adb, "-s", device, "shell", "pkill", "-INT", "-f", remote],
                           capture_output=True, timeout=ADB_TIMEOUT_S)
            try:
                recording.wait(timeout=ADB_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                recording.kill()
            pull = subprocess.run([adb, "-s", device, "pull", remote, path],
                                  capture_output=True, text=True, timeout=ADB_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"adb did not answer within {ADB_TIMEOUT_S} s while stopping the recording. "
                                 f"It may still be on the device at {remote}.") from None
        if pull.returncode:
            raise AssertionError(f"Could not copy the recording from the device: {pull.stderr.strip()}. "
                                 f"The recording is kept on the device at {remote}.")
        try:
            subprocess.run([adb, "-s", device, "shell", "rm", "-f", remote], capture_output=True, timeout=ADB_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            logger.warn(f"The recording was saved, but adb did not answer while deleting {remote} on the device.")
        log_link(path, "Screen recording")
        return path

    @keyword
    def start_screen_mirroring(self, *options: str, control: bool = False):
        """Shows the device screen in a scrcpy window on this computer. Android only; needs
        [https://github.com/Genymobile/scrcpy|scrcpy] on PATH and a display.

        The window is view only: set `control` to use the mouse and keyboard on the device
        (a click there can disturb the test). `options` go to scrcpy as given. scrcpy's output is
        saved as ``scrcpy-<device>.log`` in the output directory. The import argument
        ``mirror=True`` opens the window for the whole run instead.

        | `Start Screen Mirroring` |
        | `Start Screen Mirroring` | --max-size=1024 | --always-on-top |
        """
        device = self.lib.device_id()
        if self.lib.platform != "android":
            # WIP, needs testing: the iOS Simulator is already a window on this Mac.
            logger.info("The iOS Simulator window already shows the screen; nothing to mirror.")
            return
        self.lib.screen_mirror.start(device, control, options)

    @keyword
    def stop_screen_mirroring(self):
        """Closes the scrcpy window. Does nothing when no mirroring is running, so it fits a teardown."""
        self.lib.screen_mirror.stop()

    # WIP, needs testing on an iOS simulator (no Mac here): simctl's recordVideo, from Apple's docs.
    def _start_ios_recording(self, time_limit):
        xcrun = self.lib.xcrun()
        if not xcrun:
            raise AssertionError("Screen recording on an iOS simulator needs xcrun (Xcode) on PATH.")
        if self._recording and self._recording.poll() is None:
            raise AssertionError("A screen recording is already running. Stop it with Stop Screen Recording.")
        self._ios_video = output_path(f"maestro-recording-{os.getpid()}-{next(self._index)}.mp4")
        self._recording = subprocess.Popen([xcrun, "simctl", "io", self.lib.device, "recordVideo", "--force",
                                            self._ios_video], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # simctl records until interrupted; the timer stands in for screenrecord's --time-limit.
        self._timer = threading.Timer(time_limit.total_seconds(), self._interrupt, args=(self._recording,))
        self._timer.daemon = True
        self._timer.start()

    def _stop_ios_recording(self, filename):
        recording, video, timer = self._recording, self._ios_video, self._timer
        self._recording = self._ios_video = self._timer = None
        timer.cancel()
        if recording.poll() is None:
            self._interrupt(recording)  # simctl finishes the file on SIGINT
            try:
                recording.wait(timeout=ADB_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                recording.kill()
                raise AssertionError(f"The iOS recorder did not stop within {ADB_TIMEOUT_S} s; it was killed.") from None
        if not os.path.isfile(video) or not os.path.getsize(video):
            raise AssertionError(f"The iOS recorder exited ({recording.returncode}) and left no video at {video}.")
        path = output_path(filename or f"maestro-recording-{next(self._index)}.mp4")
        os.replace(video, path)
        log_link(path, "Screen recording")
        return path

    @staticmethod
    def _interrupt(recording):
        if recording.poll() is None:
            recording.send_signal(signal.SIGINT)

    def _require_adb(self):
        from .. import ADB_MISSING  # here: the package imports this module
        self.lib.device_id()
        if self.lib.platform != "android":
            raise AssertionError("Screen recording needs an Android device: it uses adb screenrecord.")
        adb = self.lib.adb()
        if not adb:
            raise AssertionError(ADB_MISSING)
        return adb
