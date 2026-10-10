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

    def start(self):
        pass

    def read(self):
        return self.chunks.pop(0) if self.chunks and not self.stopped else b""

    def stop(self):
        self.stopped = True


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class StreamReaderTest(unittest.TestCase):
    def test_a_slow_ui_gets_the_newest_frame_not_a_backlog(self):
        from MaestroLibrary.studio_qt import StreamReader
        reader, signals = StreamReader(FakeStream(h264(frames=8))), []
        reader.ready.connect(lambda: signals.append(1))   # nobody takes: the UI is busy
        reader.run()
        self.assertEqual(len(signals), 1)                   # one pending notice, not eight queued frames
        image, decoded_at = reader.take()
        self.assertIsNotNone(image)
        self.assertGreater(decoded_at, 0)
        self.assertEqual(reader.take()[0], None)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_emits_frames_then_failed_when_the_stream_ends(self):
        from MaestroLibrary.studio_qt import StreamReader
        reader, frames, failures = StreamReader(FakeStream(h264())), [], []
        reader.ready.connect(lambda: frames.append(reader.take()[0]))
        reader.failed.connect(failures.append)
        reader.run()                                    # on this thread: direct signal delivery
        self.assertGreaterEqual(len(frames), 4)
        self.assertEqual(frames[0].format(), frames[0].Format.Format_RGB32)
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


HOSTILE = "<b>x</b><img src=x>"


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PySide6.QtGui import QImage
        from test_studio import FakeLib
        from MaestroLibrary.studio import Session
        from MaestroLibrary.studio_qt import ActionWorker, MainWindow
        screen = NESTED + [{"b": "[0,1000][1080,1200]", "txt": HOSTILE}]
        self.lib = FakeLib(screen)
        self.session = Session(self.lib)
        self.worker = ActionWorker(self.session)           # same thread: steps run at once
        self.window = MainWindow(self.session, self.worker, device_name="SER")
        self.window.resize(1400, 900)
        self.window.show()
        self.view = self.window.device
        self.view.set_frame(QImage(1080, 2400, QImage.Format.Format_RGB888))
        self.worker.refresh()
        self.app.processEvents()
        self.acts = []
        self.view.act.connect(lambda kind, kw: self.acts.append((kind, kw)))

    def tearDown(self):
        self.window.close()

    def point(self, x, y):
        """The widget point that shows device point (x, y)."""
        from PySide6.QtCore import QPoint
        r = self.view.frame_rect()
        return QPoint(round(r.x() + x * r.width() / 1080), round(r.y() + y * r.height() / 2400))

    def test_click_maps_widget_to_device_pixels(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(self.view, Qt.MouseButton.LeftButton, pos=self.point(500, 200))
        kind, kw = self.acts[0]
        self.assertEqual(kind, "click")
        self.assertAlmostEqual(kw["x"], 500, delta=3)
        self.assertAlmostEqual(kw["y"], 200, delta=3)
        self.assertIn("Click Element", self.window.recorder.lines.item(0).text())

    def test_drag_is_a_swipe(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mousePress(self.view, Qt.MouseButton.LeftButton, pos=self.point(540, 1800))
        QTest.mouseMove(self.view, self.point(540, 1200))
        QTest.mouseRelease(self.view, Qt.MouseButton.LeftButton, pos=self.point(540, 600))
        self.assertEqual(self.acts[0][0], "swipe")

    def test_typing_then_enter_and_secret_overlay(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.view.setFocus()
        self.window.secret.setChecked(True)
        QTest.keyClicks(self.view, "wifi")
        self.assertEqual(self.view.typing_text(), "****")
        QTest.keyClick(self.view, Qt.Key.Key_Return)
        self.assertEqual(self.acts, [("type", {"text": "wifi", "secret": True})])
        self.assertEqual(self.view.typing_text(), "")

    def test_inspect_selects_without_acting(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.inspect_mode.trigger()
        QTest.mouseClick(self.view, Qt.MouseButton.LeftButton, pos=self.point(500, 200))
        self.assertEqual(self.acts, [])
        table = self.window.inspector.locators
        self.assertEqual(table.item(0, 0).text(), "id=com.app:id/search")
        self.assertEqual(table.item(0, 1).text(), "unique")

    def test_device_text_is_never_rich_text(self):                                  # S8
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel
        self.window.inspect_mode.trigger()
        QTest.mouseMove(self.view, self.point(500, 1100))
        QTest.mouseClick(self.view, Qt.MouseButton.LeftButton, pos=self.point(500, 1100))
        texts = [self.window.inspector.title.text(), self.window.hover.text()]
        tree = self.window.inspector.source
        texts += [tree.topLevelItem(1).text(0)] if tree.topLevelItemCount() > 1 else []
        attrs = self.window.inspector.attributes
        texts += [attrs.item(r, 1).text() for r in range(attrs.rowCount())]
        self.assertTrue(any(HOSTILE in t for t in texts), texts)
        for label in self.window.findChildren(QLabel):
            self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText, label.objectName())

    def test_save_forces_robot_suffix(self):
        import tempfile
        from unittest import mock
        from MaestroLibrary import studio_qt
        self.worker.run("back", {})
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(studio_qt.QFileDialog, "getSaveFileName", return_value=(os.path.join(tmp, "t"), "")):
                self.window.recorder.save()
            with open(os.path.join(tmp, "t.robot"), encoding="utf-8") as f:
                self.assertIn("    Go Back", f.read())

    def test_undo_clear_and_record_toggle(self):
        self.worker.run("back", {})
        self.worker.run("hide_keyboard", {})
        self.window.recorder.undo_button.click()
        self.app.processEvents()
        self.assertEqual(self.session.lines, ["Go Back"])
        self.assertEqual(self.window.recorder.lines.count(), 1)
        self.window.recorder.record_button.click()
        self.assertFalse(self.session.recording)
        self.window.recorder.clear_button.click()
        self.app.processEvents()
        self.assertEqual(self.session.lines, [])
        self.assertFalse(self.session.recording)                # Clear keeps the recording state


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class MainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def run_main(self, platform, adb="adb"):
        from unittest import mock
        import MaestroLibrary
        from MaestroLibrary import studio, studio_qt
        from test_studio import FakeLib
        lib = FakeLib(NESTED)
        lib.device_id, lib.platform, lib.adb, lib.mcp = (lambda: "SER"), platform, (lambda: adb), mock.Mock()
        lib.mcp.call_tool.return_value = [{"type": "image", "data": "iVBORw0KGgo="}]
        reader = mock.Mock()
        windows = []
        real_window = studio_qt.MainWindow

        def window(*args, **kwargs):
            windows.append(real_window(*args, **kwargs))
            return windows[-1]
        with mock.patch.object(MaestroLibrary, "MaestroLibrary", return_value=lib), \
                mock.patch.object(studio_qt, "StreamReader", return_value=reader) as make_reader, \
                mock.patch.object(studio_qt, "MainWindow", side_effect=window), \
                mock.patch.object(QApplication, "exec", return_value=0):
            self.assertEqual(studio.main(["--app", "com.app", "--max-size", "800"]), 0)
        windows[0].close()
        return lib, reader, make_reader, windows[0]

    def test_android_starts_the_live_view_and_cleans_up(self):
        lib, reader, make_reader, window = self.run_main("android")
        self.assertEqual(make_reader.call_args.args[0].max_size, 800)
        reader.start.assert_called_once()
        reader.stop.assert_called_once()
        lib.mcp.close.assert_called_once()
        self.assertEqual(window.windowTitle()[:31], "MaestroLibrary Studio - SER (ke")

    def test_ios_falls_back_to_screenshots(self):
        lib, reader, make_reader, window = self.run_main("ios", adb=None)
        make_reader.assert_not_called()
        self.assertIn("screenshots", window.state.text())
        self.assertIn("Android only", window.state.toolTip())

    def test_missing_extra_says_how_to_install(self):
        from unittest import mock
        from MaestroLibrary import studio
        with mock.patch.dict(sys.modules, {"PySide6.QtCore": None}), mock.patch("sys.stderr") as err:
            self.assertEqual(studio.main([]), 2)
        self.assertIn("[studio]", "".join(c.args[0] for c in err.write.call_args_list))


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class LiveStateTest(WindowTest):
    def test_live_then_fallback(self):
        from PySide6.QtGui import QImage
        self.window.go_live(QImage(10, 20, QImage.Format.Format_RGB888))
        self.assertTrue(self.window.live and self.worker.live)
        self.assertTrue(self.window.state.text().endswith(": live"))
        self.window.fallback("No live view (test)")
        self.assertFalse(self.window.live or self.worker.live)
        self.assertEqual(self.window.message.text(), "No live view (test)")

    def test_worker_screenshots_while_not_live(self):
        from PySide6.QtGui import QImage
        shots = []
        self.worker.screenshot = lambda: shots.append(1) or QImage(5, 5, QImage.Format.Format_RGB888)
        self.worker.run("back", {})
        self.assertEqual(len(shots), 1)
        self.worker.live = True
        self.worker.run("back", {})
        self.assertEqual(len(shots), 1)

    def test_inspector_actions_and_handles(self):
        self.window.inspector.show_element(self.session.tree()["elements"][1])
        acts = []
        self.window.inspector.act.disconnect()
        self.window.inspector.act.connect(lambda kind, kw: acts.append((kind, kw)))
        for button in self.window.inspector.findChildren(studio_qt_button()):
            if button.text() == "Text should be":
                button.click()
        self.assertEqual(acts, [("text_should_be", {"x": 540, "y": 200, "text": "Search"})])
        self.window.handles.setChecked(True)
        self.window.device.repaint()

    def test_delete_removes_the_selected_line(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        for kind in ("back", "hide_keyboard", "screenshot"):
            self.worker.run(kind, {})
        self.window.recorder.lines.setCurrentRow(1)
        self.window.recorder.lines.setFocus()
        QTest.keyClick(self.window.recorder.lines, Qt.Key.Key_Delete)
        self.app.processEvents()
        self.assertEqual(self.session.lines, ["Go Back", "Capture Page Screenshot"])

    def test_inspector_is_compact_when_nothing_is_selected(self):
        inspector = self.window.inspector
        self.assertFalse(inspector.locators.isVisibleTo(inspector))
        self.assertIn("Nothing selected", inspector.title.text())
        self.window.inspect_mode.trigger()
        self.assertTrue(self.window.hint.text().startswith("Inspect"))


def studio_qt_button():
    from PySide6.QtWidgets import QPushButton
    return QPushButton


class SourceTreeTest(unittest.TestCase):
    @unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
    def test_system_ui_and_unlabeled_containers_are_left_out(self):
        from MaestroLibrary.studio_qt import visible_tree
        screen = NESTED + [
            {"b": "[0,0][1080,80]", "rid": "com.android.systemui:id/status_bar", "c": [{"txt": "10:58"}]},
            {"rid": "com.google.android.inputmethod.latin:id/key", "txt": "q"}]

        def shape(rows):
            return [(e.get("txt") or e.get("rid"), shape(c)) for e, c in rows]
        # the root and the row container have nothing locatable: their children move up a level
        self.assertEqual(shape(visible_tree(screen)), [("Search", []), ("Apps", [])])


if __name__ == "__main__":
    unittest.main()
