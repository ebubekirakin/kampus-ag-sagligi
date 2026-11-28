"""Veritabanı erişim köprüsü.

Tüm doğrudan SQL ve veritabanı motoru işlemleri storage/ paketine taşınmıştır.
Bu modül geriye dönük uyumluluk ve yardımcı işlevler için get_store()'u sarmalar.
"""

from pathlib import Path
from backend.config import BASE_DIR, load_config
from storage import get_store


def get_db_path() -> Path:
    """Veritabanı dosyasının yolunu bulur."""
    config = load_config()
    db_path = BASE_DIR / config.get("database_path", "data/netnabiz.db")
    return db_path


def init_db() -> None:
    """Depolama katmanı üzerinden şemayı başlatır."""
    store = get_store()
    store.init_schema()
