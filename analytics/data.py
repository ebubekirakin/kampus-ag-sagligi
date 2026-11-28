"""
NetNabız Analiz Veri Yükleme Modülü.
Depolama katmanı (MeasurementStore) üzerinden salt okunur biçimde ölçümleri okur,
zaman damgalarını yerel saat dilimine göre ayrıştırır.
"""

from pathlib import Path
import pandas as pd

from backend.config import BASE_DIR, load_config
from storage import get_store
from storage.sqlite_store import SQLiteMeasurementStore


def get_db_path() -> Path:
    """Veritabanı dosya yolunu yapılandırmadan okur."""
    config = load_config()
    db_relative = config.get("database_path", "data/netnabiz.db")
    return BASE_DIR / db_relative


def load_measurements(
    data_type: str = "simulated",
    verified_only: bool = True,
    utc_offset_hours: int | None = None,
    db_path: Path | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Veritabanından ölçüm verilerini yükler ve analiz için hazırlar.

    Parametreler:
        data_type: 'simulated' (is_simulated=1), 'real' (is_simulated=0) veya 'all'
        verified_only: Sadece is_verified=1 olan doğrulanmış ölçümleri alır
        utc_offset_hours: Gerçek veriler için Türkiye/yerel saat ofseti (varsayılan: config veya 3)
        db_path: Özel veritabanı yolu (testler için)

    Dönüş:
        (df, metadata)
    """
    if data_type not in ("simulated", "real", "all"):
        raise ValueError("data_type 'simulated', 'real' veya 'all' olmalı.")

    target_db = db_path or get_db_path()
    if not target_db.exists():
        raise FileNotFoundError(f"Veritabanı dosyası bulunamadı: {target_db}")

    config = load_config()
    analytics_cfg = config.get("analytics", {})
    if utc_offset_hours is None:
        utc_offset_hours = analytics_cfg.get("utc_offset_hours", 3)
    effective_offset = 0 if data_type == "simulated" else utc_offset_hours
    time_basis = "UTC" if effective_offset == 0 else f"UTC{effective_offset:+g}"

    if db_path is not None:
        store = SQLiteMeasurementStore(db_path=target_db)
    else:
        store = get_store(config)

    df = store.load_dataframe(data_kind=data_type, verified_only=verified_only)

    if df.empty:
        return df, {
            "total_records": 0,
            "data_type": data_type,
            "verified_only": verified_only,
            "utc_offset_hours": effective_offset,
            "time_basis": time_basis,
            "reference_time": None,
            "min_time": None,
            "max_time": None,
        }

    # Tüm kayıtlar UTC saklanır. Gerçek ve açıkça karışık veri analizinde
    # karşılaştırılabilir yerel saat için bütün satırlara aynı ofset uygulanır.
    # ISO string'leri UTC datetime'a çevir
    df["dt_utc"] = pd.to_datetime(df["timestamp"], utc=True)
    if effective_offset != 0:
        df["dt"] = df["dt_utc"] + pd.Timedelta(hours=effective_offset)
    else:
        df["dt"] = df["dt_utc"]

    # Saat, hafta içi/sonu ve tarih sütunları
    df["hour"] = df["dt"].dt.hour
    df["is_weekend"] = df["dt"].dt.day_of_week >= 5
    df["day_str"] = df["dt"].dt.strftime("%Y-%m-%d")

    # "Şimdi" yerine verideki en son zaman damgası referans alınır (simülasyon tutarlılığı için)
    reference_time = df["dt"].max()
    min_time = df["dt"].min()

    metadata = {
        "total_records": len(df),
        "data_type": data_type,
        "verified_only": verified_only,
        "utc_offset_hours": effective_offset,
        "time_basis": time_basis,
        "reference_time": reference_time,
        "min_time": min_time,
        "max_time": reference_time,
    }


    return df, metadata
