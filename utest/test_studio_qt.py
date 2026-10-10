import os
import shutil
import sys
import tempfile
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
class WindowCase(unittest.TestCase):
    """The window fixture shared by the window tests; holds no tests itself."""

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
        self.settings = self.ini_settings()
        self.window = MainWindow(self.session, self.worker, device_name="SER", settings=self.settings)
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

    def ini_settings(self):
        """QSettings in a temp ini file, so tests never touch the user's real settings."""
        from PySide6.QtCore import QSettings
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        settings = QSettings(os.path.join(folder, "studio.ini"), QSettings.Format.IniFormat)
        self.addCleanup(settings.sync)
        return settings

    def point(self, x, y):
        """The widget point that shows device point (x, y)."""
        from PySide6.QtCore import QPoint
        r = self.view.frame_rect()
        return QPoint(round(r.x() + x * r.width() / 1080), round(r.y() + y * r.height() / 2400))


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class WindowTest(WindowCase):
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
class ThemeTest(WindowCase):
    def images(self, icon_):
        from PySide6.QtGui import QIcon
        return [icon_.pixmap(32, 32, QIcon.Mode.Normal, state).toImage()
                for state in (QIcon.State.Off, QIcon.State.On)]

    def new_window(self):
        from MaestroLibrary.studio_qt import MainWindow
        window = MainWindow(self.session, self.worker, device_name="SER", settings=self.settings)
        self.addCleanup(window.close)
        return window

    def test_checked_icon_is_drawn_in_its_own_color(self):
        from MaestroLibrary.studio_qt import icon
        off, on = self.images(icon("act", "#000000", "#ff0000"))
        self.assertNotEqual(off, on)

    def test_icon_without_on_color_looks_the_same_when_checked(self):
        from MaestroLibrary.studio_qt import icon
        off, on = self.images(icon("act", "#000000"))
        self.assertEqual(off, on)

    def test_checked_toolbar_action_icon_is_visible(self):
        off, on = self.images(self.window.inspect_mode.icon())
        self.assertNotEqual(off, on)

    def test_theme_button_cycles_and_persists(self):
        from MaestroLibrary.studio_qt import THEMES
        window = self.window
        self.assertEqual(window.theme_mode, "system")
        self.assertEqual(window.theme_action.toolTip(), "Theme: System (click to change)")
        window.theme_action.trigger()
        self.assertEqual((window.theme_mode, self.settings.value("theme")), ("light", "light"))
        self.assertEqual(window.t["ground"], THEMES["light"]["ground"])
        self.assertIs(window.device.t, window.t)
        self.assertEqual(window.theme_action.toolTip(), "Theme: Light (click to change)")
        window.theme_action.trigger()
        self.assertEqual((window.theme_mode, self.settings.value("theme")), ("dark", "dark"))
        self.assertEqual(window.t["ground"], THEMES["dark"]["ground"])
        window.theme_action.trigger()
        self.assertEqual(window.theme_mode, "system")
        window.theme_action.trigger()
        self.assertEqual(self.new_window().theme_mode, "light")

    def test_chip_text_has_4_5_contrast_in_both_themes(self):
        from MaestroLibrary.studio_qt import THEMES

        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        for t in THEMES.values():
            hi, lo = sorted((lum(t["accent_text"]), lum(t["accent_soft"])), reverse=True)
            self.assertGreaterEqual((hi + 0.05) / (lo + 0.05), 4.5)

    def test_both_pane_titles_share_one_height(self):
        self.assertEqual(self.window.inspector.source_label.height(), self.window.recorder.name.height())

    def test_menus_and_tooltips_are_see_through(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtWidgets import QMenu, QStyle, QToolTip
        menu = QMenu()
        menu.ensurePolished()
        self.assertTrue(menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(menu.windowFlags() & Qt.WindowType.FramelessWindowHint)
        QToolTip.showText(QPoint(50, 50), "tip")
        tips = [w for w in self.app.topLevelWidgets() if w.metaObject().className() == "QTipLabel"]
        self.assertTrue(tips and all(w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) for w in tips))
        self.assertEqual(self.app.style().styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay), 150)

    def test_buttons_take_focus_by_keyboard_only(self):
        from PySide6.QtCore import Qt
        self.assertEqual(self.window.recorder.record_button.focusPolicy(), Qt.FocusPolicy.TabFocus)
        self.assertEqual(self.window.theme_button.focusPolicy(), Qt.FocusPolicy.TabFocus)

    def test_one_device_has_no_dropdown(self):
        self.assertFalse(self.window.chevron.isVisibleTo(self.window))
        self.window.switch_device("OTHER")
        self.assertIsNone(self.window.next_device)

    def test_several_devices_make_the_pill_a_dropdown(self):
        from MaestroLibrary.studio_qt import MainWindow
        window = MainWindow(self.session, self.worker, device_name="SER", settings=self.settings, devices=["SER", "A&B"])
        self.addCleanup(window.close)
        window.show()
        self.assertTrue(window.chevron.isVisibleTo(window))
        window.switch_device("SER")
        self.assertIsNone(window.next_device)
        window.switch_device("not-listed")
        self.assertIsNone(window.next_device)
        window.switch_device("A&B")
        self.assertEqual(window.next_device, "A&B")

    def test_invalid_stored_theme_falls_back_to_system(self):
        self.settings.setValue("theme", "neon")
        self.assertEqual(self.new_window().theme_mode, "system")

    def test_apply_theme_returns_tokens_and_sets_stylesheet(self):
        from MaestroLibrary.studio_qt import THEMES, apply_theme, theme_name
        self.assertEqual(apply_theme(self.app, "light"), THEMES["light"])
        self.assertTrue(self.app.styleSheet())
        self.assertEqual(theme_name(self.app, "dark"), "dark")


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
        from PySide6.QtCore import QSettings
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ini = QSettings(os.path.join(folder, "studio.ini"), QSettings.Format.IniFormat)

        def window(*args, **kwargs):
            windows.append(real_window(*args, **kwargs))
            return windows[-1]
        with mock.patch.object(MaestroLibrary, "MaestroLibrary", return_value=lib), \
                mock.patch.object(studio_qt, "StreamReader", return_value=reader) as make_reader, \
                mock.patch.object(studio_qt, "MainWindow", side_effect=window), \
                mock.patch.object(studio_qt, "QSettings", return_value=ini), \
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

    def test_choosing_another_device_reopens_studio_with_the_recording(self):
        import json
        from unittest import mock
        import MaestroLibrary
        from MaestroLibrary import studio, studio_qt
        from test_studio import FakeLib
        from PySide6.QtCore import QSettings
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ini = QSettings(os.path.join(folder, "studio.ini"), QSettings.Format.IniFormat)
        made, windows, real_window = [], [], studio_qt.MainWindow

        def make_lib(device=None, **kwargs):
            lib = FakeLib(NESTED)
            lib.device_id, lib.platform, lib.adb, lib.mcp = (lambda: device or "A"), "ios", (lambda: None), mock.Mock()
            devices = [{"device_id": d, "platform": "ios", "connected": True} for d in ("A", "B")]
            lib.mcp.call_tool.return_value = [{"type": "text", "text": json.dumps({"devices": devices})}]
            made.append((device, lib))
            return lib

        def window(*args, **kwargs):
            windows.append(real_window(*args, **kwargs))
            return windows[-1]

        def run():
            if len(windows) == 1:
                windows[0].session.lines.append("Go Back")
                windows[0].recorder.name.setText("My test")
                windows[0].switch_device("B")
            return 0
        with mock.patch.object(MaestroLibrary, "MaestroLibrary", side_effect=make_lib),                 mock.patch.object(studio_qt, "MainWindow", side_effect=window),                 mock.patch.object(studio_qt, "QSettings", return_value=ini),                 mock.patch.object(QApplication, "exec", side_effect=run):
            self.assertEqual(studio.main([]), 0)
        self.assertEqual([d for d, _ in made], [None, "B"])
        self.assertEqual(windows[0].devices, ["A", "B"])
        self.assertEqual(windows[1].session.lines, ["Go Back"])
        self.assertEqual(windows[1].recorder.name.text(), "My test")
        for _, lib in made:
            lib.mcp.close.assert_called_once()
        for w in windows:
            w.close()

    def test_missing_extra_says_how_to_install(self):
        from unittest import mock
        from MaestroLibrary import studio
        with mock.patch.dict(sys.modules, {"PySide6.QtCore": None}), mock.patch("sys.stderr") as err:
            self.assertEqual(studio.main([]), 2)
        self.assertIn("[studio]", "".join(c.args[0] for c in err.write.call_args_list))


@unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
class LiveStateTest(WindowCase):
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
        for action in self.window.inspector.assert_menu.actions():
            if action.text() == "Text should be":
                action.trigger()
        self.assertEqual(acts, [("text_should_be", {"x": 540, "y": 200, "text": "Search"})])
        self.window.handles.setChecked(True)
        self.window.device.repaint()

    def test_attributes_are_collapsed_until_asked_for(self):
        inspector = self.window.inspector
        inspector.show_element(self.session.tree()["elements"][1])
        self.assertTrue(inspector.attr_head.isVisibleTo(inspector))
        self.assertFalse(inspector.attributes.isVisibleTo(inspector))
        inspector.attr_toggle.setChecked(True)
        self.assertTrue(inspector.attributes.isVisibleTo(inspector))

    def test_focus_ring_only_for_keyboard_focus(self):
        from PySide6.QtCore import Qt
        self.view.setFocus(Qt.FocusReason.MouseFocusReason)
        self.assertFalse(self.view._ring)
        self.view.clearFocus()
        self.view.setFocus(Qt.FocusReason.TabFocusReason)
        self.assertTrue(self.view._ring)

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


class SourceTreeTest(unittest.TestCase):
    @unittest.skipIf(av is None, "needs the studio extra (PySide6, av)")
    def test_system_ui_and_unlabeled_containers_are_left_out(self):
        from MaestroLibrary.studio_qt import visible_tree
        screen = NESTED + [
            {"b": "[0,0][1080,80]", "rid": "com.android.systemui:id/status_bar", "c": [{"txt": "10:58"}]},
            {"rid": "com.google.android.inputmethod.latin:id/key", "txt": "q"},
            {"rid": "android:id/content", "c": [{"rid": "app:id/0_obf", "c": [{"rid": "app:id/0_obf", "a11y": "Play"}]}]}]

        def shape(rows):
            return [(e.get("txt") or e.get("a11y") or e.get("rid"), shape(c)) for e, c in rows]
        # the root and the row container have nothing locatable: their children move up a level
        self.assertEqual(shape(visible_tree(screen)), [("Search", []), ("Apps", []), ("Play", [])])


if __name__ == "__main__":
    unittest.main()
