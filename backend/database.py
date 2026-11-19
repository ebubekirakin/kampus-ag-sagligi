"""SQLite veritabanı bağlantısı ve küçük şema geçişleri."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from backend.config import BASE_DIR, load_config

CREATE_TABLE_SQL = """
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

MEASUREMENT_COLUMNS = (
    "id", "device_hash", "source", "ssid", "bssid", "rssi_dbm", "rtt_ms",
    "loss_pct", "down_mbps", "up_mbps", "building", "floor", "zone",
    "campus_confidence", "is_verified", "is_simulated", "timestamp",
)
NULLABLE_METRICS = ("rtt_ms", "loss_pct", "down_mbps", "up_mbps")


def get_db_path() -> Path:
    """Veritabanı dosyasının yolunu bulur ve üst klasörünü hazırlar."""
    config = load_config()
    db_path = BASE_DIR / config.get("database_path", "data/netnabiz.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@contextmanager
def get_connection():
    """SQLite bağlantısını açar, işlemi tamamlar ve bağlantıyı kapatır."""
    connection = sqlite3.connect(get_db_path(), timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_measurements_table(connection: sqlite3.Connection) -> None:
    """Yeni kurulumlar için ölçüm tablosunu oluşturur."""
    connection.execute(CREATE_TABLE_SQL)


def add_simulated_column(connection: sqlite3.Connection) -> None:
    """Eski tabloya simülasyon işaretini ekler; eski kayıtlar gerçek sayılır."""
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(measurements)")}
    if "is_simulated" not in columns:
        connection.execute(
            "ALTER TABLE measurements ADD COLUMN is_simulated INTEGER NOT NULL "
            "DEFAULT 0 CHECK (is_simulated IN (0, 1))"
        )


def migrate_nullable_metrics(connection: sqlite3.Connection) -> None:
    """Eski NOT NULL ağ ölçümlerini nullable hale getirerek satırları korur."""
    table_info = {
        row["name"]: row for row in connection.execute("PRAGMA table_info(measurements)")
    }
    if not any(table_info[field]["notnull"] for field in NULLABLE_METRICS):
        return

    connection.execute("ALTER TABLE measurements RENAME TO measurements_legacy")
    connection.execute(CREATE_TABLE_SQL)
    old_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(measurements_legacy)")
    }
    defaults = {
        "source": "'desktop'",
        "campus_confidence": "1.0",
        "is_verified": "1",
        "is_simulated": "0",
    }
    source_columns = [
        column if column in old_columns else defaults.get(column, "NULL")
        for column in MEASUREMENT_COLUMNS
    ]
    columns_sql = ", ".join(MEASUREMENT_COLUMNS)
    source_sql = ", ".join(source_columns)
    connection.execute(
        f"INSERT INTO measurements ({columns_sql}) "
        f"SELECT {source_sql} FROM measurements_legacy"
    )
    connection.execute("DROP TABLE measurements_legacy")


def init_db() -> None:
    """Tabloyu oluşturur ve gerekiyorsa eski şemayı iki küçük geçişle yeniler."""
    with get_connection() as connection:
        create_measurements_table(connection)
        add_simulated_column(connection)
        migrate_nullable_metrics(connection)
