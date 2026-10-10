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


NESTED = [{"b": "[0,0][1080,2400]", "c": [
    {"b": "[0,100][1080,300]", "rid": "com.app:id/search", "txt": "Search"},
    {"b": "[0,400][1080,600]", "c": [{"b": "[0,400][540,600]", "txt": "Apps"}]}]}]


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class ActionWorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from test_studio import FakeLib
        from MaestroLibrary.studio import Session
        from MaestroLibrary.studio_qt import ActionWorker
        self.lib = FakeLib(NESTED)
        self.session = Session(self.lib)
        self.worker = ActionWorker(self.session)
        self.events = []
        self.worker.recorded.connect(lambda line: self.events.append(("recorded", line)))
        self.worker.failed.connect(lambda message: self.events.append(("failed", message)))
        self.worker.tree.connect(lambda tree: self.events.append(("tree", len(tree["elements"]))))

    def test_steps_run_in_order_and_refresh_the_tree(self):
        self.worker.run("back", {})
        self.worker.run("hide_keyboard", {})
        self.assertEqual(self.lib.ran, [("go_back", []), ("hide_keyboard", [])])
        self.assertEqual(self.events, [("recorded", "Go Back"), ("tree", 4), ("recorded", "Hide Keyboard"), ("tree", 4)])

    def test_a_device_failure_records_nothing(self):
        self.lib.fail = "Element not found"
        self.worker.run("click", {"x": 500, "y": 200})
        self.assertEqual(self.events[0], ("failed", "Element not found"))
        self.assertEqual(self.session.lines, [])

    def test_refused_text_says_why(self):
        self.worker.run("type", {"text": "${1}"})
        self.assertIn("JavaScript", self.events[0][1])

    def test_steps_queue_across_threads(self):
        from PySide6.QtCore import QThread
        from PySide6.QtTest import QTest
        thread = QThread()
        self.worker.moveToThread(thread)
        thread.start()
        try:
            for kind in ("back", "hide_keyboard", "back"):
                self.worker.request.emit(kind, {})
            for _ in range(100):
                if len(self.lib.ran) == 3:
                    break
                QTest.qWait(20)
        finally:
            thread.quit()
            thread.wait(2000)
        self.assertEqual([r[0] for r in self.lib.ran], ["go_back", "hide_keyboard", "go_back"])


class SourceTreeTest(unittest.TestCase):
    @unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
    def test_depths(self):
        from MaestroLibrary.studio_qt import source_tree
        self.assertEqual([(d, e["b"]) for d, e in source_tree(NESTED)],
                         [(0, "[0,0][1080,2400]"), (1, "[0,100][1080,300]"), (1, "[0,400][1080,600]"),
                          (2, "[0,400][540,600]")])


if __name__ == "__main__":
    unittest.main()
