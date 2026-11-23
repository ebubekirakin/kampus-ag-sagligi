"""
NetNabız Analiz Veri Yükleme Modülü.
SQLite veritabanından doğrudan ve salt okunur biçimde ölçümleri okur,
zaman damgalarını yerel saat dilimine göre ayrıştırır.
"""

from pathlib import Path
import sqlite3
import pandas as pd

from backend.config import BASE_DIR, load_config


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
    SQLite veritabanından ölçüm verilerini yükler ve analiz için hazırlar.

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

    query = "SELECT * FROM measurements WHERE 1=1"

    if data_type == "simulated":
        query += " AND is_simulated = 1"
    elif data_type == "real":
        query += " AND is_simulated = 0"
    elif data_type != "all":
        raise ValueError(f"Geçersiz data_type: {data_type}. 'simulated', 'real' veya 'all' olmalı.")

    if verified_only:
        query += " AND is_verified = 1"

    query += " ORDER BY id ASC"

    # Windows yollarını da doğru kaçışlayan URI ile salt okunur aç.
    uri = f"{target_db.resolve().as_uri()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        raise RuntimeError(
            f"Veritabanı salt okunur açılamadı: {target_db}"
        ) from error

    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

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
