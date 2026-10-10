"""The Studio window (PySide6): live device screen, inspector and recorder. Needs the `studio` extra."""
import av
from PySide6.QtCore import QThread, Signal
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
