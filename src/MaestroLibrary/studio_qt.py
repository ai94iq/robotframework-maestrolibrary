"""The Studio window (PySide6): live device screen, inspector and recorder. Needs the `studio` extra."""
import av
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImage

MAX_SIDE = 8192            # larger frames are dropped: our scrcpy-server never sends them


class FrameDecoder:
    """Decodes raw Annex-B H.264, fed in chunks of any size, into QImages."""

    def __init__(self, max_side=MAX_SIDE):
        self.codec = av.CodecContext.create("h264", "r")
        self.max_side = max_side

    def _images(self, packets):
        images = []
        for packet in packets:
            try:
                frames = self.codec.decode(packet)
            except av.error.FFmpegError:       # damaged data: skip it, keep the stream going
                continue
            for frame in frames:
                if max(frame.width, frame.height) > self.max_side:
                    continue
                rgb = frame.reformat(format="rgb24")
                plane = rgb.planes[0]
                images.append(QImage(bytes(plane), rgb.width, rgb.height, plane.line_size,
                                     QImage.Format.Format_RGB888).copy())
        return images

    def feed(self, data):
        try:
            return self._images(self.codec.parse(data))
        except av.error.FFmpegError:
            return []

    def flush(self):
        return self._images([None])


def source_tree(screen, depth=0):
    """(depth, element) pairs of a nested inspect_screen tree, depth first."""
    pairs = []
    for element in screen:
        pairs.append((depth, element))
        pairs += source_tree(element.get("c", []), depth + 1)
    return pairs


class ActionWorker(QObject):
    """Runs studio steps on its own thread, one at a time in the order they were requested.

    One Maestro session per device: everything that talks to the device goes through here.
    """

    request = Signal(str, dict)       # (kind, keyword arguments for Session.act)
    poll = Signal()                    # refresh the element tree
    recorded = Signal(object)          # the recorded line, or None while recording is off
    failed = Signal(str)
    tree = Signal(dict)
    done = Signal()                    # a step finished, whatever its outcome

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.request.connect(self.run)
        self.poll.connect(self.refresh)

    @Slot(str, dict)
    def run(self, kind, kwargs):
        try:
            self.recorded.emit(self.session.act(kind, **kwargs))
        except Exception as err:       # a refused input or a device failure: nothing was recorded
            self.failed.emit(str(err) or type(err).__name__)
        finally:
            self.refresh()
            self.done.emit()

    @Slot()
    def refresh(self):
        try:
            self.tree.emit(self.session.tree(fresh=True))
        except Exception as err:
            self.failed.emit(f"Could not read the screen: {err}")


class StreamReader(QThread):
    """Reads a started ScrcpyStream on its own thread and emits each decoded frame."""

    frame = Signal(QImage)
    failed = Signal(str)

    def __init__(self, stream, decoder=None):
        super().__init__()
        self.stream, self.decoder = stream, decoder or FrameDecoder()
        self._stopping = False

    def run(self):
        for chunk in iter(self.stream.read, b""):
            for image in self.decoder.feed(chunk):
                self.frame.emit(image)
        if not self._stopping:
            self.failed.emit("The live view ended; showing screenshots after each step.")

    def stop(self):
        self._stopping = True
        self.stream.stop()
        self.wait(5000)
