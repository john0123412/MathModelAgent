"""字体检测/fallback/本地覆盖逻辑的单元测试。"""

import unittest
from unittest import mock

from app.utils import font_utils


class TestCheckFontInstalledDispatch(unittest.TestCase):
    """check_font_installed 按平台分派到 Windows 注册表 / fc-match。"""

    def test_windows_dispatches_to_registry(self):
        with (
            mock.patch("platform.system", return_value="Windows"),
            mock.patch(
                "app.utils.font_utils._windows_installed_font_families",
                return_value={"Times New Roman", "SimSun"},
            ),
        ):
            self.assertTrue(font_utils.check_font_installed("Times New Roman"))
            self.assertFalse(font_utils.check_font_installed("KaiTi"))

    def test_windows_registry_unavailable_returns_none(self):
        with (
            mock.patch("platform.system", return_value="Windows"),
            mock.patch(
                "app.utils.font_utils._windows_installed_font_families",
                return_value=None,
            ),
        ):
            self.assertIsNone(font_utils.check_font_installed("Times New Roman"))

    def test_non_windows_dispatches_to_fc_match(self):
        with (
            mock.patch("platform.system", return_value="Linux"),
            mock.patch(
                "app.utils.font_utils._fc_match_family", return_value="Liberation Serif"
            ),
        ):
            self.assertFalse(font_utils.check_font_installed("Times New Roman"))

        with (
            mock.patch("platform.system", return_value="Linux"),
            mock.patch(
                "app.utils.font_utils._fc_match_family", return_value="Times New Roman"
            ),
        ):
            self.assertTrue(font_utils.check_font_installed("Times New Roman"))

    def test_non_windows_accepts_fontconfig_family_alias_list(self):
        with (
            mock.patch("platform.system", return_value="Linux"),
            mock.patch(
                "app.utils.font_utils._fc_match_family", return_value="SimSun,NSimSun"
            ),
        ):
            self.assertTrue(font_utils.check_font_installed("SimSun"))

    def test_non_windows_fc_match_unavailable_returns_none(self):
        with (
            mock.patch("platform.system", return_value="Linux"),
            mock.patch("app.utils.font_utils._fc_match_family", return_value=None),
        ):
            self.assertIsNone(font_utils.check_font_installed("Times New Roman"))


class TestWindowsFontFamilyMatching(unittest.TestCase):
    """注册表值名归一化 + 匹配逻辑。"""

    def test_exact_and_variant_match(self):
        families = {"Times New Roman", "Times New Roman Bold", "SimSun & NSimSun"}
        self.assertTrue(font_utils._is_family_in_set("Times New Roman", families))
        self.assertTrue(font_utils._is_family_in_set("SimSun", families))
        # 不应该把 "SimSun-ExtB" 误判为 SimSun 的变体（没有空格分隔）
        self.assertFalse(
            font_utils._is_family_in_set("SimSun", {"SimSun-ExtB"})
        )

    def test_case_insensitive(self):
        self.assertTrue(font_utils._is_family_in_set("times new roman", {"Times New Roman"}))


class TestResolveFont(unittest.TestCase):
    """resolve_font()：Docker/Linux 自动化路径，无用户覆盖、只记录日志。"""

    def test_font_without_fallback_entry_returned_unchanged(self):
        # "Consolas" 不在 FONT_FALLBACKS 里，不做任何检测直接原样返回
        with mock.patch("app.utils.font_utils.check_font_installed") as mocked:
            self.assertEqual(font_utils.resolve_font("Consolas"), "Consolas")
            mocked.assert_not_called()

    def test_installed_font_returned_unchanged(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=True):
            self.assertEqual(font_utils.resolve_font("Times New Roman"), "Times New Roman")

    def test_missing_font_falls_back(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=False):
            self.assertEqual(font_utils.resolve_font("Times New Roman"), "Liberation Serif")
            self.assertEqual(font_utils.resolve_font("SimSun"), "Noto Serif CJK SC")

    def test_undetectable_optimistically_keeps_preferred(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=None):
            self.assertEqual(font_utils.resolve_font("Times New Roman"), "Times New Roman")


class TestResolveFontForLocal(unittest.TestCase):
    """resolve_font_for_local()：本地手动导出路径，支持用户覆盖 + 提示文案。"""

    def test_override_always_wins_even_when_installed_unknown(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=None):
            font, warnings = font_utils.resolve_font_for_local("Times New Roman", override="Georgia")
        self.assertEqual(font, "Georgia")
        self.assertEqual(len(warnings), 1)
        self.assertIn("无法自动检测", warnings[0])

    def test_override_missing_warns_but_still_used(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=False):
            font, warnings = font_utils.resolve_font_for_local("SimSun", override="MyFakeFont")
        # 用户显式指定的字体永远原样使用，绝不被静默替换
        self.assertEqual(font, "MyFakeFont")
        self.assertEqual(len(warnings), 1)
        self.assertIn("MyFakeFont", warnings[0])
        self.assertIn("未检测到已安装", warnings[0])

    def test_override_installed_no_warning(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=True):
            font, warnings = font_utils.resolve_font_for_local("SimSun", override="KaiTi")
        self.assertEqual(font, "KaiTi")
        self.assertEqual(warnings, [])

    def test_no_override_installed_no_warning(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=True):
            font, warnings = font_utils.resolve_font_for_local("Times New Roman")
        self.assertEqual(font, "Times New Roman")
        self.assertEqual(warnings, [])

    def test_no_override_missing_falls_back_with_warning(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=False):
            font, warnings = font_utils.resolve_font_for_local("Times New Roman")
        self.assertEqual(font, "Liberation Serif")
        self.assertEqual(len(warnings), 1)
        self.assertIn("Times New Roman", warnings[0])
        self.assertIn("Liberation Serif", warnings[0])

    def test_no_override_undetectable_optimistic_with_note(self):
        with mock.patch("app.utils.font_utils.check_font_installed", return_value=None):
            font, warnings = font_utils.resolve_font_for_local("SimSun")
        self.assertEqual(font, "SimSun")
        self.assertEqual(len(warnings), 1)
        self.assertIn("无法自动检测", warnings[0])


if __name__ == "__main__":
    unittest.main()
