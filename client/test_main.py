"""İstemcinin kampüs doğrulama kararları için küçük testler."""

import unittest

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


if __name__ == "__main__":
    unittest.main()
