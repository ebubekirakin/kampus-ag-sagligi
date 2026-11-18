"""
Wi-Fi Bilgisi Ayrıştırma Testleri.
Hem İngilizce hem Türkçe netsh çıktılarını, sinyal/dBm dönüşümünü
ve bağlantı kesikliği durumlarını test eder.
"""

import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from client.wifi_info import get_wifi_info, parse_netsh_output


ENGLISH_NETSH_SAMPLE = """
There is 1 interface on the system: 

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : a1b2c3d4-e5f6-7890-1234-567890abcdef
    Physical address       : 12:34:56:78:9a:bc
    State                  : connected
    SSID                   : Kampus_WiFi
    BSSID                  : 02:00:00:11:00:01
    Network type           : Infrastructure
    Radio type             : 802.11ax
    Authentication         : WPA2-Enterprise
    Cipher                 : CCMP
    Connection mode        : Profile
    Channel                : 36
    Receive rate (Mbps)    : 866
    Transmit rate (Mbps)   : 866
    Signal                 : 85% 
    Profile                : Kampus_WiFi 

    Hosted network status  : Not available
"""

TURKISH_NETSH_SAMPLE = """
Sistemde 1 arabirim var: 

    Ad                     : Wi-Fi
    Açıklama               : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : a1b2c3d4-e5f6-7890-1234-567890abcdef
    Fiziksel adres         : 12:34:56:78:9a:bc
    Durum                  : bağlı
    SSID                   : Kampus_WiFi
    BSSID                  : 02:00:00:22:00:02
    Ağ türü                : Altyapı
    Radyo türü             : 802.11ax
    Kimlik doğrulama       : WPA2-Enterprise
    Şifre                  : CCMP
    Bağlantı modu          : Profil
    Kanal                  : 36
    Alma hızı (Mbps)       : 866
    İletim hızı (Mbps)     : 866
    Sinyal                 : %90 
    Profil                 : Kampus_WiFi 

    Barındırılan ağ durumu : Kullanılamıyor
"""

DISCONNECTED_ENGLISH_SAMPLE = """
There is 1 interface on the system: 

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    State                  : disconnected
    Radio status           : Hardware On, Software On
"""

DISCONNECTED_TURKISH_SAMPLE = """
Sistemde 1 arabirim var: 

    Ad                     : Wi-Fi
    Açıklama               : Intel(R) Wi-Fi 6 AX201 160MHz
    Durum                  : bağlantı kesildi
    Radyo durumu           : Donanım Açık, Yazılım Açık
"""


class TestWifiInfo(unittest.TestCase):
    def test_english_netsh_parsing(self):
        """İngilizce Windows çıktısının doğru ayrıştırıldığını doğrular."""
        res = parse_netsh_output(ENGLISH_NETSH_SAMPLE)
        self.assertTrue(res["connected"])
        self.assertEqual(res["ssid"], "Kampus_WiFi")
        self.assertEqual(res["bssid"], "02:00:00:11:00:01")
        self.assertEqual(res["signal_pct"], 85)
        # 85 / 2 - 100 = 42.5 - 100 = -57.5 dBm
        self.assertEqual(res["rssi_dbm"], -57.5)

    def test_turkish_netsh_parsing(self):
        """Türkçe Windows çıktısının doğru ayrıştırıldığını doğrular."""
        res = parse_netsh_output(TURKISH_NETSH_SAMPLE)
        self.assertTrue(res["connected"])
        self.assertEqual(res["ssid"], "Kampus_WiFi")
        self.assertEqual(res["bssid"], "02:00:00:22:00:02")
        self.assertEqual(res["signal_pct"], 90)
        # 90 / 2 - 100 = 45 - 100 = -55.0 dBm
        self.assertEqual(res["rssi_dbm"], -55.0)

    def test_percentage_to_dbm_conversion(self):
        """Yüzde -> dBm dönüşüm formülünün (yüzde / 2 - 100) doğruluğunu test eder."""
        sample_100 = "State: connected\nSSID: Test\nBSSID: 00:11:22:33:44:55\nSignal: 100%"
        res_100 = parse_netsh_output(sample_100)
        self.assertEqual(res_100["rssi_dbm"], -50.0)

        sample_50 = "State: connected\nSSID: Test\nBSSID: 00:11:22:33:44:55\nSignal: 50%"
        res_50 = parse_netsh_output(sample_50)
        self.assertEqual(res_50["rssi_dbm"], -75.0)

        sample_0 = "State: connected\nSSID: Test\nBSSID: 00:11:22:33:44:55\nSignal: 0%"
        res_0 = parse_netsh_output(sample_0)
        self.assertEqual(res_0["rssi_dbm"], -100.0)

    def test_disconnected_and_missing_wifi_handles_safely(self):
        """Bağlantı kesikken veya Wi-Fi yokken çökmeden None döndüğünü test eder."""
        res_en = parse_netsh_output(DISCONNECTED_ENGLISH_SAMPLE)
        self.assertFalse(res_en["connected"])
        self.assertIsNone(res_en["ssid"])
        self.assertIsNone(res_en["bssid"])
        self.assertIsNone(res_en["rssi_dbm"])

        res_tr = parse_netsh_output(DISCONNECTED_TURKISH_SAMPLE)
        self.assertFalse(res_tr["connected"])
        self.assertIsNone(res_tr["ssid"])
        self.assertIsNone(res_tr["bssid"])

        # Tamamen boş veya hata mesajı içeren çıktı
        res_empty = parse_netsh_output("There is no wireless interface on the system.")
        self.assertFalse(res_empty["connected"])
        self.assertIsNone(res_empty["ssid"])

    def test_explicit_disconnected_state_wins_over_ssid(self):
        sample = "State: disconnected\nSSID: OldNetwork\nBSSID: 00:11:22:33:44:55\nSignal: 80%"
        result = parse_netsh_output(sample)
        self.assertFalse(result["connected"])
        self.assertIsNone(result["ssid"])
        self.assertIsNone(result["bssid"])
        self.assertIsNone(result["signal_pct"])

    def test_wifi_unavailable_warning_is_not_debug_only(self):
        process = SimpleNamespace(stdout=b"", stderr=b"", returncode=1)
        output = StringIO()
        with patch("client.wifi_info.subprocess.run", return_value=process):
            with redirect_stdout(output):
                result = get_wifi_info(debug=False)
        self.assertFalse(result["connected"])
        self.assertIn("Konum", output.getvalue())


if __name__ == "__main__":
    unittest.main()
