"""Simülasyon, cevap anahtarı ve eski veritabanı uyumluluğu testleri."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

from backend import database
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
    def test_old_measurements_table_gets_is_simulated_column(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(db_path)
            connection.execute("CREATE TABLE measurements (id INTEGER PRIMARY KEY)")
            connection.close()

            with patch.object(database, "get_db_path", return_value=db_path):
                database.init_db()
                constraint_raised = False
                with database.get_connection() as connection:
                    column = connection.execute(
                        "PRAGMA table_info(measurements)"
                    ).fetchall()
                    row = connection.execute(
                        "INSERT INTO measurements (id) VALUES (1) RETURNING is_simulated"
                    ).fetchone()
                    try:
                        connection.execute(
                            "INSERT INTO measurements (id, is_simulated) VALUES (2, 2)"
                        )
                    except sqlite3.IntegrityError:
                        constraint_raised = True

            self.assertIn("is_simulated", {item["name"] for item in column})
            self.assertEqual(row[0], 0)
            self.assertTrue(constraint_raised)


class TestBackendEndpoints(unittest.TestCase):
    def test_post_accepts_optional_simulated_flag(self):
        try:
            from fastapi.testclient import TestClient
            from backend.main import app
        except ImportError:
            self.skipTest("FastAPI veya httpx kurulu değil.")

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "api.db"
            with patch.object(database, "get_db_path", return_value=db_path):
                with TestClient(app) as client:
                    payload = {
                        "device_hash": "test-hash",
                        "rtt_ms": 20,
                        "loss_pct": 0,
                        "down_mbps": 50,
                        "up_mbps": 20,
                        "zone": "Test bölgesi",
                    }
                    response = client.post("/measurements", json=payload)
                    self.assertEqual(response.status_code, 201)
                    rows = client.get("/measurements?is_simulated=0").json()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["is_simulated"], 0)


if __name__ == "__main__":
    unittest.main()
