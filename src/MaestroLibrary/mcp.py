"""Minimal client for the Maestro MCP server (`maestro mcp`, JSON-RPC over stdio)."""

import collections
import json
import os
import queue
import re
import subprocess
import threading

VIEWER_NOTICE = "Maestro Viewer is available"
PROBE_TIMEOUT_S = 10


def find_exe(name):
    """Returns the absolute path of the executable `name` from PATH's absolute directories, or None.

    Never the working directory: Windows (and shutil.which there) checks it before PATH, so an
    adb.exe in a checked-out test repository would run instead of the real one. A `name` that
    already holds a directory is used as given.
    """
    if os.path.dirname(name):
        return name if os.path.isfile(name) else None
    exts = os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(os.pathsep) if os.name == "nt" else [""]
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isabs(folder):
            continue
        for ext in exts:
            path = os.path.join(folder, name + ext)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


def verified_exe(name, args, pattern, timeout=PROBE_TIMEOUT_S):
    """Returns find_exe(name) once running it with `args` prints output matching `pattern`.

    Raises AssertionError when the tool is missing, answers differently (something else took its
    name), or doesn't answer within `timeout` (subprocess.run then kills it).
    """
    exe = find_exe(name)
    if not exe:
        raise AssertionError(f"{name} not found on PATH.")
    try:
        out = subprocess.run([exe, *args], capture_output=True, text=True, errors="replace", timeout=timeout).stdout
    except subprocess.TimeoutExpired:
        raise AssertionError(f"{exe} did not answer within {timeout:g} s, so it was stopped and is not used.") from None
    except OSError as err:
        raise AssertionError(f"{exe} did not run: {err}") from None
    if not re.match(pattern, out):
        first = out.strip().splitlines()[0][:200] if out.strip() else ""
        raise AssertionError(f"{exe} does not answer like {os.path.basename(name)} ({first!r}), "
                             "so it is not used.")
    return exe


class MaestroError(AssertionError):
    """A Maestro tool call failed. Subclasses AssertionError so Robot reports it as a test failure."""

    ROBOT_SUPPRESS_NAME = True


class MaestroMCP:
    def __init__(self, command=("maestro", "mcp")):
        self.command = list(command)
        self._proc = None
        self._lines = None
        self._stderr = collections.deque(maxlen=50)
        self._id = 0
        self._lock = threading.RLock()     # one request in flight: answers are matched by the last id sent

    @property
    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self, timeout=60):
        if self.running:
            return
        from . import __version__  # here, not at the top: the package imports this module
        exe = find_exe(self.command[0])
        if not exe:
            raise MaestroError(f"'{self.command[0]}' not found on PATH. Install the Maestro CLI.")
        env = dict(os.environ, MAESTRO_CLI_NO_ANALYTICS="1", MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED="true")
        self._proc = subprocess.Popen(
            [exe, *self.command[1:]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=env,
        )
        self._lines = queue.Queue()
        threading.Thread(target=self._pump, args=(self._proc.stdout, self._lines.put), daemon=True).start()
        threading.Thread(target=self._pump, args=(self._proc.stderr, self._stderr.append), daemon=True).start()
        result = self._request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "robotframework-maestrolibrary", "version": __version__},
        }, timeout)
        # Maestro 2.11.0 answers serverInfo.name "maestro" (measured); anything else took its name.
        server = result.get("serverInfo", {}).get("name")
        if server != "maestro":
            self.close(grace=0)
            raise MaestroError(f"{exe} is not Maestro: its MCP server calls itself {server!r}. It was stopped.")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name, arguments, timeout=300):
        """Calls an MCP tool and returns its content items, minus the Maestro Viewer notice.

        Raises MaestroError if the tool reports an error.
        """
        with self._lock:                   # callers on several threads (Studio's workers) take turns
            self.start()
            result = self._request("tools/call", {"name": name, "arguments": arguments}, timeout)
        content = [c for c in result.get("content", []) if VIEWER_NOTICE not in c.get("text", "")]
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in content).strip()
            raise MaestroError(text.removeprefix("Failed to run flow: ") or f"Maestro tool '{name}' failed")
        return content

    def close(self, grace=10):
        """Stops the server: `grace` seconds to exit on its own, then its whole process tree is killed."""
        if not self._proc:
            return
        proc, self._proc = self._proc, None
        # Closing stdin lets the server exit on its own; killing only the .bat
        # wrapper on Windows would leave its JVM running.
        try:
            proc.stdin.close()
            proc.wait(grace)
        except (OSError, subprocess.TimeoutExpired):
            taskkill = find_exe("taskkill") if os.name == "nt" else None
            if taskkill:
                # proc is maestro.bat; /T also ends the JVM it started.
                subprocess.run([taskkill, "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()
            proc.wait()

    @staticmethod
    def _pump(stream, sink):
        with stream:
            for line in stream:
                sink(line)
        sink(None)

    def _send(self, message):
        try:
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()
        except OSError as err:
            raise MaestroError(f"Maestro MCP server is not running: {err}{self._stderr_tail()}") from None

    def _request(self, method, params, timeout):
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty:
                # The server would still be busy with this call; restart it for the next one.
                self.close()
                raise MaestroError(f"Maestro did not answer '{method}' within {timeout:g} s; "
                                   "its server was restarted.") from None
            if line is None:
                self.close()
                raise MaestroError(f"Maestro MCP server exited{self._stderr_tail()}")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") != self._id or "method" in message:
                continue
            if "error" in message:
                raise MaestroError(f"Maestro '{method}' error: {message['error'].get('message')}")
            return message["result"]

    def _stderr_tail(self):
        tail = "".join(line for line in self._stderr if line).strip()
        return f"\n{tail[-2000:]}" if tail else ""
