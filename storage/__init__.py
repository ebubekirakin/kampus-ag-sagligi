"""Depolama katmanı fabrika ve yardımcı işlevleri."""

from pathlib import Path
from typing import Any
from storage.base import MeasurementStore
from storage.sqlite_store import SQLiteMeasurementStore

_BASE_DIR = Path(__file__).resolve().parent.parent


def get_store(config: dict[str, Any] | None = None) -> MeasurementStore:
    """Yapılandırmaya göre uygun MeasurementStore uygulamasını döner."""
    if config is None:
        from backend.config import load_config
        config = load_config()

    storage_cfg = config.get("storage", {})
    if not isinstance(storage_cfg, dict):
        storage_cfg = {}

    backend_type = storage_cfg.get("backend", "sqlite")

    if backend_type == "sqlite":
        db_raw = config.get("database_path", "data/netnabiz.db")
        db_p = Path(db_raw)
        db_path = db_p if db_p.is_absolute() else _BASE_DIR / db_p
        busy_timeout = int(storage_cfg.get("busy_timeout_ms", 5000))
        wal_mode = bool(storage_cfg.get("wal_mode", True))
        return SQLiteMeasurementStore(db_path=db_path, busy_timeout_ms=busy_timeout, wal_mode=wal_mode)

    raise ValueError(
        f"Desteklenmeyen veritabanı depolama motoru: '{backend_type}'. "
        "Geçerli seçenekler: 'sqlite'."
    )

