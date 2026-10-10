"""Builds a Studio desktop bundle for this platform, checks it, and packs it for a GitHub release.

    python packaging/build_bundle.py FFMPEG_PREFIX OUT_DIR

FFMPEG_PREFIX comes from build_ffmpeg.py. Steps: PyAV built against that FFmpeg (and repaired so its wheel carries
the FFmpeg libraries on Windows and macOS), Studio's other dependencies, PyInstaller, then the bundle's own
--self-check, which must report an LGPL FFmpeg with no GPL or nonfree parts and decoded frames. Output:
MaestroLibrary-Studio-<version>-windows-x64.exe, -linux-x64.tar.gz or -macos-<arch>.dmg in OUT_DIR.
"""
import argparse
import ast
import glob
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "MaestroLibrary-Studio"
AV = "19.0.1"                          # built from source against the LGPL FFmpeg
TOOLS = ["pyinstaller==6.22.3", "pillow==12.3.0", "delvewheel==1.13.2", "delocate==0.13.0"]


def version():
    tree = ast.parse(open(os.path.join(ROOT, "src", "MaestroLibrary", "__init__.py"), encoding="utf-8").read())
    return next(n.value.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "__version__")


def pip(*args, env=None):
    subprocess.run([sys.executable, "-m", "pip", *args], check=True, env=env)


def build_av(ffmpeg, env, work):
    """PyAV's wheel against our FFmpeg; on Windows and macOS repaired so the wheel holds the FFmpeg libraries."""
    built, fixed = os.path.join(work, "built"), os.path.join(work, "fixed")
    extra = ([f"--config-settings=--build-option=--ffmpeg-dir={ffmpeg}"] if sys.platform == "win32" else [])
    pip("wheel", "--no-deps", "--no-binary", "av", f"av=={AV}", "-w", built, *extra, env=env)
    wheel = glob.glob(os.path.join(built, "av-*.whl"))[0]
    if sys.platform == "win32":
        subprocess.run([sys.executable, "-m", "delvewheel", "repair", "--add-path", os.path.join(ffmpeg, "bin"),
                        "-w", fixed, wheel], check=True, env=env)
    elif sys.platform == "darwin":
        subprocess.run(["delocate-wheel", "-w", fixed, wheel], check=True, env=env)
    else:
        return wheel                    # Linux: PyInstaller collects the libraries through LD_LIBRARY_PATH
    return glob.glob(os.path.join(fixed, "av-*.whl"))[0]


def executable():
    if sys.platform == "win32":
        return os.path.join(ROOT, "dist", f"{NAME}.exe")
    if sys.platform == "darwin":
        return os.path.join(ROOT, "dist", f"{NAME}.app", "Contents", "MacOS", NAME)
    return os.path.join(ROOT, "dist", NAME, NAME)


def self_check(env, work):
    """The bundle's own check: LGPL FFmpeg, no GPL or nonfree parts, frames decoded."""
    report = os.path.join(work, "self-check.txt")
    code = subprocess.run([executable(), "--self-check", report], env=dict(env, QT_QPA_PLATFORM="offscreen")).returncode
    text = open(report, encoding="utf-8").read() if os.path.exists(report) else ""
    print(text)
    if code or "ffmpeg license: LGPL" not in text or "gpl or nonfree parts: none" not in text:
        raise SystemExit(f"The bundle failed its self-check (exit {code}).")


def pack(out):
    os.makedirs(out, exist_ok=True)
    stem = f"{NAME}-{version()}"
    if sys.platform == "win32":
        target = os.path.join(out, f"{stem}-windows-x64.exe")
        shutil.copy(executable(), target)
    elif sys.platform == "darwin":
        arch = "arm64" if platform.machine() == "arm64" else "x64"
        target = os.path.join(out, f"{stem}-macos-{arch}.dmg")
        subprocess.run(["hdiutil", "create", "-volname", "MaestroLibrary Studio", "-srcfolder",
                        os.path.join(ROOT, "dist", f"{NAME}.app"), "-ov", "-format", "UDZO", target], check=True)
    else:
        target = os.path.join(out, f"{stem}-linux-x64.tar.gz")
        with tarfile.open(target, "w:gz") as tar:
            tar.add(os.path.join(ROOT, "dist", NAME), arcname=f"{stem}-linux-x64")
    print(f"{target}: {os.path.getsize(target) / 2 ** 20:.0f} MB")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ffmpeg")
    parser.add_argument("out")
    args = parser.parse_args(argv)
    ffmpeg = os.path.abspath(args.ffmpeg)
    env = dict(os.environ, STUDIO_FFMPEG=ffmpeg, PKG_CONFIG_PATH=os.path.join(ffmpeg, "lib", "pkgconfig"))
    if sys.platform.startswith("linux"):
        env["LD_LIBRARY_PATH"] = os.path.join(ffmpeg, "lib")
    elif sys.platform == "darwin":
        env["DYLD_LIBRARY_PATH"] = os.path.join(ffmpeg, "lib")
    pip("install", "-q", "-U", "pip", *TOOLS, env=env)
    pip("install", "-q", f"{ROOT}[studio]", env=env)
    with tempfile.TemporaryDirectory() as work:
        pip("install", "--force-reinstall", "--no-deps", build_av(ffmpeg, env, work), env=env)
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN",
                        os.path.join(ROOT, "packaging", "studio.spec")], check=True, cwd=ROOT, env=env)
        self_check(env, work)
    pack(os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
