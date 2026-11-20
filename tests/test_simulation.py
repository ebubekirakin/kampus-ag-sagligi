"""Simülasyon, cevap anahtarı ve eski veritabanı uyumluluğu testleri."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

from backend import database
from backend.config import load_config
from data.generate_simulated import (
    generate_measurements,
    get_ground_truth_scenarios,
    save_ground_truth,
)


class TestSimulation(unittest.TestCase):
    def test_same_seed_produces_same_measurements(self):
        first, first_truth = generate_measurements(days=2, seed=42)
        second, second_truth = generate_measurements(days=2, seed=42)
        self.assertEqual(first, second)
        self.assertEqual(first_truth, second_truth)

    def test_ground_truth_is_written_and_has_four_scenarios(self):
        scenarios = get_ground_truth_scenarios(
            ["Bölge 1", "Bölge 2"], "02:00:00:02:00:02"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ground_truth.json"
            save_ground_truth(scenarios, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 4)
        self.assertEqual(saved[2]["bssid"], "02:00:00:02:00:02")

    def test_measurement_values_and_scenarios_are_valid(self):
        measurements, scenarios = generate_measurements(days=14, seed=42)
        self.assertGreater(len(measurements), 0)
        self.assertEqual({item["scenario_id"] for item in scenarios}, {
            "congestion", "coverage_gap", "faulty_ap", "sudden_outage"
        })

        for item in measurements:
            self.assertEqual(item["is_simulated"], 1)
            self.assertEqual(item["source"], "desktop")
            self.assertIn(item["is_verified"], (0, 1))
            self.assertTrue(0 <= item["campus_confidence"] <= 1)
            self.assertTrue(-85 <= item["rssi_dbm"] <= -45)
            self.assertGreater(item["rtt_ms"], 0)
            self.assertTrue(0 <= item["loss_pct"] <= 100)
            self.assertGreaterEqual(item["down_mbps"], 0)
            self.assertGreaterEqual(item["up_mbps"], 0)

        outage = [item for item in measurements if item["rtt_ms"] >= 500]
        self.assertTrue(outage, "Yedinci gün için bir kesinti ölçümü bulunmalı.")
        outside = [item for item in measurements if item["is_verified"] == 0]
        self.assertTrue(outside, "Kampüs dışı ölçümler de üretilmeli.")
        self.assertTrue(all(item["campus_confidence"] < 0.5 for item in outside))

        off_campus_ratio = len(outside) / len(measurements)
        self.assertTrue(0.02 <= off_campus_ratio <= 0.08)

        congestion_zone = scenarios[0]["zone"]
        congestion_rows = [
            item for item in measurements
            if item["zone"] == congestion_zone
            and datetime.fromisoformat(item["timestamp"]).weekday() < 5
            and 16 <= datetime.fromisoformat(item["timestamp"]).hour < 19
        ]
        self.assertTrue(congestion_rows)
        self.assertTrue(all(item["rtt_ms"] >= 150 for item in congestion_rows))
        self.assertTrue(all(item["rssi_dbm"] >= -55 for item in congestion_rows))

        coverage_rows = [item for item in measurements if item["zone"] == scenarios[1]["zone"]]
        self.assertTrue(coverage_rows)
        self.assertTrue(all(item["rssi_dbm"] <= -78 for item in coverage_rows))
        self.assertTrue(all(item["down_mbps"] < 5 for item in coverage_rows))

        faulty_rows = [
            item for item in measurements
            if item["zone"] == scenarios[2]["zone"]
            and item["bssid"] == scenarios[2]["bssid"]
        ]
        self.assertTrue(faulty_rows)
        self.assertTrue(all(item["loss_pct"] >= 12 for item in faulty_rows))

        campus_aps_by_zone = {}
        for item in measurements:
            if item["is_verified"] == 1:
                campus_aps_by_zone.setdefault(item["zone"], set()).add(item["bssid"])
        self.assertTrue(all(2 <= len(aps) <= 3 for aps in campus_aps_by_zone.values()))

    def test_zone_count_can_be_smaller_than_four(self):
        scenarios = get_ground_truth_scenarios(["Tek bölge"], "02:00:00:01:00:02")
        self.assertEqual({item["zone"] for item in scenarios}, {"Tek bölge"})


class TestDatabaseMigration(unittest.TestCase):
    def test_old_table_migrates_without_losing_rows_and_accepts_missing_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(db_path)
            connection.execute("""
                CREATE TABLE measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_hash TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'desktop',
                    ssid TEXT, bssid TEXT, rssi_dbm REAL,
                    rtt_ms REAL NOT NULL, loss_pct REAL NOT NULL,
                    down_mbps REAL NOT NULL, up_mbps REAL NOT NULL,
                    building TEXT, floor TEXT, zone TEXT NOT NULL,
                    campus_confidence REAL NOT NULL DEFAULT 1.0,
                    is_verified INTEGER NOT NULL DEFAULT 1,
                    timestamp TEXT NOT NULL
                )
            """)
            connection.execute(
                "INSERT INTO measurements "
                "(device_hash, rtt_ms, loss_pct, down_mbps, up_mbps, zone, timestamp) "
                "VALUES ('existing-hash', 23, 0, 40, 10, 'Bölge', '2026-11-18T10:00:00Z')"
            )
            connection.commit()
            connection.close()

            with patch.object(database, "get_db_path", return_value=db_path):
                database.init_db()
                with database.get_connection() as connection:
                    row = connection.execute(
                        "SELECT device_hash, rtt_ms, is_simulated FROM measurements"
                    ).fetchone()
                    connection.execute(
                        "INSERT INTO measurements "
                        "(device_hash, zone, timestamp, rtt_ms) VALUES (?, ?, ?, ?)",
                        ("new-hash", "Bölge", "2026-11-18T10:01:00Z", None),
                    )
                    null_metric = connection.execute(
                        "SELECT rtt_ms, is_simulated FROM measurements WHERE device_hash = ?",
                        ("new-hash",),
                    ).fetchone()

            self.assertEqual(tuple(row), ("existing-hash", 23.0, 0))
            self.assertEqual(tuple(null_metric), (None, 0))


class TestBackendEndpoints(unittest.TestCase):
    def test_post_accepts_optional_simulated_flag(self):
        from types import SimpleNamespace
        from fastapi import HTTPException
        from backend.main import MeasurementCreate, create_measurement, list_measurements

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "api.db"
            with patch.object(database, "get_db_path", return_value=db_path):
                database.init_db()
                config = load_config()
                valid_zone = config["zones"][0]
                payload = MeasurementCreate(
                    device_hash="test-hash",
                    rtt_ms=None,
                    loss_pct=None,
                    down_mbps=None,
                    up_mbps=None,
                    zone=valid_zone,
                )
                request = SimpleNamespace(
                    client=SimpleNamespace(host="127.0.0.1")
                )

                with self.assertRaises(HTTPException) as unauthorized:
                    create_measurement(payload, request, None)
                self.assertEqual(unauthorized.exception.status_code, 401)

                response = create_measurement(
                    payload, request, config["api_key"]
                )
                self.assertEqual(response["status"], "created")

                with self.assertRaises(HTTPException) as unauthorized_get:
                    list_measurements(x_api_key=None)
                self.assertEqual(unauthorized_get.exception.status_code, 401)

                rows = list_measurements(
                    limit=100,
                    offset=0,
                    is_simulated=0,
                    zone=None,
                    x_api_key=config["api_key"],
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["is_simulated"], 0)
                self.assertIsNone(rows[0]["rtt_ms"])


if __name__ == "__main__":
    unittest.main()
