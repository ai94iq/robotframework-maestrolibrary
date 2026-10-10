# PyInstaller spec for the Studio desktop bundles:
#     STUDIO_FFMPEG=<prefix from build_ffmpeg.py> pyinstaller --noconfirm packaging/studio.spec
# Windows: one MaestroLibrary-Studio.exe. Linux: a MaestroLibrary-Studio folder (tarred by CI).
# macOS: MaestroLibrary-Studio.app (put in a .dmg by CI). Licenses of everything shipped go in licenses/.
import importlib.metadata
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.dirname(SPECPATH)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import MaestroLibrary  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from MaestroLibrary.studio_qt import app_icon  # noqa: E402

NAME = "MaestroLibrary-Studio"
qt = QGuiApplication.instance() or QGuiApplication([])
ICON = os.path.join(workpath, "studio.png")   # PyInstaller makes the .ico or .icns from it (needs Pillow)
os.makedirs(workpath, exist_ok=True)
app_icon().pixmap(256, 256).save(ICON)

# Every license of what ships: the packages' own files, Qt's LGPL (PySide6 wheels carry no text), FFmpeg's.
LICENSED = ("PySide6_Essentials", "shiboken6", "av", "grpcio", "typing_extensions", "robotframework",
            "robotframework-pythonlibcore")
licenses = [(os.path.join(ROOT, "LICENSE"), "licenses/robotframework-maestrolibrary"),
            (os.path.join(SPECPATH, "licenses", "LGPL-3.0.txt"), "licenses/Qt-PySide6"),
            (os.path.join(SPECPATH, "licenses", "GPL-3.0.txt"), "licenses/Qt-PySide6")]
for dist in LICENSED:
    for file in importlib.metadata.distribution(dist).files or []:
        if any(k in file.name.upper() for k in ("LICENSE", "COPYING")) and file.suffix not in (".py", ".pyc"):
            licenses.append((str(file.locate()), f"licenses/{dist}"))
ffmpeg_notices = os.path.join(os.environ["STUDIO_FFMPEG"], "share", "licenses", "ffmpeg")
licenses += [(os.path.join(ffmpeg_notices, name), "licenses/FFmpeg") for name in ("COPYING.LGPLv2.1", "SOURCE.txt")]

# Parts Studio never loads: unused Qt modules, and Pillow, which Robot Framework imports only if present.
EXCLUDES = ["tkinter", "PIL", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
            "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtCharts",
            "PySide6.QtDesigner"]

a = Analysis([os.path.join(SPECPATH, "studio_entry.py")], pathex=[os.path.join(ROOT, "src")],
             datas=collect_data_files("MaestroLibrary") + licenses, hiddenimports=["grpc"], excludes=EXCLUDES)
pyz = PYZ(a.pure)
if sys.platform == "win32":
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name=NAME, console=False, icon=ICON, upx=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=ICON, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
    if sys.platform == "darwin":
        app = BUNDLE(coll, name=f"{NAME}.app", icon=ICON, bundle_identifier="io.github.maestrolibrary.studio",
                     version=MaestroLibrary.__version__, info_plist={"NSHighResolutionCapable": True})
