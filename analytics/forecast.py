"""
NetNabız Mevsimsel Tahmin ve Katılım Analizi Modülü.
Basit mevsimsel medyan modeli (bölge + hafta içi/sonu + saat) ile
tekil medyan taban çizgisini (baseline) karşılaştırır.
Ayrıca saatlik ölçüm katılım yoğunluğunu modeller.
"""

from typing import Any
import pandas as pd
from backend.config import load_config


def predict_seasonal_rtt(
    df: pd.DataFrame, zone: str, is_weekend: bool, hour: int
) -> float | None:
    """İstenen bölge ve zaman için mevsimsel medyan tahmini üretir."""
    if df.empty or "rtt_ms" not in df.columns:
        return None

    zone_df = df[(df["zone"] == zone) & df["rtt_ms"].notna()]
    if zone_df.empty:
        return None

    seasonal = zone_df[
        (zone_df["is_weekend"] == is_weekend) & (zone_df["hour"] == hour)
    ]["rtt_ms"]
    if not seasonal.empty:
        return float(seasonal.median())

    return float(zone_df["rtt_ms"].median())


def evaluate_forecast(df: pd.DataFrame, config: dict | None = None) -> dict[str, Any]:
    """
    Verinin son N gününü test kümesi olarak ayırır (varsayılan: 3 gün).
    Eğitim kümesi üzerinde (bölge, hafta sonu, saat) gruplamasıyla mevsimsel medyanları hesaplar.
    Test kümesi üzerinde hem mevsimsel modelin hem de tekil bölge medyanı modelinin
    Ortalama Mutlak Hatasını (MAE) ölçerek karşılaştırır.
    """
    if config is None:
        config = load_config()
    cfg = config.get("analytics", {})
    test_days = cfg.get("forecast_test_days", 3)

    if df.empty or "rtt_ms" not in df.columns or "dt" not in df.columns:
        return {
            "status": "yetersiz veri",
            "test_sample_count": 0,
            "train_sample_count": 0,
            "mae_seasonal": None,
            "mae_baseline": None,
            "improvement_pct": None,
            "zone_comparison": [],
        }

    valid_df = df[df["rtt_ms"].notna()].sort_values("dt").copy()
    if len(valid_df) < 50:
        return {
            "status": "yetersiz veri",
            "test_sample_count": len(valid_df),
            "train_sample_count": 0,
            "mae_seasonal": None,
            "mae_baseline": None,
            "improvement_pct": None,
            "zone_comparison": [],
        }

    # "Şimdi" yerine verideki en son zaman damgasını baz alarak test kümesini ayır
    ref_time = valid_df["dt"].max()
    split_time = ref_time - pd.Timedelta(days=test_days)

    train_df = valid_df[valid_df["dt"] < split_time]
    test_df = valid_df[valid_df["dt"] >= split_time]

    if train_df.empty or test_df.empty:
        return {
            "status": "yetersiz veri aralığı",
            "test_sample_count": len(test_df),
            "train_sample_count": len(train_df),
            "mae_seasonal": None,
            "mae_baseline": None,
            "improvement_pct": None,
            "zone_comparison": [],
        }

    # 1. Eğitim Kümesi Üzerinde Modelleri Eğit
    # Taban Model (Baseline): Bölge başına tekil medyan
    zone_baseline_medians = train_df.groupby("zone")["rtt_ms"].median().to_dict()
    global_train_median = float(train_df["rtt_ms"].median())

    # Mevsimsel Model: (zone, is_weekend, hour) medyanı
    seasonal_medians = (
        train_df.groupby(["zone", "is_weekend", "hour"])["rtt_ms"]
        .median()
        .to_dict()
    )

    # 2. Test Kümesi Üzerinde Tahmin Yap ve MAE Hesapla
    y_true = test_df["rtt_ms"].values
    y_pred_seasonal = []
    y_pred_baseline = []

    for _, row in test_df.iterrows():
        z = row["zone"]
        wk = row["is_weekend"]
        hr = row["hour"]

        # Mevsimsel tahmin (varsa spesifik hücre medyanı, yoksa bölge medyanı, en kötü genel medyan)
        pred_s = seasonal_medians.get(
            (z, wk, hr),
            zone_baseline_medians.get(z, global_train_median)
        )
        y_pred_seasonal.append(pred_s)

        # Taban model tahmini (sadece tekil bölge medyanı)
        pred_b = zone_baseline_medians.get(z, global_train_median)
        y_pred_baseline.append(pred_b)

    test_df_eval = test_df.copy()
    test_df_eval["abs_err_seasonal"] = (test_df_eval["rtt_ms"] - y_pred_seasonal).abs()
    test_df_eval["abs_err_baseline"] = (test_df_eval["rtt_ms"] - y_pred_baseline).abs()

    mae_seasonal = float(test_df_eval["abs_err_seasonal"].mean())
    mae_baseline = float(test_df_eval["abs_err_baseline"].mean())

    improvement_pct = 0.0
    if mae_baseline > 0:
        improvement_pct = round(((mae_baseline - mae_seasonal) / mae_baseline) * 100.0, 1)

    # Bölge bazında detay karşılaştırma
    zone_comparison = []
    for zone, grp in test_df_eval.groupby("zone"):
        z_mae_s = float(grp["abs_err_seasonal"].mean())
        z_mae_b = float(grp["abs_err_baseline"].mean())
        zone_comparison.append({
            "zone": zone,
            "test_samples": len(grp),
            "mae_seasonal": round(z_mae_s, 2),
            "mae_baseline": round(z_mae_b, 2),
            "mae_difference": round(z_mae_b - z_mae_s, 2),
        })

    return {
        "status": "basarili",
        "split_time": str(split_time),
        "test_sample_count": len(test_df),
        "train_sample_count": len(train_df),
        "mae_seasonal": round(mae_seasonal, 2),
        "mae_baseline": round(mae_baseline, 2),
        "improvement_pct": improvement_pct,
        "zone_comparison": zone_comparison,
    }


def evaluate_participation_forecast(
    df: pd.DataFrame, config: dict | None = None
) -> dict[str, Any]:
    """Saatlik katılım sayısını son günlerde test edip mevsimsel medyanla kıyaslar."""
    if config is None:
        config = load_config()
    test_days = config.get("analytics", {}).get("forecast_test_days", 3)
    if df.empty or "dt" not in df.columns or "zone" not in df.columns:
        return {"status": "yetersiz veri", "zone_comparison": []}

    valid = df.dropna(subset=["dt", "zone"]).copy()
    if valid.empty:
        return {"status": "yetersiz veri", "zone_comparison": []}

    # Her bölge ve saat için sıfır ölçüm olan saatleri de tabloya kat.
    first_hour = valid["dt"].min().normalize()
    last_hour = valid["dt"].max().floor("h")
    hours = pd.date_range(first_hour, last_hour, freq="h")
    zones = sorted(valid["zone"].unique())
    grid = pd.MultiIndex.from_product(
        [zones, hours], names=["zone", "hour_start"]
    ).to_frame(index=False)

    valid["hour_start"] = valid["dt"].dt.floor("h")
    counts = (
        valid.groupby(["zone", "hour_start"]).size()
        .rename("count")
        .reset_index()
    )
    hourly = grid.merge(counts, on=["zone", "hour_start"], how="left")
    hourly["count"] = hourly["count"].fillna(0).astype(int)
    hourly["hour"] = hourly["hour_start"].dt.hour
    hourly["is_weekend"] = hourly["hour_start"].dt.day_of_week >= 5

    reference_time = valid["dt"].max()
    split_time = reference_time - pd.Timedelta(days=test_days)
    # Bölünme saat içindeyse o saati eğitime katma; test verisi sızmasın.
    split_hour = split_time.floor("h")
    train = hourly[hourly["hour_start"] < split_hour]
    test = hourly[hourly["hour_start"] >= split_hour]
    if train.empty or test.empty:
        return {
            "status": "yetersiz veri aralığı",
            "train_hour_count": len(train),
            "test_hour_count": len(test),
            "zone_comparison": [],
        }

    # Eğitim verisinden bölge taban çizgisi ve saat/gün türü mevsimsel medyanı çıkar.
    zone_baseline = train.groupby("zone")["count"].median().to_dict()
    global_baseline = float(train["count"].median())
    seasonal = train.groupby(["zone", "is_weekend", "hour"])["count"].median().to_dict()
    prediction_rows = test.copy()
    prediction_rows["predicted_seasonal"] = [
        seasonal.get(
            (row.zone, row.is_weekend, row.hour),
            zone_baseline.get(row.zone, global_baseline),
        )
        for row in prediction_rows.itertuples()
    ]
    prediction_rows["predicted_baseline"] = [
        zone_baseline.get(zone, global_baseline)
        for zone in prediction_rows["zone"]
    ]
    prediction_rows["error_seasonal"] = (
        prediction_rows["count"] - prediction_rows["predicted_seasonal"]
    ).abs()
    prediction_rows["error_baseline"] = (
        prediction_rows["count"] - prediction_rows["predicted_baseline"]
    ).abs()

    comparisons = []
    for zone, rows in prediction_rows.groupby("zone"):
        mae_seasonal = float(rows["error_seasonal"].mean())
        mae_baseline = float(rows["error_baseline"].mean())
        comparisons.append({
            "zone": zone,
            "test_hours": len(rows),
            "mae_seasonal": round(mae_seasonal, 2),
            "mae_baseline": round(mae_baseline, 2),
            "mae_difference": round(mae_baseline - mae_seasonal, 2),
        })

    return {
        "status": "başarılı",
        "split_time": str(split_time),
        "train_hour_count": len(train),
        "test_hour_count": len(test),
        "mae_seasonal": round(float(prediction_rows["error_seasonal"].mean()), 2),
        "mae_baseline": round(float(prediction_rows["error_baseline"].mean()), 2),
        "zone_comparison": comparisons,
    }


def compute_participation_density(
    df: pd.DataFrame, config: dict | None = None
) -> dict[str, Any]:
    """
    Saatlik ölçüm katılım yoğunluğunu (örnek sayısını) çıkarır.
    
    ÖNEMLİ DİPNOT: Bu analiz ağın bant genişliği tüketimini değil;
    kullanıcıların hangi saatlerde aktif olarak ölçüm gönderdiğini
    (katılımcı yoğunluğunu) gösterir.
    """
    if df.empty or "hour" not in df.columns:
        return {"hourly_distribution": {}, "methodological_note": ""}

    hourly_dist = df["hour"].value_counts().sort_index().to_dict()
    # 0-23 arası tüm saatleri doldur
    complete_dist = {f"{h:02d}:00": int(hourly_dist.get(h, 0)) for h in range(24)}

    # En yoğun ve en sakin saatler
    peak_hour = max(complete_dist, key=lambda k: complete_dist[k]) if complete_dist else "-"
    quiet_hour = min(complete_dist, key=lambda k: complete_dist[k]) if complete_dist else "-"

    return {
        "hourly_distribution": complete_dist,
        "peak_hour": peak_hour,
        "quiet_hour": quiet_hour,
        "total_measurements": len(df),
        "forecast": evaluate_participation_forecast(df, config),
        "methodological_note": (
            "Bu tablo ağ bant genişliği kullanımını değil, kullanıcıların "
            "ölçüm yapma/katılım sıklığını göstermektedir."
        ),
    }
