"""Stand-in for `maestro mcp`: answers like the real server, as measured with Maestro CLI 2.11.0."""

import json
import os
import sys

VIEWER = {"type": "text", "text": "Important: Maestro Viewer is available at http://127.0.0.1:9999/."}
first_call = True

for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    if msg["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": os.environ.get("FAKE_MCP_NAME", "maestro"), "version": "1.0.0"}}
    else:
        name, args = msg["params"]["name"], msg["params"]["arguments"]
        if name == "exit":
            sys.exit(3)
        if name == "hang":
            continue  # never answers, like a flow that runs longer than the client waits
        if os.environ.get("FAKE_MCP_LOG"):
            # One JSON line per tool call, for tests that check what a keyword sent.
            with open(os.environ["FAKE_MCP_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps({"tool": name, "arguments": args}) + "\n")
        # A server-side notification in between must be skipped by the client.
        print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}), flush=True)
        if name == "list_devices":
            devices = [{"device_id": "emulator-5554", "platform": "android", "connected": True}]
            content = [{"type": "text", "text": json.dumps({"devices": devices})}]
        elif name == "take_screenshot":
            content = [{"type": "image", "mimeType": "image/jpeg", "data": "/9j/"}]
        elif name == "inspect_screen":
            # FAKE_MCP_SCREEN: a JSON file holding the `elements` tree to serve.
            with open(os.environ["FAKE_MCP_SCREEN"], encoding="utf-8") as screen:
                content = [{"type": "text", "text": json.dumps({"ui_schema": {}, "elements": json.load(screen)})}]
        elif name == "fail":
            content = [{"type": "text", "text": "Failed to run flow: Assertion is false: \"X\" is visible"}]
        else:
            content = [{"type": "text", "text": json.dumps(args)}]
        result = {"content": ([VIEWER] if first_call else []) + content, "isError": name == "fail"}
        first_call = False
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
