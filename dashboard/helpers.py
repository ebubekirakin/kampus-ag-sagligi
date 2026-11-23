"""
NetNabız Dashboard Yardımcı Fonksiyonları.
Panel arayüzünde kullanılan saf (pure), test edilebilir iş mantığı fonksiyonlarını içerir.
Kesinlikle ham cihaz kimliği (device_hash), SSID veya ham BSSID döndürmez.
"""

from typing import Any
from pathlib import Path
import pandas as pd
from analytics.forecast import predict_seasonal_rtt
from backend.config import load_config
from analytics.summary import generate_ap_aliases, mask_issues_bssids


def get_score_badge(score: float | None, config: dict | None = None) -> tuple[str, str, str]:
    """
    Skor değerini (0-100) renk, etiket ve hex renk koduna dönüştürür.
    Renk körlüğü için renkle birlikte her zaman metin etiketi ('İyi', 'Orta', 'Zayıf') sağlar.

    Dönüş:
        (renk_adi, etiket, hex_kod)
        Örnek: ('yeşil', 'İyi', '#28a745')
    """
    if config is None:
        config = load_config()
    cfg = config.get("analytics", {})
    score_green = cfg.get("score_green", 75.0)
    score_yellow = cfg.get("score_yellow", 50.0)

    if score is None:
        return "gri", "Yetersiz veri", "#6c757d"
    if score >= score_green:
        return "yeşil", "İyi", "#28a745"
    if score >= score_yellow:
        return "sarı", "Orta", "#ffc107"
    return "kırmızı", "Zayıf", "#dc3545"


def parse_building_floor_zone(zone_name: str) -> tuple[str, str, str]:
    """
    Bölge adını Bina -> Kat -> Bölge şeklinde ayrıştırır.

    Örnekler:
      'Kütüphane 1. kat Okuma salonu' -> ('Kütüphane', '1. kat', 'Kütüphane 1. kat Okuma salonu')
      'Mühendislik B Blok 2. kat Derslik koridoru' -> ('Mühendislik B Blok', '2. kat', ...)
      'Yemekhane Zemin Kat' -> ('Yemekhane', 'Zemin Kat', ...)
    """
    parts = zone_name.strip().split()
    if not parts:
        return "Bilinmeyen Bina", "Bilinmeyen Kat", zone_name

    building = parts[0]
    floor = "Genel"

    floor_markers = {"1.", "2.", "3.", "4.", "5.", "zemin", "giriş", "bodrum", "asma"}
    for index, part in enumerate(parts):
        if part.casefold() in floor_markers:
            building = " ".join(parts[:index]) or parts[0]
            if index + 1 < len(parts) and parts[index + 1].casefold() == "kat":
                floor = f"{part} kat" if part.endswith(".") else f"{part.capitalize()} Kat"
            else:
                floor = f"{part} kat" if part.endswith(".") else f"{part.capitalize()} Kat"
            break

    return building, floor, zone_name


def group_zones_by_hierarchy(zone_scores: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """
    Bölge skorlarını Bina -> Kat hiyerarşisinde gruplar.
    Dönüş: {bina: {kat: [bölge_verisi, ...]}}
    """
    hierarchy: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in zone_scores:
        zone_name = item.get("zone", "")
        building, floor, _ = parse_building_floor_zone(zone_name)
        if building not in hierarchy:
            hierarchy[building] = {}
        if floor not in hierarchy[building]:
            hierarchy[building][floor] = []
        hierarchy[building][floor].append(item)
    return hierarchy


def find_best_spot(
    df: pd.DataFrame,
    is_weekend: bool,
    hour: int,
    zone_scores: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Seçilen gün türü ve saat için en düşük tahmini gecikmeye sahip bölgeyi önerir.
    ÖNEMLİ: Yetersiz veri ('yetersiz veri' / score is None) olan bölgeler ASLA önerilmez.
    """
    if df.empty or not zone_scores:
        return None

    # Yalnızca yeterli verisi ve skoru olan bölgeleri aday al
    valid_scores = {
        item["zone"]: item
        for item in zone_scores
        if item.get("score") is not None and item.get("status") != "yetersiz veri"
    }
    if not valid_scores:
        return None

    candidates = []
    for zone, score_info in valid_scores.items():
        z_df = df[df["zone"] == zone]
        if z_df.empty or "rtt_ms" not in z_df.columns:
            continue

        # Tahmini, analizdeki mevsimsel medyan yöntemiyle aynı fonksiyondan al.
        est_rtt = predict_seasonal_rtt(df, zone, is_weekend, hour)
        if est_rtt is None:
            continue

        candidates.append({
            "zone": zone,
            "estimated_rtt_ms": round(est_rtt, 1),
            "score": score_info["score"],
            "status": score_info["status"],
            "color": score_info["color"],
            "median_down_mbps": score_info.get("median_down_mbps"),
        })

    if not candidates:
        return None

    # En düşük tahmini gecikmeli bölgeyi seç (eşitlik durumunda en yüksek skor)
    best = min(candidates, key=lambda c: (c["estimated_rtt_ms"], -c["score"]))
    return best


def find_underperforming_forecast_zones(forecast_result: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Mevsimsel yöntemin tekil medyan taban yönteminden DAHA KÖTÜ (MAE değeri daha yüksek)
    olduğu bölgeleri veriden dinamik olarak hesaplar. Rakamları koda elle yazmaz.
    """
    comparisons = forecast_result.get("zone_comparison", [])
    underperforming = []
    for item in comparisons:
        mae_s = item.get("mae_seasonal")
        mae_b = item.get("mae_baseline")
        if mae_s is not None and mae_b is not None and mae_s > mae_b:
            underperforming.append({
                "zone": item["zone"],
                "test_samples": item.get("test_samples", 0),
                "mae_seasonal": mae_s,
                "mae_baseline": mae_b,
                "mae_difference": round(mae_s - mae_b, 2),
            })
    return underperforming


def build_hourly_day_matrix(df: pd.DataFrame, zone: str) -> pd.DataFrame:
    """
    Seçilen bölge için saat x gün ortalama gecikme matrisini üretir.
    """
    day_names = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    hours = [f"{h:02d}:00" for h in range(24)]

    matrix = pd.DataFrame(index=hours, columns=day_names, dtype=float)

    if df.empty or "zone" not in df.columns or "rtt_ms" not in df.columns:
        return matrix

    z_df = df[(df["zone"] == zone) & df["rtt_ms"].notna()].copy()
    if z_df.empty:
        return matrix

    z_df["weekday"] = z_df["dt"].dt.day_of_week
    z_df["hour_int"] = z_df["dt"].dt.hour

    grouped = z_df.groupby(["hour_int", "weekday"])["rtt_ms"].mean()

    for (h, w), val in grouped.items():
        if 0 <= h < 24 and 0 <= w < 7:
            matrix.loc[f"{h:02d}:00", day_names[w]] = round(val, 1)

    return matrix


def get_record_counts(data_type: str, db_path: str | Path | None = None) -> dict[str, int]:
    """Seçili veri türünün özet sayılarını SQLite'tan salt okunur alır."""
    import sqlite3
    from analytics.data import get_db_path

    target_db = Path(db_path) if db_path is not None else get_db_path()
    uri = f"{target_db.resolve().as_uri()}?mode=ro"
    conditions = {
        "simulated": "WHERE is_simulated = 1",
        "real": "WHERE is_simulated = 0",
        "all": "",
    }
    if data_type not in conditions:
        raise ValueError("data_type simulated, real veya all olmalı.")

    with sqlite3.connect(uri, uri=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(is_verified), 0), "
            "COALESCE(SUM(is_simulated), 0) FROM measurements "
            + conditions[data_type]
        ).fetchone()
    total, verified, simulated = (int(value) for value in row)
    return {
        "total": total,
        "verified": verified,
        "unverified": total - verified,
        "simulated": simulated,
        "real": total - simulated,
    }


def prepare_masked_issues_and_anomalies(
    issues: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
    all_bssids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Panelde gösterilecek sorunlar ve anomalilerdeki ham BSSID adreslerini
    AP-1, AP-2 gibi anonim takma adlarla maskeler. Asla ham BSSID sızdırmaz.
    """
    alias_map = generate_ap_aliases(all_bssids)
    masked_issues = mask_issues_bssids(issues, alias_map)
    masked_anomalies = mask_issues_bssids(anomalies, alias_map)
    return masked_issues, masked_anomalies
