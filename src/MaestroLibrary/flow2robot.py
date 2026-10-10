"""Converts a Maestro flow (for example one recorded in Maestro Studio) to a Robot Framework test.

    python -m MaestroLibrary.flow2robot flow.yaml > flow.robot

Commands with a keyword become that keyword; the rest become an inline `Run Flow` line. Needs
PyYAML (``pip install robotframework-maestrolibrary[convert]``).
"""
import os
import re
import sys

SEP = "    "


def to_locator(selector):
    """Returns the locator for a Maestro selector, or None when no locator strategy matches it."""
    if isinstance(selector, str):
        selector = {"text": selector}
    if not isinstance(selector, dict):
        return None
    selector = {k: v for k, v in selector.items() if k != "label"}
    if len(selector) != 1:
        return None
    (key, value), = selector.items()
    value = str(value)
    literal = not re.search(r"[.^$*+?{}\[\]\|()]", value)
    if key == "text":
        return f"text={value}" if literal else f"regex={value}"
    if key == "id":
        return f"id={value}" if literal else f"id_regex={value}"
    if key == "point":
        return f"point={value}"
    return None


def _seconds(ms):
    return f"{int(ms) / 1000:g}s"


def _step(command, app_id):
    """Returns the keyword and arguments for one Maestro command, or None when there is no keyword."""
    if isinstance(command, str):
        name, arg = command, None
    elif isinstance(command, dict) and len(command) == 1:
        (name, arg), = command.items()
    else:
        return None
    simple = {"back": "Go Back", "hideKeyboard": "Hide Keyboard"}
    if name in simple and arg is None:
        return [simple[name]]
    if name == "launchApp":
        launch = {"appId": arg} if isinstance(arg, str) else dict(arg or {})
        launch.setdefault("appId", app_id)
        if not launch["appId"] or set(launch) - {"appId", "clearState", "stopApp"}:
            return None
        step = ["Open Application", launch["appId"]]
        if launch.get("clearState"):
            step.append(("clear_state", "True"))
        if launch.get("stopApp") is False:
            step.append(("stop_app", "False"))
        return step
    if name in ("stopApp", "killApp", "clearState") and (arg is None or isinstance(arg, str)):
        keyword = {"stopApp": "Terminate Application", "killApp": "Kill Application",
                   "clearState": "Clear Application State"}[name]
        target = arg or (app_id if name == "stopApp" else None)
        return [keyword, target] if target else ([keyword] if name != "stopApp" else ["Close Application"])
    if name in ("tapOn", "longPressOn"):
        repeat = arg.get("repeat", 1) if isinstance(arg, dict) else 1
        selector = {k: v for k, v in arg.items() if k != "repeat"} if isinstance(arg, dict) else arg
        locator = to_locator(selector)
        if locator is None:
            return None
        if name == "longPressOn":
            return ["Long Press", locator] if repeat == 1 else None
        return ["Click Element", locator] if repeat == 1 else ["Tap", locator, str(repeat)]
    if name in ("assertVisible", "assertNotVisible"):
        locator = to_locator(arg)
        keyword = "Wait Until Page Contains Element" if name == "assertVisible" else \
            "Wait Until Page Does Not Contain Element"
        return [keyword, locator] if locator else None
    if name == "scrollUntilVisible" and isinstance(arg, dict):
        rest = {k: v for k, v in arg.items() if k not in ("element", "direction", "timeout")}
        direction = str(arg.get("direction", "DOWN")).upper()
        locator = to_locator(arg.get("element"))
        if rest or locator is None or direction not in ("DOWN", "UP"):
            return None
        step = ["Scroll Down" if direction == "DOWN" else "Scroll Up", locator]
        return step + [("timeout", _seconds(arg["timeout"]))] if "timeout" in arg else step
    if name == "inputText" and isinstance(arg, (str, int, float)):
        return ["Input Text Into Current Element", str(arg)]
    if name == "pressKey" and isinstance(arg, str):
        return ["Press Key", arg]
    if name == "openLink" and isinstance(arg, str):
        return ["Go To Url", arg]
    if name == "takeScreenshot" and isinstance(arg, str):
        return ["Capture Page Screenshot", f"{arg}.jpg"]   # the library saves JPEG data
    if name == "waitForAnimationToEnd":
        if arg is None:
            return ["Wait For Animation To End"]
        if isinstance(arg, dict) and set(arg) == {"timeout"}:
            return ["Wait For Animation To End", ("timeout", _seconds(arg["timeout"]))]
    if name == "runFlow" and isinstance(arg, str):
        return ["Run Flow", arg if os.path.isabs(arg) else "${CURDIR}/" + arg]
    if name == "setLocation" and isinstance(arg, dict) and set(arg) == {"latitude", "longitude"}:
        return ["Set Location", str(arg["latitude"]), str(arg["longitude"])]
    return None


def escape(arg, keep_variables=True):
    """Escapes what Robot would read as a separator, escape, comment, named argument, variable or empty cell.

    With `keep_variables`, a plain ``${name}`` stays, so Maestro's variables become Robot variables
    to define. Every other variable syntax is escaped: ``${{ }}`` would run Python when the test runs.
    """
    if arg == "":
        return "${EMPTY}"
    arg = arg.replace("\\", "\\\\")
    arg = re.sub(r"[$@&%]\{", lambda m: m.group() if keep_variables and re.match(r"\$\{\w+\}", m.string[m.start():])
                 else "\\" + m.group(), arg)
    arg = re.sub(r"^(\w+)=", r"\1\\=", arg)
    arg = re.sub(r" {2,}", lambda m: " " + "\\ " * (len(m.group()) - 1), arg)
    if arg.startswith((" ", "#")):
        arg = "\\" + arg
    if arg.endswith(" "):
        arg = arg[:-1] + "\\ "
    return arg.replace("\n", "\\n")


def convert(text, name="Recorded Flow"):
    """Returns a Robot Framework test file for the Maestro flow in `text`."""
    import yaml

    docs = [d for d in yaml.safe_load_all(text) if d is not None]
    config = docs[0] if len(docs) > 1 and isinstance(docs[0], dict) else {}
    commands = docs[-1] if docs and isinstance(docs[-1], list) else []
    app_id = config.get("appId")
    steps = []
    for command in commands:
        step = _step(command, app_id)
        if step is None:
            # Flow style keeps the YAML on one line with single spaces, so Robot reads one cell.
            inline = yaml.safe_dump(command, default_flow_style=True, sort_keys=False, width=1e9).strip()
            step = ["Run Flow", "- " + inline]
        elif step[0] == "Input Text Into Current Element" and steps and steps[-1][0] == "Click Element":
            step = ["Input Text", steps.pop()[1], step[1]]
        steps.append(step)
    lines = ["*** Settings ***", "Library    MaestroLibrary", "", "*** Test Cases ***", name]
    lines += [SEP + SEP.join(f"{a[0]}={escape(a[1])}" if isinstance(a, tuple) else escape(str(a)) for a in step) for step in steps]
    return "\n".join(lines) + "\n"


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: python -m MaestroLibrary.flow2robot FLOW.yaml|-", file=sys.stderr)
        return 2
    if args[0] == "-":
        text, name = sys.stdin.read(), "Recorded Flow"
    else:
        with open(args[0], encoding="utf-8") as f:
            text = f.read()
        name = os.path.splitext(os.path.basename(args[0]))[0].replace("_", " ").replace("-", " ").title()
    sys.stdout.write(convert(text, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
