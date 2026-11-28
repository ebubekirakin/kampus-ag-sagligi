"""
NetNabız Dashboard Yardımcı Fonksiyonları ve App Duman Testleri.
"""

from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import pytest
import py_compile
from dashboard.helpers import (
    get_score_badge,
    parse_building_floor_zone,
    group_zones_by_hierarchy,
    find_best_spot,
    find_underperforming_forecast_zones,
    build_hourly_day_matrix,
    prepare_masked_issues_and_anomalies,
    get_record_counts,
)


@pytest.fixture
def mock_config():
    return {
        "analytics": {
            "score_green": 75.0,
            "score_yellow": 50.0,
        }
    }


class TestScoreBadge:
    """Skordan renk ve metin etiketi dönüşümü sınır testleri."""

    def test_ideal_score(self, mock_config):
        color, label, hex_code = get_score_badge(100.0, mock_config)
        assert color == "yeşil" and label == "İyi" and hex_code == "#22c55e"

    def test_boundary_green_threshold(self, mock_config):
        color, label, _ = get_score_badge(75.0, mock_config)
        assert color == "yeşil" and label == "İyi"

    def test_just_below_green_threshold(self, mock_config):
        color, label, _ = get_score_badge(74.9, mock_config)
        assert color == "sarı" and label == "Orta"

    def test_boundary_yellow_threshold(self, mock_config):
        color, label, _ = get_score_badge(50.0, mock_config)
        assert color == "sarı" and label == "Orta"

    def test_just_below_yellow_threshold(self, mock_config):
        color, label, _ = get_score_badge(49.9, mock_config)
        assert color == "kırmızı" and label == "Zayıf"

    def test_zero_score(self, mock_config):
        color, label, _ = get_score_badge(0.0, mock_config)
        assert color == "kırmızı" and label == "Zayıf"

    def test_none_score_returns_gray_and_insufficient_data(self, mock_config):
        color, label, hex_code = get_score_badge(None, mock_config)
        assert color == "gri"
        assert label == "Yetersiz veri"
        assert hex_code == "#64748b"


class TestZoneHierarchy:
    """Bölge adından bina ve kat hiyerarşisi ayrıştırma testleri."""

    def test_parsing_standard_zones(self):
        b1, f1, _ = parse_building_floor_zone("Kütüphane 1. kat Okuma salonu")
        assert b1 == "Kütüphane" and f1 == "1. kat"

        b2, f2, _ = parse_building_floor_zone("Mühendislik B Blok 2. kat Derslik koridoru")
        assert b2 == "Mühendislik B Blok" and f2 == "2. kat"

        b3, f3, _ = parse_building_floor_zone("Yemekhane Zemin Kat")
        assert b3 == "Yemekhane" and f3 == "Zemin Kat"

        b4, f4, _ = parse_building_floor_zone("Öğrenci İşleri Giriş Kat")
        assert b4 == "Öğrenci İşleri" and f4 == "Giriş Kat"

    def test_group_zones_by_hierarchy(self):
        zone_scores = [
            {"zone": "Kütüphane 1. kat Okuma salonu", "score": 80.0},
            {"zone": "Kütüphane 2. kat Sessiz salon", "score": 85.0},
            {"zone": "Yemekhane Zemin Kat", "score": 70.0},
        ]
        hierarchy = group_zones_by_hierarchy(zone_scores)
        assert "Kütüphane" in hierarchy
        assert "Yemekhane" in hierarchy
        assert "1. kat" in hierarchy["Kütüphane"]
        assert "2. kat" in hierarchy["Kütüphane"]
        assert "Zemin Kat" in hierarchy["Yemekhane"]
        assert len(hierarchy["Kütüphane"]["1. kat"]) == 1


class TestBestSpotSelection:
    """En iyi nokta önerisi testleri."""

    def test_insufficient_data_zone_never_recommended(self):
        """Yetersiz veri olan bölge gecikmesi çok düşük olsa bile önerilmemelidir."""
        df = pd.DataFrame([
            {"zone": "Yetersiz Bölge", "is_weekend": False, "hour": 14, "rtt_ms": 5.0},
            {"zone": "Geçerli Bölge", "is_weekend": False, "hour": 14, "rtt_ms": 25.0},
        ])
        zone_scores = [
            {"zone": "Yetersiz Bölge", "score": None, "status": "yetersiz veri", "color": "gri"},
            {"zone": "Geçerli Bölge", "score": 85.0, "status": "iyi", "color": "yeşil", "median_down_mbps": 40.0},
        ]

        best = find_best_spot(df, is_weekend=False, hour=14, zone_scores=zone_scores)
        assert best is not None
        assert best["zone"] == "Geçerli Bölge"
        assert best["score"] == 85.0

    def test_recommends_lowest_latency_among_valid_zones(self):
        """Yeterli veriye sahip bölgeler arasından gecikmesi en düşük olan seçilmelidir."""
        df = pd.DataFrame([
            {"zone": "Bölge A", "is_weekend": False, "hour": 10, "rtt_ms": 40.0},
            {"zone": "Bölge B", "is_weekend": False, "hour": 10, "rtt_ms": 15.0},
        ])
        zone_scores = [
            {"zone": "Bölge A", "score": 80.0, "status": "iyi", "color": "yeşil", "median_down_mbps": 30.0},
            {"zone": "Bölge B", "score": 90.0, "status": "iyi", "color": "yeşil", "median_down_mbps": 45.0},
        ]
        best = find_best_spot(df, is_weekend=False, hour=10, zone_scores=zone_scores)
        assert best is not None
        assert best["zone"] == "Bölge B"
        assert best["estimated_rtt_ms"] == 15.0

    def test_recommendation_uses_seasonal_forecast_not_zone_median(self):
        df = pd.DataFrame([
            {"zone": "Bölge A", "is_weekend": False, "hour": 10, "rtt_ms": 80.0},
            {"zone": "Bölge A", "is_weekend": False, "hour": 11, "rtt_ms": 20.0},
            {"zone": "Bölge B", "is_weekend": False, "hour": 10, "rtt_ms": 30.0},
        ])
        scores = [
            {"zone": "Bölge A", "score": 80.0, "status": "iyi", "color": "yeşil"},
            {"zone": "Bölge B", "score": 80.0, "status": "iyi", "color": "yeşil"},
        ]
        best = find_best_spot(df, False, 10, scores)
        assert best["zone"] == "Bölge B"
        assert best["estimated_rtt_ms"] == 30.0

    def test_empty_data_returns_none(self):
        best = find_best_spot(pd.DataFrame(), is_weekend=False, hour=12, zone_scores=[])
        assert best is None


class TestUnderperformingForecastZones:
    """Mevsimsel yöntemin taban modelden kötü olduğu bölgelerin tespiti."""

    def test_identifies_underperforming_zones_dynamically(self):
        forecast_result = {
            "zone_comparison": [
                {"zone": "İyi Bölge", "mae_seasonal": 10.0, "mae_baseline": 20.0, "test_samples": 50},
                {"zone": "Kötü Bölge 1", "mae_seasonal": 8.5, "mae_baseline": 7.0, "test_samples": 40},
                {"zone": "Kötü Bölge 2", "mae_seasonal": 15.0, "mae_baseline": 12.0, "test_samples": 30},
            ]
        }
        underperforming = find_underperforming_forecast_zones(forecast_result)
        assert len(underperforming) == 2
        bad_names = [u["zone"] for u in underperforming]
        assert "Kötü Bölge 1" in bad_names
        assert "Kötü Bölge 2" in bad_names
        assert "İyi Bölge" not in bad_names
        diff_1 = next(u["mae_difference"] for u in underperforming if u["zone"] == "Kötü Bölge 1")
        assert diff_1 == 1.5

    def test_empty_forecast_returns_empty_list(self):
        assert find_underperforming_forecast_zones({}) == []


class TestMatrixAndMasking:
    """Matris oluşturma ve BSSID takma ad maskeleme testleri."""

    def test_matrix_dimensions_and_empty_handling(self):
        matrix = build_hourly_day_matrix(pd.DataFrame(), "Herhangi Bölge")
        assert matrix.shape == (24, 7)
        assert list(matrix.columns) == ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

    def test_matrix_uses_average(self):
        df = pd.DataFrame({
            "zone": ["Bölge" , "Bölge"],
            "rtt_ms": [10.0, 30.0],
            "dt": pd.to_datetime(["2026-11-23 10:00", "2026-11-23 10:30"]),
        })
        matrix = build_hourly_day_matrix(df, "Bölge")
        assert matrix.loc["10:00", "Pazartesi"] == 20.0

    def test_record_counts_include_verified_and_unverified(self, tmp_path):
        from storage.sqlite_store import SQLiteMeasurementStore

        db_path = tmp_path / "counts.db"
        store = SQLiteMeasurementStore(db_path=db_path)
        store.init_schema()
        store.insert_measurement({
            "device_hash": "d1", "zone": "Z", "timestamp": "2026-11-20T10:00:00Z",
            "is_verified": 1, "is_simulated": 1,
        })
        store.insert_measurement({
            "device_hash": "d2", "zone": "Z", "timestamp": "2026-11-20T10:01:00Z",
            "is_verified": 0, "is_simulated": 1,
        })
        store.insert_measurement({
            "device_hash": "d3", "zone": "Z", "timestamp": "2026-11-20T10:02:00Z",
            "is_verified": 1, "is_simulated": 0,
        })
        assert get_record_counts("all", db_path) == {
            "total": 3, "verified": 2, "unverified": 1, "simulated": 2, "real": 1
        }
        assert get_record_counts("simulated", db_path)["total"] == 2


    def test_prepare_masked_issues_and_anomalies(self):
        issues = [{"title": "Arıza", "bssid": "02:00:00:03:00:02", "details": "AP 02:00:00:03:00:02 sorunlu"}]
        anomalies = [{"title": "Sıçrama", "bssid": None}]
        masked_iss, masked_anom = prepare_masked_issues_and_anomalies(issues, anomalies, ["02:00:00:03:00:02"])
        assert masked_iss[0]["bssid"] == "AP-1"
        assert "02:00:00:03:00:02" not in masked_iss[0]["details"]
        assert "AP-1" in masked_iss[0]["details"]


class TestDashboardAppSyntax:
    """Streamlit AppTest Windows olay döngüsünde takıldığı için sözdizimini sınar."""

    def test_app_syntax_and_compilation(self):
        app_file = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
        compiled = py_compile.compile(str(app_file), doraise=True)
        assert compiled is not None
