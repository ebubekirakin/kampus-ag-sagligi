"""
NetNabız Analiz Modülü Birim Testleri.
Bölüm 5 gereksinimlerine göre:
  1. Skorlama ve sınır değer kontrolleri (0-100, ağırlıklar, yeşil/sarı/kırmızı)
  2. Yetersiz veri kontrolü (<20 örnek durumunda 'yetersiz veri')
  3. Kural tabanlı sorun teşhisleri (Tıkanıklık, Kapsama, Arızalı AP)
  4. MAD anomali hesaplaması, aykırı değer yakalama ve MAD=0 güvenli bölme testi
  5. Zaman serisi sızıntısı (train/test split leakage) kontrolü
  6. Gizlilik ve özet çıktısı denetimi (device_hash, ssid ve ham bssid bulunmama garantisi)
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import analytics.run as analytics_run
import pandas as pd
import pytest

from storage.sqlite_store import SQLiteMeasurementStore


from analytics.data import load_measurements
from analytics.rules import calculate_zone_scores, diagnose_issues
from analytics.anomaly import detect_anomalies
from analytics.forecast import (
    evaluate_forecast,
    compute_participation_density,
    evaluate_participation_forecast,
)
from analytics.summary import (
    generate_ap_aliases,
    mask_issues_bssids,
    build_analysis_summary,
)
from analytics.evaluate import (
    _classify_extra_findings,
    _detection_interval,
    _expected_outage_interval,
    _generate_markdown_report,
    _intervals_overlap,
    _matches_congestion,
)


@pytest.fixture
def mock_analytics_config():
    """Testler için standart analiz yapılandırması."""
    return {
        "zones": ["Test Bölgesi A", "Test Bölgesi B"],
        "analytics": {
            "min_samples": 20,
            "weight_rtt": 0.30,
            "weight_loss": 0.25,
            "weight_download": 0.25,
            "weight_signal": 0.20,
            "rtt_best_ms": 20.0,
            "rtt_worst_ms": 150.0,
            "loss_best_pct": 0.5,
            "loss_worst_pct": 10.0,
            "download_best_mbps": 50.0,
            "download_worst_mbps": 5.0,
            "signal_best_dbm": -55.0,
            "signal_worst_dbm": -85.0,
            "score_green": 75.0,
            "score_yellow": 50.0,
            "congestion_rtt_multiplier": 2.0,
            "congestion_min_signal_dbm": -70.0,
            "coverage_poor_signal_dbm": -75.0,
            "coverage_poor_download_mbps": 5.0,
            "ap_min_loss_pct": 8.0,
            "ap_loss_multiplier": 2.0,
            "min_ap_samples": 10,
            "min_hour_samples": 2,
            "anomaly_z_threshold": 4.0,
            "anomaly_mad_floor": 1.0,
            "forecast_test_days": 3,
        },
    }


class TestZoneScoring:
    """Bölge skorlama ve normalizasyon testleri."""

    def test_insufficient_samples_returns_status(self, mock_analytics_config):
        """Örnek sayısı 20'nin altında olduğunda 'yetersiz veri' dönmelidir."""
        data = {
            "zone": ["Test Bölgesi A"] * 10,
            "rtt_ms": [25.0] * 10,
            "loss_pct": [0.5] * 10,
            "down_mbps": [45.0] * 10,
            "rssi_dbm": [-60.0] * 10,
        }
        df = pd.DataFrame(data)
        results = calculate_zone_scores(df, mock_analytics_config)
        assert len(results) == 2
        res_a = next(r for r in results if r["zone"] == "Test Bölgesi A")
        assert res_a["status"] == "yetersiz veri"
        assert res_a["score"] is None
        assert res_a["color"] == "gri"

    def test_ideal_conditions_returns_perfect_score(self, mock_analytics_config):
        """Tüm metrikler en iyi eşiklerdeyken skor 100 ve yeşil olmalıdır."""
        data = {
            "zone": ["Test Bölgesi A"] * 25,
            "rtt_ms": [20.0] * 25,       # En iyi (1.0)
            "loss_pct": [0.5] * 25,      # En iyi (1.0)
            "down_mbps": [50.0] * 25,    # En iyi (1.0)
            "rssi_dbm": [-55.0] * 25,    # En iyi (1.0)
        }
        df = pd.DataFrame(data)
        results = calculate_zone_scores(df, mock_analytics_config)
        res_a = next(r for r in results if r["zone"] == "Test Bölgesi A")
        assert res_a["status"] == "iyi"
        assert res_a["color"] == "yeşil"
        assert res_a["score"] == 100.0

    def test_worst_conditions_returns_zero_score(self, mock_analytics_config):
        """Tüm metrikler en kötü eşiklerdeyken skor 0 ve kırmızı olmalıdır."""
        data = {
            "zone": ["Test Bölgesi A"] * 25,
            "rtt_ms": [200.0] * 25,      # 150 ms üstü -> 0.0
            "loss_pct": [15.0] * 25,     # %10 üstü -> 0.0
            "down_mbps": [2.0] * 25,     # 5 Mbps altı -> 0.0
            "rssi_dbm": [-90.0] * 25,    # -85 dBm altı -> 0.0
        }
        df = pd.DataFrame(data)
        results = calculate_zone_scores(df, mock_analytics_config)
        res_a = next(r for r in results if r["zone"] == "Test Bölgesi A")
        assert res_a["status"] == "zayıf"
        assert res_a["color"] == "kırmızı"
        assert res_a["score"] == 0.0

    def test_missing_signal_redistributes_weights(self, mock_analytics_config):
        """Sinyal verisi None iken kalan ağırlıklar orantılı paylaştırılmalıdır."""
        data = {
            "zone": ["Test Bölgesi A"] * 25,
            "rtt_ms": [20.0] * 25,       # 1.0 (w=0.30)
            "loss_pct": [0.5] * 25,      # 1.0 (w=0.25)
            "down_mbps": [50.0] * 25,    # 1.0 (w=0.25)
            "rssi_dbm": [None] * 25,     # Yok
        }
        df = pd.DataFrame(data)
        results = calculate_zone_scores(df, mock_analytics_config)
        res_a = next(r for r in results if r["zone"] == "Test Bölgesi A")
        # 1.0 ağırlıkla yine 100 dönmeli
        assert res_a["score"] == 100.0
        assert res_a["median_signal_dbm"] is None


class TestRuleDiagnosis:
    """Kural tabanlı arıza tespit testleri."""

    def test_congestion_detection(self, mock_analytics_config):
        """Hafta içi iyi sinyale rağmen yüksek gecikme tıkanıklık teşhisini tetiklemelidir."""
        # 5 gün boyunca saat 16'da 200 ms RTT, normal saatlerde 30 ms RTT
        records = []
        base_dt = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)  # Pazartesi
        for day in range(5):
            for h in range(8, 20):
                is_busy = (h == 16)
                rtt = 220.0 if is_busy else 30.0
                records.append({
                    "zone": "Test Bölgesi A",
                    "rtt_ms": rtt,
                    "loss_pct": 0.5,
                    "down_mbps": 30.0,
                    "rssi_dbm": -60.0,  # İyi sinyal
                    "is_weekend": False,
                    "hour": h,
                    "dt": base_dt + timedelta(days=day, hours=h),
                })
        df = pd.DataFrame(records)
        issues = diagnose_issues(df, mock_analytics_config)
        cong = [i for i in issues if i["issue_type"] == "congestion"]
        assert len(cong) == 1
        assert cong[0]["zone"] == "Test Bölgesi A"
        assert "16:00" in cong[0]["time_window"]

    def test_coverage_gap_detection(self, mock_analytics_config):
        """Düşük sinyal ve düşük hız kapsama eksikliği teşhisini tetiklemelidir."""
        records = [{
            "zone": "Test Bölgesi A",
            "rtt_ms": 50.0,
            "loss_pct": 0.5,
            "down_mbps": 3.0,     # <= 5.0 Mbps
            "rssi_dbm": -82.0,    # <= -75 dBm
            "is_weekend": False,
            "hour": 10,
        } for _ in range(25)]
        df = pd.DataFrame(records)
        issues = diagnose_issues(df, mock_analytics_config)
        gap = [i for i in issues if i["issue_type"] == "coverage_gap"]
        assert len(gap) == 1
        assert gap[0]["zone"] == "Test Bölgesi A"

    def test_faulty_ap_detection(self, mock_analytics_config):
        """Bir AP'nin paket kaybı yüksek ve komşularından kat kat fazlaysa arızalı AP teşhis edilmelidir."""
        records = []
        # Sağlam AP-1: %0.5 kayıp (15 ölçüm)
        for _ in range(15):
            records.append({
                "zone": "Test Bölgesi A",
                "bssid": "02:00:00:00:00:01",
                "loss_pct": 0.5,
            })
        # Arızalı AP-2: %18.0 kayıp (15 ölçüm)
        for _ in range(15):
            records.append({
                "zone": "Test Bölgesi A",
                "bssid": "02:00:00:00:00:02",
                "loss_pct": 18.0,
            })
        df = pd.DataFrame(records)
        issues = diagnose_issues(df, mock_analytics_config)
        f_ap = [i for i in issues if i["issue_type"] == "faulty_ap"]
        assert len(f_ap) == 1
        assert f_ap[0]["bssid"] == "02:00:00:00:00:02"

    def test_faulty_ap_requires_enough_neighbor_samples(self, mock_analytics_config):
        """Kıyas AP'sinde yeterli veri yoksa arızalı AP kararı verilmemelidir."""
        records = [
            {"zone": "Test Bölgesi A", "bssid": "AP-A", "loss_pct": 18.0}
            for _ in range(15)
        ]
        records.extend([
            {"zone": "Test Bölgesi A", "bssid": "AP-B", "loss_pct": 0.5}
            for _ in range(2)
        ])
        issues = diagnose_issues(pd.DataFrame(records), mock_analytics_config)
        assert not [issue for issue in issues if issue["issue_type"] == "faulty_ap"]


class TestAnomalyDetection:
    """MAD ve Sağlam Z-Skor anomali tespit testleri."""

    def test_mad_zero_division_safety(self, mock_analytics_config):
        """Veriler tamamen sabitken MAD=0 olur; safe_mad sıfıra bölmeyi önlemelidir."""
        base_dt = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
        records = []
        for d in range(5):
            for h in range(10, 16):
                records.append({
                    "zone": "Test Bölgesi A",
                    "rtt_ms": 25.0,  # Tamamen sabit, MAD = 0
                    "loss_pct": 0.5,
                    "dt": base_dt + timedelta(days=d, hours=h),
                    "day_str": (base_dt + timedelta(days=d)).strftime("%Y-%m-%d"),
                    "hour": h,
                })
        df = pd.DataFrame(records)
        # Sıfıra bölme hatası fırlatmamalı
        anomalies = detect_anomalies(df, mock_analytics_config)
        assert len(anomalies) == 0

    def test_weekday_and_weekend_use_separate_hour_baselines(self, mock_analytics_config):
        """Hafta sonunun kendi normal seviyesi hafta içiyle kıyaslanmamalıdır."""
        start = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
        records = []
        for day in range(14):
            date = start + timedelta(days=day)
            value = 400.0 if date.weekday() >= 5 else 50.0
            for sample in range(3):
                records.append({
                    "zone": "Test Bölgesi A",
                    "rtt_ms": value,
                    "loss_pct": 0.5,
                    "dt": date + timedelta(minutes=sample * 10),
                })
        anomalies = detect_anomalies(pd.DataFrame(records), mock_analytics_config)
        assert anomalies == []

    def test_sparse_weekend_falls_back_to_same_hour_only(self, mock_analytics_config):
        """Seyrek hafta sonu saati, diğer saatlerle değil aynı saatle kıyaslanmalıdır."""
        start = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        records = []
        for day in range(4):
            date = start + timedelta(days=day)
            # Saat 13:00 değerleri fallback'in yanlış saate bakmadığını da sınar.
            for hour, value in ((12, 50.0), (13, 200.0)):
                for sample in range(3):
                    records.append({
                        "zone": "Test Bölgesi A",
                        "rtt_ms": value,
                        "loss_pct": 0.5,
                        "dt": date.replace(hour=hour) + timedelta(minutes=sample * 10),
                    })

        weekend = start + timedelta(days=5)
        for sample in range(3):
            records.append({
                "zone": "Test Bölgesi A",
                "rtt_ms": 600.0,
                "loss_pct": 0.5,
                "dt": weekend + timedelta(minutes=sample * 10),
            })

        anomalies = detect_anomalies(pd.DataFrame(records), mock_analytics_config)
        outage = next(
            item for item in anomalies
            if item["date"] == "2026-11-07"
            and item["metric"] == "rtt_ms"
            and "12:00-13:00" in item["time_window"]
        )
        assert outage["baseline_median"] == 50.0
        assert outage["robust_z"] > 4.0

    def test_negative_robust_z_score_is_not_reported(self, mock_analytics_config):
        """Sorun olmayan düşük RTT anomalisi raporlanmamalıdır."""
        start = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
        records = []
        for index, value in enumerate((100.0, 100.0, 100.0, 0.0)):
            date = start + timedelta(days=7 * index)
            for sample in range(3):
                records.append({
                    "zone": "Test Bölgesi A",
                    "rtt_ms": value,
                    "loss_pct": 0.5,
                    "dt": date + timedelta(minutes=sample * 10),
                })
        anomalies = detect_anomalies(pd.DataFrame(records), mock_analytics_config)
        assert not anomalies

    def test_only_high_rtt_and_loss_directions_are_reported(self, mock_analytics_config):
        """Yüksek sorun değerleri bulunur, düşük değerler sonuçlara girmez."""
        start = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
        values = [100.0, 100.0, 100.0, 100.0, 0.0, 1000.0]
        loss_values = [0.5, 0.5, 0.5, 0.5, 0.0, 50.0]
        records = []
        for day, (rtt, loss) in enumerate(zip(values, loss_values)):
            for sample in range(3):
                records.append({
                    "zone": "Test Bölgesi A",
                    "rtt_ms": rtt,
                    "loss_pct": loss,
                    "dt": start + timedelta(days=7 * day, minutes=sample * 10),
                })

        anomalies = detect_anomalies(pd.DataFrame(records), mock_analytics_config)

        assert anomalies
        assert all(item["direction"] == "high" for item in anomalies)
        assert {item["metric"] for item in anomalies} == {"rtt_ms", "loss_pct"}

    def test_known_outlier_detected_with_high_z_score(self, mock_analytics_config):
        """Tek bir günde meydana gelen büyük gecikme sıçraması z > 4.0 ile tespit edilmelidir."""
        base_dt = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
        records = []
        for d in range(14):
            for h in range(8, 20):
                records.append({
                    "zone": "Test Bölgesi A",
                    "rtt_ms": 20.0,
                    "loss_pct": 0.5,
                    "dt": base_dt + timedelta(days=d, hours=h),
                    "day_str": (base_dt + timedelta(days=d)).strftime("%Y-%m-%d"),
                    "hour": h,
                })
        # 6. gün saat 14'te ani kesinti (2 ölçüm: 600 ms)
        records.append({
            "zone": "Test Bölgesi A",
            "rtt_ms": 600.0,
            "loss_pct": 50.0,
            "dt": base_dt + timedelta(days=5, hours=14, minutes=10),
            "day_str": (base_dt + timedelta(days=5)).strftime("%Y-%m-%d"),
            "hour": 14,
        })
        records.append({
            "zone": "Test Bölgesi A",
            "rtt_ms": 620.0,
            "loss_pct": 55.0,
            "dt": base_dt + timedelta(days=5, hours=14, minutes=40),
            "day_str": (base_dt + timedelta(days=5)).strftime("%Y-%m-%d"),
            "hour": 14,
        })
        df = pd.DataFrame(records)
        anomalies = detect_anomalies(df, mock_analytics_config)
        assert len(anomalies) >= 1
        outage = next(a for a in anomalies if a["date"] == (base_dt + timedelta(days=5)).strftime("%Y-%m-%d") and "14:00" in a["time_window"])
        assert outage["robust_z"] > 4.0


class TestForecastAndLeakage:
    """Mevsimsel tahmin ve eğitim/test veri sızıntısı testleri."""

    def test_train_test_split_no_leakage(self, mock_analytics_config):
        """Son 3 günün verisi eğitim seti medyanlarına kesinlikle sızmamalıdır."""
        base_dt = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        records = []
        # İlk 7 gün (Eğitim): RTT = 20.0 ms (Gün 0..6, saat 0..23)
        for d in range(7):
            for h in range(24):
                records.append({
                    "zone": "Test Bölgesi A",
                    "rtt_ms": 20.0,
                    "dt": base_dt + timedelta(days=d, hours=h),
                    "is_weekend": (base_dt + timedelta(days=d)).weekday() >= 5,
                    "hour": h,
                })
        # Son 3 gün (Test): RTT = 150.0 ms (Gün 7..9, saat 0..23)
        for d in range(7, 10):
            for h in range(24):
                records.append({
                    "zone": "Test Bölgesi A",
                    "rtt_ms": 150.0,
                    "dt": base_dt + timedelta(days=d, hours=h),
                    "is_weekend": (base_dt + timedelta(days=d)).weekday() >= 5,
                    "hour": h,
                })
        # Referans zamanı tam gün 9 sonu yapacak bir kapanış damgası (saat 23:59)
        records[-1]["dt"] = base_dt + timedelta(days=9, hours=23, minutes=59)

        df = pd.DataFrame(records)
        res = evaluate_forecast(df, mock_analytics_config)
        assert res["status"] == "basarili"
        assert res["train_sample_count"] > 160
        assert res["test_sample_count"] > 70
        # Taban model eğitim medyanı 20.0 ms olmalı, test verisindeki 150.0 ms ise MAE'yi (150 - 20) = 130 yapmalıdır
        assert abs(res["mae_baseline"] - 130.0) < 0.1

    def test_participation_forecast_splits_time_and_reports_zone_mae(self, mock_analytics_config):
        """Katılım tahmini son üç günü testte tutar ve bölge MAE tablosu üretir."""
        start = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
        records = []
        for day in range(10):
            for hour in range(24):
                for zone in ("Test Bölgesi A", "Test Bölgesi B"):
                    count = 8 if day >= 7 and hour == 12 else 2
                    for sample in range(count):
                        records.append({
                            "zone": zone,
                            "dt": start + timedelta(days=day, hours=hour, minutes=sample),
                            "hour": hour,
                            "is_weekend": (start + timedelta(days=day)).weekday() >= 5,
                        })

        df = pd.DataFrame(records)
        result = evaluate_participation_forecast(df, mock_analytics_config)
        density = compute_participation_density(df, mock_analytics_config)

        assert result["status"] == "başarılı"
        assert result["train_hour_count"] == (6 * 24 + 23) * 2
        assert result["test_hour_count"] == (3 * 24 + 1) * 2
        assert {row["zone"] for row in result["zone_comparison"]} == {
            "Test Bölgesi A", "Test Bölgesi B"
        }
        assert len(density["hourly_distribution"]) == 24
        assert density["forecast"]["mae_seasonal"] is not None


class TestAnalyticsDataLoading:
    """Veri seçimi, saat tabanı ve salt okunur depolama bağlantısını denetler."""

    def create_database(self, path: Path):
        store = SQLiteMeasurementStore(db_path=path)
        with store._write_connection() as connection:
            connection.execute(
                "CREATE TABLE measurements (id INTEGER PRIMARY KEY, is_simulated INTEGER, "
                "is_verified INTEGER, timestamp TEXT, zone TEXT)"
            )
            connection.executemany(
                "INSERT INTO measurements VALUES (?, ?, ?, ?, ?)",
                [
                    (1, 1, 1, "2026-11-02T08:00:00+00:00", "Test Bölgesi A"),
                    (2, 0, 1, "2026-11-02T08:00:00+00:00", "Test Bölgesi A"),
                    (3, 1, 0, "2026-11-02T09:00:00+00:00", "Test Bölgesi A"),
                ],
            )

    def test_filters_time_bases_and_read_only_uri(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "measurements.db"
            self.create_database(db_path)
            config = {"analytics": {"utc_offset_hours": 3}}

            with patch("analytics.data.load_config", return_value=config):
                all_rows, all_meta = load_measurements("all", db_path=db_path)
                simulated, sim_meta = load_measurements("simulated", db_path=db_path)
                real, real_meta = load_measurements("real", db_path=db_path)

            assert len(all_rows) == 2  # Doğrulanmamış simüle satır varsayılan olarak dışarıda.
            assert set(all_rows["dt"].dt.hour) == {11}
            assert all_meta["time_basis"] == "UTC+3"
            assert len(simulated) == 1 and simulated.iloc[0]["hour"] == 8
            assert sim_meta["time_basis"] == "UTC"
            assert len(real) == 1 and real.iloc[0]["hour"] == 11
            assert real_meta["time_basis"] == "UTC+3"

    def test_read_only_open_failure_does_not_retry_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "measurements.db"
            self.create_database(db_path)
            with patch("analytics.data.load_config", return_value={"analytics": {}}):
                with patch.object(
                    SQLiteMeasurementStore,
                    "_get_ro_connection",
                    side_effect=RuntimeError("Veritabanı salt okunur açılamadı"),
                ):
                    with pytest.raises(RuntimeError, match="salt okunur"):
                        load_measurements(db_path=db_path)



class TestPrivacyAndSummary:
    """Gizlilik güvencesi testleri."""

    def test_summary_contains_no_sensitive_fields(self):
        """Özet çıktısı device_hash, ssid ve ham bssid adreslerini asla içermemelidir."""
        raw_bssids = ["02:00:00:03:00:02", "02:00:00:01:00:01"]
        alias_map = generate_ap_aliases(raw_bssids)

        assert "02:00:00:03:00:02" not in alias_map.values()
        assert alias_map["02:00:00:03:00:02"] == "AP-2"

        raw_issues = [{
            "issue_type": "faulty_ap",
            "zone": "Yemekhane Zemin Kat",
            "bssid": "02:00:00:03:00:02",
            "details": "BSSID 02:00:00:03:00:02 için paket kaybı %18",
        }]

        meta = {"data_type": "simulated", "total_records": 100}
        summary = build_analysis_summary(
            metadata=meta,
            zone_scores=[],
            issues=raw_issues,
            anomalies=[],
            forecast={},
            participation={},
            alias_map=alias_map,
        )

        json_str = json.dumps(summary, ensure_ascii=False)
        assert "02:00:00:03:00:02" not in json_str
        assert "AP-2" in json_str
        assert "device_hash" not in json_str
        assert '"ssid":' not in json_str


class TestGroundTruthMatching:
    """Ground truth saat eşleşmesinin gerçek aralıklara dayandığını denetler."""

    def test_outage_uses_configured_day_and_time_offset(self):
        scenario = {"time_window": "7. gün 14:00-15:00 UTC"}
        first_date = datetime(2026, 11, 2).date()

        utc_interval = _expected_outage_interval(scenario, first_date, 0)
        local_interval = _expected_outage_interval(scenario, first_date, 3)

        assert utc_interval == (
            datetime(2026, 11, 8, 14), datetime(2026, 11, 8, 15)
        )
        assert local_interval == (
            datetime(2026, 11, 8, 17), datetime(2026, 11, 8, 18)
        )

    def test_outage_match_requires_actual_time_overlap(self):
        expected = {"date": "2026-11-08", "time_window": "2026-11-08 14:00-15:00"}
        wrong_hour = {"date": "2026-11-08", "time_window": "2026-11-08 09:00-10:00"}
        right_hour = {"date": "2026-11-08", "time_window": "2026-11-08 14:30-15:30"}

        assert not _intervals_overlap(
            _expected_outage_interval(
                {"time_window": "7. gün 14:00-15:00 UTC"},
                datetime(2026, 11, 2).date(),
                0,
            ),
            _detection_interval(wrong_hour),
        )
        assert _intervals_overlap(
            _expected_outage_interval(
                {"time_window": "7. gün 14:00-15:00 UTC"},
                datetime(2026, 11, 2).date(),
                0,
            ),
            _detection_interval(right_hour),
        )

    def test_congestion_match_checks_expected_hours_and_offset(self):
        scenario = {"time_window": "Hafta içi 16:00-19:00"}
        overlapping = {"issue_type": "congestion", "time_window": "Hafta içi 19:00-21:00"}
        unrelated = {"issue_type": "congestion", "time_window": "Hafta içi 12:00-14:00"}

        assert _matches_congestion(scenario, overlapping, utc_offset=3)
        assert not _matches_congestion(scenario, unrelated, utc_offset=3)

    def test_extra_findings_are_grouped_from_ground_truth_type_and_zone(self):
        scenarios = [
            {"issue_type": "high_latency", "zone": "Kütüphane", "time_window": "Hafta içi 16:00-19:00"},
            {"issue_type": "high_packet_loss", "zone": "Yemekhane", "bssid": "test-ap", "time_window": "Sürekli"},
        ]
        detections = [
            {"issue_type": "anomaly", "zone": "Kütüphane", "metric": "rtt_ms", "direction": "high", "date": "2026-11-03", "time_window": "2026-11-03 17:00-18:00"},
            {"issue_type": "anomaly", "zone": "Yemekhane", "metric": "loss_pct", "direction": "high", "date": "2026-11-03", "time_window": "2026-11-03 17:00-18:00"},
            {"issue_type": "anomaly", "zone": "Kütüphane", "metric": "rtt_ms", "direction": "high", "date": "2026-11-03", "time_window": "2026-11-03 12:00-13:00"},
            {"issue_type": "anomaly", "zone": "Başka Bölge", "metric": "loss_pct", "direction": "high", "date": "2026-11-03", "time_window": "2026-11-03 17:00-18:00"},
        ]

        related, unrelated = _classify_extra_findings(
            detections, set(), scenarios, datetime(2026, 11, 2).date(), 0
        )
        sample_result = [{
            "status": "Bulundu",
            "title": "Örnek senaryo",
            "zone": "Kütüphane",
            "expected_time": "16:00-19:00",
            "detected_by": "rules",
            "detected_info": "Örnek kanıt",
        }]
        markdown = _generate_markdown_report(sample_result, related, unrelated)

        assert len(related) == 2
        assert len(unrelated) == 2
        assert "Gömülü Senaryoyla İlişkili Ek Bulgular" in markdown
        assert "İlgisiz Yanlış Alarmlar" in markdown


def test_analytics_run_masks_raw_bssid(capsys):
    """Terminal analiz raporunda ham BSSID yerine AP takma adı gösterilir."""
    raw_bssid = "02:00:00:00:00:99"
    data = pd.DataFrame({"bssid": [raw_bssid]})
    metadata = {
        "total_records": 1,
        "min_time": "2026-11-02T00:00:00+00:00",
        "max_time": "2026-11-02T00:00:00+00:00",
        "reference_time": "2026-11-02T00:00:00+00:00",
    }
    issue = {
        "title": "Arızalı AP",
        "zone": "Test Bölgesi",
        "time_window": "Sürekli",
        "bssid": raw_bssid,
        "details": f"BSSID {raw_bssid} sorunlu",
    }

    with patch.object(analytics_run, "load_config", return_value={}), \
         patch.object(analytics_run, "load_measurements", return_value=(data, metadata)), \
         patch.object(analytics_run, "calculate_zone_scores", return_value=[]), \
         patch.object(analytics_run, "diagnose_issues", return_value=[issue]), \
         patch.object(analytics_run, "detect_anomalies", return_value=[]), \
         patch.object(analytics_run, "evaluate_forecast", return_value={"status": "yetersiz veri"}), \
         patch.object(analytics_run, "compute_participation_density", return_value={"hourly_distribution": {}, "peak_hour": "-", "quiet_hour": "-", "methodological_note": "test"}), \
         patch.object(analytics_run, "save_summary_files", return_value=(Path("summary.json"), Path("aliases.json"))):
        result = analytics_run.run_pipeline()

    output = capsys.readouterr().out
    assert result == 0
    assert raw_bssid not in output
    assert "AP-1" in output
