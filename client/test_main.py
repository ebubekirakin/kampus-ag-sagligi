"""İstemcinin kampüs doğrulama kararları için küçük testler."""

import unittest
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from client import main as client_main
from client.main import classify_campus


class TestCampusClassification(unittest.TestCase):
    def test_disconnected_device_is_not_verified(self):
        self.assertEqual(
            classify_campus({"connected": False}, {"campus_ssids": [], "campus_bssids": []}),
            (0.0, 0),
        )

    def test_both_local_network_identifiers_must_match_to_verify(self):
        config = {
            "campus_ssids": ["Campus-WiFi"],
            "campus_bssids": ["AA:BB:CC:DD:EE:FF"],
        }
        wifi = {
            "connected": True,
            "ssid": "campus-wifi",
            "bssid": "aa:bb:cc:dd:ee:ff",
        }
        self.assertEqual(classify_campus(wifi, config), (0.95, 1))

        wifi["bssid"] = "11:22:33:44:55:66"
        self.assertEqual(classify_campus(wifi, config), (0.6, 0))

    def test_empty_allow_list_does_not_claim_campus_verification(self):
        wifi = {"connected": True, "ssid": "Unknown", "bssid": "11:22:33:44:55:66"}
        self.assertEqual(classify_campus(wifi, {}), (0.25, 0))


class TestClientState(unittest.TestCase):
    def test_device_id_is_created_once_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(client_main, "CLIENT_DIR", Path(directory)):
                first = client_main.get_or_create_device_id()
                second = client_main.get_or_create_device_id()
                self.assertEqual(first, second)
                self.assertTrue((Path(directory) / "device_id.txt").exists())

    def test_zone_selection_remembers_last_choice(self):
        zones = ["Kütüphane", "Mühendislik"]
        response = Mock(status_code=200)
        response.json.return_value = zones
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(client_main, "CLIENT_DIR", Path(directory)):
                with patch("client.main.httpx.get", return_value=response):
                    with patch("builtins.input", return_value="2"):
                        self.assertEqual(client_main.select_zone("http://localhost"), "Mühendislik")
                    with patch("builtins.input", return_value=""):
                        self.assertEqual(client_main.select_zone("http://localhost"), "Mühendislik")


if __name__ == "__main__":
    unittest.main()
