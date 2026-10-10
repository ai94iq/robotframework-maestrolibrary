"""Android helpers that run beside Maestro: the adb logcat stream and the scrcpy mirror."""
import itertools
import os
import re
import subprocess

from .keywords._screenshot import log_link, output_path
from .mcp import verified_exe


def end_process(proc):
    """Ends `proc`, which may already have exited (an unplugged device ends adb by itself)."""
    try:
        proc.terminate()
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except OSError:
        pass


class Logcat:
    """Streams the device log to one file per test, or per suite for suite setup and teardown:
    adb logcat on Android, the simulator's `log stream` on iOS (WIP, needs testing).

    The device's ring buffers hold a few hundred KiB, so a crash early in a long test can be gone
    by its end; a stream on disk keeps it. Robot calls the start/end methods (library listener).
    The stream starts when a keyword first uses the device, so a dry run starts nothing.
    """
    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self, lib):
        self.lib = lib
        self._name = self._proc = self._file = None
        self._index = itertools.count(1)

    def start_suite(self, data, result):
        self._switch(data.full_name)

    def end_suite(self, data, result):
        self._switch(data.parent.full_name if data.parent else None)

    def start_test(self, data, result):
        self._switch(data.full_name)

    def end_test(self, data, result):
        self._switch(data.parent.full_name)

    def _switch(self, name):
        self.stop()
        self._name = name

    def ensure(self):
        if self._proc or not self._name or not self.lib.platform:
            return
        command = self._command()
        if not command:
            return
        name = re.sub(r"[^\w.-]+", "_", self._name)[:100]
        path = output_path(os.path.join("logcat", f"{next(self._index)}-{name}.txt"))
        self._file = open(path, "wb")
        self._proc = subprocess.Popen(command, stdout=self._file, stderr=subprocess.STDOUT)
        log_link(path, "logcat")

    def _command(self):
        if self.lib.platform == "android":
            adb = self.lib.adb()
            # -T 1 starts at the newest line and leaves the device's log alone (no -c).
            return [adb, "-s", self.lib.device, "logcat", "-v", "threadtime", "-T", "1"] if adb else None
        # WIP, needs testing on an iOS simulator: the simulator's unified log, from `simctl spawn`.
        xcrun = self.lib.xcrun()
        return [xcrun, "simctl", "spawn", self.lib.device, "log", "stream", "--style", "compact"] if xcrun else None

    def stop(self):
        if self._proc:
            end_process(self._proc)
            self._file.close()
            self._proc = self._file = None


# scrcpy 5.0 exits within 0.1 s on a bad option (measured). A serial that isn't connected makes it
# wait instead, which is why the keyword passes the device Maestro just found connected.
MIRROR_STARTUP_S = 2
SCRCPY_ANSWER = r"scrcpy \d+\.\d+"  # `scrcpy --version`, measured with scrcpy 5.0


class Mirror:
    """A scrcpy window that shows the device screen on this computer while the tests run."""

    def __init__(self):
        self._proc = None

    @property
    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self, device, control=False, options=()):
        if self.running:
            raise AssertionError("Screen mirroring is already running. Stop it with Stop Screen Mirroring.")
        try:
            scrcpy = verified_exe("scrcpy", ["--version"], SCRCPY_ANSWER)
        except AssertionError as err:
            raise AssertionError(f"scrcpy did not run: {err}") from None
        command = [scrcpy, "-s", device, "--no-audio", f"--window-title=Maestro {device}",
                   *([] if control else ["--no-control"]), *options]
        safe = re.sub(r"[^\w.-]+", "_", device)
        log = output_path(f"scrcpy-{safe}.log")
        with open(log, "wb") as out:  # scrcpy logs steadily; a file, unlike a pipe, never fills up
            try:
                proc = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT)
            except OSError:
                raise AssertionError("scrcpy did not run: install scrcpy and put it on PATH.") from None
        try:
            proc.wait(MIRROR_STARTUP_S)
        except subprocess.TimeoutExpired:
            self._proc = proc
            return
        raise AssertionError(f"scrcpy exited ({proc.returncode}); see {log}.")

    def stop(self):
        proc, self._proc = self._proc, None
        if proc:
            end_process(proc)
