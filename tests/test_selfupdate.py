import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from forever_deals import selfupdate
from forever_deals.updater import UpdateError

REL = {"target_commitish": "f" * 40, "assets": [
    {"name": "ForeverDeals-windows.zip", "url": "https://api.github.com/repos/x/y/releases/assets/7",
     "browser_download_url": "https://github.com/x/y/releases/download/windows-latest/ForeverDeals-windows.zip"}]}


def zip_with(files: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


class R:
    def __init__(self, d): self.d = d
    def read(self): return self.d
    def __enter__(self): return self
    def __exit__(self, *a): return False


class ReleaseTest(unittest.TestCase):
    def op(self, rel=REL, seen=None, zip_bytes=b""):
        def f(req, timeout=0):
            if seen is not None:
                seen.append(req)
            return R(json.dumps(rel).encode() if "/releases/tags/" in req.full_url else zip_bytes)
        return f

    def test_check_compares_release_commit_with_local(self):
        self.assertEqual(selfupdate.check("a" * 40, opener=self.op()), (True, "a" * 40, "f" * 40))
        self.assertFalse(selfupdate.check("f" * 40, opener=self.op())[0])

    def test_unknown_local_means_update(self):
        self.assertTrue(selfupdate.check("unknown", opener=self.op())[0])

    def test_release_without_asset_is_error(self):
        with self.assertRaises(UpdateError):
            selfupdate.check("a", opener=self.op({"target_commitish": "x", "assets": []}))

    def test_private_repo_uses_api_asset_url_with_token(self):
        seen = []
        data = zip_with({"ForeverDeals.exe": b"MZ"})
        selfupdate.download(opener=self.op(seen=seen, zip_bytes=data), token="t")
        last = seen[-1]
        self.assertEqual(last.full_url, REL["assets"][0]["url"])
        self.assertEqual(last.get_header("Accept"), "application/octet-stream")
        self.assertEqual(last.get_header("Authorization"), "Bearer t")

    def test_public_download_uses_browser_url(self):
        seen = []
        selfupdate.download(opener=self.op(seen=seen, zip_bytes=zip_with({"ForeverDeals.exe": b"MZ"})))
        self.assertEqual(seen[-1].full_url, REL["assets"][0]["browser_download_url"])


class ExtractTest(unittest.TestCase):
    def test_extracts_only_exe_to_new_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = selfupdate.stage(zip_with({"ForeverDeals.exe": b"MZ-new" + b"\0" * 2000, "README.md": b"x"}), d)
            self.assertTrue(p.read_bytes().startswith(b"MZ-new"))
            self.assertEqual(p.name, "ForeverDeals.new.exe")
            self.assertEqual(sorted(x.name for x in Path(d).iterdir()), ["ForeverDeals.new.exe"])

    def test_missing_exe_or_bad_zip_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(UpdateError):
                selfupdate.stage(zip_with({"README.md": b"x"}), d)
            with self.assertRaises(UpdateError):
                selfupdate.stage(b"not a zip", d)

    def test_tiny_exe_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(UpdateError):
                selfupdate.stage(zip_with({"ForeverDeals.exe": b""}), d)


class ScriptTest(unittest.TestCase):
    def test_script_waits_swaps_restarts_and_cleans_up(self):
        s = selfupdate.script(r"C:\Apps\ForeverDeals.exe", r"C:\Apps\ForeverDeals.new.exe", 1234)
        self.assertIn(r'move /y "C:\Apps\ForeverDeals.new.exe" "C:\Apps\ForeverDeals.exe"', s)
        self.assertIn("1234", s)                       # ждёт завершения процесса
        self.assertIn(r'start "" "C:\Apps\ForeverDeals.exe"', s)
        self.assertIn("goto", s)                       # повторные попытки, пока файл занят
        self.assertIn('del "%~f0"', s)
        self.assertTrue(s.index("move /y") < s.index("start"))

    def test_script_rejects_quotes_in_paths(self):
        with self.assertRaises(ValueError):
            selfupdate.script('C:\\a"b.exe', "C:\\n.exe", 1)


class EnvTest(unittest.TestCase):
    def test_pyinstaller_vars_removed_others_kept(self):
        env = {"PATH": "x", "_MEIPASS2": "t", "_PYI_APPLICATION_HOME_DIR": "t", "FD_HOME": "h"}
        self.assertEqual(selfupdate.clean_env(env), {"PATH": "x", "FD_HOME": "h"})


class VersionTest(unittest.TestCase):
    def test_bundled_version_read_from_dir(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "VERSION").write_text("abc\n")
            self.assertEqual(selfupdate.bundled_version(d), "abc")
            self.assertEqual(selfupdate.bundled_version(d + "/none"), "unknown")


if __name__ == "__main__":
    unittest.main()
