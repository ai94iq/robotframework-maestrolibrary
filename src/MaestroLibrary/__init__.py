import atexit
import json
import re
import subprocess
import time
from datetime import timedelta

from robot.api import logger
from robotlibcore import DynamicCore

from .keywords import ApplicationManagementKeywords, DeviceKeywords, ElementKeywords, KeyeventKeywords, RunOnFailureKeywords, ScreenshotKeywords, TouchKeywords, WaitingKeywords
from .locators import matches, walk
from .android import Logcat, Mirror
from .mcp import MaestroError, MaestroMCP, verified_exe
from .recorder import FlowRecorder

__version__ = "0.4.2"
NO_APP = "maestro.no.app"
SETTLE_TIMEOUT_MS = 3000
APP_LAUNCH_TIMEOUT_S = 20  # Appium's default appWaitDuration
ADB_TIMEOUT_S = 10
ADB_MISSING = "adb did not run: install Android platform-tools and put adb on PATH."
XCRUN_ANSWER = r"xcrun version \d"  # WIP: from memory, not measured (no Mac)
IOS_WIP = ("iOS support in MaestroLibrary is WIP and untested: Android-only keywords fail, and the iOS "
           "log stream, recording, Clear Keychain, Click Alert Button and Hide Keyboard key_name need "
           "testing on an iOS simulator.")
ADB_ANSWER = r"Android Debug Bridge version \d"  # `adb version`, measured with platform-tools 37.0.1
MCP_TIMEOUT_S = 300  # how long to wait for one Maestro command flow beyond its own timeouts
FLOW_TIMEOUT_S = 3600  # a Run Flow file or directory can hold any number of commands


class MaestroLibrary(DynamicCore):
    """MaestroLibrary drives Android and iOS apps through [https://maestro.dev|Maestro].

    It mirrors [https://github.com/serhatbolsu/robotframework-appiumlibrary|AppiumLibrary]:
    the keyword names, the argument order and the `strategy=value` locators are the same,
    so most AppiumLibrary suites read the same with this library. There's no Appium server
    and no capabilities, and Maestro waits for the UI to settle after every action.

    = Locating elements =

    | *Strategy*         | *Example*                  | *Matches*                                              |
    | text               | ``text=Log in``            | whole text, content-desc or hint, literally            |
    | accessibility_id   | ``accessibility_id=Back``  | same as text (Maestro matches content-desc as text)    |
    | id                 | ``id=login_button``        | whole resource-id or Flutter ``Semantics.identifier``  |
    | regex              | ``regex=Log.*``            | text, as a Maestro (Java) regular expression           |
    | id_regex           | ``id_regex=.*login``       | id, as a regular expression                            |
    | point              | ``point=50%,90%``          | a screen position, in percent or pixels                |

    A locator without a strategy is treated as text, because Flutter widgets expose
    text far more often than ids. xpath, class, android, ios, predicate, chain, css, name and identifier
    have no Maestro equivalent and fail immediately.

    Actions match on the device with Java regular expressions. The `Should` and `Get`
    keywords match the inspected screen with Python's ``re``. The two behave the same for
    literal locators and for common patterns. Keep ``regex=`` and ``id_regex=`` to
    syntax that both engines share (no possessive quantifiers, ``\\p{...}`` classes or inline flags).

    = Timeouts =

    `timeout` (default 5 seconds) is the default for the `Wait Until` keywords and `Expect`
    keywords, the same as AppiumLibrary. The `Should` keywords check the current screen once
    and don't wait. Every action waits for its element on its own.

    = Android logcat =

    On Android, every test's ``adb logcat`` is streamed to ``logcat/<n>-<test>.txt`` in the output
    directory and linked in the log, so a crash's log is kept. Turn it off with ``logcat=False``.

    = Screen mirroring =

    `Start Screen Mirroring` shows the Android screen in a scrcpy window on this computer, view
    only unless ``control=True``. ``mirror=True`` opens it for the whole run.

    = iOS =

    WIP and untested: Maestro drives iOS simulators only (macOS with Xcode). Android-only keywords
    (`Go Back`, `Set Airplane Mode`, `Execute Adb Shell`, ...) fail at once on iOS; the iOS log
    stream, recording, `Clear Keychain`, `Click Alert Button` and `Hide Keyboard` ``key_name``
    need testing on a simulator.

    = Anything else =

    `Run Flow` runs raw Maestro YAML or a flow file, for the Maestro commands that have
    no keyword yet.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"
    ROBOT_LIBRARY_VERSION = __version__

    def __init__(
        self,
        timeout: timedelta = timedelta(seconds=5),
        run_on_failure: str = "Capture Page Screenshot",
        device: str | None = None,
        maestro: str = "maestro",
        speed: timedelta = timedelta(0),
        logcat: bool = True,
        mirror: bool = False,
        record_flows: bool = False,
    ):
        """`device` is a Maestro device id such as ``emulator-5554``. By default the first
        connected device is used. `maestro` is the Maestro CLI executable.

        `speed` pauses before every Maestro command, like SeleniumLibrary's speed. Raise it
        (for example ``speed=0.5s``) when a slow or overloaded emulator stops responding.

        `logcat` streams ``adb logcat`` to ``logcat/<n>-<test>.txt`` in the output directory, one
        file per test, linked in the log; skipped without adb. On an iOS simulator it streams the
        simulator's log instead (WIP, needs testing; needs xcrun).

        `mirror` opens a scrcpy window showing the Android device when the device is first used,
        and closes it when the run ends. A failure to start it is a warning.

        `record_flows` writes the Maestro commands each test sends to ``flows/<n>-<test>.yaml`` in
        the output directory, linked in the log: a flow that ``maestro test`` can replay. Checks
        made on a screen snapshot (`Page Should Contain Element`, `Get Text`, ...), screenshots,
        adb and Python steps are not Maestro commands and are not in it. `Input Password` is
        recorded as ``${PASSWORD}``.
        """
        self.timeout = timeout
        self.speed = speed
        self.run_on_failure_keyword = None if run_on_failure.upper() in ("NOTHING", "NONE", "") else run_on_failure
        self.device = device
        self.platform = None
        self.app_id = None
        self._adb = None
        self._xcrun = None
        self.mcp = MaestroMCP([maestro, "mcp"])
        self._running_on_failure = False
        atexit.register(self.mcp.close)
        self.logcat = Logcat(self) if logcat else None
        if self.logcat:
            self.ROBOT_LIBRARY_LISTENER = self.logcat
            atexit.register(self.logcat.stop)
        self.screen_mirror = Mirror()
        self.mirror_at_start = mirror
        self.recorder = FlowRecorder() if record_flows else None
        atexit.register(self.screen_mirror.stop)
        DynamicCore.__init__(self, [
            ApplicationManagementKeywords(self),
            ElementKeywords(self),
            WaitingKeywords(self),
            TouchKeywords(self),
            DeviceKeywords(self),
            KeyeventKeywords(self),
            ScreenshotKeywords(self),
            RunOnFailureKeywords(self),
        ])

    def run_keyword(self, name, args, kwargs=None):
        try:
            return DynamicCore.run_keyword(self, name, args, kwargs)
        except Exception:
            self.run_on_failure()
            raise

    def run_on_failure(self):
        if not self.run_on_failure_keyword or self._running_on_failure:
            return
        self._running_on_failure = True
        try:
            from robot.libraries.BuiltIn import BuiltIn
            BuiltIn().run_keyword(self.run_on_failure_keyword)
        except Exception as err:
            logger.warn(f"Keyword '{self.run_on_failure_keyword}' could not be run on failure: {err}")
        finally:
            self._running_on_failure = False

    def device_id(self):
        if not self.platform:
            content = self.mcp.call_tool("list_devices", {})
            connected = [d for d in json.loads(content[0]["text"])["devices"] if d.get("connected")]
            if self.device:
                connected = [d for d in connected if d["device_id"] == self.device]
            if not connected:
                raise MaestroError(f"Device '{self.device or 'any'}' is not connected. Start an emulator or "
                                   "simulator, or connect a device.")
            self.device, self.platform = connected[0]["device_id"], connected[0]["platform"]
            logger.info(f"Using {self.platform} device '{self.device}'.")
            if self.platform != "android":
                logger.warn(IOS_WIP)
            if self.mirror_at_start and self.platform == "android":
                try:
                    self.screen_mirror.start(self.device)
                except AssertionError as err:
                    logger.warn(f"Screen mirroring did not start: {err}")
        if self.logcat:
            self.logcat.ensure()
        return self.device

    def require_android(self, what):
        """Fails unless the current device is Android: `what` has no iOS equivalent in Maestro."""
        self.device_id()
        if self.platform != "android":
            raise AssertionError(f"{what} needs an Android device; Maestro has no iOS equivalent.")

    def wait_for_app_focus(self, app_id):
        """Waits until `app_id` has window focus, like Appium waiting for the app's activity.

        Maestro's launchApp returns while the launch transition is still running, so the
        first inspect_screen can show the previous app. Android only: other platforms return at once.
        """
        self.device_id()
        if self.platform != "android":
            return
        deadline = time.monotonic() + APP_LAUNCH_TIMEOUT_S
        while time.monotonic() < deadline:
            focus = self.adb_shell("dumpsys", "window", purpose="waiting for the app's window")
            if focus is None:
                return
            if re.search(rf"mCurrentFocus=.*\s{re.escape(app_id)}/", focus):
                # Focus arrives before the first frames are drawn; a gesture sent then can be lost.
                self.run_commands({"waitForAnimationToEnd": {"timeout": SETTLE_TIMEOUT_MS}}, log=False)
                return
            # dumpsys window is a heavy call; focus arrived within 2 s in measurements, so 1 s is enough.
            time.sleep(1)
        logger.warn(f"App '{app_id}' did not get window focus within {APP_LAUNCH_TIMEOUT_S} s.")

    def adb(self):
        """Returns adb's path once `adb version` answers like adb, else None. Checked once.

        adb is looked up in PATH's directories only, never the working directory, and a program that
        answers differently is refused with a warning (see verified_exe).
        """
        if self._adb is None:
            try:
                self._adb = verified_exe("adb", ["version"], ADB_ANSWER, ADB_TIMEOUT_S)
            except AssertionError as err:
                self._adb = ""
                logger.warn(str(err))
        return self._adb or None

    def xcrun(self):
        """Returns xcrun's path once `xcrun --version` answers like xcrun, else None. Checked once.

        WIP: used for the iOS simulator (simctl); the expected answer is not measured yet.
        """
        if self._xcrun is None:
            try:
                self._xcrun = verified_exe("xcrun", ["--version"], XCRUN_ANSWER, ADB_TIMEOUT_S)
            except AssertionError as err:
                self._xcrun = ""
                logger.warn(str(err))
        return self._xcrun or None

    def adb_shell(self, *args, purpose):
        """Runs `adb shell args` on the current Android device and returns its output.

        Returns None, with a warning naming `purpose`, when adb is missing or doesn't answer:
        Maestro itself needs no adb, so the checks built on it degrade instead of failing.
        """
        adb = self.adb()
        if not adb:
            logger.warn(f"{ADB_MISSING} Skipped {purpose}.")
            return None
        try:
            return subprocess.run([adb, "-s", self.device, "shell", *args], capture_output=True,
                                  text=True, errors="replace", timeout=ADB_TIMEOUT_S).stdout
        except subprocess.TimeoutExpired:
            logger.warn(f"adb did not answer within {ADB_TIMEOUT_S} s while {purpose}; is the device responsive?")
            return None

    def run_commands(self, *commands, app_id=None, log=True):
        """Runs Maestro commands (dicts or strings) as one flow on the current device."""
        header = f"appId: {json.dumps(app_id or self.app_id or NO_APP)}\n---\n"
        body = "\n".join(f"- {json.dumps(command)}" for command in commands)
        if log:
            logger.debug(f"Maestro flow:\n{body}")
        if self.recorder:
            self.recorder.commands(app_id or self.app_id or NO_APP, commands, secret=not log)
        if self.speed:
            time.sleep(self.speed.total_seconds())
        # A wait or scroll may legitimately take longer than the default; allow its own timeout.
        waits = [c[k]["timeout"] for c in commands if isinstance(c, dict) for k in c
                 if isinstance(c[k], dict) and isinstance(c[k].get("timeout"), int)]
        self._run({"yaml": header + body}, None, max([MCP_TIMEOUT_S] + [w / 1000 + 60 for w in waits]))

    def run_yaml(self, yaml, env=None):
        if self.recorder:
            self.recorder.yaml(self.app_id or NO_APP, yaml, env)
        self._run({"yaml": yaml}, env, FLOW_TIMEOUT_S)

    def run_files(self, files, env=None):
        if self.recorder:
            self.recorder.files(self.app_id or NO_APP, files, env)
        self._run({"files": files}, env, FLOW_TIMEOUT_S)

    def run_dir(self, path, env=None, include_tags=None, exclude_tags=None):
        flow = {"dir": path}
        if include_tags is not None:
            flow["include_tags"] = include_tags
        if exclude_tags is not None:
            flow["exclude_tags"] = exclude_tags
        if self.recorder:
            self.recorder.record(self.app_id or NO_APP, [f"# Run Flow {path} (a directory) is not recorded"])
        self._run(flow, env, FLOW_TIMEOUT_S)

    def _run(self, flow, env, timeout):
        arguments = {"device_id": self.device_id(), **flow}
        if env:
            arguments["env"] = {k: str(v) for k, v in env.items()}
        self.mcp.call_tool("run", arguments, timeout=timeout)

    def screen(self):
        """Returns the settled current screen's element tree, from Maestro's inspect_screen.

        Actions return before transitions finish, so inspecting at once can see the
        previous screen. Waiting for animations first makes snapshot checks deterministic.
        """
        self.run_commands({"waitForAnimationToEnd": {"timeout": SETTLE_TIMEOUT_MS}}, log=False)
        content = self.mcp.call_tool("inspect_screen", {"device_id": self.device_id()})
        return json.loads(content[0]["text"])["elements"]

    def elements(self):
        """Returns every element on the current screen, flattened."""
        return list(walk(self.screen()))

    def timeout_ms(self, timeout=None):
        return int((self.timeout if timeout is None else timeout).total_seconds() * 1000)

    def wait_until(self, selector, visible=True, timeout=None, error=None):
        """Waits for a selector to become visible (or not visible) using Maestro's extendedWaitUntil."""
        state = "visible" if visible else "notVisible"
        try:
            self.run_commands({"extendedWaitUntil": {state: selector, "timeout": self.timeout_ms(timeout)}})
        except MaestroError as err:
            raise AssertionError(error or str(err)) from None

    def find(self, selector):
        return [e for e in self.elements() if matches(e, selector)]
