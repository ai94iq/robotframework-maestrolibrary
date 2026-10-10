# Plan

Current work: **MaestroLibrary Studio**. A native Qt (PySide6) window shows the live device screen; acting on it runs MaestroLibrary keywords and records the Robot lines. Full plan, with security and platform notes: `docs/superpowers/plans/2026-10-10-maestro-studio.md`.

## Status

- [x] Task 1: hit testing and locator choice (`locators.py`), `e8eead1`
- [x] Task 2: `studio.Session` (actions to keyword runs and recorded lines, escaping), `ae8ee8b`
- [x] Task 3: `stream.ScrcpyStream` (raw H.264 from scrcpy-server), `afc6226`; scrcpy from PATH only, `fd2c65d`
- [x] Task 3b: Python floor 3.12; plan.md and handover.md
- [ ] Task 3b step 5: fms-flutter-automation CI image python:3.14-alpine (push after 0.6.0 is on PyPI)
- [x] Task 4: web layer removed (`b0cf27b`); decoding spike (PyAV chosen); `FrameDecoder`, `StreamReader`, `studio` extra
- [x] Task 5: `ActionWorker` (ordered steps off the UI thread), `source_tree`; `Session.tree` keeps the nested screen
- [x] Task 6 code: the Qt window (impeccable Operate mode), `main()`, newest-frame live view, scid per run, `--video-encoder`
- [ ] Task 6 device: end to end, replay, fallback, viewfinder smoothness (run at the end, per the user)
- [x] Task 7: README and CHANGELOG, skill line (both copies), CI (Qt offscreen on Linux, Windows, macOS; pip-audit over the extras), security pass; pushed
- [ ] Release 0.6.0 (only when the user says so)

## Measured (2026-10-10, Samsung A70, Android 15)

- Screenshots are too slow to feel live: MCP `take_screenshot` 2.3 s, `adb screencap` 0.8 to 2.2 s. `inspect_screen` takes 0.36 s.
- scrcpy-server 5.0 with `raw_stream=true video_codec=h264` streams live. First bytes arrive after 1.5 to 1.8 s, and adb accepts the forward before the server listens. NAL order is 7, 8, 5, then 1. The codec is `avc1.42800a`.
- Decoding: Qt's own FFmpeg (`QMediaPlayer` on a live pipe) gave 2 frames in 15 s, so it was rejected. PyAV 19.0.1 decodes at 30.4 fps while swiping, with the first frame 0.1 s after the stream starts and 1.6 ms per frame to a QImage. Frames are 486x1080 at max_size=1080.
- Tap to changed frame on the PC (app redraw + capture + encode + adb + decode), Play Store tabs, clocks synced to +/-10 ms: median 141 ms at 720 px, 123 ms at 1080 px, 148 ms at 720 again (min about 85 ms). Downscaling did not lower latency; decode to paint is 4 ms.
- The real window at 1080 px under 30 s of swipes painted 53 fps (1588 of 1602 decoded frames), and the UI thread never stalled (max 15 ms). The lag seen during the e2e run came from the harness calling Maestro on the UI thread.
- Queuing every decoded frame to the UI made the view lag; keeping only the newest frame fixed it (59 fps painted).
- Revision 1 (a browser page) reached a live view in headless Edge, but dropped a step sent while another was running, so steps must queue.

## Decisions

- Frontend: native Qt (PySide6), the user's choice over a browser page.
- Python 3.12 or newer: 3.10 reached end of life on 2026-10-01, and 3.12 is PyAV's floor.
- New dependencies are only in the `studio` extra, at their latest versions: PySide6 6.12.0 and av 19.0.1 (checked live 2026-10-10).
