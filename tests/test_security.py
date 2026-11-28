"""Sunucu tarafı gizlilik ve doğrulama kurallarını test eder."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend import database
from backend.config import load_config
from backend.main import (
    MeasurementCreate,
    calculate_campus_confidence,
    create_measurement,
    hash_device_id,
)


class TestServerSecurity(unittest.TestCase):
    def setUp(self):
        self.config = dict(load_config())
        self.config["hash_salt"] = "unit-test-hmac-key"
        self.api_key = self.config["api_key"]
        self.valid_zone = self.config["zones"][0]

    @contextmanager
    def temporary_database(self, config=None):
        """Her test için geçici veritabanı ve yapılandırma kullanır."""
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            selected_config = dict(config or self.config)
            selected_config["database_path"] = str(db_path)
            from storage.sqlite_store import SQLiteMeasurementStore
            store = SQLiteMeasurementStore(db_path=db_path)
            with patch("storage.get_store", return_value=store):
                with patch("backend.database.get_store", return_value=store):
                    with patch("backend.main.get_store", return_value=store):
                        with patch("backend.main.load_config", return_value=selected_config):
                            database.init_db()
                            self._current_store = store
                            yield

    def make_request(self, host="192.0.2.10", forwarded_for=None):
        """Endpoint fonksiyonlarına küçük bir sahte istemci adresi verir."""
        headers = {}
        if forwarded_for:
            headers["x-forwarded-for"] = forwarded_for
        return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)

    def make_measurement(self, **changes):
        """Testlerde kullanılacak geçerli bir ölçüm modeli hazırlar."""
        payload = {
            "device_hash": "client-device-hash",
            "source": "desktop",
            "zone": self.valid_zone,
            "is_simulated": 0,
            "campus_confidence": 1.0,
            "is_verified": 1,
        }
        payload.update(changes)
        return MeasurementCreate(**payload)

    def read_device_hashes(self):
        """Geçici veritabanına yazılan cihaz hash'lerini döndürür."""
        rows = self._current_store.fetch_measurements(limit=1000)
        return [row["device_hash"] for row in reversed(rows)]


    def test_salt_changes_value_stored_in_database(self):
        """Sunucunun sakladığı HMAC, istemcinin gönderdiği değerden farklıdır."""
        with self.temporary_database():
            measurement = self.make_measurement(device_hash="known-client-hash")
            create_measurement(measurement, self.make_request(), self.api_key)

            stored_hash = self.read_device_hashes()[0]

        expected_hash = hash_device_id(
            "known-client-hash", self.config["hash_salt"]
        )
        self.assertEqual(stored_hash, expected_hash)
        self.assertNotEqual(stored_hash, "known-client-hash")

    def test_missing_salt_fails_closed(self):
        """Boş tuzla cihaz kimliği kaydetmeye izin verilmez."""
        config = dict(self.config)
        for invalid_salt in ("  ", "BU_DEGERI_KENDI_CONFIG_DOSYANDA_DEGISTIR"):
            with self.subTest(salt_type="empty" if not invalid_salt.strip() else "example"):
                config["hash_salt"] = invalid_salt
                with self.temporary_database(config):
                    with self.assertRaises(HTTPException) as error:
                        create_measurement(
                            self.make_measurement(), self.make_request(), self.api_key
                        )
                self.assertEqual(error.exception.status_code, 500)

    def test_same_device_hash_has_same_stored_value(self):
        """Aynı istemci hash'i iki kayıtta aynı sunucu hash'ini üretir."""
        with self.temporary_database():
            for _ in range(2):
                create_measurement(
                    self.make_measurement(device_hash="same-client-hash"),
                    self.make_request(),
                    self.api_key,
                )
            stored_hashes = self.read_device_hashes()

        self.assertEqual(len(stored_hashes), 2)
        self.assertEqual(stored_hashes[0], stored_hashes[1])

    def test_real_measurement_recalculates_client_verification(self):
        """Gerçek ölçümde sahte istemci skorları yerine istek IP'si kullanılır."""
        config = dict(self.config)
        config.update(dev_mode=False, campus_ip_ranges=["10.0.0.0/8"])
        with self.temporary_database(config):
            create_measurement(
                self.make_measurement(is_simulated=0),
                self.make_request(
                    "192.0.2.10", forwarded_for="10.1.2.3"
                ),
                self.api_key,
            )
            rows = self._current_store.fetch_measurements(limit=1)
            row = rows[0] if rows else {}

        self.assertEqual(row.get("campus_confidence"), 0.0)
        self.assertEqual(row.get("is_verified"), 0)

    def test_simulated_measurement_preserves_client_confidence(self):
        """Simüle kayıtta gelen güven ve doğrulama değerleri korunur."""
        with self.temporary_database():
            create_measurement(
                self.make_measurement(
                    is_simulated=1, campus_confidence=0.15, is_verified=0
                ),
                self.make_request(),
                self.api_key,
            )
            rows = self._current_store.fetch_measurements(limit=1)
            row = rows[0] if rows else {}

        self.assertEqual(row.get("campus_confidence"), 0.15)
        self.assertEqual(row.get("is_verified"), 0)


    def test_campus_confidence_uses_only_configured_ip_rules(self):
        """Kampüs IP aralığı ve geliştirme modundaki yerel adresler tanınır."""
        config = {"dev_mode": False, "campus_ip_ranges": ["10.0.0.0/8"]}
        self.assertEqual(calculate_campus_confidence("10.2.3.4", config), 1.0)
        self.assertEqual(calculate_campus_confidence("192.0.2.1", config), 0.0)
        config["dev_mode"] = True
        self.assertEqual(calculate_campus_confidence("127.0.0.1", config), 1.0)
        self.assertEqual(calculate_campus_confidence("::1", config), 1.0)

    def test_ipv6_ip_with_ipv4_cidr_does_not_crash(self):
        """IPv4 CIDR ile IPv6 istemciyi karşılaştırmak hata üretmez."""
        config = {"dev_mode": False, "campus_ip_ranges": ["10.0.0.0/8"]}
        self.assertEqual(calculate_campus_confidence("2001:db8::1", config), 0.0)

    def test_invalid_source_and_timestamp_are_rejected_by_request_model(self):
        """Geçersiz kaynak ve ISO 8601 olmayan zaman damgası modelden geçmez."""
        with self.assertRaises(ValidationError):
            self.make_measurement(source="smart_tv")
        with self.assertRaises(ValidationError):
            self.make_measurement(timestamp="gecersiz-tarih")

    def test_timestamp_is_utc_and_far_future_is_rejected(self):
        """Zaman UTC'ye çevrilir ve beş dakikadan fazla gelecek kabul edilmez."""
        measurement = self.make_measurement(
            timestamp="2026-11-20T15:00:00+03:00"
        )
        self.assertTrue(measurement.timestamp.endswith("+00:00"))

        far_future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        with self.assertRaises(ValidationError):
            self.make_measurement(timestamp=far_future)

    def test_unknown_or_unconfigured_zone_is_rejected(self):
        """Tanımsız bölge ve boş bölge ayarları ölçüm kabul etmez."""
        with self.temporary_database():
            with self.assertRaises(HTTPException) as unknown_zone:
                create_measurement(
                    self.make_measurement(zone="Uzay Üssü Koridoru"),
                    self.make_request(),
                    self.api_key,
                )
            self.assertEqual(unknown_zone.exception.status_code, 422)

        empty_config = dict(self.config)
        empty_config["zones"] = []
        with self.temporary_database(empty_config):
            with self.assertRaises(HTTPException) as empty_zones:
                create_measurement(
                    self.make_measurement(), self.make_request(), self.api_key
                )
            self.assertEqual(empty_zones.exception.status_code, 422)

    def test_empty_building_and_floor_are_filled_from_zone(self):
        """Bina ve kat boş bırakılınca bölge adından tamamlanır."""
        with self.temporary_database():
            create_measurement(
                self.make_measurement(building=None, floor=None),
                self.make_request(),
                self.api_key,
            )
            rows = self._current_store.fetch_measurements(limit=1)
            row = rows[0] if rows else {}

        self.assertEqual(row.get("building"), "Kütüphane")
        self.assertEqual(row.get("floor"), "1. Kat")



if __name__ == "__main__":
    unittest.main()
