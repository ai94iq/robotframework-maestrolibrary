"""How packaging/build_ffmpeg.py fetches the FFmpeg source: which failures it retries and which it does not."""
import hashlib
import http.client
import importlib.util
import io
import os
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "packaging", "build_ffmpeg.py")
spec = importlib.util.spec_from_file_location("build_ffmpeg", SCRIPT)
build_ffmpeg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_ffmpeg)


def source_tarball():
    """A tiny .tar.xz holding the folder the script expects, standing in for the FFmpeg release."""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:xz") as tar:
        folder = tarfile.TarInfo(f"ffmpeg-{build_ffmpeg.VERSION}")
        folder.type = tarfile.DIRTYPE
        tar.addfile(folder)
    return data.getvalue()


def answer(body):
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = body
    return response


class FetchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = tmp.name
        self.body = source_tarball()
        for patch in (mock.patch.object(build_ffmpeg, "SHA256", hashlib.sha256(self.body).hexdigest()),
                      mock.patch.object(build_ffmpeg.time, "sleep")):
            patch.start()
            self.addCleanup(patch.stop)

    def fetch(self, *answers, folder=None):
        with mock.patch.object(build_ffmpeg.urllib.request, "urlopen", side_effect=answers) as urlopen, \
                mock.patch.object(sys, "stderr", io.StringIO()):
            try:
                return build_ffmpeg.fetch(folder or self.folder, attempts=3)
            finally:
                self.calls = urlopen.call_count

    def test_retries_cut_off_body(self):
        cut = answer(b"")
        cut.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b"partial", 100)
        source = self.fetch(cut, answer(self.body))
        self.assertTrue(os.path.isdir(source))
        self.assertEqual(self.calls, 2)

    def test_retries_network_error(self):
        source = self.fetch(build_ffmpeg.urllib.error.URLError("reset"), answer(self.body))
        self.assertTrue(os.path.isdir(source))
        self.assertEqual(self.calls, 2)

    def test_gives_up_at_last_try(self):
        failure = build_ffmpeg.urllib.error.URLError("down")
        with self.assertRaisesRegex(SystemExit, "after 3 attempts"):
            self.fetch(failure, failure, failure)
        self.assertEqual(self.calls, 3)

    def test_no_retry_on_write_error(self):
        missing = os.path.join(self.folder, "missing")   # open(path, "wb") fails here, which no retry fixes
        with self.assertRaises(FileNotFoundError):
            self.fetch(answer(self.body), answer(self.body), folder=missing)
        self.assertEqual(self.calls, 1)

    def test_rejects_bad_checksum(self):
        with self.assertRaisesRegex(SystemExit, "refusing to build it"):
            self.fetch(answer(b"not ffmpeg"))
        self.assertEqual(self.calls, 1)


if __name__ == "__main__":
    unittest.main()
