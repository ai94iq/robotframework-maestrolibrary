# Plan

Current work: **MaestroLibrary Studio**. A native Qt (PySide6) window shows the live device screen; acting on it runs MaestroLibrary keywords and records the Robot lines. Full plan, with security and platform notes: `docs/superpowers/plans/2026-10-10-maestro-studio.md`.

## Status

- [x] Task 1: hit testing and locator choice (`locators.py`), `e8eead1`
- [x] Task 2: `studio.Session` (actions to keyword runs and recorded lines, escaping), `ae8ee8b`
- [x] Task 3: `stream.ScrcpyStream` (raw H.264 from scrcpy-server), `afc6226`; scrcpy from PATH only, `fd2c65d`
- [x] Task 3b: Python floor 3.12; plan.md and handover.md
- [ ] Task 3b step 5: fms-flutter-automation CI image python:3.14-alpine; on hold until iOS is checked (the user's call)
- [x] Task 4: web layer removed (`b0cf27b`); decoding spike (PyAV chosen); `FrameDecoder`, `StreamReader`, `studio` extra
- [x] Task 5: `ActionWorker` (ordered steps off the UI thread), `source_tree`; `Session.tree` keeps the nested screen
- [x] Task 6 code: the Qt window (impeccable Operate mode), `main()`, newest-frame live view, scid per run, `--video-encoder`
- [x] Task 6 device: end to end 18 of 18 in the real window, replay PASS, screenshot fallback (2026-10-10)
- [x] Task 6 follow-ups (user review rounds): UI rounds one to seven (impeccable detect clean in both themes), theme button, empty states, app icon, control tooltips, footer notice; device switch in place; adb touch steps; pending lines; tree reads from Maestro's driver over gRPC; screenshot keywords outside Robot
- [x] Code review (inline, superpowers checklist): failed adb touches no longer record, gRPC channel closed, reader for every device, steps keep their order across the two workers, MCP client takes one call at a time (`dde9ed4`)
- [x] Task 7: README and CHANGELOG, skill line (both copies), CI jobs (Qt offscreen on Linux, Windows, macOS; pip-audit over the extras), security pass, wheel check (`d4ef116`)
- [x] Task 7: CI tests green on ubuntu (check jobs), windows and macos (studio job): last full green run seen at `1120c10`
- [x] Task 8: desktop bundles (plan `C:/Users/abdoi/.claude/plans/logical-watching-lemon.md`): LGPL decode-only FFmpeg 9.0.2 (`packaging/build_ffmpeg.py`), PyAV built on it, PyInstaller (`packaging/studio.spec`, `packaging/build_bundle.py`), `--self-check` license gate, CI `bundles` job on every run and `release-bundles` on tags
- [x] Task 8 Linux: verified in WSL (Ubuntu 26.04) and in CI; macOS arm64 green in CI (self-check only, no Mac here)
- [ ] Task 8 Windows: the first run failed (bash resolved to the WSL launcher); fixed in `ede0d9e`, its CI result not seen yet. macOS Intel: result not seen yet
- [ ] Task 8: run the CI-built Windows `.exe` on this PC against the phone (Defender on), with timings
- [ ] Release 0.6.0 (only when the user says so)

## Measured (2026-10-10, Samsung A70, Android 15)

- Screenshots are too slow to feel live: MCP `take_screenshot` 2.3 s, `adb screencap` 0.8 to 2.2 s. `inspect_screen` took 0.36 s on a simple screen and 2.2 to 4.3 s (median 4.0) on the Play Store home.
- scrcpy-server 5.0 with `raw_stream=true video_codec=h264` streams live. First bytes arrive after 1.5 to 1.8 s, and adb accepts the forward before the server listens. NAL order is 7, 8, 5, then 1. The codec is `avc1.42800a`.
- Decoding: Qt's own FFmpeg (`QMediaPlayer` on a live pipe) gave 2 frames in 15 s, so it was rejected. PyAV 19.0.1 decodes at 30.4 fps while swiping, with the first frame 0.1 s after the stream starts and 1.6 ms per frame to a QImage. Frames are 486x1080 at max_size=1080.
- Tap to changed frame on the PC (app redraw + capture + encode + adb + decode), Play Store tabs, clocks synced to +/-10 ms: median 141 ms at 720 px, 123 ms at 1080 px, 148 ms at 720 again (min about 85 ms). Downscaling did not lower latency; decode to paint is 4 ms.
- The real window at 1080 px under 30 s of swipes painted 53 fps (1588 of 1602 decoded frames), and the UI thread never stalled (max 15 ms). The lag seen during the e2e run came from the harness calling Maestro on the UI thread.
- A step on the phone (Play Store, 2026-10-10): Maestro's tap returns after the screen settles, 5.9 s for a tab click and 2.3 s for Back; the screen read after it took 2.5 to 4.8 s. Studio shows the planned line at once, dimmed, and the recorded line replaces it.
- Device switch in place (phone and Pixel 9 emulator, 2026-10-10): live view back 0.7 s (emulator) and 2.2 s (phone) after the click; the element tree follows in 5 to 8 s (20 s on the first visit while Maestro connects). Screen reads used to queue every 5 s while each took about 5 s, holding back steps and switches; only one read is queued now.
- Touch steps on the phone (2026-10-10): Maestro tap by locator 4.1 to 7.2 s (median 5.1), Maestro point tap 2.3 s, adb input tap 0.17 s. Studio sends Android taps, long presses, swipes and Back with adb on their own worker: the line is confirmed 0.13 to 0.17 s after the click and the screen changes 0.33 to 0.43 s after it. Typing, asserts and Launch still run through Maestro (5 to 14 s in the e2e run).
- Tree reads (2026-10-10), median of 5: MCP inspect_screen 2.17 s (phone) and 0.70 s (emulator); Maestro's driver over gRPC viewHierarchy 0.45 s and 0.04 s, same elements; adb uiautomator dump 3.36 s and 1.97 s, with fewer nodes. Studio reads through the driver with MCP as the fallback: after a tap the Elements pane shows the new screen in 0.17 to 1.60 s on the phone. Maestro Studio on the same emulator: 0.76 to 1.35 s.
- Linux bundle (WSL, phone over adb Wi-Fi, 2026-10-10): tarball 88 MB; self-check "LGPL version 2.1 or later", no GPL or nonfree parts; live view started 6.7 s after launch; through the same code a tap recorded in 0.11 to 0.23 s and the Elements pane showed the new screen in 1.23 to 2.39 s.
- Maestro Studio (desktop) on an emulator, same steps: its tree updated 0.76 to 1.35 s after a tap (it reads the driver every 0.35 s); a Maestro tap took 2.1 to 2.3 s there and 2.2 to 2.4 s through ours.
- Queuing every decoded frame to the UI made the view lag; keeping only the newest frame fixed it (59 fps painted).
- Revision 1 (a browser page) reached a live view in headless Edge, but dropped a step sent while another was running, so steps must queue.

## Decisions

- Frontend: native Qt (PySide6), the user's choice over a browser page.
- Python 3.12 or newer: 3.10 reached end of life on 2026-10-01, and 3.12 is PyAV's floor.
- New dependencies are only in the `studio` extra, at their latest versions: PySide6 6.12.0 and av 19.0.1 (checked live 2026-10-10).
