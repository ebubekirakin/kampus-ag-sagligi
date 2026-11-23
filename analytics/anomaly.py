"""Saatlik ölçümlerde sağlam Z-skoru ile anomali arar."""

from typing import Any
import pandas as pd

from backend.config import load_config


def detect_anomalies(df: pd.DataFrame, config: dict | None = None) -> list[dict[str, Any]]:
    """Aynı bölge, gün türü ve saat dilimini MAD tabanıyla karşılaştırır."""
    if config is None:
        config = load_config()
    cfg = config.get("analytics", {})
    z_threshold = cfg.get("anomaly_z_threshold", 4.0)
    min_hour_samples = cfg.get("min_hour_samples", 2)
    mad_floor = cfg.get("anomaly_mad_floor", 1.0)

    if df.empty or "zone" not in df.columns or "dt" not in df.columns:
        return []

    work_df = df.copy()
    if "day_str" not in work_df.columns:
        work_df["day_str"] = work_df["dt"].dt.strftime("%Y-%m-%d")
    if "hour" not in work_df.columns:
        work_df["hour"] = work_df["dt"].dt.hour
    if "is_weekend" not in work_df.columns:
        work_df["is_weekend"] = work_df["dt"].dt.day_of_week >= 5

    metrics = (
        ("rtt_ms", "Gecikme", "ms"),
        ("loss_pct", "Paket kaybı", "%"),
    )
    anomalies = []

    for metric, label, unit in metrics:
        if metric not in work_df.columns:
            continue
        valid_df = work_df[work_df[metric].notna()]

        for zone, zone_df in valid_df.groupby("zone"):
            hourly = (
                zone_df.groupby(["day_str", "is_weekend", "hour"])[metric]
                .agg(median="median", count="count")
                .reset_index()
            )

            # Taban ve MAD, aynı hafta içi/sonu ve saat dilimindeki günlerden çıkar.
            for (is_weekend, hour), slot in hourly.groupby(["is_weekend", "hour"]):
                for _, row in slot.iterrows():
                    if int(row["count"]) < min_hour_samples:
                        continue

                    # Ölçülen günü referans grubundan çıkar; olay kendi tabanını bozmasın.
                    reference = slot[slot["day_str"] != row["day_str"]]["median"]
                    if reference.empty:
                        # Gün türünde örnek yoksa aynı bölge ve saatin diğer günlerini kullan.
                        reference = hourly.loc[
                            (hourly["hour"] == hour)
                            & (hourly["day_str"] != row["day_str"]),
                            "median",
                        ]
                        if reference.empty:
                            continue
                    baseline = float(reference.median())
                    mad = float((reference - baseline).abs().median())
                    safe_mad = max(mad, mad_floor)

                    observed = float(row["median"])
                    robust_z = (observed - baseline) / (1.4826 * safe_mad)
                    if abs(robust_z) <= z_threshold:
                        continue

                    direction = "high" if robust_z > 0 else "low"
                    direction_text = "yüksek" if direction == "high" else "düşük"
                    anomalies.append({
                        "zone": zone,
                        "date": str(row["day_str"]),
                        "hour": int(hour),
                        "is_weekend": bool(is_weekend),
                        "metric": metric,
                        "unit": unit,
                        "direction": direction,
                        "title": f"Beklenenden {direction_text} {label} ({zone})",
                        "observed_median": observed,
                        "baseline_median": baseline,
                        "robust_z": robust_z,
                        "sample_count": int(row["count"]),
                    })

    return _merge_consecutive_anomaly_hours(anomalies)


def _merge_consecutive_anomaly_hours(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aynı gün, ölçüt ve yöndeki ardışık saatleri bir aralıkta birleştirir."""
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            record["zone"],
            record["date"],
            record["metric"],
            record["direction"],
        )
        grouped.setdefault(key, []).append(record)

    merged = []
    for (_, date_str, _, _), items in grouped.items():
        items.sort(key=lambda item: item["hour"])
        clusters: list[list[dict[str, Any]]] = []
        current = [items[0]]

        for item in items[1:]:
            if item["hour"] == current[-1]["hour"] + 1:
                current.append(item)
            else:
                clusters.append(current)
                current = [item]
        clusters.append(current)

        for cluster in clusters:
            representative = max(cluster, key=lambda item: abs(item["robust_z"]))
            start_hour = cluster[0]["hour"]
            end_hour = cluster[-1]["hour"] + 1
            time_window = f"{date_str} {start_hour:02d}:00-{end_hour:02d}:00"
            metric = representative["metric"]
            unit = representative["unit"]
            observed = representative["observed_median"]
            baseline = representative["baseline_median"]
            robust_z = representative["robust_z"]

            merged.append({
                "issue_type": "anomaly",
                "title": representative["title"],
                "zone": representative["zone"],
                "bssid": None,
                "date": date_str,
                "time_window": time_window,
                "metric": metric,
                "direction": representative["direction"],
                "observed_median": round(observed, 1),
                "baseline_median": round(baseline, 1),
                "robust_z": round(robust_z, 2),
                "sample_count": sum(item["sample_count"] for item in cluster),
                "details": (
                    f"{time_window}: {metric} medyanı {observed:.1f} {unit}; "
                    f"aynı gün türü/saat tabanı {baseline:.1f} {unit}; "
                    f"sağlam Z-skoru {robust_z:.2f}"
                ),
            })

    return sorted(merged, key=lambda item: (item["date"], item["hour"] if "hour" in item else item["time_window"]))
