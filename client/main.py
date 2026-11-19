"""
NetNabız Gerçek Masaüstü Ölçüm İstemcisi.
Kullanıcının bilgisayarından Wi-Fi bilgilerini ve ağ performansını ölçer,
seçilen kampüs bölgesiyle eşleştirip yerel FastAPI sunucusuna gönderir.
Sunucu kapalıysa ölçümleri 'pending.jsonl' dosyasına biriktirir.
"""

import argparse
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys
import time
import tomllib
import uuid
import httpx

from client.network_tests import run_network_tests
from client.wifi_info import get_wifi_info
from project_utils import parse_building_floor

# İstemci klasör yolu
CLIENT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def load_client_config() -> dict:
    """İstemci ayarlarını bir kez okur; eksik veya bozuksa anlaşılır hata verir."""
    local_file = CLIENT_DIR / "client_config.toml"
    example_file = CLIENT_DIR / "client_config.example.toml"

    try:
        config = {}
        if example_file.exists():
            with open(example_file, "rb") as file:
                config.update(tomllib.load(file))
        if local_file.exists():
            with open(local_file, "rb") as file:
                config.update(tomllib.load(file))
        if not config:
            raise FileNotFoundError(example_file)
        return config
    except FileNotFoundError as error:
        raise RuntimeError(
            "İstemci ayarı bulunamadı. client_config.example.toml dosyasını "
            "client_config.toml adıyla kopyalayın."
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(
            f"İstemci ayarı okunamadı. TOML yazımını kontrol edin: {error}"
        ) from error
    except OSError as error:
        raise RuntimeError(f"İstemci ayarı açılamadı: {error}") from error


def get_or_create_device_id() -> str:
    """
    Cihaz için kalıcı, rastgele bir UUID üretir veya mevcut olanı okur.
    Gerçek cihaz MAC/IP adresi yerine bu kimlik kullanılır ve sunucuya hash'lenerek iletilir.
    """
    device_file = CLIENT_DIR / "device_id.txt"
    if device_file.exists():
        device_id = device_file.read_text(encoding="utf-8").strip()
        if device_id:
            return device_id

    new_id = str(uuid.uuid4())
    device_file.write_text(new_id, encoding="utf-8")
    return new_id


def select_zone(server_url: str, fallback_zones: list[str]) -> str:
    """
    Kullanıcıya bölgeleri numaralı liste olarak sunar ve seçim yaptırır.
    Son seçimi 'last_zone.txt' dosyasına kaydeder.
    """
    zones = []
    # 1. Sunucudan bölge listesini almayı dene
    try:
        resp = httpx.get(f"{server_url}/zones", timeout=3.0)
        if resp.status_code == 200:
            server_zones = resp.json()
            if isinstance(server_zones, list) and all(
                isinstance(zone, str) and zone.strip() for zone in server_zones
            ):
                zones = server_zones
    except Exception:
        pass

    # Sunucu kapalıysa yerel ayar dosyasındaki bölgeler kullanılır.
    if not zones:
        zones = [zone for zone in fallback_zones if isinstance(zone, str) and zone.strip()]
    if not zones:
        raise RuntimeError(
            "Bölge listesi alınamadı. Sunucuyu açın veya client_config.toml içindeki "
            "zones listesine bölgeleri ekleyin."
        )

    last_zone_file = CLIENT_DIR / "last_zone.txt"
    last_zone = None
    if last_zone_file.exists():
        last_zone = last_zone_file.read_text(encoding="utf-8").strip()
        if last_zone not in zones:
            last_zone = None

    print("\n--- Ölçüm Yapılacak Bölgeyi Seçin ---")
    for idx, z in enumerate(zones, start=1):
        marker = " (Son Seçim)" if z == last_zone else ""
        print(f"  [{idx}] {z}{marker}")

    prompt_text = "Seçiminiz"
    if last_zone:
        prompt_text += f" (Varsayılan: '{last_zone}', Enter tuşuna basabilirsiniz)"
    prompt_text += ": "

    selected = None
    while not selected:
        try:
            user_input = input(prompt_text).strip()
            if not user_input and last_zone:
                selected = last_zone
                break
            if user_input.isdigit():
                num = int(user_input)
                if 1 <= num <= len(zones):
                    selected = zones[num - 1]
                    break
            # Doğrudan isim girilmişse
            if user_input in zones:
                selected = user_input
                break
            print("Geçersiz seçim. Lütfen listedeki bir numarayı girin.")
        except (EOFError, KeyboardInterrupt):
            selected = last_zone if last_zone in zones else zones[0]
            print(f"\nOtomatik seçim: {selected}")
            break

    last_zone_file.write_text(selected, encoding="utf-8")
    return selected


def classify_campus(wifi: dict, config: dict) -> tuple[float, int]:
    """Yerel izin listesiyle ağı sınıflandırır; eşleşme yoksa doğrulanmamış bırakır."""
    if not wifi.get("connected"):
        return 0.0, 0

    known_ssids = {item.casefold() for item in config.get("campus_ssids", [])}
    known_bssids = {item.upper() for item in config.get("campus_bssids", [])}
    ssid_matches = wifi.get("ssid", "").casefold() in known_ssids if wifi.get("ssid") else False
    bssid_matches = wifi.get("bssid", "").upper() in known_bssids if wifi.get("bssid") else False

    # Yalnızca SSID eşleşmesi kolay taklit edilebilir; doğrulama için iki alan da eşleşmeli.
    if ssid_matches and bssid_matches:
        return 0.95, 1
    if ssid_matches or bssid_matches:
        return 0.6, 0
    return 0.25, 0


def send_pending_measurements(server_url: str, api_key: str, debug: bool = False):
    """
    Daha önce sunucu kapalıyken 'pending.jsonl' dosyasına yazılmış
    bekleyen ölçümleri sunucuya yeniden göndermeyi dener.
    """
    pending_file = CLIENT_DIR / "pending.jsonl"
    if not pending_file.exists():
        return

    lines = pending_file.read_text(encoding="utf-8").splitlines()
    if not lines:
        return

    print(f"[*] Çevrimdışı kuyrukta {len(lines)} adet bekleyen ölçüm bulundu, gönderiliyor...")
    still_pending = []
    sent_count = 0

    headers = {"Content-Type": "application/json", "X-API-Key": api_key}

    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            resp = httpx.post(f"{server_url}/measurements", json=payload, headers=headers, timeout=5.0)
            if resp.status_code in (200, 201):
                sent_count += 1
            else:
                still_pending.append(line)
        except Exception:
            still_pending.append(line)

    if still_pending:
        pending_file.write_text("\n".join(still_pending) + "\n", encoding="utf-8")
        if debug:
            print(f"[!] {len(still_pending)} adet ölçüm halen bekliyor.")
    else:
        pending_file.unlink(missing_ok=True)
        print(f"[+] Bekleyen {sent_count} ölçümün tamamı sunucuya başarıyla aktarıldı!")


def save_pending_measurement(payload: dict):
    """Sunucuya ulaşılamadığında ölçümü kuyruk dosyasına ekler."""
    pending_file = CLIENT_DIR / "pending.jsonl"
    with open(pending_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print("  [!] Sunucuya ulaşılamadı. Ölçüm 'client/pending.jsonl' dosyasına kaydedildi (kuyruk).")


def perform_single_measurement(
    config: dict,
    zone: str,
    device_hash: str,
    debug: bool = False,
):
    """Tek bir Wi-Fi ve ağ testi turu gerçekleştirip sonucu sunucuya gönderir."""
    server_url = config.get("server_url", "http://127.0.0.1:8000")
    api_key = config.get("api_key", "yerel-gelistirme-anahtari")

    print("\n" + "=" * 65)
    print(f"[*] Ölçüm Başlatılıyor... [{datetime.now().strftime('%H:%M:%S')}]")
    print(f"    Seçilen Bölge: {zone}")

    # 1. Wi-Fi bilgilerini oku
    print("[1/2] Wi-Fi bağdaştırıcı bilgileri taranıyor...")
    wifi = get_wifi_info(debug=debug)

    # 2. Ağ performansını test et
    print("[2/2] Gecikme, paket kaybı ve hız testleri yapılıyor...")
    net = run_network_tests(config, debug=debug)

    building, floor = parse_building_floor(zone)

    campus_confidence, is_verified = classify_campus(wifi, config)

    payload = {
        "device_hash": device_hash,
        "source": "desktop",
        "ssid": wifi.get("ssid"),
        "bssid": wifi.get("bssid"),
        "rssi_dbm": wifi.get("rssi_dbm"),
        "rtt_ms": net["rtt_ms"],
        "loss_pct": net["loss_pct"],
        "down_mbps": net["down_mbps"],
        "up_mbps": net["up_mbps"],
        "building": building,
        "floor": floor,
        "zone": zone,
        "campus_confidence": campus_confidence,
        "is_verified": is_verified,
        "is_simulated": 0,  # Gerçek ölçüm
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # İnsan okunabilir özet çıktısı
    sig_str = f"{wifi.get('rssi_dbm')} dBm" if wifi.get("rssi_dbm") is not None else "Ölçülemedi"
    rtt_str = f"{net['rtt_ms']:.1f} ms" if net["rtt_ms"] is not None else "Ölçülemedi"
    loss_str = f"%{net['loss_pct']:.0f}" if net["loss_pct"] is not None else "Ölçülemedi"
    down_str = f"{net['down_mbps']:.2f} Mbps" if net["down_mbps"] is not None else "Ölçülemedi"
    up_str = f"{net['up_mbps']:.2f} Mbps" if net["up_mbps"] is not None else "Ölçülemedi"

    print("-" * 65)
    print(
        f"  Gecikme: {rtt_str} | Kayıp: {loss_str} | İndirme: {down_str} | "
        f"Yükleme: {up_str} | Sinyal: {sig_str}"
    )
    print(f"  SSID: {wifi.get('ssid') or 'Bağlı Değil'} | BSSID: {wifi.get('bssid') or 'Yok'}")
    print("-" * 65)

    # 3. Sunucuya gönder
    headers = {"Content-Type": "application/json", "X-API-Key": api_key}
    try:
        resp = httpx.post(f"{server_url}/measurements", json=payload, headers=headers, timeout=5.0)
        if resp.status_code in (200, 201):
            print(f"  [+] Ölçüm sunucuya kaydedildi (ID: {resp.json().get('id')})")
        else:
            print(f"  [!] Sunucu hata döndürdü ({resp.status_code}): {resp.text}")
            save_pending_measurement(payload)
    except Exception as exc:
        if debug:
            print(f"  [DEBUG Bağlantı Hatası] {exc}")
        save_pending_measurement(payload)


def main():
    parser = argparse.ArgumentParser(description="NetNabız Gerçek Masaüstü Ölçüm İstemcisi")
    parser.add_argument("--repeat", type=int, default=1, help="Ölçüm tekrar sayısı (varsayılan: 1)")
    parser.add_argument("--interval", type=int, default=60, help="Tekrarlar arası bekleme saniyesi (varsayılan: 60)")
    parser.add_argument("--debug", action="store_true", help="Detaylı hata ayıklama çıktılarını göster")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat en az 1 olmalıdır.")
    if args.interval < 0:
        parser.error("--interval negatif olamaz.")

    try:
        config = load_client_config()
    except RuntimeError as error:
        parser.error(str(error))
    server_url = config.get("server_url", "http://127.0.0.1:8000")
    api_key = config.get("api_key", "yerel-gelistirme-anahtari")

    # Cihaz kimliği (UUID hash)
    raw_device_id = get_or_create_device_id()
    device_hash = hashlib.sha256(raw_device_id.encode()).hexdigest()

    # Kullanıcıdan bölge seçimi al
    try:
        selected_zone = select_zone(server_url, config.get("zones", []))
    except RuntimeError as error:
        parser.error(str(error))

    # Varsa önce çevrimdışı kuyruktaki bekleyenleri gönder
    send_pending_measurements(server_url, api_key, debug=args.debug)

    # Ölçüm döngüsü
    for round_idx in range(1, args.repeat + 1):
        perform_single_measurement(
            config=config,
            zone=selected_zone,
            device_hash=device_hash,
            debug=args.debug,
        )
        if round_idx < args.repeat:
            print(f"\nSonraki ölçüm için {args.interval} saniye bekleniyor (Ctrl+C ile durdurabilirsiniz)...")
            time.sleep(args.interval)

    print("\n[+] İstemci ölçüm işlemlerini tamamladı.\n")


if __name__ == "__main__":
    main()
