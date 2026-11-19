"""Ayar dosyaları için hata mesajı ve önbellek kontrolleri."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import config as backend_config


class TestBackendConfig(unittest.TestCase):
    def tearDown(self):
        backend_config.load_config.cache_clear()

    def test_missing_config_has_clear_message(self):
        with tempfile.TemporaryDirectory() as directory:
            backend_config.load_config.cache_clear()
            with patch.object(backend_config, "BASE_DIR", Path(directory)):
                with self.assertRaisesRegex(RuntimeError, "config.toml oluşturun"):
                    backend_config.load_config()

    def test_config_is_cached_after_first_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.example.toml").write_text('api_key = "first"', encoding="utf-8")
            backend_config.load_config.cache_clear()
            with patch.object(backend_config, "BASE_DIR", root):
                self.assertEqual(backend_config.load_config()["api_key"], "first")
                (root / "config.example.toml").write_text('api_key = "second"', encoding="utf-8")
                self.assertEqual(backend_config.load_config()["api_key"], "first")


if __name__ == "__main__":
    unittest.main()
