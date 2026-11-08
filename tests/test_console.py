import io
import unittest

from forever_deals import console


class ConsoleTest(unittest.TestCase):
    def stream(self):
        return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")

    def test_russian_text_crashes_without_fix(self):
        s = self.stream()
        with self.assertRaises(UnicodeEncodeError):
            print("Ошибка", file=s, flush=True)

    def test_safe_stream_does_not_crash(self):
        s = self.stream()
        console.make_safe(s)
        print("Ошибка: нет связи", file=s, flush=True)

    def test_none_and_plain_streams_are_ignored(self):
        console.make_safe(None)
        console.make_safe(io.StringIO())


if __name__ == "__main__":
    unittest.main()
