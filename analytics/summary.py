"""
NetNabız Analiz Özeti ve Gizlilik Modülü.
Tüm analiz çıktılarını gizlilik ilkelerine tam uyumlu biçimde
(device_hash yok, ssid yok, ham BSSID yerine AP-1, AP-2 maskeleri)
JSON formatında dışa aktarır. BSSID eşleme tablosunu data/ap_alias_map.json'a yazar.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from backend.config import BASE_DIR


def generate_ap_aliases(all_bssids: list[str]) -> dict[str, str]:
    """
    Ham BSSID adreslerini sıralı biçimde AP-1, AP-2 gibi anonim rumuzlara çevirir.
    Boş veya geçersiz BSSID'leri atlar.
    """
    clean_bssids = sorted(list(set(b for b in all_bssids if b and str(b).strip() != "")))
    alias_map = {}
    for idx, bssid in enumerate(clean_bssids, start=1):
        alias_map[bssid] = f"AP-{idx}"
    return alias_map


def mask_issues_bssids(issues: list[dict[str, Any]], alias_map: dict[str, str]) -> list[dict[str, Any]]:
    """Sorun listesindeki ham BSSID'leri anonim rumuz ile değiştirir ve detay metnini temizler."""
    masked = []
    for issue in issues:
        item = issue.copy()
        raw_bssid = item.get("bssid")
        if raw_bssid and raw_bssid in alias_map:
            alias = alias_map[raw_bssid]
            item["bssid"] = alias
            if "details" in item and raw_bssid in item["details"]:
                item["details"] = item["details"].replace(raw_bssid, alias)
        masked.append(item)
    return masked


def build_analysis_summary(
    metadata: dict[str, Any],
    zone_scores: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
    forecast: dict[str, Any],
    participation: dict[str, Any],
    alias_map: dict[str, str],
) -> dict[str, Any]:
    """Gizlilik kurallarına uygun analiz özet sözlüğünü oluşturur."""
    masked_issues = mask_issues_bssids(issues, alias_map)
    masked_anomalies = mask_issues_bssids(anomalies, alias_map)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "data_type": metadata.get("data_type"),
            "total_records": metadata.get("total_records"),
            "verified_only": metadata.get("verified_only"),
            "reference_time": str(metadata.get("reference_time")),
            "min_time": str(metadata.get("min_time")),
            "max_time": str(metadata.get("max_time")),
            "utc_offset_hours": metadata.get("utc_offset_hours"),
            "time_basis": metadata.get("time_basis"),
        },
        "zone_scores": zone_scores,
        "diagnosed_issues": masked_issues,
        "anomalies": masked_anomalies,
        "forecast_performance": forecast,
        "participation_density": participation,
    }
    return summary


def save_summary_files(
    summary_data: dict[str, Any],
    alias_map: dict[str, str],
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    """
    data/analysis_summary.json ve data/ap_alias_map.json dosyalarını kaydeder.
    """
    target_dir = output_dir or (BASE_DIR / "data")
    target_dir.mkdir(parents=True, exist_ok=True)

    summary_file = target_dir / "analysis_summary.json"
    alias_file = target_dir / "ap_alias_map.json"

    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    with open(alias_file, "w", encoding="utf-8") as f:
        json.dump(alias_map, f, ensure_ascii=False, indent=2)

    return summary_file, alias_file
