"""Maestro Studio-style recorder: act on the live device screen and get Robot Framework lines.

    python -m MaestroLibrary.studio [--device ID] [--app APP_ID] [--port N]

Do not run it while a Robot run uses the same device: Maestro allows one session per device.
"""
import argparse
import base64
import hmac
import json
import math
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .flow2robot import SEP, escape
from .locators import best_locator, element_at, locator_candidates, parse_bounds
from .recorder import MASKED_INPUT

TREE_MAX_AGE_S = 1.0
GAP = "    # GAP: no unique locator, ask for a test id"
ELEMENT_KINDS = {"click": "click_element", "long_press": "long_press",
                 "wait_visible": "wait_until_page_contains_element",
                 "should_be_visible": "element_should_be_visible", "text_should_be": "element_text_should_be"}
SIMPLE_KINDS = {"back": "go_back", "hide_keyboard": "hide_keyboard", "screenshot": "capture_page_screenshot"}
KINDS = set(ELEMENT_KINDS) | set(SIMPLE_KINDS) | {"type", "swipe", "launch"}
KEYWORD_NAMES = {"click_element": "Click Element", "long_press": "Long Press",
                 "wait_until_page_contains_element": "Wait Until Page Contains Element",
                 "element_should_be_visible": "Element Should Be Visible",
                 "element_text_should_be": "Element Text Should Be", "swipe_by_percent": "Swipe By Percent",
                 "go_back": "Go Back", "hide_keyboard": "Hide Keyboard",
                 "open_application": "Open Application", "capture_page_screenshot": "Capture Page Screenshot"}


def arg(value):
    """A recorded argument: every variable escaped, since device texts must never run as Robot code."""
    return escape(str(value), keep_variables=False)


def no_maestro_js(text):
    if "${" in text:
        raise ValueError("Maestro would evaluate ${...} in this text as JavaScript; leave out the ${.")
    return text


class Session:
    """Runs studio actions on the device through MaestroLibrary and records the matching Robot lines."""

    def __init__(self, lib, app_id=None):
        self.lib, self.app_id, self.lines, self.recording = lib, app_id, [], True
        self.lock = threading.RLock()   # one Maestro session: one action at a time
        self._tree, self._at, self._last_locator = None, 0.0, None

    def tree(self):
        """The current screen's flat element list and size, fetched again when older than a second."""
        with self.lock:
            if self._tree is None or time.monotonic() - self._at > TREE_MAX_AGE_S:
                elements = self.lib.elements()
                root = max((parse_bounds(e.get("b")) or (0, 0, 0, 0) for e in elements),
                           key=lambda b: b[2] * b[3], default=(0, 0, 0, 0))
                self._tree = {"elements": elements, "width": root[2] or 1, "height": root[3] or 1,
                              "platform": getattr(self.lib, "platform", None)}
                self._at = time.monotonic()
            return self._tree

    def _pct(self, x, y):
        t = self.tree()
        return round(100 * x / t["width"]), round(100 * y / t["height"])

    def _locate(self, x, y):
        t = self.tree()
        element = element_at(t["elements"], x, y)
        locator = best_locator(element, t["elements"]) if element else None
        if locator:
            return locator, ""
        px, py = self._pct(x, y)
        return f"point={px}%,{py}%", GAP

    def _run(self, keyword, args, comment=""):
        self.lib.run_keyword(keyword, list(args))          # raises: nothing is recorded
        self._tree = None                                   # the screen changed
        if not self.recording:
            return None
        line = SEP.join([KEYWORD_NAMES[keyword]] + [arg(a) for a in args]) + comment
        self.lines.append(line)
        return line

    def act(self, kind, x=None, y=None, x2=None, y2=None, text=None, secret=False):
        """Runs one action; returns its recorded line (None while recording is off)."""
        if kind not in KINDS:
            raise ValueError(f"Unknown action {kind!r}.")
        with self.lock:
            if kind == "type":
                return self._type(no_maestro_js(str(text)), secret)
            if kind in ELEMENT_KINDS:
                expected = [no_maestro_js(str(text))] if kind == "text_should_be" else []
                locator, comment = self._locate(x, y)
                line = self._run(ELEMENT_KINDS[kind], [locator] + expected, comment)
                self._last_locator = locator if kind == "click" else None
                return line
            self._last_locator = None
            if kind == "swipe":
                return self._run("swipe_by_percent", [*self._pct(x, y), *self._pct(x2, y2)])
            if kind == "launch":
                return self._run("open_application", [self.app_id or self.lib.app_id])
            return self._run(SIMPLE_KINDS[kind], [])

    def _type(self, text, secret):
        """Types into the focused field; right after a click, the click line becomes Input Text/Password."""
        if secret:
            try:
                self.lib.run_commands({"inputText": text}, log=False)  # never logged
            except Exception as err:                                   # nor echoed in an error
                raise AssertionError(str(err).replace(text, "***")) from None
        else:
            self.lib.run_keyword("input_text_into_current_element", [text])
        self._tree = None
        locator, self._last_locator = self._last_locator, None
        if not self.recording:
            return None
        shown = MASKED_INPUT if secret else arg(text)
        if locator and self.lines and self.lines[-1].startswith("Click Element"):
            self.lines[-1] = SEP.join(["Input Password" if secret else "Input Text", arg(locator), shown])
        else:
            self.lines.append(SEP.join(["Input Text Into Current Element", shown]))
        return self.lines[-1]

    def undo(self):
        with self.lock:
            if self.lines:
                self.lines.pop()

    def clear(self):
        with self.lock:
            self.lines = []

    def robot(self, name):
        """The recorded lines as a Robot test file."""
        title = arg(name.strip() or "Recorded Test")
        title = "\\" + title if title.startswith("*") else title      # a leading * would start a section
        return "\n".join(["*** Settings ***", "Library    MaestroLibrary", "", "*** Test Cases ***", title]
                         + [SEP + line for line in self.lines]) + "\n"


MAX_BODY = 64 * 1024
COORDS = ("x", "y", "x2", "y2")
ACT_FIELDS = set(COORDS) | {"kind", "text", "secret"}
PAGE = os.path.join(os.path.dirname(__file__), "studio.html")
HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
           "X-Frame-Options": "DENY"}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) \
        and 0 <= value <= 100000


def act_kwargs(body):
    """Validated keyword arguments for Session.act from a request body; ValueError when anything is off."""
    if not isinstance(body, dict) or set(body) - ACT_FIELDS or body.get("kind") not in KINDS:
        raise ValueError("unknown action or field")
    kind = body["kind"]
    needed = COORDS if kind == "swipe" else ("x", "y") if kind in ELEMENT_KINDS else ()
    if any(not _number(body.get(c)) for c in needed) or any(c in body and c not in needed for c in COORDS):
        raise ValueError("coordinates")
    text = body.get("text")
    if (kind in ("type", "text_should_be")) != isinstance(text, str) or len(text or "") > 10000:
        raise ValueError("text")
    if not isinstance(body.get("secret", False), bool) or (body.get("secret") and kind != "type"):
        raise ValueError("secret")
    return {k: (round(v) if k in COORDS else v) for k, v in body.items()}


def make_server(session, stream_factory, screenshot, port=8787):
    """A studio server on 127.0.0.1 and its per-run token. Nothing is served without the token."""
    token, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
    streams = {"current": None, "lock": threading.Lock()}

    class Handler(BaseHTTPRequestHandler):
        timeout = 30                      # slow clients are dropped

        def log_message(self, *args):     # quiet: request lines would print the token
            pass

        def _send(self, status, body=b"", kind="application/json", extra=None):
            if not isinstance(body, (bytes, str)):
                body = json.dumps(body)
            body = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            headers = {**HEADERS, "Content-Type": kind, "Content-Length": str(len(body)), **(extra or {})}
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self, path, query):
            port = self.server.server_port
            if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return False                  # DNS rebinding
            given = query.get("t", [""])[0] if path == "/" else self.headers.get("X-Token", "")
            return hmac.compare_digest(given.encode(), token.encode())

        def do_GET(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if not self._allowed(url.path, query):
                return self._send(403, {"error": "forbidden"})
            try:
                if url.path == "/":
                    return self._page()
                if url.path == "/tree":
                    return self._send(200, session.tree())
                if url.path == "/inspect":
                    return self._inspect(int(query["x"][0]), int(query["y"][0]))
                if url.path == "/robot":
                    return self._send(200, session.robot(query.get("name", [""])[0]), "text/plain; charset=utf-8")
                if url.path == "/screenshot":
                    with session.lock:
                        return self._send(200, screenshot(), "image/jpeg")
                if url.path == "/stream":
                    return self._stream()
            except (KeyError, ValueError):
                return self._send(400, {"error": "bad request"})
            except Exception as err:          # a device or Maestro failure: report it, keep serving
                return self._send(409, {"error": str(err)})
            return self._send(404, {"error": "not found"})

        def _page(self):
            with open(PAGE, encoding="utf-8") as f:
                page = f.read().replace("__NONCE__", nonce)
            csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
                   "img-src 'self' blob: data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            return self._send(200, page, "text/html; charset=utf-8", {"Content-Security-Policy": csp})

        def _inspect(self, x, y):
            elements = session.tree()["elements"]
            element = element_at(elements, x, y)
            if not element:
                return self._send(200, {"element": None, "locators": []})
            return self._send(200, {"element": {k: v for k, v in element.items() if k != "c"},
                                    "locators": locator_candidates(element, elements)})

        def _stream(self):
            if stream_factory is None:
                return self._send(503, "live view is off", "text/plain")
            with streams["lock"]:
                if streams["current"]:
                    streams["current"].stop()     # one viewer at a time
                try:
                    stream = streams["current"] = stream_factory()
                except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as err:
                    return self._send(503, str(err), "text/plain")
            self.send_response(200)
            for name, value in {**HEADERS, "Content-Type": "application/octet-stream"}.items():
                self.send_header(name, value)
            self.end_headers()
            self.connection.settimeout(None)      # a still screen sends nothing for a while
            try:
                for chunk in iter(stream.read, b""):
                    self.wfile.write(chunk)
            except OSError:
                pass                              # the page went away
            finally:
                stream.stop()

        def do_POST(self):
            url = urlsplit(self.path)
            if not self._allowed(url.path, parse_qs(url.query)):
                return self._send(403, {"error": "forbidden"})
            if int(self.headers.get("Content-Length") or 0) > MAX_BODY:
                self.close_connection = True
                return self._send(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
                if url.path == "/act":
                    return self._send(200, {"line": session.act(**act_kwargs(body))})
                if url.path in ("/undo", "/clear"):
                    session.undo() if url.path == "/undo" else session.clear()
                    return self._send(200, {"ok": True})
                if url.path == "/record":
                    if not isinstance(body, dict) or not isinstance(body.get("on"), bool):
                        raise ValueError("on")
                    session.recording = body["on"]
                    return self._send(200, {"ok": True})
                if url.path == "/save":
                    return self._save(body)
            except (ValueError, TypeError):
                return self._send(400, {"error": "bad request"})
            except Exception as err:              # a device or Maestro failure: nothing was recorded
                return self._send(409, {"error": str(err)})
            return self._send(404, {"error": "not found"})

        def _save(self, body):
            path, name = body.get("path"), body.get("name")
            if not isinstance(path, str) or not isinstance(name, str) or "\0" in path or not path.endswith(".robot"):
                raise ValueError("path")
            root = os.path.realpath(os.getcwd())
            target = os.path.realpath(os.path.join(root, path))
            if os.path.isabs(path) or not target.startswith(root + os.sep):
                raise ValueError("path")
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(session.robot(name))
            return self._send(200, {"saved": os.path.relpath(target, root)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server, token


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m MaestroLibrary.studio", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", help="Maestro device id; default: the first connected device")
    parser.add_argument("--app", help="app id to launch first (recorded as Open Application)")
    parser.add_argument("--port", type=int, default=8787, help="local port (default 8787)")
    parser.add_argument("--no-browser", action="store_true", help="print the URL without opening it")
    args = parser.parse_args(argv)

    from . import MaestroLibrary
    from .stream import ScrcpyStream

    lib = MaestroLibrary(device=args.device, run_on_failure="Nothing", logcat=False)
    try:
        device = lib.device_id()
        session = Session(lib, args.app)

        def stream_factory():
            if lib.platform != "android":
                raise RuntimeError("The live view is Android only; the page shows screenshots instead.")
            if not lib.adb():
                raise RuntimeError("adb was not found on PATH.")
            stream = ScrcpyStream(lib.adb(), device)
            stream.start()
            return stream

        def screenshot():
            content = lib.mcp.call_tool("take_screenshot", {"device_id": device})
            return base64.b64decode(next(c["data"] for c in content if c.get("type") == "image"))

        if args.app:
            session.act("launch")
        server, token = make_server(session, stream_factory, screenshot, args.port)
        url = f"http://127.0.0.1:{server.server_port}/?t={token}"
        print(f"MaestroLibrary Studio for {device}: {url}\n"
              "Keep Robot runs off this device while Studio is open (one Maestro session per device). "
              "Ctrl+C stops it.", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        lib.mcp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
