"""Configured input-file resolution for the short CLI commands."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from record_io import configured_path  # noqa: E402


class ConfiguredPathTests(unittest.TestCase):
    def test_relative_configured_path_is_project_relative(self):
        with patch.dict(os.environ, {"INPUT_DATA_FILE": "data/bigquery_pilot.csv"}):
            self.assertEqual(
                configured_path("INPUT_DATA_FILE"),
                ROOT / "data" / "bigquery_pilot.csv",
            )

    def test_absolute_configured_path_is_preserved(self):
        configured = ROOT / "data" / "sample_data.json"
        with patch.dict(os.environ, {"INPUT_DATA_FILE": str(configured)}):
            self.assertEqual(configured_path("INPUT_DATA_FILE"), configured)

    def test_missing_setting_uses_default(self):
        default = ROOT / "data" / "sample_data.json"
        with patch.dict(os.environ):
            os.environ.pop("INPUT_DATA_FILE", None)
            self.assertEqual(configured_path("INPUT_DATA_FILE", default), default)


if __name__ == "__main__":
    unittest.main()
