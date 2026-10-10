"""The Studio window (PySide6): live device screen, inspector and recorder. Needs the `studio` extra."""
import html
import os
import tempfile
from collections import Counter
import subprocess
import threading
import time

import av
from PySide6.QtCore import QByteArray, QObject, QPointF, QRectF, QSettings, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFontDatabase, QGuiApplication, QIcon, QIconEngine, QImage,
                           QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap, QShortcut)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QGraphicsDropShadowEffect,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QPushButton, QSizePolicy, QSplitter, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QToolBar, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetAction)

from .locators import element_at, locator_candidates, parse_bounds, walk
from .studio_icons import ICONS

# Qt draws an icon and its label about 4 px apart and has no style setting for it: one space doubles it.
GAP_SPACE = " "
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
    "light": {"ground": "#e9ecf1", "panel": "#ffffff", "raised": "#f4f6f9", "hover": "#eceff4", "line": "#d6dae3",
              "ink": "#14171c", "ink2": "#566070", "ink3": "#9097a5", "accent": "#4361ee", "accent_soft": "#e4e9fd",
              "accent_ink": "#ffffff", "rec": "#e5484d", "rec_soft": "#fde4e5", "ok": "#15803d", "ok_soft": "#dcf5e5",
              "warn": "#b45309", "warn_soft": "#fdebd0", "select": "#4361ee", "screen": "#0b0d10", "shadow_alpha": 70, "shadow_blur": 28, "shadow_y": 6, "edge": "#d6dae3"},
    "dark": {"ground": "#050608", "panel": "#181c24", "raised": "#20252f", "hover": "#2a303c", "line": "#303746",
             "ink": "#eef0f4", "ink2": "#b7bfcc", "ink3": "#858e9e", "accent": "#7b93ff", "accent_soft": "#252d4d",
             "accent_ink": "#0d0f13", "rec": "#ff6369", "rec_soft": "#3a1d20", "ok": "#3ecf8e", "ok_soft": "#16342a",
             "warn": "#f5b14c", "warn_soft": "#3b2d14", "select": "#7b93ff", "screen": "#000000", "shadow_alpha": 230, "shadow_blur": 44, "shadow_y": 12, "edge": "#3d4555"},
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
QFrame#card {{ background: {panel}; border: 1px solid {line}; border-top-color: {edge}; border-radius: 14px; }}
QToolBar#shell {{ background: {panel}; border: 0; border-bottom: 1px solid {line}; padding: 10px 16px; spacing: 4px; }}
QToolBar#shell QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 6px 10px; color: {ink}; }}
QToolBar#shell QToolButton:hover {{ background: {hover}; }}
QToolBar#shell QToolButton:checked {{ background: {accent_soft}; color: {accent}; }}
QToolBar#shell QToolButton:disabled {{ color: {ink3}; }}
QToolBar#shell QToolButton:focus {{ border-color: {accent}; }}
QToolBar#shell QToolButton::menu-indicator {{ image: none; width: 0px; }}
QToolBar#shell QToolButton[popupMode="2"] {{ padding-right: 10px; }}
QToolBar::separator {{ background: {line}; width: 1px; margin: 6px 8px; }}
QFrame#seg {{ background: {raised}; border: 1px solid {line}; border-radius: 11px; }}
QToolBar#shell QFrame#seg QToolButton {{ border-radius: 8px; padding: 5px 14px; }}
QToolBar#shell QFrame#seg QToolButton:hover {{ background: {hover}; }}
QToolBar#shell QFrame#seg QToolButton:checked {{ background: {accent}; color: {accent_ink}; }}
QFrame#pill {{ background: {raised}; border: 1px solid {line}; border-radius: 14px; }}
QFrame#pill QLabel {{ background: transparent; }}
QLabel#product {{ font-size: 16px; font-weight: 700; padding-right: 8px; }}
QLabel#state {{ color: {ink}; }}
QLabel#pane {{ font-size: 12px; font-weight: 600; color: {ink2}; }}
QLabel#hint {{ background: {panel}; border: 1px solid {line}; border-radius: 14px; color: {ink2};
    padding: 6px 14px; }}
QLabel#title {{ font-size: 15px; font-weight: 600; }}
QLabel#title[empty="true"] {{ font-size: 13px; font-weight: 400; color: {ink2}; }}
QLabel#empty {{ color: {ink2}; }}
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
QLineEdit#testname {{ background: transparent; border: 1px solid transparent; font-size: 16px; font-weight: 600;
    padding: 6px 8px; }}
QLineEdit#testname:hover {{ border-color: {line}; }}
QLineEdit#testname:focus {{ border-color: {accent}; background: {raised}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: transparent; border: 0; outline: 0; gridline-color: transparent; }}
QTableWidget::item, QListWidget::item {{ padding: 4px 8px; border: 0; border-radius: 6px; }}
QTableWidget::item:hover {{ background: {hover}; }}
QTableWidget::item:selected {{ background: {accent_soft}; color: {ink}; }}
QTreeView {{ show-decoration-selected: 1; }}
QTreeView::item {{ padding: 4px 8px 4px 6px; border: 0; }}
QTreeView::item:selected, QTreeView::item:selected:active, QTreeView::item:selected:!active {{ background: {accent_soft}; color: {ink}; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:hover {{ background: transparent; }}
QTreeView::branch:selected {{ background: {accent_soft}; }}
QTreeView::branch:closed:has-children {{ image: url({chevron_right}); }}
QTreeView::branch:open:has-children {{ image: url({chevron_down}); }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {ink2}; border: 0; border-bottom: 1px solid {line};
    padding: 6px 8px; font-size: 12px; font-weight: 600; }}
QTableCornerButton::section {{ background: transparent; border: 0; }}
QScrollBar:vertical {{ background: transparent; border: 0; width: 8px; margin: 6px 2px; }}
QScrollBar:horizontal {{ background: transparent; border: 0; height: 8px; margin: 2px 6px; }}
QScrollBar::handle {{ background: {line}; border-radius: 4px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {ink3}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; border: 0; background: none;
    subcontrol-origin: margin; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: transparent; }}
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
    app.setStyleSheet(QSS.format(**t, **chevrons(t["ink2"])))
    return t


ICON_SIZE = QSize(16, 16)              # square icons only; the icon-text gap is the stylesheet's padding
ICON_NAMES = {"act": "mouse-pointer-click", "inspect": "scan-search", "grid": "scan", "launch": "play",
              "back": "arrow-left", "keyboard": "keyboard", "camera": "camera", "lock": "lock", "theme": "sun-moon",
              "record": "circle-dot", "undo": "undo-2", "clear": "trash-2", "copy": "copy", "save": "save",
              "device": "smartphone", "chevron-right": "chevron-right", "chevron-down": "chevron-down"}


def svg_bytes(name, color, opacity=1.0, pixels=24):
    """The icon's SVG; `pixels` is the physical size it is drawn at, so the stroke can land on whole pixels."""
    # Lucide strokes are 2 units on a 24-unit grid: 1.67 px at 20 px (16 px at 125%), which anti-aliasing
    # smears over two pixels. Round the stroke to whole device pixels instead.
    width = max(1, round(2 * pixels / 24)) * 24 / pixels
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-opacity="%s" '
            'stroke-width="%.3f" stroke-linecap="round" stroke-linejoin="round">%s</svg>'
            % (QColor(color).name(), opacity, width, ICONS[ICON_NAMES.get(name, name)])).encode()


class SvgIconEngine(QIconEngine):
    """Lucide icons drawn from the SVG at exactly the size and pixel ratio asked for, so they are always sharp."""

    def __init__(self, name, color, on_color=None):
        super().__init__()
        self.name, self.color, self.on_color = name, color, on_color

    def paint(self, painter, rect, mode, state):
        color = self.on_color if state == QIcon.State.On and self.on_color else self.color
        side = min(rect.width(), rect.height())
        ratio = painter.device().devicePixelRatioF() if painter.device() else 1.0
        renderer = QSvgRenderer(QByteArray(svg_bytes(self.name, color, 0.4 if mode == QIcon.Mode.Disabled else 1.0,
                                                     side * ratio)))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2,
                                        side, side))
        painter.restore()

    def pixmap(self, size, mode, state):
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        self.paint(painter, pm.rect(), mode, state)
        painter.end()
        return pm

    def clone(self):
        return SvgIconEngine(self.name, self.color, self.on_color)


def icon(name, color, on_color=None):
    """Lucide outline icons (studio_icons) drawn in `color`; `on_color` draws the checked state."""
    return QIcon(SvgIconEngine(name, color, on_color))


def chevrons(color):
    """Paths of chevron PNGs (plus @2x) in a temp folder, for the tree's branch arrows in the stylesheet."""
    folder = os.path.join(tempfile.gettempdir(), "maestrolibrary-studio")
    os.makedirs(folder, exist_ok=True)
    paths = {}
    for name in ("chevron-right", "chevron-down"):
        base = os.path.join(folder, "%s-%s" % (name, QColor(color).name()[1:]))
        for suffix, side in (("", 16), ("@2x", 32)):
            image = QImage(side, side, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            QSvgRenderer(QByteArray(svg_bytes(name, color))).render(painter, QRectF(0, 0, side, side))
            painter.end()
            image.save(base + suffix + ".png")
        paths[name.replace("-", "_")] = (base + ".png").replace("\\", "/")
    return paths


def dot_pixmap(color, size=10):
    """A filled status dot, antialiased at the screen's pixel ratio."""
    screen = QGuiApplication.primaryScreen()
    ratio = max(2.0, screen.devicePixelRatio() if screen else 2.0)
    pm = QPixmap(round(size * ratio), round(size * ratio))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(0, 0, size * ratio, size * ratio))
    p.end()
    pm.setDevicePixelRatio(ratio)
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
        for element, width, line, fill in ((self.hover, 1, 120, 16), (self.pick, 2, 255, 28)):
            box = self._box(element) if element else None
            if box:
                c = QColor(self.t["select"]); c.setAlpha(fill); p.setBrush(c)
                c.setAlpha(line); p.setPen(QPen(c, width))
                p.drawRoundedRect(box.adjusted(width / 2, width / 2, -width / 2, -width / 2), 6, 6)
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


def paint_background(painter, option, widget):
    """The style's own hover and selection background (rounded by the stylesheet), without its text."""
    opt = QStyleOptionViewItem(option)
    opt.text = ""
    opt.icon = QIcon()
    (widget.style() if widget else QApplication.style()).drawControl(QStyle.ControlElement.CE_ItemViewItem, opt,
                                                                     painter, widget)


class MatchDelegate(QStyledItemDelegate):
    """The Matches column: 'unique' as a small green pill, 'N matches' as an amber one. The text stays the item's."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.t = theme

    def paint(self, painter, option, index):
        paint_background(painter, option, option.widget)
        text = index.data() or ""
        fg, bg = (self.t["ok"], self.t["ok_soft"]) if text == "unique" else (self.t["warn"], self.t["warn_soft"])
        font = QFont(option.font)
        font.setPixelSize(12); font.setWeight(QFont.Weight.DemiBold)
        width = QFontMetrics(font).horizontalAdvance(text) + 20
        pill = QRectF(option.rect.left() + 4, 0, width, 22)
        pill.moveCenter(QPointF(pill.center().x(), option.rect.center().y()))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(pill, 11, 11)
        painter.setPen(QColor(fg)); painter.setFont(font)
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width() + 16, max(size.height(), 32))


class LineDelegate(QStyledItemDelegate):
    """A recorded line like Maestro's editor: number gutter, keyword, locator and other arguments in colours.

    The item's text is '<n>  <robot line>'; it is parsed here for painting only."""

    GUTTER = 40

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.t = theme

    def _parts(self, index):
        text = index.data() or ""
        number, line = text[:3].strip(), text[5:]
        return number, line

    def _runs(self, line):
        t = self.t
        parts = line.split("    ")
        runs = [(parts[0], t["warn"] if parts[0].startswith("#") else t["accent"], True)]
        for arg in parts[1:]:
            if arg:
                runs.append((arg, t["warn"] if arg.startswith("#") else t["ok"] if "\\=" in arg else t["ink"], False))
        return runs

    def _flow(self, line, font, width):
        """[(word, colour, bold, x, row)] with the runs wrapped to `width`, and the number of rows."""
        words, x, row = [], 0, 0
        for text, color, bold in self._runs(line):
            f = QFont(font)
            f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
            metrics = QFontMetrics(f)
            space = metrics.horizontalAdvance(" ")
            for word in text.split(" "):
                w = metrics.horizontalAdvance(word)
                if x and x + w > width:
                    x, row = 0, row + 1
                words.append((word, color, bold, x, row))
                x += w + space
            x += 3 * space                  # runs are four spaces apart
        return words, row + 1

    def _width(self, option, widget_width):
        return max(120, widget_width - 12 - self.GUTTER - 4 - 8)

    def paint(self, painter, option, index):
        number, line = self._parts(index)
        t = self.t
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(option.rect).adjusted(6, 1, -6, -1)
        state = option.state
        fill = index.data(Qt.ItemDataRole.BackgroundRole)
        if state & QStyle.StateFlag.State_Selected:
            fill = QColor(t["accent_soft"])
        elif isinstance(fill, QBrush) and fill.style() != Qt.BrushStyle.NoBrush:
            fill = fill.color()
        elif state & QStyle.StateFlag.State_MouseOver:
            fill = QColor(t["hover"])
        else:
            fill = None
        if fill is not None:
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(fill)
            painter.drawRoundedRect(box, 6, 6)
        height = QFontMetrics(option.font).height()
        mid = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
        painter.setFont(option.font)
        painter.setPen(QColor(t["ink3"]))
        painter.drawText(QRectF(box.left(), box.top(), self.GUTTER - 8, 28), Qt.AlignmentFlag.AlignRight | mid, number)
        words, rows = self._flow(line, option.font, int(box.width() - self.GUTTER - 4 - 8))
        top = box.top() + (box.height() - rows * height) / 2
        for word, color, bold, x, row in words:
            font = QFont(option.font)
            font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(QColor(color))
            painter.drawText(QRectF(box.left() + self.GUTTER + 4 + x, top + row * height,
                                    QFontMetrics(font).horizontalAdvance(word) + 2, height), mid, word)
        painter.restore()

    def sizeHint(self, option, index):
        number, line = self._parts(index)
        view = option.widget.viewport().width() if option.widget else 480
        height = QFontMetrics(option.font).height()
        _, rows = self._flow(line, option.font, self._width(option, view))
        return QSize(view, max(rows * height + 14, 30))


class InspectorPane(QWidget):
    """Source tree and the selected element: suggested locators, attributes, actions."""

    act = Signal(str, dict)
    picked = Signal(object)

    def __init__(self, theme=None):
        super().__init__()
        self.tree, self.element = None, None
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 12, 12, 8); layout.setSpacing(8)
        layout.addWidget(plain_label("Selected element", "pane"))
        self.title = plain_label(PICK_HINT, "title")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.locators = QTableWidget(0, 2)
        self.locators.setHorizontalHeaderLabels(["Suggested locator (double-click copies)", "Matches"])
        self.locators.setItemDelegateForColumn(1, MatchDelegate(theme or THEMES["light"], self.locators))
        self.attributes = QTableWidget(0, 2)
        self.attributes.setHorizontalHeaderLabels(["Attribute", "Value"])
        for table in (self.locators, self.attributes):
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setDefaultSectionSize(32)
            table.setShowGrid(False)
            table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            table.setFrameShape(QFrame.Shape.NoFrame)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setWordWrap(True)
        self.attributes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.locators.cellDoubleClicked.connect(lambda r, c: QGuiApplication.clipboard().setText(self.locators.item(r, 0).text()))
        layout.addWidget(self.locators)
        self.actions = QWidget()
        actions = QGridLayout(self.actions); actions.setContentsMargins(0, 0, 0, 0)
        actions.setHorizontalSpacing(8); actions.setVerticalSpacing(8)
        for number, (kind, text) in enumerate((("click", "Tap"), ("long_press", "Long press"),
                                               ("wait_visible", "Wait visible"),
                                               ("should_be_visible", "Should be visible"),
                                               ("text_should_be", "Text should be"))):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, k=kind: self._act(k))
            actions.addWidget(button, number // 3, number % 3)
        layout.addWidget(self.actions)
        layout.addWidget(self.attributes)
        layout.addWidget(plain_label("Source (system UI and unlabeled containers left out)", "pane"))
        self.source = QTreeWidget()
        self.source.setFrameShape(QFrame.Shape.NoFrame)
        self.source.setHeaderLabels(["Element", "Class"])
        self.source.setIndentation(16)
        self.source.header().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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
    """The recorded Robot lines under an editable test title, with Record, Undo, Clear, Copy and Save."""

    edit = Signal(str)                  # "undo" or "clear", run on the worker thread

    def __init__(self, session, theme):
        super().__init__()
        self.session, self.t = session, theme
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(8)
        self.name = QLineEdit("Recorded Test")
        self.name.setObjectName("testname")
        self.name.setPlaceholderText("Untitled test")
        self.name.setAccessibleName("Test name")
        layout.addWidget(self.name)
        head = QHBoxLayout(); head.setSpacing(8); head.setContentsMargins(9, 0, 0, 0)
        head.addWidget(plain_label("Recorded steps", "pane")); head.addStretch()
        self.record_button = QPushButton(GAP_SPACE + "Recording")
        self.record_button.setCheckable(True); self.record_button.setChecked(True)
        self.record_button.toggled.connect(self._record)
        self.undo_button = QPushButton(GAP_SPACE + "Undo")
        self.undo_button.setToolTip("Removes the last line; the action on the device is not undone")
        self.clear_button = QPushButton(GAP_SPACE + "Clear")
        self.undo_button.clicked.connect(lambda: self.edit.emit("undo"))
        self.clear_button.clicked.connect(lambda: self.edit.emit("clear"))
        for button in (self.record_button, self.undo_button, self.clear_button):
            head.addWidget(button)
        layout.addLayout(head)
        self.lines = QListWidget()
        self.lines.setFrameShape(QFrame.Shape.NoFrame)
        self.lines.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.lines.setItemDelegate(LineDelegate(theme, self.lines))
        self.lines.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lines.setResizeMode(QListWidget.ResizeMode.Adjust)          # long lines re-wrap on resize
        self.lines.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.lines.setMouseTracking(True)
        self.lines.setToolTip("Delete removes the selected line")
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.lines, activated=self._remove_selected)
        layout.addWidget(self.lines, 1)
        self.empty = plain_label("Act on the device: each step becomes a Robot Framework line here.", "empty")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        foot = QHBoxLayout(); foot.setSpacing(8)
        foot.addStretch()
        self.copy_button = QPushButton(GAP_SPACE + "Copy")
        self.copy_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.session.robot(self.name.text())))
        save = QPushButton(GAP_SPACE + "Save")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        foot.addWidget(self.copy_button); foot.addWidget(save)
        layout.addLayout(foot)
        self.icons = [(self.record_button, "record", "rec"), (self.undo_button, "undo", "ink"),
                      (self.clear_button, "clear", "ink"), (self.copy_button, "copy", "ink"),
                      (save, "save", "accent_ink")]
        for button, _, _ in self.icons:
            button.setIconSize(ICON_SIZE)
        self.retheme()

    def retheme(self):
        for button, name, key in self.icons:
            button.setIcon(icon(name, self.t[key]))
        self.lines.viewport().update()

    def _remove_selected(self):
        row = self.lines.currentRow()
        if row >= 0:
            self.edit.emit(f"remove:{row}")

    def _record(self, on):
        self.session.recording = on
        self.record_button.setText(GAP_SPACE + ("Recording" if on else "Paused"))

    def show_lines(self, lines, stamp=False):
        self.lines.clear()
        for number, line in enumerate(lines, 1):
            item = QListWidgetItem(f"{number:>3}  {line}")
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


def card(widget, theme):
    """A pane on the window's ground: a rounded panel with a hairline border and a soft drop shadow.

    The pane is inset by the corner radius' worth of margin, so its square widgets never cover the rounded corners."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.addWidget(widget)
    effect = QGraphicsDropShadowEffect(frame)
    effect.setBlurRadius(28)
    effect.setOffset(0, 6)
    frame.setGraphicsEffect(effect)
    shade(frame, theme)
    return frame


def shade(frame, theme):
    effect = frame.graphicsEffect()
    effect.setColor(QColor(0, 0, 0, theme["shadow_alpha"]))
    effect.setBlurRadius(theme["shadow_blur"])      # dark needs a wider, deeper shadow to show on a dark ground
    effect.setOffset(0, theme["shadow_y"])


class MainWindow(QMainWindow):
    def __init__(self, session, worker, device_name="", platform="android", settings=None):
        super().__init__()
        self.session, self.worker, self.platform = session, worker, platform
        self.live, self.pending, self._icons, self._cards = False, 0, [], []
        self.settings = settings if settings is not None else QSettings("MaestroLibrary", "Studio")
        mode = self.settings.value("theme", "system")
        self.theme_mode = mode if mode in THEME_MODES else "system"
        self.t = apply_theme(QApplication.instance(), self.theme_mode)
        self.setWindowTitle(f"MaestroLibrary Studio - {device_name} (keep Robot runs off this device while it is open)")
        self.device = DeviceView(self.t)
        self.inspector = InspectorPane(self.t)
        self.recorder = RecorderPane(session, self.t)
        self._toolbar(device_name)
        device_pane = QWidget()
        column = QVBoxLayout(device_pane); column.setContentsMargins(0, 0, 0, 0); column.setSpacing(8)
        column.addWidget(self.device, 1)
        self.hint = plain_label(ACT_HINT, "hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        chip = QHBoxLayout()                # a chip as wide as its text, centred under the phone
        chip.addStretch(); chip.addWidget(self.hint); chip.addStretch()
        column.addLayout(chip)
        device_pane.setMinimumWidth(440)
        split = QSplitter()
        split.setHandleWidth(16)
        self._cards = [card(self.inspector, self.t), card(self.recorder, self.t)]
        for widget, stretch in ((device_pane, 4), (self._cards[0], 3), (self._cards[1], 3)):
            split.addWidget(widget)
            split.setStretchFactor(split.count() - 1, stretch)
        split.setSizes([580, 420, 480])                  # the device screen leads
        split.setChildrenCollapsible(False)
        ground = QWidget(); ground.setObjectName("ground")
        outer = QVBoxLayout(ground); outer.setContentsMargins(16, 16, 16, 16)
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
        self.device.setFocus()                # typing goes to the phone; no toolbar button starts focused
        for keys, slot in (("Ctrl+1", self.act_mode.trigger), ("Ctrl+2", self.inspect_mode.trigger),
                           ("Ctrl+Z", lambda: worker.edit.emit("undo")), ("Ctrl+S", self.recorder.save)):
            QShortcut(QKeySequence(keys), self, activated=slot)

    def _toolbar(self, device_name):
        bar = QToolBar("Studio"); bar.setObjectName("shell"); bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.setIconSize(ICON_SIZE)
        self.addToolBar(bar)
        gap = lambda: bar.addWidget(self._gap())
        bar.addWidget(plain_label("MaestroLibrary Studio", "product"))
        gap()
        pill = QFrame(); pill.setObjectName("pill")
        row = QHBoxLayout(pill); row.setContentsMargins(10, 4, 12, 4); row.setSpacing(6)
        self.device_icon = plain_label("", "device_icon")
        self.dot = plain_label("", "dot")
        self.state = plain_label(f"{device_name}: connecting", "state")
        for widget in (self.device_icon, self.dot, self.state):
            row.addWidget(widget)
        bar.addWidget(pill)
        gap()
        self._dot("ink3")
        modes = QActionGroup(self); modes.setExclusive(True)
        self.act_mode = self._iconed(QAction("Act", self, checkable=True, checked=True), "act", on="accent_ink")
        self.act_mode.setToolTip("Click, drag and type act on the device and are recorded")
        self.inspect_mode = self._iconed(QAction("Inspect", self, checkable=True), "inspect", on="accent_ink")
        self.inspect_mode.setToolTip("Click selects an element; nothing runs on the device")
        seg = QFrame(); seg.setObjectName("seg")
        segment = QHBoxLayout(seg); segment.setContentsMargins(3, 3, 3, 3); segment.setSpacing(2)
        for action, mode in ((self.act_mode, "act"), (self.inspect_mode, "inspect")):
            modes.addAction(action)
            button = QToolButton(); button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); button.setIconSize(ICON_SIZE)
            button.setAutoRaise(True)
            segment.addWidget(button)
            action.triggered.connect(lambda _=False, m=mode: self._mode(m))
        bar.addWidget(seg)
        gap()
        self.handles = self._iconed(QAction("Elements", self, checkable=True), "grid")
        self.handles.setToolTip("Outline every element a locator can find")
        self.handles.toggled.connect(lambda on: (setattr(self.device, "handles", on), self.device.update()))
        bar.addAction(self.handles)
        spacer = self._gap(16); spacer.setMaximumWidth(16777215)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
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
        theme = self._iconed(QAction("Theme", self), "theme")
        theme.setToolTip("Theme: follow the system, or always light or dark")
        theme.setMenu(themes)
        bar.addAction(theme)
        self.theme_button = bar.widgetForAction(theme)           # a toolbar button like the others
        self.theme_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.theme_button.setAutoRaise(True)

    @staticmethod
    def _gap(width=8):
        """Blank space between toolbar groups (the toolbar's own spacing is added on both sides)."""
        spacer = QWidget(); spacer.setFixedWidth(width)
        return spacer

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

    def _iconed(self, target, name, key="ink", on="accent"):
        """Gives an action or button a theme-following icon whose checked state uses `on` (the accent)."""
        self._icons.append((target, name, key, on))
        target.setIcon(icon(name, self.t[key], self.t[on]))
        if isinstance(target, QAction) and target.text():
            target.setIconText(GAP_SPACE + target.text())    # Qt has no QSS gap between icon and text
        return target

    def set_theme(self, mode):
        """System, light or dark; applied at once and remembered for the next start."""
        self.theme_mode = mode
        self.settings.setValue("theme", mode)
        self.t.update(apply_theme(QApplication.instance(), mode))      # the panes share this dict
        for target, name, key, on in self._icons:
            target.setIcon(icon(name, self.t[key], self.t[on]))
        for frame in self._cards:
            shade(frame, self.t)
        self.theme_actions[mode].setChecked(True)
        self.recorder.retheme()
        self.recorder.show_lines(self.session.lines)
        self._dot("ok" if self.live else "ink3")
        self.device.update()

    def _dot(self, key):
        self.dot.setPixmap(dot_pixmap(self.t[key]))
        self.device_icon.setPixmap(icon("device", self.t["ink"]).pixmap(ICON_SIZE, self.devicePixelRatioF()))

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
