"""
SQLite veritabanı bağlantısı ve tablo yönetim modülü.
"""

from pathlib import Path
from contextlib import contextmanager
import sqlite3
from backend.config import BASE_DIR, load_config


def get_db_path() -> Path:
    """Veritabanı dosyasının mutlak yolunu döner ve gerekirse üst dizini oluşturur."""
    config = load_config()
    db_relative_path = config.get("database_path", "data/netnabiz.db")
    db_full_path = BASE_DIR / db_relative_path
    db_full_path.parent.mkdir(parents=True, exist_ok=True)
    return db_full_path


@contextmanager
def get_connection():
    """SQLite bağlantısını açar, işlemi tamamlar ve bağlantıyı kapatır."""
    conn = sqlite3.connect(get_db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Ölçüm tablosunu oluşturur ve eski tabloya yeni sütunları ekler."""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_hash TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'desktop',
        ssid TEXT,
        bssid TEXT,
        rssi_dbm REAL,
        rtt_ms REAL NOT NULL,
        loss_pct REAL NOT NULL,
        down_mbps REAL NOT NULL,
        up_mbps REAL NOT NULL,
        building TEXT,
        floor TEXT,
        zone TEXT NOT NULL,
        campus_confidence REAL NOT NULL DEFAULT 1.0,
        is_verified INTEGER NOT NULL DEFAULT 1,
        is_simulated INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1)),
        timestamp TEXT NOT NULL
    );
    """
    with get_connection() as conn:
        conn.execute(create_table_sql)
        # CREATE TABLE IF NOT EXISTS eski tabloları değiştirmez; eksik alanları ekle.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(measurements)")}
        if "is_simulated" not in columns:
            conn.execute(
                "ALTER TABLE measurements "
                "ADD COLUMN is_simulated INTEGER NOT NULL DEFAULT 0 "
                "CHECK (is_simulated IN (0, 1))"
            )
        conn.commit()
