"""Reads the screen's element tree straight from Maestro's Android driver over gRPC.

The driver (Maestro's open-source instrumentation, Apache-2.0) serves `maestro_android.MaestroDriver/viewHierarchy`
on device port 7001 (`maestro-proto/src/main/proto/maestro_android.proto`). Measured on an Android 15 phone: 0.45 s
per read, against 2.2 s for Maestro MCP's inspect_screen. Studio uses it for its element tree and falls back to
inspect_screen when it fails; Maestro itself still starts the driver and runs every step.
"""
import subprocess
# Device XML: elements_from_xml refuses DOCTYPE and entity declarations before parsing (defusedxml's guard).
import xml.etree.ElementTree as ET  # nosec B405

DRIVER_PORT = 7001                    # the driver's default port (MaestroDriverService)
METHOD = "/maestro_android.MaestroDriver/viewHierarchy"
MAX_BYTES = 64 << 20
TEXT_KEYS = (("bounds", "b"), ("text", "txt"), ("resource-id", "rid"), ("content-desc", "a11y"), ("hintText", "hint"),
             ("class", "cls"))
FLAG_KEYS = (("clickable", "clickable"), ("scrollable", "scroll"), ("selected", "selected"))


def hierarchy_text(message):
    """`hierarchy` (field 1, a string) from a serialized ViewHierarchyResponse, without the protobuf runtime."""
    if not message:
        return ""
    if message[0] != 0x0A:                            # field 1, length-delimited
        raise ValueError("Unexpected viewHierarchy response.")
    size = shift = 0
    i = 1
    while True:
        byte = message[i]
        size |= (byte & 0x7F) << shift
        i += 1
        shift += 7
        if not byte & 0x80:
            break
    return message[i:i + size].decode("utf-8", "replace")


def elements_from_xml(text):
    """The driver's uiautomator-style XML as Maestro MCP's compact element tree (the shape `lib.screen()` returns)."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:     # device data: no entities, so no entity expansion attacks
        raise ValueError("The view hierarchy declares a DOCTYPE or entities; refused.")

    def node(n):
        e = {key: n.get(attr) for attr, key in TEXT_KEYS if n.get(attr)}
        e.update({key: True for attr, key in FLAG_KEYS if n.get(attr) == "true"})
        if n.get("enabled") == "false":
            e["enabled"] = False
        children = [node(c) for c in n if c.tag == "node"]
        if children:
            e["c"] = children
        return e

    root = ET.fromstring(text)  # nosec B314
    return [{"c": [node(c) for c in root if c.tag == "node"]}]


class DriverReader:
    """Reads the current device's tree through an adb forward to the driver; `lib` gives adb and the device."""

    def __init__(self, lib):
        self.lib, self.device, self.port, self._call, self._channel = lib, None, None, None, None

    def _connect(self):
        import grpc                           # the studio extra; only Studio reads this way
        device = self.lib.device_id()
        self.close()
        answer = subprocess.run([self.lib.adb(), "-s", device, "forward", "tcp:0", f"tcp:{DRIVER_PORT}"],
                                capture_output=True, text=True, timeout=10, check=True).stdout
        self.port = int(answer.strip())
        self._channel = grpc.insecure_channel(f"127.0.0.1:{self.port}",
                                              options=[("grpc.max_receive_message_length", MAX_BYTES)])
        self._call = self._channel.unary_unary(METHOD, request_serializer=bytes, response_deserializer=bytes)
        self.device = device

    def screen(self, timeout=10):
        if self.lib.platform != "android":       # an iOS device after a switch: the caller falls back to Maestro
            raise LookupError("The driver reader reads Android devices only.")
        if self._call is None or self.device != self.lib.device:       # first read, or the device was switched
            self._connect()
        return elements_from_xml(hierarchy_text(self._call(b"", timeout=timeout)))

    def close(self):
        if self._channel:
            self._channel.close()
        if self.port and self.device:
            subprocess.run([self.lib.adb(), "-s", self.device, "forward", "--remove", f"tcp:{self.port}"],
                           capture_output=True, timeout=10)
        self.port = self._call = self._channel = None
