"""Raw H.264 screen stream from scrcpy-server (shipped with scrcpy), for the studio's live view."""
import os
import re
import secrets
import socket
import subprocess
import time

from .mcp import find_exe

REMOTE = "/data/local/tmp/scrcpy-server.jar"
SAFE_SERIAL = re.compile(r"[\w.:-]+")
SAFE_VERSION = re.compile(r"\d+(\.\d+)*")


def server_file():
    """(scrcpy-server path, scrcpy version) on Windows, Linux and macOS; SCRCPY_SERVER_PATH wins."""
    scrcpy = find_exe("scrcpy")        # PATH only, never the working directory
    if not scrcpy:
        raise RuntimeError("scrcpy is not on PATH; the live view needs it (recording still works).")
    answer = subprocess.run([scrcpy, "--version"], capture_output=True, text=True, errors="replace", timeout=10).stdout
    version = re.match(r"scrcpy (\d+(?:\.\d+)*)\b", answer)
    if not version:
        raise RuntimeError(f"{scrcpy} does not answer like scrcpy, so it is not used.")
    here = os.path.dirname(os.path.realpath(scrcpy))
    candidates = [os.environ.get("SCRCPY_SERVER_PATH"), os.path.join(here, "scrcpy-server"),
                  os.path.join(here, "..", "share", "scrcpy", "scrcpy-server"),
                  "/usr/share/scrcpy/scrcpy-server", "/usr/local/share/scrcpy/scrcpy-server",
                  "/opt/homebrew/share/scrcpy/scrcpy-server"]
    path = next((c for c in candidates if c and os.path.isfile(c)), None)
    if not path:
        raise RuntimeError("scrcpy-server was not found; set SCRCPY_SERVER_PATH to the file.")
    return path, version.group(1)


class ScrcpyStream:
    """Starts scrcpy-server on an Android device and reads its raw Annex-B H.264 video."""

    def __init__(self, adb, device, max_size=1080, video_encoder=None):
        # Everything after `adb shell` is joined into one device shell command line: allow no metacharacters.
        if not SAFE_SERIAL.fullmatch(str(device)):
            raise ValueError(f"Unexpected device serial {device!r}.")
        if not isinstance(max_size, int):
            raise ValueError(f"max_size must be an int, not {max_size!r}.")
        if video_encoder is not None and not SAFE_SERIAL.fullmatch(video_encoder):
            raise ValueError(f"Unexpected video encoder name {video_encoder!r}.")
        self.adb, self.device, self.port, self.max_size = adb, device, None, max_size
        # A socket name of its own per run (scrcpy's scid), so a crashed run's server or forward never collides.
        self.scid = f"{secrets.randbits(31):08x}"
        self.video_encoder = video_encoder     # None: the device's default (a hardware encoder on phones)
        self._proc = self._sock = None
        self._pending = b""

    def _adb(self, *args):
        return subprocess.run([self.adb, "-s", self.device, *args], capture_output=True, timeout=30, check=True)

    def start(self):
        path, version = server_file()
        if not SAFE_VERSION.fullmatch(version):
            raise ValueError(f"Unexpected scrcpy version {version!r}.")
        self._adb("push", path, REMOTE)
        answer = self._adb("forward", "tcp:0", f"localabstract:scrcpy_{self.scid}").stdout
        self.port = int(answer.strip())          # adb picks a free local port and prints it
        self._proc = subprocess.Popen(
            [self.adb, "-s", self.device, "shell", f"CLASSPATH={REMOTE}", "app_process", "/",
             "com.genymobile.scrcpy.Server", version, f"scid={self.scid}", "tunnel_forward=true", "audio=false", "control=false",
             "raw_stream=true", "video_codec=h264", f"max_size={self.max_size}"]
            + ([f"video_encoder={self.video_encoder}"] if self.video_encoder else []),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # adb accepts the forwarded connection before the server listens, then closes it: the server is up
        # only once video bytes arrive (measured: about 1.5 s on an Android 15 phone).
        for _ in range(60):
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            try:
                first = sock.recv(65536)
            except OSError:
                first = b""
            if first:
                self._sock, self._pending = sock, first
                sock.settimeout(None)
                return
            sock.close()
            time.sleep(0.25)
        self.stop()
        raise RuntimeError("scrcpy-server did not start streaming on the device.")

    def read(self, n=65536):
        """The next chunk of H.264 bytes; b"" when the stream ended."""
        if self._pending:
            chunk, self._pending = self._pending, b""
            return chunk
        try:
            return self._sock.recv(n) if self._sock else b""
        except OSError:
            return b""

    def stop(self):
        if self._sock:
            self._sock.close()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()       # ending the adb shell ends the server (checked: no app_process left)
        if self.port:
            try:
                self._adb("forward", "--remove", f"tcp:{self.port}")
            except (subprocess.SubprocessError, OSError):
                pass
        self._proc = self._sock = None
