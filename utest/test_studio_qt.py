import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import av
    from PySide6.QtWidgets import QApplication
except ImportError:          # the studio extra is not installed
    av = None


def h264(width=320, height=640, frames=6):
    """Annex-B H.264 for a few solid-color frames, encoded here so the test needs no recording."""
    codec = av.CodecContext.create("libx264", "w")
    codec.width, codec.height, codec.pix_fmt = width, height, "yuv420p"
    codec.options = {"tune": "zerolatency"}
    out = b""
    for i in range(frames):
        frame = av.VideoFrame(width, height, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes([40 * i % 256]) * plane.buffer_size)
        frame.pts = i
        out += b"".join(bytes(p) for p in codec.encode(frame))
    return out + b"".join(bytes(p) for p in codec.encode(None))


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class FrameDecoderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_decodes_frames_fed_in_any_chunking(self):
        from MaestroLibrary.studio_qt import FrameDecoder
        data, decoder, images = h264(), FrameDecoder(), []
        for i in range(0, len(data), 997):              # odd chunk sizes split NAL units mid-way
            images += decoder.feed(data[i:i + 997])
        images += decoder.flush()
        self.assertGreaterEqual(len(images), 5)
        self.assertEqual((images[0].width(), images[0].height()), (320, 640))

    def test_garbage_gives_no_frame_and_no_error(self):
        from MaestroLibrary.studio_qt import FrameDecoder
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(os.urandom(1 << 20)) + decoder.flush(), [])

    def test_oversized_frames_are_dropped(self):
        from MaestroLibrary.studio_qt import FrameDecoder
        decoder = FrameDecoder(max_side=200)
        self.assertEqual(decoder.feed(h264()) + decoder.flush(), [])


class FakeStream:
    def __init__(self, data):
        self.chunks, self.stopped = [data[i:i + 4096] for i in range(0, len(data), 4096)], False

    def read(self):
        return self.chunks.pop(0) if self.chunks and not self.stopped else b""

    def stop(self):
        self.stopped = True


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class StreamReaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_emits_frames_then_failed_when_the_stream_ends(self):
        from MaestroLibrary.studio_qt import StreamReader
        reader, frames, failures = StreamReader(FakeStream(h264())), [], []
        reader.frame.connect(frames.append)
        reader.failed.connect(failures.append)
        reader.run()                                    # on this thread: direct signal delivery
        self.assertGreaterEqual(len(frames), 4)
        self.assertEqual(len(failures), 1)
        self.assertIn("screenshots", failures[0])

    def test_stop_is_quiet(self):
        from MaestroLibrary.studio_qt import StreamReader
        stream = FakeStream(h264())
        reader, failures = StreamReader(stream), []
        reader.failed.connect(failures.append)
        reader.stop()
        reader.run()
        self.assertTrue(stream.stopped)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
