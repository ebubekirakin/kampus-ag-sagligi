"""Depolama katmanı sözleşme (contract) ve mimari denetim testleri."""

from pathlib import Path
import tempfile
import pytest
import pandas as pd
from storage import get_store
from storage.base import MeasurementStore
from storage.sqlite_store import SQLiteMeasurementStore


@pytest.fixture
def temp_store(tmp_path: Path) -> MeasurementStore:
    """Geçici SQLite veritabanı ile başlatılmış store döner."""
    db_file = tmp_path / "contract_test.db"
    store = SQLiteMeasurementStore(db_path=db_file, busy_timeout_ms=3000, wal_mode=True)
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
        assert "rtt_ms" in df_sim.columns
        assert "timestamp" in df_sim.columns

        df_all_verified = temp_store.load_dataframe(data_kind="all", verified_only=True)
        assert len(df_all_verified) == 2

        df_all_unfiltered = temp_store.load_dataframe(data_kind="all", verified_only=False)
        assert len(df_all_unfiltered) == 3

    def test_read_only_connection_rejects_writes(self, temp_store: MeasurementStore):
        # SQLiteMeasurementStore._get_ro_connection() ile dönen bağlantıdan yazma denenirse reddedilmeli
        if isinstance(temp_store, SQLiteMeasurementStore):
            conn = temp_store._get_ro_connection()
            try:
                with pytest.raises(Exception):
                    conn.execute("INSERT INTO measurements (device_hash, zone, timestamp) VALUES ('x', 'y', 'z')")
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

