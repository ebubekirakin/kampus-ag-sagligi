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
    """Tabloyu hazırlar ve eski, zorunlu ağ alanlarını NULL kabul edecek biçimde taşır."""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_hash TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'desktop',
        ssid TEXT,
        bssid TEXT,
        rssi_dbm REAL,
        rtt_ms REAL,
        loss_pct REAL,
        down_mbps REAL,
        up_mbps REAL,
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
        table_info = {
            row["name"]: row for row in conn.execute("PRAGMA table_info(measurements)")
        }
        # Eski tabloya simülasyon işaretini varsayılanı 0 olacak şekilde ekle.
        if "is_simulated" not in table_info:
            conn.execute(
                "ALTER TABLE measurements "
                "ADD COLUMN is_simulated INTEGER NOT NULL DEFAULT 0 "
                "CHECK (is_simulated IN (0, 1))"
            )
            table_info = {
                row["name"]: row for row in conn.execute("PRAGMA table_info(measurements)")
            }

        # SQLite mevcut sütundaki NOT NULL şartını kaldıramaz; tabloyu veri kaybı olmadan yenile.
        nullable_fields = ("rtt_ms", "loss_pct", "down_mbps", "up_mbps")
        needs_rebuild = any(table_info[field]["notnull"] for field in nullable_fields)
        if needs_rebuild:
            conn.execute("ALTER TABLE measurements RENAME TO measurements_legacy")
            conn.execute(create_table_sql)
            new_columns = [
                "id", "device_hash", "source", "ssid", "bssid", "rssi_dbm",
                "rtt_ms", "loss_pct", "down_mbps", "up_mbps", "building", "floor",
                "zone", "campus_confidence", "is_verified", "is_simulated", "timestamp",
            ]
            old_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(measurements_legacy)")
            }
            defaults = {
                "source": "'desktop'",
                "campus_confidence": "1.0",
                "is_verified": "1",
                "is_simulated": "0",
            }
            expressions = [
                column if column in old_columns else defaults.get(column, "NULL")
                for column in new_columns
            ]
            column_list = ", ".join(new_columns)
            value_list = ", ".join(expressions)
            conn.execute(
                f"INSERT INTO measurements ({column_list}) "
                f"SELECT {value_list} FROM measurements_legacy"
            )
            conn.execute("DROP TABLE measurements_legacy")
