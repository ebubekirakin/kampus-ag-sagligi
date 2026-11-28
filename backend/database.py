"""Veritabanı erişim köprüsü.

Tüm doğrudan SQL ve veritabanı motoru işlemleri storage/ paketine taşınmıştır.
Bu modül geriye dönük uyumluluk ve yardımcı işlevler için get_store()'u sarmalar.
"""

from storage import get_store


def init_db() -> None:
    """Depolama katmanı üzerinden şemayı başlatır."""
    store = get_store()
    store.init_schema()
