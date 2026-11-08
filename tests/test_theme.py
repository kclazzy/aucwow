import unittest

from forever_deals import theme, viewmodel as vm


class ThemeTest(unittest.TestCase):
    def test_contrast_reference_values(self):
        self.assertAlmostEqual(theme.contrast("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(theme.contrast("#ffffff", "#ffffff"), 1.0, places=2)

    def test_every_text_pair_is_readable(self):
        for name, fg, bg in theme.TEXT_PAIRS:
            self.assertGreaterEqual(theme.contrast(fg, bg), 4.5, f"{name}: {fg} на {bg}")

    def test_palette_values_are_hex_colors(self):
        for k, v in theme.PALETTE.items():
            self.assertRegex(v, r"^#[0-9a-f]{6}$", k)


class RowTagTest(unittest.TestCase):
    def test_status_wins_over_zebra(self):
        self.assertEqual(vm.row_tag("✅ выгодно", 0), "ok")
        self.assertEqual(vm.row_tag("❌ мала прибыль", 1), "bad")

    def test_zebra_for_neutral_rows(self):
        self.assertEqual(vm.row_tag("", 0), "even")
        self.assertEqual(vm.row_tag("—", 1), "odd")


if __name__ == "__main__":
    unittest.main()
