import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path

from forever_deals import updater


def make_zip(files: dict, top="kclazzy-aucwow-abc1234/") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(top + name, data)
    return buf.getvalue()


class Resp:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(sha="abc1234def", zip_bytes=b"", fail=None, seen=None):
    def op(req, timeout=0):
        if seen is not None:
            seen.append(req)
        if fail:
            raise fail
        if "/commits/" in req.full_url:
            return Resp(json.dumps({"sha": sha}).encode())
        return Resp(zip_bytes)
    return op


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_local_version_means_update_available(self):
        has, local, remote = updater.check(self.dir, opener=opener())
        self.assertEqual((has, local, remote), (True, "unknown", "abc1234def"))

    def test_no_update_when_versions_match(self):
        (self.dir / "VERSION").write_text("abc1234def\n")
        has, local, _ = updater.check(self.dir, opener=opener())
        self.assertFalse(has)
        self.assertEqual(local, "abc1234def")

    def test_update_replaces_code_keeps_foreign_files_and_writes_version(self):
        (self.dir / "app.py").write_text("old")
        (self.dir / "my_notes.txt").write_text("mine")
        z = make_zip({"app.py": "new", "forever_deals/core.py": "core"})
        changed = updater.update(self.dir, opener=opener(zip_bytes=z))
        self.assertEqual((self.dir / "app.py").read_text(), "new")
        self.assertEqual((self.dir / "forever_deals" / "core.py").read_text(), "core")
        self.assertEqual((self.dir / "my_notes.txt").read_text(), "mine")
        self.assertEqual(updater.local_version(self.dir), "abc1234def")
        self.assertEqual(sorted(changed), ["app.py", "forever_deals/core.py"])

    def test_update_is_idempotent(self):
        z = make_zip({"app.py": "new"})
        updater.update(self.dir, opener=opener(zip_bytes=z))
        changed = updater.update(self.dir, opener=opener(zip_bytes=z))
        self.assertEqual(changed, [])

    def test_path_traversal_entries_are_refused_and_nothing_written(self):
        z = make_zip({"app.py": "new", "../evil.txt": "x"})
        with self.assertRaises(updater.UpdateError):
            updater.update(self.dir, opener=opener(zip_bytes=z))
        self.assertFalse((self.dir / "app.py").exists())
        self.assertFalse((self.dir.parent / "evil.txt").exists())

    def test_user_data_dirs_in_archive_are_skipped(self):
        z = make_zip({"app.py": "new", ".git/config": "x", "reports/a.md": "y"})
        updater.update(self.dir, opener=opener(zip_bytes=z))
        self.assertFalse((self.dir / ".git").exists())
        self.assertFalse((self.dir / "reports").exists())

    def test_http_errors_become_readable_messages(self):
        err = urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b""))
        with self.assertRaises(updater.UpdateError) as cm:
            updater.check(self.dir, opener=opener(fail=err))
        self.assertIn("github_token", str(cm.exception))
        net = urllib.error.URLError("down")
        with self.assertRaises(updater.UpdateError) as cm:
            updater.check(self.dir, opener=opener(fail=net))
        self.assertIn("нет связи", str(cm.exception))

    def test_token_sent_only_when_given(self):
        seen = []
        updater.check(self.dir, opener=opener(seen=seen))
        self.assertIsNone(seen[0].get_header("Authorization"))
        updater.check(self.dir, opener=opener(seen=seen), token="t0k")
        self.assertEqual(seen[1].get_header("Authorization"), "Bearer t0k")

    def test_unsupported_when_frozen(self):
        import sys
        self.assertTrue(updater.supported())
        sys.frozen = True
        try:
            self.assertFalse(updater.supported())
        finally:
            del sys.frozen

    def test_bad_zip_is_refused(self):
        with self.assertRaises(updater.UpdateError):
            updater.update(self.dir, opener=opener(zip_bytes=b"not a zip"))


if __name__ == "__main__":
    unittest.main()
