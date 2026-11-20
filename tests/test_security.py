"""
Sunucu tarafı güvenlik, doğrulama, hash_salt ve IP tabanlı güven skoru testleri.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend import database
from backend.config import load_config
from backend.main import app, hash_device_id, calculate_campus_confidence


class TestServerSecurity(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.api_key = self.config["api_key"]
        self.valid_zone = self.config.get("zones", ["Kütüphane 1. kat Okuma salonu"])[0]

    def test_salt_hashes_device_differently_from_input(self):
        """Saklanan değerin gönderilen device_hash'ten farklı olduğunu doğrular (salt çalışıyor)."""
        raw_device_hash = "f4c28a528e46b9a8"
        salt = self.config.get("hash_salt", "test-salt")
        stored_hash = hash_device_id(raw_device_hash, salt)

        self.assertNotEqual(stored_hash, raw_device_hash)
        self.assertEqual(len(stored_hash), 64)  # SHA-256 çıktısı 64 hex karakterdir

    def test_same_device_hash_yields_same_stored_hash(self):
        """Aynı device_hash için her zaman aynı saklanan HMAC değerinin üretildiğini doğrular."""
        raw_hash = "abc123456789"
        salt = self.config.get("hash_salt", "test-salt")
        hash_1 = hash_device_id(raw_hash, salt)
        hash_2 = hash_device_id(raw_hash, salt)

        self.assertEqual(hash_1, hash_2)

    def test_real_measurement_ignores_client_verified_flag(self):
        """
        is_simulated=0 iken istemcinin sahte is_verified=1 ve campus_confidence=1.0 göndermesi
        durumunda sunucunun bunu yok sayıp istek IP'sine göre yeniden hesapladığını doğrular.
        """
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "sec.db"
            with patch.object(database, "get_db_path", return_value=db_path):
                database.init_db()
                with TestClient(app) as client:
                    # İstemci hileli olarak kendini doğrulanmış (is_verified=1, confidence=1.0) gönderiyor
                    payload = {
                        "device_hash": "untrusted_device_1",
                        "source": "desktop",
                        "zone": self.valid_zone,
                        "campus_confidence": 1.0,
                        "is_verified": 1,
                        "is_simulated": 0,
                    }
                    # TestClient varsayılan olarak testclient IP'siyle gelir (dev_mode=true iken 1.0 sayılır).
                    # dev_mode=false ve kampüs dışı bir IP taklit edelim:
                    with patch.dict(self.config, {"dev_mode": False, "campus_ip_ranges": ["10.0.0.0/8"]}):
                        # calculate_campus_confidence testclient için dev_mode=false iken 0.0 dönecektir
                        resp = client.post(
                            "/measurements",
                            json=payload,
                            headers={"X-API-Key": self.api_key},
                        )
                        self.assertEqual(resp.status_code, 201)

                        data = client.get(
                            "/measurements?is_simulated=0",
                            headers={"X-API-Key": self.api_key},
                        ).json()
                        self.assertEqual(len(data), 1)
                        # Sunucu istemcinin gönderdiği 1.0 ve 1 değerlerini YOK SAYMALI, 0 yapmalı:
                        self.assertEqual(data[0]["campus_confidence"], 0.0)
                        self.assertEqual(data[0]["is_verified"], 0)

    def test_simulated_measurement_preserves_client_confidence(self):
        """is_simulated=1 olduğunda gönderilen güven skorunun ve doğrulama durumunun korunduğunu doğrular."""
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "sim.db"
            with patch.object(database, "get_db_path", return_value=db_path):
                database.init_db()
                with TestClient(app) as client:
                    payload = {
                        "device_hash": "sim_device_1",
                        "source": "desktop",
                        "zone": self.valid_zone,
                        "campus_confidence": 0.15,
                        "is_verified": 0,
                        "is_simulated": 1,
                    }
                    resp = client.post(
                        "/measurements",
                        json=payload,
                        headers={"X-API-Key": self.api_key},
                    )
                    self.assertEqual(resp.status_code, 201)

                    rows = client.get(
                        "/measurements?is_simulated=1",
                        headers={"X-API-Key": self.api_key},
                    ).json()
                    self.assertEqual(len(rows), 1)
                    # Simülasyon skorları korunmalı:
                    self.assertEqual(rows[0]["campus_confidence"], 0.15)
                    self.assertEqual(rows[0]["is_verified"], 0)

    def test_invalid_source_returns_422(self):
        """source yalnızca desktop, web veya android olabilir; başka bir değerde 422 dönmeli."""
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "val.db"
            with patch.object(database, "get_db_path", return_value=db_path):
                database.init_db()
                with TestClient(app) as client:
                    payload = {
                        "device_hash": "dev_test",
                        "source": "smart_tv",  # Geçersiz kaynak
                        "zone": self.valid_zone,
                    }
                    resp = client.post(
                        "/measurements",
                        json=payload,
                        headers={"X-API-Key": self.api_key},
                    )
                    self.assertEqual(resp.status_code, 422)

    def test_invalid_and_future_timestamp_returns_422(self):
        """Geçersiz format veya gelecekte 5 dakikadan fazla ileri tarihli zaman damgasında 422 dönmeli."""
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "val.db"
            with patch.object(database, "get_db_path", return_value=db_path):
                database.init_db()
                with TestClient(app) as client:
                    # 1. Format hatası
                    resp1 = client.post(
                        "/measurements",
                        json={"device_hash": "dev", "zone": self.valid_zone, "timestamp": "gecersiz-tarih"},
                        headers={"X-API-Key": self.api_key},
                    )
                    self.assertEqual(resp1.status_code, 422)

                    # 2. 10 dakika gelecekteki tarih
                    far_future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
                    resp2 = client.post(
                        "/measurements",
                        json={"device_hash": "dev", "zone": self.valid_zone, "timestamp": far_future},
                        headers={"X-API-Key": self.api_key},
                    )
                    self.assertEqual(resp2.status_code, 422)

    def test_invalid_zone_returns_422(self):
        """Tanımlı olmayan bölge girildiğinde 422 dönmeli."""
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "val.db"
            with patch.object(database, "get_db_path", return_value=db_path):
                database.init_db()
                with TestClient(app) as client:
                    payload = {
                        "device_hash": "dev",
                        "zone": "Uzay Üssü Koridoru",  # Tanımlı değil
                    }
                    resp = client.post(
                        "/measurements",
                        json=payload,
                        headers={"X-API-Key": self.api_key},
                    )
                    self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
