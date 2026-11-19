"""İstemci ayar dosyasının hata mesajı ve önbellek kontrolleri."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from client import main as client_main


class TestClientConfig(unittest.TestCase):
    def tearDown(self):
        client_main.load_client_config.cache_clear()

    def test_missing_config_has_clear_message(self):
        with tempfile.TemporaryDirectory() as directory:
            client_main.load_client_config.cache_clear()
            with patch.object(client_main, "CLIENT_DIR", Path(directory)):
                with self.assertRaisesRegex(RuntimeError, "client_config.example.toml"):
                    client_main.load_client_config()

    def test_example_config_is_used_if_local_copy_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "client_config.example.toml").write_text(
                'server_url = "http://127.0.0.1:8000"', encoding="utf-8"
            )
            client_main.load_client_config.cache_clear()
            with patch.object(client_main, "CLIENT_DIR", root):
                config = client_main.load_client_config()
            self.assertEqual(config["server_url"], "http://127.0.0.1:8000")

    def test_local_settings_keep_example_zone_fallbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "client_config.example.toml").write_text(
                'server_url = "http://127.0.0.1:8000"\nzones = ["Zone A"]',
                encoding="utf-8",
            )
            (root / "client_config.toml").write_text(
                'api_key = "local-key"', encoding="utf-8"
            )
            client_main.load_client_config.cache_clear()
            with patch.object(client_main, "CLIENT_DIR", root):
                config = client_main.load_client_config()
            self.assertEqual(config["api_key"], "local-key")
            self.assertEqual(config["zones"], ["Zone A"])


if __name__ == "__main__":
    unittest.main()
