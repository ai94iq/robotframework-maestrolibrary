## Studio desktop bundles

Studio without Python: download the file for your system, then start it.

| System | File |
|---|---|
| Windows 10 or 11, x64 | `MaestroLibrary-Studio-<version>-windows-x64.exe` |
| Linux x64 (glibc 2.39 or newer, such as Ubuntu 24.04) | `MaestroLibrary-Studio-<version>-linux-x64.tar.gz` |
| macOS on Apple silicon | `MaestroLibrary-Studio-<version>-macos-arm64.dmg` |
| macOS on Intel | `MaestroLibrary-Studio-<version>-macos-x64.dmg` |

**You still need** on the machine: the Maestro CLI (with Java), adb, and scrcpy for the live view. Studio finds them
on PATH or where their installers put them (`~/.maestro/bin`, the Android SDK's `platform-tools`, Homebrew).
On Linux, Qt also needs the system's X11 or Wayland libraries (Debian and Ubuntu: `libxcb-cursor0`).

**The bundles are not signed yet**, so the system warns the first time:

- Windows: SmartScreen says it protected your PC; choose More info, then Run anyway. Antivirus software sometimes
  flags single-file Python apps; compare the file with `SHA256SUMS` before running it.
- macOS: right-click the app and choose Open, or run `xattr -dr com.apple.quarantine MaestroLibrary-Studio.app`.

**Licenses**: Studio is MIT. The bundles also ship Qt (PySide6, LGPL-3.0), an LGPL FFmpeg built for H.264 decoding
only (no GPL parts), PyAV (BSD), grpcio (Apache-2.0) and Robot Framework (Apache-2.0); every license text, and where
the FFmpeg source comes from, is in the bundle's `licenses` folder.
