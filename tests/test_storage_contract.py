"""Depolama katmanı sözleşme (contract) ve mimari denetim testleri."""

from pathlib import Path
import re
import tempfile
import pytest
import pandas as pd
from storage import get_store
from storage.base import MeasurementStore
from storage.sqlite_store import SQLiteMeasurementStore


@pytest.fixture(params=["sqlite"], ids=["sqlite"])
def temp_store(request, tmp_path: Path) -> MeasurementStore:
    """Sözleşmeyi kayıtlı depo uygulamalarında geçici DB ile çalıştırır."""
    db_file = tmp_path / "contract_test.db"
    # Yeni bir depo eklenince fabrika bu listeye eklenir; sözleşme testleri aynen çalışır.
    factories = {
        "sqlite": lambda: SQLiteMeasurementStore(
            db_path=db_file, busy_timeout_ms=3000, wal_mode=True
        ),
    }
    store = factories[request.param]()
    store.init_schema()
    return store



class TestStorageContract:
    """MeasurementStore arayüzünü uygulayan herhangi bir depo için genel sözleşme testleri."""

    def test_implements_protocol(self, temp_store: MeasurementStore):
        assert isinstance(temp_store, MeasurementStore)

    def test_insert_and_fetch_measurements(self, temp_store: MeasurementStore):
        record = {
            "device_hash": "hash-abc",
            "source": "desktop",
            "ssid": "eduroam",
            "bssid": "02:00:00:01:00:01",
            "rssi_dbm": -65.0,
            "rtt_ms": 25.5,
            "loss_pct": 0.0,
            "down_mbps": 45.0,
            "up_mbps": 15.0,
            "building": "Mühendislik",
            "floor": "1. kat",
            "zone": "Laboratuvar",
            "campus_confidence": 1.0,
            "is_verified": 1,
            "is_simulated": 0,
            "timestamp": "2026-11-20T10:00:00+00:00",
        }
        rec_id = temp_store.insert_measurement(record)
        assert rec_id > 0

        rows = temp_store.fetch_measurements(limit=10)
        assert len(rows) == 1
        assert rows[0]["id"] == rec_id
        assert rows[0]["device_hash"] == "hash-abc"
        assert rows[0]["zone"] == "Laboratuvar"
        assert rows[0]["rtt_ms"] == 25.5

    def test_fetch_filters_and_pagination(self, temp_store: MeasurementStore):
        # 3 kayıt ekle: 2 simüle, 1 gerçek; farklı bölgeler
        base_record = {
            "device_hash": "hash-1",
            "source": "desktop",
            "zone": "Bölge A",
            "is_verified": 1,
            "is_simulated": 1,
            "timestamp": "2026-11-20T10:00:00+00:00",
        }
        temp_store.insert_measurement(base_record)
        temp_store.insert_measurement({**base_record, "zone": "Bölge B", "is_simulated": 1})
        temp_store.insert_measurement({**base_record, "zone": "Bölge A", "is_simulated": 0})

        # is_simulated filtresi
        simulated = temp_store.fetch_measurements(is_simulated=1)
        assert len(simulated) == 2

        real = temp_store.fetch_measurements(is_simulated=0)
        assert len(real) == 1

        # zone filtresi
        zone_a = temp_store.fetch_measurements(zone="Bölge A")
        assert len(zone_a) == 2

        # limit ve offset
        paged = temp_store.fetch_measurements(limit=1, offset=1)
        assert len(paged) == 1

    def test_insert_nullable_metrics(self, temp_store: MeasurementStore):
        record = {
            "device_hash": "hash-nulls",
            "zone": "Açık Alan",
            "rtt_ms": None,
            "loss_pct": None,
            "down_mbps": None,
            "up_mbps": None,
            "is_verified": 0,
            "is_simulated": 1,
            "timestamp": "2026-11-20T11:00:00+00:00",
        }
        rec_id = temp_store.insert_measurement(record)
        assert rec_id > 0
        rows = temp_store.fetch_measurements(zone="Açık Alan")
        assert len(rows) == 1
        assert rows[0]["rtt_ms"] is None
        assert rows[0]["loss_pct"] is None

    def test_count_summary(self, temp_store: MeasurementStore):
        # 1 doğrulanmış simüle, 1 doğrulanmamış simüle, 1 doğrulanmış gerçek
        temp_store.insert_measurement({
            "device_hash": "h1", "zone": "Z1", "is_verified": 1, "is_simulated": 1, "timestamp": "2026-11-20T10:00:00Z"
        })
        temp_store.insert_measurement({
            "device_hash": "h2", "zone": "Z1", "is_verified": 0, "is_simulated": 1, "timestamp": "2026-11-20T10:01:00Z"
        })
        temp_store.insert_measurement({
            "device_hash": "h3", "zone": "Z2", "is_verified": 1, "is_simulated": 0, "timestamp": "2026-11-20T10:02:00Z"
        })

        summary_all = temp_store.count_summary("all")
        assert summary_all == {
            "total": 3,
            "verified": 2,
            "unverified": 1,
            "simulated": 2,
            "real": 1,
        }

        summary_sim = temp_store.count_summary("simulated")
        assert summary_sim["total"] == 2
        assert summary_sim["verified"] == 1
        assert summary_sim["unverified"] == 1

        summary_real = temp_store.count_summary("real")
        assert summary_real["total"] == 1
        assert summary_real["verified"] == 1
        assert summary_real["unverified"] == 0

    def test_load_dataframe_filters_and_columns(self, temp_store: MeasurementStore):
        temp_store.insert_measurement({
            "device_hash": "h1", "zone": "Z1", "rtt_ms": 20.0, "is_verified": 1, "is_simulated": 1, "timestamp": "2026-11-20T10:00:00Z"
        })
        temp_store.insert_measurement({
            "device_hash": "h2", "zone": "Z1", "rtt_ms": 40.0, "is_verified": 0, "is_simulated": 1, "timestamp": "2026-11-20T10:01:00Z"
        })
        temp_store.insert_measurement({
            "device_hash": "h3", "zone": "Z2", "rtt_ms": 60.0, "is_verified": 1, "is_simulated": 0, "timestamp": "2026-11-20T10:02:00Z"
        })

        df_sim = temp_store.load_dataframe(data_kind="simulated", verified_only=True)
        assert len(df_sim) == 1
        assert df_sim.iloc[0]["device_hash"] == "h1"
        assert list(df_sim.columns) == [
            "id", "device_hash", "source", "ssid", "bssid", "rssi_dbm",
            "rtt_ms", "loss_pct", "down_mbps", "up_mbps", "building", "floor",
            "zone", "campus_confidence", "is_verified", "is_simulated", "timestamp",
        ]

        df_all_verified = temp_store.load_dataframe(data_kind="all", verified_only=True)
        assert len(df_all_verified) == 2

        df_all_unfiltered = temp_store.load_dataframe(data_kind="all", verified_only=False)
        assert len(df_all_unfiltered) == 3


class TestSQLiteSpecificBehavior:
    """SQLite sürücüsüne özgü bağlantı ve PRAGMA kontrolleri."""

    def test_read_only_connection_rejects_writes(self, tmp_path: Path):
        store = SQLiteMeasurementStore(db_path=tmp_path / "read_only.db")
        store.init_schema()
        conn = store._get_ro_connection()
        try:
            with pytest.raises(Exception) as error:
                conn.execute(
                    "INSERT INTO measurements (device_hash, zone, timestamp) VALUES (?, ?, ?)",
                    ("x", "y", "z"),
                )
            assert error.type.__name__ == "OperationalError"
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "wal_mode,expected_mode", [(True, "wal"), (False, "delete")]
    )
    def test_journal_mode_and_busy_timeout_are_active(
        self, tmp_path: Path, wal_mode: bool, expected_mode: str
    ):
        store = SQLiteMeasurementStore(
            db_path=tmp_path / f"wal_{wal_mode}.db", busy_timeout_ms=3000,
            wal_mode=wal_mode,
        )
        store.init_schema()
        conn = store._get_ro_connection()
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == expected_mode
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 3000
        finally:
            conn.close()


class TestArchitectureRules:
    """Mimari kural: storage/ dışındaki hiçbir .py dosyasında 'import sqlite' bulunamaz."""

    def test_no_direct_sqlite3_import_outside_storage(self):
        project_root = Path(__file__).resolve().parent.parent
        forbidden_hits = []

        for py_file in project_root.rglob("*.py"):
            rel_parts = py_file.relative_to(project_root).parts
            if "venv" in rel_parts or ".venv" in rel_parts:
                continue
            if rel_parts[0] == "storage":
                continue

            content = py_file.read_text(encoding="utf-8")
            for idx, line in enumerate(content.splitlines(), start=1):
                clean_line = line.strip()
                if clean_line.startswith("#") or clean_line.startswith('"""') or clean_line.startswith("'''"):
                    continue
                # Kendisi test dosyası olduğu için denetlenen kelimeyi dinamik oluşturuyoruz
                target_word = "sqlite" + "3"
                if f"import {target_word}" in clean_line or f"from {target_word}" in clean_line:
                    forbidden_hits.append(f"{py_file.relative_to(project_root)}:{idx} -> {clean_line}")

        assert not forbidden_hits, f"storage/ dışında doğrudan sqlite3 importu tespit edildi:\n" + "\n".join(forbidden_hits)

    def test_application_does_not_import_concrete_sqlite_store(self):
        project_root = Path(__file__).resolve().parent.parent
        app_dirs = ("backend", "analytics", "dashboard", "tools")
        offenders = []
        for directory in app_dirs:
            for py_file in (project_root / directory).rglob("*.py"):
                if "SQLiteMeasurementStore" in py_file.read_text(encoding="utf-8"):
                    offenders.append(str(py_file.relative_to(project_root)))
        assert not offenders, "Uygulama modülleri concrete SQLite sınıfına bağlı: " + ", ".join(offenders)

    def test_application_sql_statements_are_confined_to_storage(self):
        project_root = Path(__file__).resolve().parent.parent
        app_dirs = ("backend", "analytics", "dashboard", "tools")
        sql_pattern = re.compile(
            r"\b(SELECT|INSERT\s+INTO|UPDATE\s+\w+|DELETE\s+FROM|"
            r"CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|PRAGMA)\b",
            re.IGNORECASE,
        )
        offenders = []
        for directory in app_dirs:
            for py_file in (project_root / directory).rglob("*.py"):
                for line_number, line in enumerate(
                    py_file.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if sql_pattern.search(line):
                        offenders.append(
                            f"{py_file.relative_to(project_root)}:{line_number}"
                        )
        assert not offenders, "Depolama dışı SQL bulundu: " + ", ".join(offenders)

    def test_store_factory_reports_unknown_backend_in_turkish(self):
        with pytest.raises(ValueError, match="Desteklenmeyen veritabanı depolama motoru"):
            get_store({"storage": {"backend": "unknown"}})

