"""Builds the decode-only, LGPL FFmpeg that Studio's desktop bundles ship (no x264, x265 or other GPL parts).

    python packaging/build_ffmpeg.py PREFIX [--jobs N]

Studio only decodes the scrcpy H.264 stream, so FFmpeg is configured with its own H.264 decoder and parser,
swscale and swresample, and nothing else; --disable-autodetect keeps system libraries out, so every runner builds
the same thing. On Windows, run it from an MSYS2 shell inside the MSVC environment (--toolchain=msvc gives the
import .lib files PyAV's MSVC build links against). PyAV is then built against PREFIX.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

VERSION = "9.0.2"
URL = f"https://ffmpeg.org/releases/ffmpeg-{VERSION}.tar.xz"
# Checked against FFmpeg's release signature (key FCF986EA15E6E293A5644F10B4322F04D67658D8) on 2026-10-10.
SHA256 = "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
CONFIGURE = [
    "--disable-everything", "--disable-autodetect", "--disable-programs", "--disable-doc", "--disable-network",
    "--enable-shared", "--disable-static",
    "--enable-decoder=h264", "--enable-parser=h264", "--enable-swscale", "--enable-swresample",
]


def fetch(folder):
    path = os.path.join(folder, os.path.basename(URL))
    with urllib.request.urlopen(URL, timeout=120) as answer, open(path, "wb") as out:   # nosec B310 - fixed https URL
        out.write(answer.read())
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"{URL} has SHA-256 {digest}, expected {SHA256}; refusing to build it.")
    with tarfile.open(path) as tar:
        tar.extractall(folder, filter="data")             # no links or paths outside the folder
    return os.path.join(folder, f"ffmpeg-{VERSION}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prefix")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    args = parser.parse_args(argv)
    prefix = os.path.abspath(args.prefix)
    options = CONFIGURE + (["--toolchain=msvc"] if sys.platform == "win32" else [])
    with tempfile.TemporaryDirectory() as work:
        source = fetch(work)
        subprocess.run(["bash", "./configure", f"--prefix={prefix.replace(os.sep, '/')}", *options], cwd=source, check=True)
        subprocess.run(["make", f"-j{args.jobs}"], cwd=source, check=True)
        subprocess.run(["make", "install"], cwd=source, check=True)
        notices = os.path.join(prefix, "share", "licenses", "ffmpeg")
        os.makedirs(notices, exist_ok=True)
        shutil.copy(os.path.join(source, "COPYING.LGPLv2.1"), notices)
        with open(os.path.join(notices, "SOURCE.txt"), "w", encoding="utf-8") as note:
            note.write(f"FFmpeg {VERSION}, LGPL 2.1 or later, built from {URL}\nSHA-256 {SHA256}\n"
                       f"configure {' '.join(options)}\n")
    print(f"FFmpeg {VERSION} (LGPL, H.264 decode only) installed in {prefix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
