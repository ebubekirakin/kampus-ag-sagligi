"""
Windows Wi-Fi Bilgisi Okuma Modülü.
'netsh wlan show interfaces' komutunu çalıştırarak bağlı bulunulan
ağın SSID, BSSID ve sinyal gücü (dBm tahmini) bilgilerini ayrıştırır.
Hem Türkçe hem İngilizce Windows sürümlerini destekler.
"""

import locale
import subprocess
import sys


def parse_netsh_output(raw_output: str) -> dict:
    """
    netsh wlan show interfaces çıktısını ayrıştırır.
    İngilizce ve Türkçe alan adlarını destekler.
    
    Not: dBm hesabı 'yüzde / 2 - 100' formülüyle hesaplanan YAKLAŞIK bir değerdir.
    """
    result = {
        "connected": False,
        "ssid": None,
        "bssid": None,
        "signal_pct": None,
        "rssi_dbm": None,
        "state": None,
    }

    if not raw_output or not raw_output.strip():
        return result

    for line in raw_output.splitlines():
        if ":" not in line:
            continue

        parts = line.split(":", 1)
        key = parts[0].strip()
        val = parts[1].strip()

        # SSID ve BSSID satırlarını kesin eşleşmeyle ayır
        if key.upper() == "SSID":
            result["ssid"] = val if val else None
        elif key.upper() == "BSSID":
            result["bssid"] = val if val else None
        elif key.lower() in ("state", "durum"):
            result["state"] = val.lower()
            if val.lower() in ("connected", "bağlı"):
                result["connected"] = True
        elif key.lower() in ("signal", "sinyal"):
            # Değer '85%' veya '%85' şeklinde gelebilir
            clean_pct = val.replace("%", "").strip()
            try:
                pct = float(clean_pct)
                result["signal_pct"] = int(pct)
                # Yaklaşık dBm dönüşümü: 100% -> -50 dBm, 0% -> -100 dBm
                result["rssi_dbm"] = round((pct / 2.0) - 100.0, 1)
            except ValueError:
                pass

    # Durum bilgisi satırı yoksa ama geçerli bir SSID varsa bağlı kabul et
    if not result["connected"] and result["ssid"]:
        result["connected"] = True

    # Eğer bağlantı kopuksa değerleri temizle
    if not result["connected"]:
        result["ssid"] = None
        result["bssid"] = None
        result["rssi_dbm"] = None

    return result


def get_wifi_info(debug: bool = False) -> dict:
    """
    Sistemdeki Wi-Fi arabirim bilgilerini çeker.
    Wi-Fi kapalıysa veya okuma hatası olursa program çökmez, None değerler döner.
    """
    system_encoding = locale.getpreferredencoding() or "utf-8"

    try:
        process = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        # Windows konsol kodlaması (Türkçe karakterler için cp857 veya cp1254 olabilmektedir)
        raw_text = process.stdout.decode(system_encoding, errors="replace")
    except Exception as exc:
        raw_text = f"Hata: {str(exc)}"

    if debug:
        print("\n--- [DEBUG] Ham netsh Çıktısı ---")
        print(raw_text)
        print("--------------------------------\n")

    info = parse_netsh_output(raw_text)

    # Kullanıcıya bilgilendirme / uyarı (bilgi okunamadıysa)
    if not info["connected"]:
        # Yaygın Windows 10/11 konum/servis kısıtlamaları uyarısı
        warning_msg = (
            "[!] Wi-Fi bilgisi alınamadı (Wi-Fi kapalı, kablolu ağ veya erişim kısıtlı olabilir).\n"
            "    İpucu: Windows Ayarlar > Gizlilik ve Güvenlik > Konum servislerinin açık olduğundan emin olun."
        )
        if debug:
            print(warning_msg)

    return info


if __name__ == "__main__":
    is_debug = "--debug" in sys.argv
    current_wifi = get_wifi_info(debug=is_debug)
    print("Ayrıştırılan Wi-Fi Bilgileri:")
    for k, v in current_wifi.items():
        print(f"  {k}: {v}")
