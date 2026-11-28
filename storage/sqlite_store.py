"""SQLite veritabanı deposu uygulaması.

Tüm doğrudan SQL işlemleri bu modülde toplanmıştır.
Yazma işlemlerinde WAL modu ve busy_timeout etkindir;
okuma işlemlerinde SQLite bağlantıları salt okunur (mode=ro) açılır.
"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any, Generator, Literal
import pandas as pd

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

INSERT_COLUMNS = (
    "device_hash", "source", "ssid", "bssid", "rssi_dbm",
    "rtt_ms", "loss_pct", "down_mbps", "up_mbps",
    "building", "floor", "zone", "campus_confidence",
    "is_verified", "is_simulated", "timestamp",
)

NULLABLE_METRICS = ("rtt_ms", "loss_pct", "down_mbps", "up_mbps")


class SQLiteMeasurementStore:
    """SQLite tabanlı ölçüm deposu."""

    def __init__(self, db_path: str | Path, busy_timeout_ms: int = 5000, wal_mode: bool = True):
        self.db_path = Path(db_path).resolve()
        self.busy_timeout_ms = busy_timeout_ms
        self.wal_mode = wal_mode

    def _ensure_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _write_connection(self) -> Generator[sqlite3.Connection, None, None]:
        self._ensure_dir()
        conn = sqlite3.connect(self.db_path, timeout=self.busy_timeout_ms / 1000.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms};")
            if self.wal_mode:
                conn.execute("PRAGMA journal_mode = WAL;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _get_ro_connection(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise RuntimeError(f"Veritabanı dosyası bulunamadı: {self.db_path}")
        uri = f"{self.db_path.as_uri()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=self.busy_timeout_ms / 1000.0)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as error:
            raise RuntimeError(f"Veritabanı salt okunur açılamadı: {self.db_path}") from error

    def init_schema(self) -> None:
        """Tabloyu oluşturur, WAL modunu doğrular ve eski şemaları geçirir."""
        with self._write_connection() as conn:
            conn.execute(CREATE_TABLE_SQL)
            # Simüle kolon geçişi
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(measurements)")}
            if "is_simulated" not in columns:
                conn.execute(
                    "ALTER TABLE measurements ADD COLUMN is_simulated INTEGER NOT NULL "
                    "DEFAULT 0 CHECK (is_simulated IN (0, 1));"
                )
            # Nullable metrik geçişi
            table_info = {
                row["name"]: row for row in conn.execute("PRAGMA table_info(measurements)")
            }
            if any(table_info[field]["notnull"] for field in NULLABLE_METRICS if field in table_info):
                conn.execute("ALTER TABLE measurements RENAME TO measurements_legacy;")
                conn.execute(CREATE_TABLE_SQL)
                old_cols = {
                    row["name"] for row in conn.execute("PRAGMA table_info(measurements_legacy)")
                }
                defaults = {
                    "source": "'desktop'",
                    "campus_confidence": "1.0",
                    "is_verified": "1",
                    "is_simulated": "0",
                }
                source_cols = [
                    c if c in old_cols else defaults.get(c, "NULL")
                    for c in MEASUREMENT_COLUMNS
                ]
                cols_sql = ", ".join(MEASUREMENT_COLUMNS)
                src_sql = ", ".join(source_cols)
                conn.execute(
                    f"INSERT INTO measurements ({cols_sql}) SELECT {src_sql} FROM measurements_legacy;"
                )
                conn.execute("DROP TABLE measurements_legacy;")

    def insert_measurement(self, record: dict[str, Any]) -> int:
        """Yeni bir ölçüm kaydeder ve üretilen kayıt kimliğini döner."""
        sql = f"""
        INSERT INTO measurements (
            {', '.join(INSERT_COLUMNS)}
        ) VALUES ({', '.join(['?'] * len(INSERT_COLUMNS))});
        """
        defaults = {
            "source": "desktop",
            "campus_confidence": 1.0,
            "is_verified": 1,
            "is_simulated": 0,
        }
        values = [record.get(col, defaults.get(col)) if record.get(col) is not None else defaults.get(col) if col in defaults else record.get(col) for col in INSERT_COLUMNS]
        with self._write_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, values)
            record_id = cursor.lastrowid
            if record_id is None:
                raise RuntimeError("Kayıt eklendi fakat son satır kimliği alınamadı.")
            return record_id


    def fetch_measurements(
        self,
        *,
        is_simulated: int | None = None,
        zone: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """API sorgusu için ölçümleri listeler (salt okunur)."""
        query = "SELECT * FROM measurements WHERE 1=1"
        params: list[Any] = []

        if is_simulated is not None:
            query += " AND is_simulated = ?"
            params.append(is_simulated)

        if zone is not None:
            query += " AND zone = ?"
            params.append(zone)

        query += " ORDER BY id DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        conn = self._get_ro_connection()
        try:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def load_dataframe(
        self,
        data_kind: Literal["simulated", "real", "all"] = "simulated",
        verified_only: bool = True,
    ) -> pd.DataFrame:
        """Analiz için verileri salt okunur SQLite bağlantısıyla DataFrame olarak yükler."""
        query = "SELECT * FROM measurements WHERE 1=1"
        params: list[Any] = []

        if data_kind == "simulated":
            query += " AND is_simulated = 1"
        elif data_kind == "real":
            query += " AND is_simulated = 0"
        elif data_kind != "all":
            raise ValueError(f"Geçersiz data_kind: {data_kind}. 'simulated', 'real' veya 'all' olmalı.")

        if verified_only:
            query += " AND is_verified = 1"

        query += " ORDER BY id ASC;"

        conn = self._get_ro_connection()
        try:
            return pd.read_sql_query(query, conn, params=params)
        finally:
            conn.close()

    def count_summary(self, data_kind: Literal["simulated", "real", "all"] = "all") -> dict[str, int]:
        """Kayıt sayıları özetini döner."""
        conditions = {
            "simulated": "WHERE is_simulated = 1",
            "real": "WHERE is_simulated = 0",
            "all": "",
        }
        if data_kind not in conditions:
            raise ValueError(f"Geçersiz data_kind: {data_kind}. 'simulated', 'real' veya 'all' olmalı.")

        sql = f"""
        SELECT
            COUNT(*),
            COALESCE(SUM(is_verified), 0),
            COALESCE(SUM(is_simulated), 0)
        FROM measurements
        {conditions[data_kind]};
        """

        conn = self._get_ro_connection()
        try:
            row = conn.execute(sql).fetchone()
            total = int(row[0]) if row else 0
            verified = int(row[1]) if row else 0
            simulated = int(row[2]) if row else 0
            return {
                "total": total,
                "verified": verified,
                "unverified": total - verified,
                "simulated": simulated,
                "real": total - simulated,
            }
        finally:
            conn.close()
