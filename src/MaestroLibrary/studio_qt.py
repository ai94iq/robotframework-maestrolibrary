"""The Studio window (PySide6): live device screen, inspector and recorder. Needs the `studio` extra."""
import html
from collections import Counter
import subprocess
import threading
import time

import av
from PySide6.QtCore import QObject, QPointF, QRectF, QSettings, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFontDatabase, QGuiApplication, QIcon, QImage,
                           QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QPushButton, QSizePolicy,
                               QSplitter, QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QTreeWidget,
                               QTreeWidgetItem,
                               QVBoxLayout, QWidget, QWidgetAction)

from .locators import element_at, locator_candidates, parse_bounds, walk

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
                # BGRA bytes are Qt's native 32-bit layout: painting needs no conversion per frame
                bgra = frame.reformat(format="bgra")
                plane = bgra.planes[0]
                images.append(QImage(bytes(plane), bgra.width, bgra.height, plane.line_size,
                                     QImage.Format.Format_RGB32).copy())
        return images

    def feed(self, data):
        try:
            return self._images(self.codec.parse(data))
        except av.error.FFmpegError:
            return []

    def flush(self):
        return self._images([None])


# System UI that is never part of the app under test: status bar, launcher/taskbar, on-screen keyboards.
SYSTEM_IDS = ("com.android.systemui:", "com.android.launcher", "launcher3:", "nexuslauncher:", "inputmethod",
              "honeyboard", "com.touchtype")


def is_system(element):
    return any(s in (element.get("rid") or "") for s in SYSTEM_IDS)


def visible_tree(screen, shared=None):
    """[(element, children)] for the Source panel: system UI left out, and containers folded away when
    nothing locates them (no text, and no id or only a generic one: android:id/..., or shared by many
    elements like Compose's obfuscated ids), so every row is something you can click and locate."""
    if shared is None:
        counts = Counter(e.get("rid") for e in walk(screen) if e.get("rid"))
        shared = {rid for rid, n in counts.items() if n > 1}

    def labelled(e):
        rid = e.get("rid") or ""
        return any(e.get(k) for k in ("txt", "a11y", "hint")) or (
            bool(rid) and rid not in shared and not rid.startswith("android:id/"))
    rows = []
    for element in screen:
        if is_system(element):
            continue
        children = visible_tree(element.get("c", []), shared)
        if labelled(element):
            rows.append((element, children))
        else:
            rows.extend(children)
    return rows


class ActionWorker(QObject):
    """Runs studio steps on its own thread, one at a time in the order they were requested.

    One Maestro session per device: everything that talks to the device goes through here.
    """

    request = Signal(str, dict)       # (kind, keyword arguments for Session.act)
    poll = Signal()                    # refresh the element tree
    recorded = Signal(object)          # the recorded line, or None while recording is off
    failed = Signal(str)
    tree = Signal(dict)
    image = Signal(QImage)             # a screenshot, while there is no live view
    snap = Signal()                    # take one now
    edit = Signal(str)                 # "undo" or "clear"
    edited = Signal()
    done = Signal()                    # a step finished, whatever its outcome

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.screenshot, self.live = None, False
        self.request.connect(self.run)
        self.poll.connect(self.refresh)
        self.snap.connect(self.grab)
        self.edit.connect(self.apply_edit)

    @Slot(str)
    def apply_edit(self, op):
        if op.startswith("remove:"):
            self.session.remove(int(op.split(":", 1)[1]))
        else:
            {"undo": self.session.undo, "clear": self.session.clear}[op]()
        self.edited.emit()

    @Slot(str, dict)
    def run(self, kind, kwargs):
        try:
            self.recorded.emit(self.session.act(kind, **kwargs))
        except Exception as err:       # a refused input or a device failure: nothing was recorded
            self.failed.emit(str(err) or type(err).__name__)
        finally:
            self.refresh()
            if not self.live:
                self.grab()
            self.done.emit()

    @Slot()
    def grab(self):
        if not self.screenshot:
            return
        try:
            self.image.emit(self.screenshot())
        except Exception as err:
            self.failed.emit(f"Screenshot failed: {err}")

    @Slot()
    def refresh(self):
        try:
            self.tree.emit(self.session.tree(fresh=True))
        except Exception as err:
            self.failed.emit(f"Could not read the screen: {err}")


class StreamReader(QThread):
    """Reads a ScrcpyStream on its own thread and decodes it, keeping only the newest frame.

    `ready` fires once per batch of new frames; the UI calls take(). Frames the UI had no time
    to paint are dropped instead of queued, so the view never falls behind the device.
    """

    ready = Signal()
    failed = Signal(str)

    def __init__(self, stream, decoder=None):
        super().__init__()
        self.stream, self.decoder = stream, decoder or FrameDecoder()
        self._stopping = False
        self._lock = threading.Lock()
        self._latest, self._signalled, self.decoded_at = None, False, 0.0

    def take(self):
        """The newest frame (or None), and when it was decoded."""
        with self._lock:
            image, self._latest, self._signalled = self._latest, None, False
            return image, self.decoded_at

    def run(self):
        try:
            self.stream.start()                # about 2 s on a phone: off the UI thread
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as err:
            self.failed.emit(f"No live view ({err}); showing screenshots after each step.")
            return
        for chunk in iter(self.stream.read, b""):
            for image in self.decoder.feed(chunk):
                with self._lock:
                    self._latest, self.decoded_at = image, time.monotonic()
                    signal, self._signalled = not self._signalled, True
                if signal:
                    self.ready.emit()
        if not self._stopping:
            self.failed.emit("The live view ended; showing screenshots after each step.")

    def stop(self):
        self._stopping = True
        self.stream.stop()
        self.wait(5000)


# ---------------------------------------------------------------- the window

# Design tokens: one set of names for both themes, so every widget and painter reads the same palette.
THEMES = {
    "light": {"ground": "#eef0f3", "panel": "#ffffff", "raised": "#f6f7f9", "hover": "#eceff3", "line": "#e1e4ea",
              "ink": "#14171c", "ink2": "#5b6372", "ink3": "#9aa1ad", "accent": "#4361ee", "accent_soft": "#e4e9fd",
              "accent_ink": "#ffffff", "rec": "#e5484d", "rec_soft": "#fde4e5", "ok": "#16a34a", "warn": "#b45309",
              "select": "#4361ee", "screen": "#0b0d10"},
    "dark": {"ground": "#0d0f13", "panel": "#15181e", "raised": "#1b1f27", "hover": "#222733", "line": "#272c37",
             "ink": "#e7e9ee", "ink2": "#9ba3b1", "ink3": "#5f6775", "accent": "#7b93ff", "accent_soft": "#252d4d",
             "accent_ink": "#0d0f13", "rec": "#ff6369", "rec_soft": "#3a1d20", "ok": "#3ecf8e", "warn": "#f5b14c",
             "select": "#7b93ff", "screen": "#000000"},
}
THEME_MODES = ("system", "light", "dark")


def theme_name(app, mode="system"):
    if mode in ("light", "dark"):
        return mode
    try:
        return "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except AttributeError:             # Qt before 6.5
        return "light"


QSS = """
QWidget {{ color: {ink}; font-size: 13px; }}
QMainWindow, QWidget#ground {{ background: {ground}; }}
QFrame#card {{ background: {panel}; border: 1px solid {line}; border-radius: 12px; }}
QToolBar#shell {{ background: {panel}; border: 0; border-bottom: 1px solid {line}; padding: 8px 12px; spacing: 4px; }}
QToolBar#shell QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 6px 10px; color: {ink}; }}
QToolBar#shell QToolButton:hover {{ background: {hover}; }}
QToolBar#shell QToolButton:checked {{ background: {accent_soft}; color: {accent}; font-weight: 600; }}
QToolBar#shell QToolButton:disabled {{ color: {ink3}; }}
QToolBar#shell QToolButton:focus {{ border-color: {accent}; }}
QToolBar#shell QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolBar::separator {{ background: {line}; width: 1px; margin: 4px 8px; }}
QLabel#product {{ font-size: 15px; font-weight: 700; padding-right: 8px; }}
QLabel#state {{ color: {ink2}; padding-right: 6px; }}
QLabel#pane {{ font-size: 12px; font-weight: 700; color: {ink2}; padding: 12px 14px 6px; }}
QLabel#hint {{ color: {ink2}; padding: 6px 12px; }}
QLabel#title {{ font-size: 15px; font-weight: 600; padding: 0 14px 8px; }}
QLabel#title[empty="true"] {{ font-size: 13px; font-weight: 400; color: {ink2}; }}
QLabel#name_label, QLabel#empty {{ color: {ink2}; }}
QPushButton {{ background: {raised}; border: 1px solid {line}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:pressed {{ background: {line}; }}
QPushButton:focus {{ border-color: {accent}; }}
QPushButton:checked {{ background: {rec_soft}; color: {rec}; border-color: {rec}; font-weight: 600; }}
QPushButton#primary {{ background: {accent}; color: {accent_ink}; border-color: {accent}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {select}; }}
QLineEdit {{ background: {raised}; border: 1px solid {line}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {accent_soft}; selection-color: {ink}; }}
QLineEdit:focus {{ border-color: {accent}; background: {panel}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: {panel}; border: 0; outline: 0; gridline-color: transparent; }}
QTableWidget::item, QTreeWidget::item {{ padding: 4px 8px; border: 0; }}
QListWidget::item {{ padding: 6px 10px; border-radius: 6px; margin: 1px 6px; }}
QTableWidget::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {{ background: {hover}; }}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {accent_soft}; color: {ink}; }}
QHeaderView {{ background: {panel}; }}
QHeaderView::section {{ background: {panel}; color: {ink2}; border: 0; border-bottom: 1px solid {line};
    padding: 6px 8px; font-size: 12px; font-weight: 600; }}
QTableCornerButton::section {{ background: {panel}; border: 0; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {line}; border-radius: 4px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {ink3}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: {ground}; }}
QMenu {{ background: {panel}; border: 1px solid {line}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 16px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {ink}; }}
QMenu::item:disabled {{ color: {ink2}; }}
QMenu::separator {{ height: 1px; background: {line}; margin: 4px 8px; }}
QMenu::indicator {{ width: 0; }}
QToolTip {{ background: {raised}; color: {ink}; border: 1px solid {line}; border-radius: 6px; padding: 4px 8px; }}
QStatusBar {{ background: {panel}; border-top: 1px solid {line}; }}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ color: {ink2}; padding: 2px 8px; }}
"""


def apply_theme(app, mode="system"):
    """Fusion (the same on Windows, Linux and macOS) themed from the tokens; mode is system, light or dark."""
    t = dict(THEMES[theme_name(app, mode)])
    app.setStyle("Fusion")
    p = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "ground"), (QPalette.ColorRole.Base, "panel"),
                      (QPalette.ColorRole.AlternateBase, "raised"), (QPalette.ColorRole.Button, "raised"),
                      (QPalette.ColorRole.Text, "ink"), (QPalette.ColorRole.WindowText, "ink"),
                      (QPalette.ColorRole.ButtonText, "ink"), (QPalette.ColorRole.Highlight, "accent"),
                      (QPalette.ColorRole.HighlightedText, "accent_ink"), (QPalette.ColorRole.PlaceholderText, "ink3"),
                      (QPalette.ColorRole.ToolTipBase, "raised"), (QPalette.ColorRole.ToolTipText, "ink")):
        p.setColor(role, QColor(t[key]))
    app.setPalette(p)
    app.setStyleSheet(QSS.format(**t))
    return t


def icon(name, color, on_color=None):
    """Line icons drawn in one stroke weight (no font glyphs); `on_color` draws the checked state."""
    result = QIcon(_icon_pixmap(name, color))
    if on_color:
        result.addPixmap(_icon_pixmap(name, on_color), QIcon.Mode.Normal, QIcon.State.On)
    return result


def _icon_pixmap(name, color):
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    if name == "launch":
        path.moveTo(10, 7); path.lineTo(24, 16); path.lineTo(10, 25); path.closeSubpath()
    elif name == "back":
        path.moveTo(19, 7); path.lineTo(10, 16); path.lineTo(19, 25)
    elif name == "keyboard":
        path.addRoundedRect(5, 8, 22, 13, 2, 2)
        for x in (10, 14.5, 19, 23):
            path.addEllipse(x - 0.6, 12.4, 1.2, 1.2)
        path.moveTo(11, 17.5); path.lineTo(21, 17.5); path.moveTo(13, 25); path.lineTo(16, 27); path.lineTo(19, 25)
    elif name == "camera":
        path.moveTo(5, 11); path.lineTo(10, 11); path.lineTo(12, 8); path.lineTo(20, 8); path.lineTo(22, 11)
        path.lineTo(27, 11); path.lineTo(27, 25); path.lineTo(5, 25); path.closeSubpath(); path.addEllipse(11.5, 12.5, 9, 9)
    elif name == "lock":
        path.addRoundedRect(8, 14, 16, 12, 2, 2); path.moveTo(11, 14); path.lineTo(11, 10)
        path.arcTo(11, 5, 10, 10, 180, -180); path.lineTo(21, 14)
    elif name == "grid":
        path.addRoundedRect(6, 6, 20, 20, 2, 2); path.moveTo(6, 16); path.lineTo(26, 16); path.moveTo(16, 6); path.lineTo(16, 26)
    elif name == "undo":
        path.moveTo(12, 19); path.lineTo(6, 13); path.lineTo(12, 7); path.moveTo(6, 13); path.lineTo(19, 13)
        path.arcTo(13, 13, 12, 12, 90, -180); path.lineTo(15, 25)
    elif name == "clear":
        path.moveTo(6, 10); path.lineTo(26, 10); path.moveTo(12, 10); path.lineTo(12, 6); path.lineTo(20, 6)
        path.lineTo(20, 10); path.moveTo(9, 10); path.lineTo(10, 26); path.lineTo(22, 26); path.lineTo(23, 10)
    elif name == "copy":
        path.addRoundedRect(11, 11, 15, 15, 2, 2); path.moveTo(21, 11); path.lineTo(21, 6); path.lineTo(6, 6)
        path.lineTo(6, 21); path.lineTo(11, 21)
    elif name == "save":
        path.moveTo(7, 6); path.lineTo(21, 6); path.lineTo(26, 11); path.lineTo(26, 26); path.lineTo(7, 26)
        path.closeSubpath(); path.moveTo(11, 6); path.lineTo(11, 12); path.lineTo(20, 12); path.lineTo(20, 6)
    elif name == "inspect":
        path.addEllipse(7, 7, 13, 13); path.moveTo(18, 18); path.lineTo(26, 26)
    elif name == "act":
        path.moveTo(9, 6); path.lineTo(9, 24); path.lineTo(14, 19); path.lineTo(18, 27); path.lineTo(21, 26)
        path.lineTo(17, 18); path.lineTo(24, 18); path.closeSubpath()
    elif name == "record":
        p.setBrush(QColor(color)); path.addEllipse(10, 10, 12, 12)
    elif name == "theme":
        path.addEllipse(7, 7, 18, 18)
        half = QPainterPath(); half.moveTo(16, 7); half.arcTo(7, 7, 18, 18, 90, 180); half.closeSubpath()
        p.fillPath(half, QColor(color))
    p.drawPath(path)
    p.end()
    return pm


def plain_label(text="", name=""):
    """Device text is shown as text, never as HTML."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setOpenExternalLinks(False)
    label.setObjectName(name)
    return label


def first_line(element):
    """A short name for an element: its text, content-desc or hint, else the last part of its id."""
    text = element.get("txt") or element.get("a11y") or element.get("hint") or (element.get("rid") or "").rsplit("/", 1)[-1]
    return text.split("\n")[0]


class DeviceView(QWidget):
    """The device screen: live frames, element boxes, and the gestures that act or inspect."""

    act = Signal(str, dict)             # (kind, keyword arguments) for ActionWorker
    selected = Signal(object)           # an element (Inspect mode), or None
    hovered = Signal(str)

    def __init__(self, theme):
        super().__init__()
        self.t = theme
        self.image, self.tree, self.mode, self.handles, self.secret = None, None, "act", False, False
        self.hover = self.pick = self._down = None
        self.typed, self._flash = "", False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 400)
        self.setAccessibleName("Device screen")

    # state
    def set_frame(self, image):
        self.image = image
        self.update()

    def set_tree(self, tree):
        self.tree = tree
        self.hover = None
        self.update()

    def flash(self):
        self._flash = True
        self.update()
        QTimer.singleShot(450, self._unflash)

    def _unflash(self):
        self._flash = False
        self.update()

    def typing_text(self):
        return "*" * len(self.typed) if self.secret else self.typed

    # geometry
    def _size(self):
        if self.tree:
            return self.tree["width"], self.tree["height"]
        if self.image:
            return self.image.width(), self.image.height()
        return 9, 20

    def frame_rect(self):
        w, h = self._size()
        area = self.rect().adjusted(12, 12, -12, -12)
        scale = min(area.width() / w, area.height() / h)
        fw, fh = w * scale, h * scale
        return QRectF(area.x() + (area.width() - fw) / 2, area.y() + (area.height() - fh) / 2, fw, fh)

    def to_device(self, pos):
        r = self.frame_rect()
        if not r.contains(QPointF(pos)):
            return None
        w, h = self._size()
        return round((pos.x() - r.x()) * w / r.width()), round((pos.y() - r.y()) * h / r.height())

    def _box(self, element):
        b = parse_bounds(element.get("b"))
        if not b:
            return None
        r, (w, h) = self.frame_rect(), self._size()
        sx, sy = r.width() / w, r.height() / h
        return QRectF(r.x() + b[0] * sx, r.y() + b[1] * sy, (b[2] - b[0]) * sx, (b[3] - b[1]) * sy)

    def element_at(self, pos):
        point = self.to_device(pos)
        return element_at(self.tree["elements"], *point) if point and self.tree else None

    # painting
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self.frame_rect()
        frame = QPainterPath()
        frame.addRoundedRect(r, 16, 16)
        p.fillPath(frame, QColor(self.t["screen"]))
        if self.image:
            p.save(); p.setClipPath(frame); p.drawImage(r, self.image); p.restore()
        else:
            p.setPen(QColor("#c9d1d9"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Connecting to the device")
        if self.tree and self.handles:
            p.setPen(QPen(QColor(self.t["select"]), 1))
            for e in self.tree["elements"]:
                if any(e.get(k) for k in ("rid", "txt", "a11y", "hint")):
                    box = self._box(e)
                    if box:
                        p.drawRect(box)
        for element, color, fill in ((self.hover, self.t["select"], 40), (self.pick, self.t["ok"], 40)):
            box = self._box(element) if element else None
            if box:
                c = QColor(color); p.setPen(QPen(c, 2.5)); c.setAlpha(fill); p.fillRect(box, c); p.drawRect(box)
        p.setPen(QPen(QColor(self.t["rec"] if self._flash else self.t["line"]), 4 if self._flash else 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(frame)
        if self.hasFocus():
            p.setPen(QPen(QColor(self.t["select"]), 2, Qt.PenStyle.DashLine))
            p.drawRoundedRect(r.adjusted(-6, -6, 6, 6), 20, 20)
        if self.typed:
            box = QRectF(r.x() + 10, r.bottom() - 54, r.width() - 20, 44)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(self.t["panel"])); p.drawRoundedRect(box, 8, 8)
            p.setPen(QColor(self.t["ink"]))
            p.drawText(box.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                       "Typing: " + self.typing_text() + "   (Enter sends, Esc cancels)")

    # input
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._down = event.position().toPoint()
            self.setFocus()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._down is None:
            return
        start, end, self._down = self._down, event.position().toPoint(), None
        if self.mode == "inspect":
            self.pick = self.element_at(start)
            self.selected.emit(self.pick)
            self.update()
            return
        a, b = self.to_device(start), self.to_device(end)
        if not a:
            return
        self.flush_typing()
        if b and (end - start).manhattanLength() > 30:
            self.act.emit("swipe", {"x": a[0], "y": a[1], "x2": b[0], "y2": b[1]})
        else:
            self.act.emit("click", {"x": a[0], "y": a[1]})

    def mouseMoveEvent(self, event):
        element = self.element_at(event.position().toPoint())
        if element is not self.hover:
            self.hover = element
            self.hovered.emit(first_line(element) if element else "")
            self.update()

    def leaveEvent(self, event):
        self.hover = None
        self.hovered.emit("")
        self.update()

    def contextMenuEvent(self, event):
        point = self.to_device(event.pos())
        if self.mode != "act" or not point:
            return
        element = element_at(self.tree["elements"], *point) if self.tree else None
        menu = QMenu(self)
        title = menu.addAction((first_line(element) or "(no text)").replace("&", "&&") if element
                               else "No locatable element here: a point tap is recorded")
        title.setEnabled(False)
        menu.addSeparator()
        for kind, text in (("long_press", "Long press"), ("wait_visible", "Wait until visible"),
                           ("should_be_visible", "Should be visible")):
            menu.addAction(text).setData(kind)
        box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(8, 4, 8, 4)
        expected = QLineEdit((element.get("txt") or element.get("a11y") or "") if element else "")
        expected.setAccessibleName("Expected text")
        check = QPushButton("Text should be")
        row.addWidget(expected); row.addWidget(check)
        holder = QWidgetAction(menu); holder.setDefaultWidget(box); menu.addAction(holder)
        x, y = point
        check.clicked.connect(lambda: (menu.close(), self.act.emit("text_should_be", {"x": x, "y": y, "text": expected.text()})))
        menu.triggered.connect(lambda action: self.act.emit(action.data(), {"x": x, "y": y}) if action.data() else None)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        if self.mode != "act" or event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                                                      | Qt.KeyboardModifier.MetaModifier):
            return super().keyPressEvent(event)
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.flush_typing()
        elif key == Qt.Key.Key_Escape:
            self.typed = ""
        elif key == Qt.Key.Key_Backspace:
            self.typed = self.typed[:-1]
        elif event.text() and event.text().isprintable():
            self.typed += event.text()
        else:
            return super().keyPressEvent(event)
        self.update()

    def flush_typing(self):
        if self.typed:
            text, self.typed = self.typed, ""
            self.act.emit("type", {"text": text, "secret": self.secret})
            self.update()


PICK_HINT = "Nothing selected. In Inspect mode (Ctrl+2), click an element on the screen or pick one in Source."


def fit(table, max_rows=8):
    """Size a table to its rows (up to max_rows), so empty space does not look like content."""
    rows = min(table.rowCount(), max_rows)
    height = table.horizontalHeader().height() + sum(table.rowHeight(r) for r in range(rows)) + 2 * table.frameWidth()
    table.setFixedHeight(height + 2)


class InspectorPane(QWidget):
    """Source tree and the selected element: suggested locators, attributes, actions."""

    act = Signal(str, dict)
    picked = Signal(object)

    def __init__(self):
        super().__init__()
        self.tree, self.element = None, None
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        layout.addWidget(plain_label("Selected element", "pane"))
        self.title = plain_label(PICK_HINT, "title")
        self.title.setWordWrap(True); self.title.setContentsMargins(10, 0, 10, 6)
        layout.addWidget(self.title)
        self.locators = QTableWidget(0, 2)
        self.locators.setHorizontalHeaderLabels(["Suggested locator (double-click copies)", "Matches"])
        self.attributes = QTableWidget(0, 2)
        self.attributes.setHorizontalHeaderLabels(["Attribute", "Value"])
        for table in (self.locators, self.attributes):
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setWordWrap(True)
        self.attributes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.locators.cellDoubleClicked.connect(lambda r, c: QGuiApplication.clipboard().setText(self.locators.item(r, 0).text()))
        layout.addWidget(self.locators)
        self.actions = QWidget()
        actions = QHBoxLayout(self.actions); actions.setContentsMargins(8, 6, 8, 6)
        for kind, text in (("click", "Tap"), ("long_press", "Long press"), ("wait_visible", "Wait visible"),
                           ("should_be_visible", "Should be visible"), ("text_should_be", "Text should be")):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, k=kind: self._act(k))
            actions.addWidget(button)
        layout.addWidget(self.actions)
        layout.addWidget(self.attributes)
        layout.addWidget(plain_label("Source (system UI and unlabeled containers left out)", "pane"))
        self.source = QTreeWidget()
        self.source.setHeaderLabels(["Element", "Class"])
        self.source.header().setStretchLastSection(False)
        self.source.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.source.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.source.itemClicked.connect(lambda item: self.picked.emit(item.data(0, Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.source, 1)
        self.show_element(None)

    def set_tree(self, tree):
        unchanged = self.tree is not None and tree.get("screen") == self.tree.get("screen")
        self.tree = tree
        if unchanged:                     # rebuilding a large tree every poll stalls the UI
            return
        self.source.setUpdatesEnabled(False)          # one repaint for the whole rebuild
        self.source.blockSignals(True)
        self.source.clear()

        def add(rows, parent):
            for element, children in rows:
                item = QTreeWidgetItem([first_line(element), (element.get("cls") or "").rsplit(".", 1)[-1]])
                item.setData(0, Qt.ItemDataRole.UserRole, element)
                if parent is None:
                    self.source.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                add(children, item)
        add(visible_tree(tree.get("screen", [])), None)
        self.source.expandAll()
        self.source.blockSignals(False)
        self.source.setUpdatesEnabled(True)

    def show_element(self, element):
        self.element = element
        self.locators.setRowCount(0)
        self.attributes.setRowCount(0)
        for widget in (self.locators, self.actions, self.attributes):
            widget.setVisible(element is not None)
        if not element:
            self.title.setText(PICK_HINT)
            self.title.setProperty("empty", True); self.title.style().polish(self.title)
            return
        self.title.setText(first_line(element) or "(no text)")
        self.title.setProperty("empty", False); self.title.style().polish(self.title)
        for locator, count in locator_candidates(element, self.tree["elements"] if self.tree else [element]):
            self._row(self.locators, locator, "unique" if count == 1 else f"{count} matches")
        for key, value in element.items():
            if key != "c":
                self._row(self.attributes, key, str(value))
        for table in (self.locators, self.attributes):
            fit(table)

    @staticmethod
    def _row(table, *texts):
        row = table.rowCount()
        table.insertRow(row)
        for column, text in enumerate(texts):
            table.setItem(row, column, QTableWidgetItem(text))      # items are plain text

    def _act(self, kind):
        if not self.element:
            return
        b = parse_bounds(self.element.get("b"))
        if not b:
            return
        kw = {"x": (b[0] + b[2]) // 2, "y": (b[1] + b[3]) // 2}
        if kind == "text_should_be":
            kw["text"] = self.element.get("txt") or self.element.get("a11y") or ""
        self.act.emit(kind, kw)


class RecorderPane(QWidget):
    """The recorded Robot lines, with Record, Undo, Clear, Copy and Save."""

    edit = Signal(str)                  # "undo" or "clear", run on the worker thread

    def __init__(self, session, theme):
        super().__init__()
        self.session, self.t = session, theme
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        head = QHBoxLayout(); head.setContentsMargins(10, 6, 10, 6)
        head.addWidget(plain_label("Recorded steps", "pane")); head.addStretch()
        self.record_button = QPushButton("Recording")
        self.record_button.setCheckable(True); self.record_button.setChecked(True)
        self.record_button.toggled.connect(self._record)
        self.undo_button = QPushButton("Undo")
        self.undo_button.setToolTip("Removes the last line; the action on the device is not undone")
        self.clear_button = QPushButton("Clear")
        copy = QPushButton("Copy")
        self.undo_button.clicked.connect(lambda: self.edit.emit("undo"))
        self.clear_button.clicked.connect(lambda: self.edit.emit("clear"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.session.robot(self.name.text())))
        for button in (self.record_button, self.undo_button, self.clear_button, copy):
            head.addWidget(button)
        layout.addLayout(head)
        self.lines = QListWidget()
        self.lines.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.lines.setWordWrap(True)
        self.lines.setToolTip("Delete removes the selected line")
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.lines, activated=self._remove_selected)
        layout.addWidget(self.lines, 1)
        self.empty = plain_label("Act on the device: each step becomes a Robot Framework line here.", "empty")
        self.empty.setContentsMargins(10, 6, 10, 6); self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        foot = QHBoxLayout(); foot.setContentsMargins(10, 6, 10, 10)
        foot.addWidget(plain_label("Test name", "name_label"))
        self.name = QLineEdit("Recorded Test")
        foot.addWidget(self.name, 1)
        save = QPushButton("Save...")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        foot.addWidget(save)
        layout.addLayout(foot)
        self.icons = [(self.record_button, "record", "rec"), (self.undo_button, "undo", "ink2"),
                      (self.clear_button, "clear", "ink2"), (copy, "copy", "ink2"), (save, "save", "accent_ink")]
        self.retheme()

    def retheme(self):
        for button, name, key in self.icons:
            button.setIcon(icon(name, self.t[key]))

    def _remove_selected(self):
        row = self.lines.currentRow()
        if row >= 0:
            self.edit.emit(f"remove:{row}")

    def _record(self, on):
        self.session.recording = on
        self.record_button.setText("Recording" if on else "Paused")

    def show_lines(self, lines, stamp=False):
        self.lines.clear()
        for number, line in enumerate(lines, 1):
            item = QListWidgetItem(f"{number:>3}  {line}")
            if "# GAP" in line:
                item.setForeground(QColor(self.t["warn"]))
            self.lines.addItem(item)
        self.empty.setVisible(not lines)
        if stamp and lines:
            last = self.lines.item(self.lines.count() - 1)
            last.setBackground(QColor(self.t["rec_soft"]))
            self.lines.scrollToBottom()
            QTimer.singleShot(700, lambda: last.setBackground(QBrush()) if self.lines.count() else None)

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save the recorded test", "recorded.robot", "Robot Framework (*.robot)")
        if not path:
            return
        if not path.endswith(".robot"):
            path += ".robot"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.session.robot(self.name.text()))
        self.window().statusBar().showMessage(f"Saved {path}", 5000)


ACT_HINT = "Act: click to tap - drag to swipe - type, then Enter - right-click to assert"
INSPECT_HINT = "Inspect: click to select (nothing runs on the device) - Ctrl+1 returns to Act"


def card(widget):
    """A pane on the window's gutter: a rounded panel with a hairline border."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(1, 1, 1, 1)
    layout.addWidget(widget)
    return frame


class MainWindow(QMainWindow):
    def __init__(self, session, worker, device_name="", platform="android", settings=None):
        super().__init__()
        self.session, self.worker, self.platform = session, worker, platform
        self.live, self.pending, self._icons = False, 0, []
        self.settings = settings if settings is not None else QSettings("MaestroLibrary", "Studio")
        mode = self.settings.value("theme", "system")
        self.theme_mode = mode if mode in THEME_MODES else "system"
        self.t = apply_theme(QApplication.instance(), self.theme_mode)
        self.setWindowTitle(f"MaestroLibrary Studio - {device_name} (keep Robot runs off this device while it is open)")
        self.device = DeviceView(self.t)
        self.inspector = InspectorPane()
        self.recorder = RecorderPane(session, self.t)
        self._toolbar(device_name)
        device_pane = QWidget()
        column = QVBoxLayout(device_pane); column.setContentsMargins(0, 0, 0, 8); column.setSpacing(0)
        column.addWidget(self.device, 1)
        self.hint = plain_label(ACT_HINT, "hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        column.addWidget(self.hint)
        device_pane.setMinimumWidth(440)
        split = QSplitter()
        split.setHandleWidth(10)
        for widget, stretch in ((device_pane, 4), (card(self.inspector), 3), (card(self.recorder), 3)):
            split.addWidget(widget)
            split.setStretchFactor(split.count() - 1, stretch)
        split.setSizes([580, 420, 480])                  # the device screen leads
        split.setChildrenCollapsible(False)
        ground = QWidget(); ground.setObjectName("ground")
        outer = QVBoxLayout(ground); outer.setContentsMargins(10, 10, 10, 10)
        outer.addWidget(split)
        self.setCentralWidget(ground)
        self.hover = plain_label("", "hover")
        self.message = plain_label("", "message")
        self.statusBar().addWidget(self.message, 1)
        self.statusBar().addPermanentWidget(self.hover)
        # wiring
        self.device.act.connect(self.submit)
        self.inspector.act.connect(self.submit)
        self.device.selected.connect(self.inspector.show_element)
        self.inspector.picked.connect(self._pick)
        self.device.hovered.connect(self.hover.setText)
        self.recorder.edit.connect(worker.edit)
        worker.edited.connect(lambda: self.recorder.show_lines(self.session.lines))
        worker.recorded.connect(self._recorded)
        worker.failed.connect(self.error)
        worker.tree.connect(self._tree)
        worker.done.connect(self._done)
        worker.image.connect(self.device.set_frame)
        self.poll = QTimer(self)
        self.poll.timeout.connect(lambda: worker.poll.emit() if not self.pending else None)
        self.poll.start(5000)                 # each read waits for the screen to settle (up to 3 s)
        self.recorder.show_lines(session.lines)
        for keys, slot in (("Ctrl+1", self.act_mode.trigger), ("Ctrl+2", self.inspect_mode.trigger),
                           ("Ctrl+Z", lambda: worker.edit.emit("undo")), ("Ctrl+S", self.recorder.save)):
            QShortcut(QKeySequence(keys), self, activated=slot)

    def _toolbar(self, device_name):
        bar = QToolBar("Studio"); bar.setObjectName("shell"); bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.setIconSize(QSize(16, 16))
        self.addToolBar(bar)
        bar.addWidget(plain_label("MaestroLibrary Studio", "product"))
        self.dot = plain_label("", "dot")
        bar.addWidget(self.dot)
        self.state = plain_label(f"{device_name}: connecting", "state")
        bar.addWidget(self.state)
        self._dot("ink3")
        bar.addSeparator()
        modes = QActionGroup(self); modes.setExclusive(True)
        self.act_mode = self._iconed(QAction("Act", self, checkable=True, checked=True), "act")
        self.act_mode.setToolTip("Click, drag and type act on the device and are recorded")
        self.inspect_mode = self._iconed(QAction("Inspect", self, checkable=True), "inspect")
        self.inspect_mode.setToolTip("Click selects an element; nothing runs on the device")
        for action, mode in ((self.act_mode, "act"), (self.inspect_mode, "inspect")):
            modes.addAction(action); bar.addAction(action)
            action.triggered.connect(lambda _=False, m=mode: self._mode(m))
        self.handles = self._iconed(QAction("Elements", self, checkable=True), "grid")
        self.handles.setToolTip("Outline every element a locator can find")
        self.handles.toggled.connect(lambda on: (setattr(self.device, "handles", on), self.device.update()))
        bar.addAction(self.handles)
        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        for kind, name, text, tip in (("launch", "launch", "Launch", "Open Application (restarts the app)"),
                                      ("back", "back", "Back", "Go Back (Android)"),
                                      ("hide_keyboard", "keyboard", "Keyboard", "Hide Keyboard"),
                                      ("screenshot", "camera", "Screenshot", "Capture Page Screenshot")):
            action = self._iconed(QAction(text, self), name)
            action.setToolTip(tip)
            action.triggered.connect(lambda _=False, k=kind: (self.device.flush_typing(), self.submit(k, {})))
            action.setEnabled(not (kind == "back" and self.platform == "ios"))
            bar.addAction(action)
        self.secret = self._iconed(QAction("Secret", self, checkable=True), "lock")
        self.secret.setToolTip("Typed text is recorded as ${PASSWORD} and never shown")
        self.secret.toggled.connect(lambda on: (setattr(self.device, "secret", on), self.device.update()))
        bar.addAction(self.secret)
        bar.addSeparator()
        themes = QMenu("Theme", self)
        group = QActionGroup(self); group.setExclusive(True)
        self.theme_actions = {}
        for mode in THEME_MODES:
            action = themes.addAction(mode.capitalize())
            action.setCheckable(True); action.setChecked(mode == self.theme_mode)
            action.triggered.connect(lambda _=False, m=mode: self.set_theme(m))
            group.addAction(action)
            self.theme_actions[mode] = action
        self.theme_button = QToolButton()
        self.theme_button.setText("Theme")
        self.theme_button.setToolTip("Theme: follow the system, or always light or dark")
        self.theme_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.theme_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.theme_button.setMenu(themes)
        self._iconed(self.theme_button, "theme")
        bar.addWidget(self.theme_button)

    def _mode(self, mode):
        self.hint.setText(ACT_HINT if mode == "act" else INSPECT_HINT)
        self.device.mode = mode
        self.device.pick = None
        self.device.update()

    def _pick(self, element):
        self.device.pick = element
        self.device.update()
        self.inspector.show_element(element)

    def submit(self, kind, kwargs):
        self.pending += 1
        self.message.setText(f"Running {self.pending} step{'s' if self.pending > 1 else ''}")
        self.worker.request.emit(kind, kwargs)

    def _recorded(self, line):
        self.recorder.show_lines(self.session.lines, stamp=line is not None)
        if line is not None:
            self.device.flash()
        self.message.setStyleSheet("")
        self.message.setText("Recorded" if line is not None else "Ran (recording is paused)")

    def _tree(self, tree):
        self.device.set_tree(tree)
        self.inspector.set_tree(tree)

    def _done(self):
        self.pending = max(0, self.pending - 1)

    def error(self, text):
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {self.t['rec']};")       # stays until the next step works

    def _iconed(self, target, name, key="ink2"):
        """Gives an action or button a theme-following icon whose checked state uses the accent."""
        self._icons.append((target, name, key))
        target.setIcon(icon(name, self.t[key], self.t["accent"]))
        return target

    def set_theme(self, mode):
        """System, light or dark; applied at once and remembered for the next start."""
        self.theme_mode = mode
        self.settings.setValue("theme", mode)
        self.t.clear()
        self.t.update(apply_theme(QApplication.instance(), mode))      # the panes share this dict
        for target, name, key in self._icons:
            target.setIcon(icon(name, self.t[key], self.t["accent"]))
        self.theme_actions[mode].setChecked(True)
        self.recorder.retheme()
        self.recorder.show_lines(self.session.lines)
        self._dot("ok" if self.live else "ink3")
        self.device.update()

    def _dot(self, key):
        self.dot.setPixmap(icon("record", self.t[key]).pixmap(14, 14))

    def show_newest(self, reader):
        image, _ = reader.take()
        if image is not None:
            self.go_live(image)

    def go_live(self, image):
        if not self.live:
            self.live = self.worker.live = True
            self._dot("ok")
            self.state.setText(self.state.text().split(":")[0] + ": live")
        self.device.set_frame(image)

    def fallback(self, reason):
        self.live = self.worker.live = False
        self._dot("warn")
        self.state.setText(self.state.text().split(":")[0] + ": screenshots")
        self.state.setToolTip(html.escape(reason))      # tooltips detect rich text: keep it plain
        self.error(reason)
        self.worker.snap.emit()
