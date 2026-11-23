"""
NetNabız İstatistiksel Anomali Tespit Modülü.
Bölge bazında saatlik medyan gecikme (rtt_ms) ve paket kaybı (loss_pct) serilerini çıkarır;
MAD (Median Absolute Deviation) ve Sağlam Z-Skor (Robust Z-Score) kullanarak
beklenmedik sıçramaları ve ani kesintileri tespit eder.
"""

from typing import Any
import pandas as pd
from backend.config import load_config


def detect_anomalies(df: pd.DataFrame, config: dict | None = None) -> list[dict[str, Any]]:
    """
    Bölge bazında saatlik medyanlar üzerinden sağlam Z-skoru (|z| > 4.0) ile anomalileri tespit eder.
    
    Yöntem:
      1. Her bölge için her gün ve saatteki gözlem medyanı hesaplanır.
      2. Bölgenin genel saatlik medyanı taban (baseline) olarak alınır.
      3. Medyan Mutlak Sapma (MAD) = medyan(|saatlik_medyan - taban_medyan|).
      4. Sıfıra bölünmeyi önlemek için safe_mad = max(MAD, 1.0) kullanılır.
      5. Sağlam Z-Skor = (gözlem_medyanı - taban_medyan) / (1.4826 * safe_mad).
      6. Eşik üstü (|z| > 4.0) ve asgari örnek sayısını sağlayan durumlar anomali sayılır.
      7. Aynı gün içindeki ardışık saatler tek bir aralık olarak birleştirilir.
    """
    if config is None:
        config = load_config()
    cfg = config.get("analytics", {})

    z_thresh = cfg.get("anomaly_z_threshold", 4.0)
    min_hour_samples = cfg.get("min_hour_samples", 2)

    anomalies = []
    if df.empty or "zone" not in df.columns or "dt" not in df.columns:
        return anomalies

    work_df = df.copy()
    if "day_str" not in work_df.columns:
        work_df["day_str"] = work_df["dt"].dt.strftime("%Y-%m-%d")
    if "hour" not in work_df.columns:
        work_df["hour"] = work_df["dt"].dt.hour

    metrics_to_check = [
        ("rtt_ms", "Yüksek Gecikme Sıçraması", "ms"),
        ("loss_pct", "Yüksek Paket Kaybı Sıçraması", "%"),
    ]

    for metric_col, title_prefix, unit in metrics_to_check:
        if metric_col not in work_df.columns:
            continue

        valid_df = work_df[work_df[metric_col].notna()]
        if valid_df.empty:
            continue

        for zone in valid_df["zone"].unique():
            z_df = valid_df[valid_df["zone"] == zone]

            # 1. Saatlik medyan ve örnek sayılarını hesapla
            hourly_agg = (
                z_df.groupby(["day_str", "hour"])[metric_col]
                .agg(median="median", count="count")
                .reset_index()
            )

            if len(hourly_agg) < 5:
                continue

            # 2. Bölge taban medyanı ve MAD
            base_median = float(hourly_agg["median"].median())
            deviations = (hourly_agg["median"] - base_median).abs()
            mad = float(deviations.median())
            safe_mad = max(mad, 1.0)  # MAD sıfır veya çok küçük olduğunda güvenli taban

            # 3. Z-Skor hesapla
            hourly_records = []
            for _, row in hourly_agg.iterrows():
                obs_count = int(row["count"])
                if obs_count < min_hour_samples:
                    continue

                obs_med = float(row["median"])
                z_score = (obs_med - base_median) / (1.4826 * safe_mad)

                if z_score > z_thresh:
                    hourly_records.append({
                        "zone": zone,
                        "date": str(row["day_str"]),
                        "hour": int(row["hour"]),
                        "metric": metric_col,
                        "unit": unit,
                        "title": f"{title_prefix} ({zone})",
                        "observed_median": obs_med,
                        "baseline_median": base_median,
                        "robust_z": z_score,
                        "sample_count": obs_count,
                    })

            # 4. Ardışık saatleri birleştir
            merged = _merge_consecutive_anomaly_hours(hourly_records)
            anomalies.extend(merged)

    return anomalies


def _merge_consecutive_anomaly_hours(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aynı gün ve bölgedeki ardışık anomali saatlerini tek bir aralıkta birleştirir."""
    if not records:
        return []

    by_date: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_date.setdefault(r["date"], []).append(r)

    merged_results = []
    for date_str, items in by_date.items():
        items.sort(key=lambda x: x["hour"])
        clusters: list[list[dict[str, Any]]] = []
        cur_cluster = [items[0]]

        for it in items[1:]:
            if it["hour"] == cur_cluster[-1]["hour"] + 1:
                cur_cluster.append(it)
            else:
                clusters.append(cur_cluster)
                cur_cluster = [it]
        clusters.append(cur_cluster)

        for cl in clusters:
            start_h = cl[0]["hour"]
            end_h = cl[-1]["hour"]
            time_window = f"{date_str} {start_h:02d}:00-{end_h+1:02d}:00"
            rep = max(cl, key=lambda x: abs(x["robust_z"]))

            merged_results.append({
                "issue_type": "anomaly",
                "title": rep["title"],
                "zone": rep["zone"],
                "bssid": None,
                "date": date_str,
                "time_window": time_window,
                "metric": rep["metric"],
                "observed_median": round(rep["observed_median"], 1),
                "baseline_median": round(rep["baseline_median"], 1),
                "robust_z": round(rep["robust_z"], 2),
                "details": (
                    f"{time_window} saatleri arasında gözlemlenen {rep['metric']} = "
                    f"{rep['observed_median']:.1f} {rep['unit']} "
                    f"(taban: {rep['baseline_median']:.1f} {rep['unit']}, "
                    f"Z-Skoru: {rep['robust_z']:.2f})"
                ),
            })

    return merged_results
