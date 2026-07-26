"""Export profile registry tests."""

import unittest

from app.schemas.enums import ExportProfile
from app.tools.export_profiles import (
    get_export_profile_config,
    list_export_profiles,
    normalize_export_profile,
)


class TestExportProfiles(unittest.TestCase):
    """Verify profile registry metadata and normalization."""

    def test_cumcm2026_profile_is_registered_without_auto_numbering(self):
        self.assertEqual(normalize_export_profile("cumcm2026"), ExportProfile.CUMCM2026)

        config = get_export_profile_config(ExportProfile.CUMCM2026)
        self.assertEqual(config.key, ExportProfile.CUMCM2026)
        self.assertEqual(config.latex_template_key, "zh/cumcm2026-ctexart")
        self.assertIn("geometry:left=3.17cm,right=3.17cm,top=3cm,bottom=2.8cm", config.pdf_variables)
        self.assertTrue(
            any(r"\emergencystretch=3em" in variable for variable in config.pdf_variables)
        )
        self.assertNotIn("--toc", config.pdf_extra_args)
        self.assertNotIn("--number-sections", config.pdf_extra_args)
        self.assertTrue(config.pdf_appendix_pagebreak)

        profile_keys = {item["key"] for item in list_export_profiles()}
        self.assertIn("cumcm2026", profile_keys)

    def test_huashubei_profile_is_registered(self):
        self.assertEqual(normalize_export_profile("huashubei"), ExportProfile.HUASHUBEI)

        config = get_export_profile_config(ExportProfile.HUASHUBEI)
        self.assertEqual(config.key, ExportProfile.HUASHUBEI)
        self.assertEqual(config.latex_template_key, "zh/huashubei-latex")
        self.assertIn("geometry:left=2.5cm,right=2.5cm,top=2.5cm,bottom=2.5cm", config.pdf_variables)

        profile_keys = {item["key"] for item in list_export_profiles()}
        self.assertIn("huashubei", profile_keys)
        self.assertFalse(config.pdf_appendix_pagebreak)


if __name__ == "__main__":
    unittest.main()
