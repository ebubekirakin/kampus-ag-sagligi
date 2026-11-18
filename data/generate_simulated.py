"""Yerli kampüs ağı için tekrarlanabilir, simüle ölçüm verisi üretir."""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import urllib.error
import urllib.request

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import load_config

# Sabit başlangıç tarihi sayesinde aynı seed aynı zaman damgalarını üretir.
SIMULATION_START_ANCHOR = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


def build_zone_aps(zones: list[str]) -> dict[str, list[str]]:
    """Her bölge için iki sahte AP adresi ve üçüncü bir yedek AP üretir."""
    return {
        zone: [
            f"02:00:{index // 256:02x}:{index % 256:02x}:00:01",
            f"02:00:{index // 256:02x}:{index % 256:02x}:00:02",
            f"02:00:{index // 256:02x}:{index % 256:02x}:00:03",
        ]
        for index, zone in enumerate(zones, start=1)
    }


def get_ground_truth_scenarios(zones: list[str], faulty_bssid: str) -> list[dict]:
    """Senaryoların bölge ve saat bilgilerini cevap anahtarı olarak döndürür."""
    # Az bölge tanımlanmışsa senaryolar mevcut bölgeleri paylaşır.
    scenario_zones = [zones[index % len(zones)] for index in range(4)]
    return [
        {
            "scenario_id": "congestion",
            "title": "Yoğun saatlerde tıkanıklık",
            "zone": scenario_zones[0],
            "bssid": None,
            "time_window": "Hafta içi 16:00-19:00",
            "issue_type": "high_latency",
        },
        {
            "scenario_id": "coverage_gap",
            "title": "Kapsama eksikliği",
            "zone": scenario_zones[1],
            "bssid": None,
            "time_window": "Sürekli",
            "issue_type": "low_signal_low_throughput",
        },
        {
            "scenario_id": "faulty_ap",
            "title": "Arızalı erişim noktası",
            "zone": scenario_zones[2],
            "bssid": faulty_bssid,
            "time_window": "Sürekli",
            "issue_type": "high_packet_loss",
        },
        {
            "scenario_id": "sudden_outage",
            "title": "Ani kısa süreli kesinti",
            "zone": scenario_zones[3],
            "bssid": None,
            "time_window": "7. gün 14:00-15:00 UTC",
            "issue_type": "service_outage",
        },
    ]


def parse_building_floor(zone_name: str) -> tuple[str, str]:
    """Bölge adından bina ve kat için basit, okunabilir etiketler çıkarır."""
    parts = zone_name.split()
    building = parts[0] if parts else "Kampüs"
    floor = "Bilinmiyor"
    for marker in ("1.", "2.", "3.", "4.", "Zemin", "Giriş"):
        if marker.lower() in zone_name.lower():
            floor = f"{marker} Kat"
            break
    return building, floor


def generate_measurements(days: int = 14, seed: int = 42) -> tuple[list[dict], list[dict]]:
    """Ölçümleri üretir; aynı gün sayısı ve seed aynı sonucu verir."""
    if days < 1:
        raise ValueError("Gün sayısı en az 1 olmalıdır.")

    rng = random.Random(seed)
    config = load_config()
    zones = config.get("zones", [])
    if not zones:
        raise ValueError("config.toml içindeki zones listesinde en az bir bölge olmalıdır.")

    zone_aps = build_zone_aps(zones)
    # Üçüncü senaryo için bir bölgenin ikinci AP'si arızalı olarak seçilir.
    faulty_zone = zones[2 % len(zones)]
    faulty_bssid = zone_aps[faulty_zone][1]
    ground_truth = get_ground_truth_scenarios(zones, faulty_bssid)

    device_hashes = [
        hashlib.sha256(f"netnabiz_sim_device_{index}".encode()).hexdigest()
        for index in range(1, 16)
    ]

    # Her bölge farklı, ama örnek kampüs değerleri içinde kalan bir temel profile sahiptir.
    profiles = {
        zone: {
            "rtt": rng.uniform(15, 40),
            "down": rng.uniform(30, 100),
            "up": rng.uniform(10, 40),
            "rssi": rng.uniform(-75, -45),
        }
        for zone in zones
    }

    measurements = []
    for day_index in range(days):
        day = SIMULATION_START_ANCHOR + timedelta(days=day_index)
        weekend = day.weekday() >= 5

        for hour in range(24):
            busy_hour = 12 <= hour < 14 or 16 <= hour < 18
            if weekend:
                count = rng.randint(1, 3) if 10 <= hour < 20 else rng.randint(0, 1)
            elif busy_hour:
                count = rng.randint(8, 14)
            elif 8 <= hour < 22:
                count = rng.randint(4, 7)
            else:
                count = rng.randint(0, 2)

            for _ in range(count):
                timestamp = day.replace(
                    hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59)
                )
                zone = rng.choice(zones)
                building, floor = parse_building_floor(zone)
                bssid = rng.choice(zone_aps[zone])
                profile = profiles[zone]

                # Temel ölçüm çevresine küçük, rastgele değişimler eklenir.
                rtt = max(1.0, rng.gauss(profile["rtt"], 4))
                loss_pct = max(0.0, rng.gauss(0.5, 0.35))
                down_mbps = max(1.0, rng.gauss(profile["down"], 8))
                up_mbps = max(1.0, rng.gauss(profile["up"], 4))
                rssi = rng.gauss(profile["rssi"], 3)

                # Hafta içi yoğun saatlerde genel gecikme ve ölçüm sayısı artar.
                if not weekend and busy_hour:
                    rtt += rng.uniform(5, 15)

                if zone == ground_truth[0]["zone"] and not weekend and 16 <= hour < 19:
                    # İyi sinyale rağmen yoğunluk gecikmeyi yükseltir.
                    rtt = rng.uniform(160, 310)
                    rssi = rng.uniform(-55, -48)
                elif zone == ground_truth[1]["zone"]:
                    rssi = rng.uniform(-85, -78)
                    down_mbps = rng.uniform(1.8, 4.8)
                    up_mbps = rng.uniform(0.8, 2.5)
                    rtt = rng.uniform(45, 75)

                if zone == faulty_zone and bssid == faulty_bssid:
                    loss_pct = rng.uniform(12, 26)

                # 7. gün oluşacak çöküş ayrıca garanti edilir; aşağıdaki koşul
                # o saatte rastgele seçilen normal kayıtları da kesinti yapar.
                if zone == ground_truth[3]["zone"] and day_index == 6 and hour == 14:
                    rtt = rng.uniform(520, 780)
                    loss_pct = rng.uniform(50, 85)
                    down_mbps = rng.uniform(0.2, 0.9)
                    up_mbps = rng.uniform(0.1, 0.4)

                if rng.random() < 0.015:
                    rtt += rng.uniform(200, 400)
                    loss_pct = min(100.0, loss_pct + rng.uniform(10, 30))

                is_off_campus = rng.random() < 0.05
                measurements.append({
                    "device_hash": rng.choice(device_hashes),
                    "source": "desktop",
                    "ssid": rng.choice(["Cafe_WiFi", "Ev_Fiber", "Misafir_Hotspot"]) if is_off_campus else "Kampus_WiFi",
                    "bssid": "00:aa:bb:cc:dd:ee" if is_off_campus else bssid,
                    "rssi_dbm": round(min(-45.0, max(-85.0, rssi)), 1),
                    "rtt_ms": round(rtt, 1),
                    "loss_pct": round(loss_pct, 1),
                    "down_mbps": round(down_mbps, 2),
                    "up_mbps": round(up_mbps, 2),
                    "building": building,
                    "floor": floor,
                    "zone": zone,
                    "campus_confidence": round(rng.uniform(0.05, 0.25), 2) if is_off_campus else round(rng.uniform(0.92, 1.0), 2),
                    "is_verified": 0 if is_off_campus else 1,
                    "is_simulated": 1,
                    "timestamp": timestamp.isoformat(),
                })

    # 14 günlük çalıştırmada kesinti senaryosu mutlaka bir satırla temsil edilir.
    if days >= 7:
        zone = ground_truth[3]["zone"]
        building, floor = parse_building_floor(zone)
        outage_time = SIMULATION_START_ANCHOR + timedelta(days=6, hours=6, minutes=30)
        measurements.append({
            "device_hash": device_hashes[0],
            "source": "desktop",
            "ssid": "Kampus_WiFi",
            "bssid": zone_aps[zone][0],
            "rssi_dbm": -55.0,
            "rtt_ms": 650.0,
            "loss_pct": 65.0,
            "down_mbps": 0.5,
            "up_mbps": 0.2,
            "building": building,
            "floor": floor,
            "zone": zone,
            "campus_confidence": 0.99,
            "is_verified": 1,
            "is_simulated": 1,
            "timestamp": outage_time.isoformat(),
        })

    return measurements, ground_truth


def save_ground_truth(ground_truth: list[dict], filepath: Path) -> None:
    """Gömülü senaryoları JSON cevap anahtarına yazar."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")


def export_csv(measurements: list[dict], filepath: Path) -> None:
    """Ölçümleri CSV dosyasına yazar."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fields = list(measurements[0]) if measurements else []
    with filepath.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(measurements)


def send_to_api(measurements: list[dict], api_url: str, api_key: str = "") -> tuple[int, int]:
    """Her ölçümü POST eder ve başarılı/hatalı kayıt sayılarını döndürür."""
    total = len(measurements)
    if total == 0:
        return 0, 0

    key = api_key or load_config().get("api_key", "yerel-gelistirme-anahtari")

    # Sunucunun çalışıp çalışmadığını başlangıçta kontrol et
    base_url = api_url.rsplit("/", 1)[0]
    health_url = f"{base_url}/health"
    try:
        with urllib.request.urlopen(health_url, timeout=3) as resp:
            if resp.status != 200:
                raise ValueError("Sunucu sağlık kontrolü başarısız.")
    except Exception:
        print(f"\n[!] HATA: '{api_url}' adresindeki sunucuya ulaşılamadı!")
        print("[!] Lütfen önce başka bir terminal penceresinde sunucuyu başlatın:")
        print("    uvicorn backend.main:app --reload\n")
        return 0, total

    print(f"[*] API'ye aktarılıyor: {api_url} ({total} adet ölçüm)...")
    success = 0
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": key,
    }
    for index, item in enumerate(measurements, start=1):
        request = urllib.request.Request(
            api_url,
            data=json.dumps(item).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status in (200, 201):
                    success += 1
        except (urllib.error.URLError, TimeoutError):
            continue

        # Büyük veri aktarımında ilerleme bilgisi ver
        if total > 50 and (index % 250 == 0 or index == total):
            print(f"  -> {index}/{total} ölçüm gönderildi...")

    return success, total - success


def print_summary(measurements: list[dict], ground_truth: list[dict], result: str) -> None:
    """Üretilen ve doğrulanan ölçümlerle senaryo listesini özetler."""
    total = len(measurements)
    verified = sum(item["is_verified"] == 1 for item in measurements)
    print(f"Ölçüm: {total} | Doğrulanmış: {verified} | Doğrulanmamış: {total - verified}")
    print(result)
    print("Gömülü sorunlar:")
    for scenario in ground_truth:
        print(f"- {scenario['title']}: {scenario['zone']} / {scenario['time_window']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="NetNabız simüle ölçüm üreticisi")
    parser.add_argument("--days", type=int, default=14, help="Üretilecek gün sayısı (varsayılan: 14)")
    parser.add_argument("--seed", type=int, default=42, help="Tekrarlanabilirlik tohumu (varsayılan: 42)")
    parser.add_argument("--mode", choices=("api", "csv"), default="api", help="Çıktı modu (api veya csv)")
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://127.0.0.1:8000/measurements",
        help="FastAPI measurements uç noktası",
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default="data/simulated.csv",
        help="CSV modu için dosya yolu",
    )
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days en az 1 olmalıdır.")

    measurements, scenarios = generate_measurements(args.days, args.seed)
    save_ground_truth(scenarios, BASE_DIR / "data" / "ground_truth.json")

    if args.mode == "csv":
        csv_path = BASE_DIR / args.csv_path
        export_csv(measurements, csv_path)
        result = f"CSV dosyası yazıldı: {csv_path}"
    else:
        success, errors = send_to_api(measurements, args.api_url)
        result = f"API kayıtları: {success} başarılı, {errors} hatalı"

    print_summary(measurements, scenarios, result)


if __name__ == "__main__":
    main()
