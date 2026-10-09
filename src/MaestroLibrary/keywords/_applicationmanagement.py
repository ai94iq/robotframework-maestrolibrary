import json
import os
import subprocess
from datetime import timedelta

from robot.api import logger
from robotlibcore import keyword


PERMISSION_STATES = ("allow", "deny", "unset")


def check_permissions(permissions: dict[str, str]) -> dict[str, str]:
    for name, state in permissions.items():
        if state not in PERMISSION_STATES:
            raise ValueError(f"Permission '{name}' must be allow, deny or unset, not '{state}'.")
    return permissions


class ApplicationManagementKeywords:
    def __init__(self, lib):
        self.lib = lib

    @keyword
    def open_application(self, app_id: str, clear_state: bool = False, stop_app: bool = True,
                         permissions: dict[str, str] | None = None):
        """Launches the app with package name / bundle id `app_id` and makes it the current app.

        `clear_state` wipes the app's data first, which is a fresh install for practical purposes.
        `stop_app` restarts the app if it is already running. Without `permissions` Maestro
        grants every runtime permission on launch. `permissions` sets them instead, with
        values allow, deny or unset, for example ``{'all': 'deny'}``.

        Unlike AppiumLibrary there's no remote URL or capabilities: Maestro talks to the
        device directly.

        | `Open Application` | com.example.app | clear_state=True |
        | `Open Application` | com.example.app | permissions={'all': 'deny'} |
        """
        launch = {"appId": app_id, "clearState": clear_state, "stopApp": stop_app}
        if permissions is not None:
            launch["permissions"] = check_permissions(permissions)
        self.lib.run_commands({"launchApp": launch}, app_id=app_id)
        self.lib.app_id = app_id
        self.lib.wait_for_app_focus(app_id)

    @keyword
    def clear_application_state(self, app_id: str | None = None):
        """Wipes the data of `app_id`, or of the current app, as if it were freshly installed.

        | `Clear Application State` | com.example.app |
        """
        app_id = self._app_id(app_id)
        self.lib.run_commands({"clearState": app_id}, app_id=app_id)

    @keyword
    def clear_keychain(self):
        """Clears the iOS simulator's keychain (stored passwords, tokens), with Maestro's clearKeychain.
        iOS only. WIP, needs testing on an iOS simulator.
        """
        self.lib.device_id()
        if self.lib.platform == "android":
            raise AssertionError("Clear Keychain needs an iOS simulator; on Android use Clear Application State.")
        self.lib.run_commands("clearKeychain")

    @keyword
    def kill_application(self, app_id: str | None = None):
        """Kills `app_id`, or the current app, the way the system does when it reclaims memory.
        It only kills an app in the background: a foreground app keeps running. Unlike
        `Terminate Application`, which stops the app, this tests that the app restores its state.

        | `Kill Application` | com.example.app |
        """
        app_id = self._app_id(app_id)
        self.lib.run_commands({"killApp": app_id}, app_id=app_id)

    @keyword
    def set_application_permissions(self, app_id: str | None = None, **permissions: str):
        """Sets runtime permissions of `app_id`, or of the current app, to allow, deny or unset.

        Each named argument is a permission and its state, for example ``all=deny``, or
        ``camera=allow``. ``unset`` returns the permission to the system default.

        | `Set Application Permissions` | com.example.app | camera=allow | notifications=unset |
        """
        app_id = self._app_id(app_id)
        if not permissions:
            raise ValueError("No permissions given. Name them as arguments, for example camera=allow.")
        self.lib.run_commands({"setPermissions": {"appId": app_id, "permissions": check_permissions(permissions)}},
                              app_id=app_id)

    def _app_id(self, app_id):
        app_id = app_id or self.lib.app_id
        if not app_id:
            raise ValueError("No app_id given and no application is open.")
        return app_id

    @keyword
    def close_application(self):
        """Stops the current app."""
        if self.lib.app_id:
            self.lib.run_commands({"stopApp": self.lib.app_id})
            self.lib.app_id = None

    @keyword
    def close_all_applications(self):
        """Stops the current app and shuts the Maestro session down. Use it in suite teardown."""
        try:
            if self.lib.mcp.running:
                self.close_application()
        finally:
            self.lib.mcp.close()

    @keyword
    def activate_application(self, app_id: str):
        """Brings `app_id` to the foreground without restarting it, and makes it the current app."""
        self.lib.run_commands({"launchApp": {"appId": app_id, "stopApp": False}}, app_id=app_id)
        self.lib.app_id = app_id
        self.lib.wait_for_app_focus(app_id)

    @keyword
    def terminate_application(self, app_id: str):
        """Stops `app_id`."""
        self.lib.run_commands({"stopApp": app_id}, app_id=app_id)

    @keyword
    def go_back(self):
        """Presses the Android back button. Android only: iOS has no back button."""
        self.lib.require_android("Go Back (iOS has no back button; tap the app's own back control)")
        self.lib.run_commands("back")

    @keyword
    def go_to_url(self, url: str):
        """Opens `url`. A deep link opens in its app, a web URL in the default browser."""
        self.lib.run_commands({"openLink": url})

    @keyword
    def get_source(self) -> str:
        """Returns the current screen's view hierarchy as JSON (Maestro ``inspect_screen``)."""
        return json.dumps(self.lib.screen(), indent=1)

    @keyword
    def log_source(self, loglevel: str = "INFO") -> str:
        """Logs and returns the current screen's view hierarchy."""
        source = self.get_source()
        logger.write(source, loglevel)
        return source

    @keyword
    def set_maestro_timeout(self, seconds: timedelta) -> timedelta:
        """Sets the default timeout of the `Wait Until` and `Expect` keywords and returns the old one."""
        old, self.lib.timeout = self.lib.timeout, seconds
        return old

    @keyword
    def get_maestro_timeout(self) -> timedelta:
        """Returns the default timeout of the `Wait Until` and `Expect` keywords."""
        return self.lib.timeout

    @keyword
    def run_flow(self, flow: str, *, include_tags: list[str] | str | None = None,
                 exclude_tags: list[str] | str | None = None, **env: str):
        """Runs a Maestro flow file, a directory of flows, or inline YAML commands, on the current device.

        Use it for the Maestro commands that have no keyword. Inline YAML without a config section
        gets the current app's ``appId``. Named arguments become flow environment
        variables (``${NAME}`` in the flow).

        A directory runs every flow in it. `include_tags` and `exclude_tags` pick flows by
        their ``tags``, and are only valid with a directory. Give several tags as a list
        variable, such as ``@{TAGS}``.

        | `Run Flow` | ${CURDIR}/flows/onboarding.yaml | USER=demo |
        | `Run Flow` | ${CURDIR}/flows/ | include_tags=smoke | exclude_tags=slow |
        | `Run Flow` | - tapOn:\\n    text: Next\\n    index: 1 |
        """
        include_tags = [include_tags] if isinstance(include_tags, str) else include_tags
        exclude_tags = [exclude_tags] if isinstance(exclude_tags, str) else exclude_tags
        if os.path.isdir(flow):
            self.lib.run_dir(os.path.abspath(flow), env, include_tags, exclude_tags)
            return
        if include_tags is not None or exclude_tags is not None:
            raise ValueError("include_tags and exclude_tags only apply to a flow directory.")
        if os.path.isfile(flow):
            # Passed by path so the flow's relative runFlow/runScript paths resolve next to it.
            self.lib.run_files([os.path.abspath(flow)], env)
            return
        if "\n" not in flow and not flow.lstrip().startswith("-") and flow.rstrip().endswith((".yaml", ".yml", "/", "\\")):
            raise ValueError(f"Flow file or directory not found: {flow}")
        if not any(line.strip() == "---" for line in flow.splitlines()):
            flow = f"appId: {json.dumps(self.lib.app_id or 'maestro.no.app')}\n---\n{flow}"
        self.lib.run_yaml(flow, env)

    @keyword
    def execute_adb_shell(self, command: str, *args: str, timeout: timedelta = timedelta(seconds=30)) -> str:
        """Runs `adb shell command args` on the current Android device and returns its output.

        Fails if the command doesn't finish within `timeout` (AppiumLibrary has a separate
        `Execute Adb Shell Timeout` keyword for this).
        """
        from .. import ADB_MISSING  # here: the package imports this module
        self.lib.require_android("Execute Adb Shell")
        adb = self.lib.adb()
        if not adb:
            raise AssertionError(ADB_MISSING)
        try:
            result = subprocess.run(
                [adb, "-s", self.lib.device_id(), "shell", command, *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout.total_seconds(),
            )
        except subprocess.TimeoutExpired:
            raise AssertionError(f"adb shell {command} timed out after {timeout.total_seconds():g} s.") from None
        if result.returncode:
            raise AssertionError(f"adb shell {command} failed ({result.returncode}): {result.stderr.strip()}")
        return result.stdout
