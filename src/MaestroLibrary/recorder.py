"""Records the Maestro commands a Robot run sends, as one replayable flow file per test."""
import itertools
import json
import os
import re

from robot.libraries.BuiltIn import BuiltIn

from .keywords._screenshot import log_link, output_path

MASKED_INPUT = "${PASSWORD}"   # what Maestro is given with -e PASSWORD=...


class FlowRecorder:
    def __init__(self):
        self._files = {}
        self._index = itertools.count(1)

    def record(self, app_id, lines):
        """Appends flow `lines` ("- command") to the current test's flow file, creating it with `app_id`."""
        variables = BuiltIn().get_variables()
        name = variables.get("${TEST NAME}") or variables.get("${SUITE NAME}", "flow")
        key = (variables.get("${SUITE SOURCE}"), name)
        path = self._files.get(key)
        if path is None:
            safe = re.sub(r"[^\w.-]+", "_", name)[:100]
            path = output_path(os.path.join("flows", f"{next(self._index)}-{safe}.yaml"))
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"appId: {json.dumps(app_id)}\n---\n")
            self._files[key] = path
            log_link(path, f'Maestro flow: <a href="{{src}}">{os.path.basename(path)}</a>')
        with open(path, "a", encoding="utf-8") as f:
            f.writelines(line + "\n" for line in lines)

    def commands(self, app_id, commands, secret):
        """Records keyword commands. A secret's inputText becomes ${PASSWORD}; settle waits are left out."""
        if secret:
            commands = [{"inputText": MASKED_INPUT} if isinstance(c, dict) and "inputText" in c else c
                        for c in commands if not (isinstance(c, dict) and "waitForAnimationToEnd" in c)]
        if commands:
            self.record(app_id, [f"- {json.dumps(c)}" for c in commands])

    def yaml(self, app_id, text, env=None):
        """Records an inline Run Flow body, without its config section; `env` wraps it in a runFlow."""
        body = text.split("\n---\n", 1)[1] if "\n---\n" in text else text
        lines = [line for line in body.splitlines() if line.strip()]
        if env:
            lines = ["- runFlow:", f"    env: {json.dumps(env)}", "    commands:"] + ["      " + line for line in lines]
        self.record(app_id, lines)

    def files(self, app_id, files, env=None):
        """Records flow files run by Run Flow as runFlow commands."""
        self.record(app_id, [f"- runFlow: {json.dumps({'file': f, 'env': env} if env else f)}" for f in files])
