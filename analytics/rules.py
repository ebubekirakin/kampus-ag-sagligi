"""
NetNabız Kural Tabanlı Analiz Modülü.
Bölge sağlık skorlarını hesaplar ve ağ sorunlarını (tıkanıklık, kapsama eksikliği,
arızalı erişim noktası) kural tabanlı istatistiksel eşiklerle tespit eder.
Kesinlikle sabit bölge veya BSSID adı içermez.
"""

from typing import Any
import pandas as pd
from backend.config import load_config


def calculate_zone_scores(df: pd.DataFrame, config: dict | None = None) -> list[dict[str, Any]]:
    """
    Her bölge için ağ sağlık skorunu (0-100) hesaplar.
    
    Bileşenler ve varsayılan ağırlıklar:
      - Gecikme (RTT): %30 (20 ms -> 1.0, 150 ms -> 0.0)
      - Paket Kaybı: %25 (0.5% -> 1.0, 10.0% -> 0.0)
      - İndirme Hızı: %25 (50 Mbps -> 1.0, 5 Mbps -> 0.0)
      - Sinyal Seviyesi: %20 (-55 dBm -> 1.0, -85 dBm -> 0.0)
      
    Eğer sinyal verisi yoksa, ağırlıklar diğer 3 bileşene oransal dağıtılır.
    Örnek sayısı min_samples (varsayılan 20) altındaysa 'yetersiz veri' döner.
    """
    if config is None:
        config = load_config()
    cfg = config.get("analytics", {})

    min_samples = cfg.get("min_samples", 20)
    w_rtt = cfg.get("weight_rtt", 0.30)
    w_loss = cfg.get("weight_loss", 0.25)
    w_down = cfg.get("weight_download", 0.25)
    w_sig = cfg.get("weight_signal", 0.20)

    rtt_best = cfg.get("rtt_best_ms", 20.0)
    rtt_worst = cfg.get("rtt_worst_ms", 150.0)
    loss_best = cfg.get("loss_best_pct", 0.5)
    loss_worst = cfg.get("loss_worst_pct", 10.0)
    down_best = cfg.get("download_best_mbps", 50.0)
    down_worst = cfg.get("download_worst_mbps", 5.0)
    sig_best = cfg.get("signal_best_dbm", -55.0)
    sig_worst = cfg.get("signal_worst_dbm", -85.0)

    score_green = cfg.get("score_green", 75.0)
    score_yellow = cfg.get("score_yellow", 50.0)

    if df.empty or "zone" not in df.columns:
        return []

    results = []
    # Yapılandırmadaki tüm bölgeleri tara, eksik olanları da listele
    all_zones = config.get("zones", [])
    present_zones = list(df["zone"].dropna().unique())
    combined_zones = sorted(list(set(all_zones + present_zones)))

    for zone in combined_zones:
        z_df = df[df["zone"] == zone]
        sample_count = len(z_df)

        if sample_count < min_samples:
            results.append({
                "zone": zone,
                "sample_count": sample_count,
                "status": "yetersiz veri",
                "color": "gri",
                "score": None,
                "median_rtt_ms": None,
                "p90_rtt_ms": None,
                "median_loss_pct": None,
                "median_down_mbps": None,
                "median_signal_dbm": None,
            })
            continue

        # Metrik medyan ve yüzdelik hesapları (boş değerleri atlayarak)
        rtt_series = z_df["rtt_ms"].dropna()
        loss_series = z_df["loss_pct"].dropna()
        down_series = z_df["down_mbps"].dropna()
        sig_series = z_df["rssi_dbm"].dropna()

        med_rtt = float(rtt_series.median()) if not rtt_series.empty else None
        p90_rtt = float(rtt_series.quantile(0.90)) if not rtt_series.empty else None
        med_loss = float(loss_series.median()) if not loss_series.empty else None
        med_down = float(down_series.median()) if not down_series.empty else None
        med_sig = float(sig_series.median()) if not sig_series.empty else None

        # Doğrusal normalizasyon (0.0 - 1.0 aralığına sıkıştırma)
        # RTT: Düşük değer iyi (20 ms -> 1.0, 150 ms -> 0.0)
        norm_rtt = None
        if med_rtt is not None:
            norm_rtt = max(0.0, min(1.0, (rtt_worst - med_rtt) / (rtt_worst - rtt_best)))

        # Paket Kaybı: Düşük değer iyi (0.5% -> 1.0, 10.0% -> 0.0)
        norm_loss = None
        if med_loss is not None:
            norm_loss = max(0.0, min(1.0, (loss_worst - med_loss) / (loss_worst - loss_best)))

        # İndirme Hızı: Yüksek değer iyi (50 Mbps -> 1.0, 5 Mbps -> 0.0)
        norm_down = None
        if med_down is not None:
            norm_down = max(0.0, min(1.0, (med_down - down_worst) / (down_best - down_worst)))

        # Sinyal: Yüksek değer iyi (-55 dBm -> 1.0, -85 dBm -> 0.0)
        norm_sig = None
        if med_sig is not None:
            norm_sig = max(0.0, min(1.0, (med_sig - sig_worst) / (sig_best - sig_worst)))

        # Ağırlıklandırma ve eksik bileşen yeniden dağıtımı
        components = []
        if norm_rtt is not None:
            components.append((norm_rtt, w_rtt))
        if norm_loss is not None:
            components.append((norm_loss, w_loss))
        if norm_down is not None:
            components.append((norm_down, w_down))
        if norm_sig is not None:
            components.append((norm_sig, w_sig))

        if not components:
            results.append({
                "zone": zone,
                "sample_count": sample_count,
                "status": "yetersiz veri",
                "color": "gri",
                "score": None,
                "median_rtt_ms": med_rtt,
                "p90_rtt_ms": p90_rtt,
                "median_loss_pct": med_loss,
                "median_down_mbps": med_down,
                "median_signal_dbm": med_sig,
            })
            continue

        total_weight = sum(w for _, w in components)
        final_score = sum((norm * (w / total_weight)) for norm, w in components) * 100.0
        final_score = round(final_score, 1)

        if final_score >= score_green:
            status = "iyi"
            color = "yeşil"
        elif final_score >= score_yellow:
            status = "orta"
            color = "sarı"
        else:
            status = "zayıf"
            color = "kırmızı"

        results.append({
            "zone": zone,
            "sample_count": sample_count,
            "status": status,
            "color": color,
            "score": final_score,
            "median_rtt_ms": round(med_rtt, 1) if med_rtt is not None else None,
            "p90_rtt_ms": round(p90_rtt, 1) if p90_rtt is not None else None,
            "median_loss_pct": round(med_loss, 2) if med_loss is not None else None,
            "median_down_mbps": round(med_down, 1) if med_down is not None else None,
            "median_signal_dbm": round(med_sig, 1) if med_sig is not None else None,
        })

    return results


def diagnose_issues(df: pd.DataFrame, config: dict | None = None) -> list[dict[str, Any]]:
    """
    Kural tabanlı ağ sorunlarını tespit eder:
      1. Tıkanıklık (Congestion):
         Hafta içi belirli saatlerde, medyan RTT >= 2 * bölge medyan RTT VE sinyal >= -70 dBm.
         (İyi sinyale rağmen yüksek gecikme yoğun kullanıcı yükünü gösterir).
      2. Kapsama Eksikliği (Coverage Gap):
         Bölge genelinde medyan sinyal <= -75 dBm VE medyan indirme <= 5 Mbps.
      3. Arızalı Erişim Noktası (Faulty AP):
         Belirli bir BSSID için örnek sayısı >= 10, medyan paket kaybı >= %8.0 VE
         aynı bölgedeki diğer AP'lerin kaybının en az 2 katı.
    """
    if config is None:
        config = load_config()
    cfg = config.get("analytics", {})

    cong_rtt_mult = cfg.get("congestion_rtt_multiplier", 2.0)
    cong_min_sig = cfg.get("congestion_min_signal_dbm", -70.0)
    cov_poor_sig = cfg.get("coverage_poor_signal_dbm", -75.0)
    cov_poor_down = cfg.get("coverage_poor_download_mbps", 5.0)
    ap_min_loss = cfg.get("ap_min_loss_pct", 8.0)
    ap_loss_mult = cfg.get("ap_loss_multiplier", 2.0)
    min_ap_samples = cfg.get("min_ap_samples", 10)
    min_hour_samples = cfg.get("min_hour_samples", 2)
    min_congestion_samples = cfg.get("min_congestion_samples", 5)

    issues = []
    if df.empty or "zone" not in df.columns:
        return issues

    zones = df["zone"].dropna().unique()

    # 1. KAPSAMA EKSİKLİĞİ (Bölge Düzeyinde)
    if "rssi_dbm" in df.columns and "down_mbps" in df.columns:
        for zone in zones:
            z_df = df[df["zone"] == zone]
            sig_series = z_df["rssi_dbm"].dropna()
            down_series = z_df["down_mbps"].dropna()

            if len(sig_series) >= 10 and len(down_series) >= 10:
                med_sig = float(sig_series.median())
                med_down = float(down_series.median())
                if med_sig <= cov_poor_sig and med_down <= cov_poor_down:
                    issues.append({
                        "issue_type": "coverage_gap",
                        "title": "Kapsama eksikliği",
                        "zone": zone,
                        "bssid": None,
                        "time_window": "Sürekli",
                        "details": (
                            f"Medyan sinyal {med_sig:.1f} dBm (eşik <= {cov_poor_sig} dBm) "
                            f"ve medyan indirme hızı {med_down:.1f} Mbps (eşik <= {cov_poor_down} Mbps)"
                        ),
                        "metrics": {
                            "median_signal_dbm": round(med_sig, 1),
                            "median_down_mbps": round(med_down, 1),
                        },
                    })

    # 2. TIKANIKLIK (Hafta içi saatlik dilimler)
    # df içerisinde 'is_weekend' ve 'hour' sütunları olmalıdır (data.py tarafından eklenir)
    if "is_weekend" in df.columns and "hour" in df.columns and "rtt_ms" in df.columns:
        weekday_df = df[~df["is_weekend"]]
        for zone in zones:
            z_week = weekday_df[weekday_df["zone"] == zone]
            overall_rtt = z_week["rtt_ms"].dropna()
            if len(overall_rtt) < 15:
                continue
            base_rtt = float(overall_rtt.median())

            congested_hours = []
            hour_stats = {}
            for h in range(24):
                h_df = z_week[z_week["hour"] == h]
                h_rtt = h_df["rtt_ms"].dropna()
                h_sig = h_df["rssi_dbm"].dropna()

                if len(h_rtt) >= min_congestion_samples:
                    med_h_rtt = float(h_rtt.median())
                    med_h_sig = float(h_sig.median()) if not h_sig.empty else -999.0

                    if med_h_rtt >= cong_rtt_mult * base_rtt and med_h_sig >= cong_min_sig:
                        congested_hours.append(h)
                        hour_stats[h] = {
                            "rtt": med_h_rtt,
                            "signal": med_h_sig,
                            "count": len(h_rtt),
                        }

            # Ardışık saatleri birleştir (örn. 16, 17, 18 -> 16:00-19:00)
            if congested_hours:
                intervals = _group_consecutive_hours(congested_hours)
                for start_h, end_h in intervals:
                    span_hours = list(range(start_h, end_h + 1))
                    avg_cong_rtt = sum(hour_stats[h]["rtt"] for h in span_hours) / len(span_hours)
                    time_window = f"Hafta içi {start_h:02d}:00-{end_h+1:02d}:00"
                    issues.append({
                        "issue_type": "congestion",
                        "title": "Yoğun saatlerde tıkanıklık",
                        "zone": zone,
                        "bssid": None,
                        "time_window": time_window,
                        "details": (
                            f"{time_window} aralığında medyan gecikme {avg_cong_rtt:.1f} ms "
                            f"(bölge normali {base_rtt:.1f} ms, {cong_rtt_mult:.1f}x katı), "
                            f"sinyal seviyesi yeterli (>= {cong_min_sig} dBm)"
                        ),
                        "metrics": {
                            "observed_median_rtt_ms": round(avg_cong_rtt, 1),
                            "baseline_rtt_ms": round(base_rtt, 1),
                            "hours": span_hours,
                        },
                    })

    # 3. ARIZALI ERİŞİM NOKTASI (BSSID Düzeyinde)
    if "bssid" in df.columns and "loss_pct" in df.columns:
        valid_bssid_df = df[df["bssid"].notna() & (df["bssid"] != "")]
        for zone in zones:
            z_bssid_df = valid_bssid_df[valid_bssid_df["zone"] == zone]
            bssids = z_bssid_df["bssid"].unique()
            if len(bssids) < 2:
                # Tek bir AP varsa diğerleriyle kıyas yapılamaz, tüm bölge verisi üzerinden bak
                continue

            for bssid in bssids:
                ap_df = z_bssid_df[z_bssid_df["bssid"] == bssid]
                ap_loss = ap_df["loss_pct"].dropna()

                if len(ap_loss) < min_ap_samples:
                    continue

                med_ap_loss = float(ap_loss.median())

                # Kıyas tabanına yalnızca yeterli ölçümü olan diğer AP'leri al.
                other_ap_medians = []
                for other_bssid, other_df in z_bssid_df.groupby("bssid"):
                    if other_bssid == bssid:
                        continue
                    other_loss = other_df["loss_pct"].dropna()
                    if len(other_loss) >= min_ap_samples:
                        other_ap_medians.append(float(other_loss.median()))

                if not other_ap_medians:
                    continue

                med_other_loss = max(float(pd.Series(other_ap_medians).median()), 0.5)

                if med_ap_loss >= ap_min_loss and med_ap_loss >= ap_loss_mult * med_other_loss:
                    issues.append({
                        "issue_type": "faulty_ap",
                        "title": "Arızalı erişim noktası",
                        "zone": zone,
                        "bssid": bssid,
                        "time_window": "Sürekli",
                        "details": (
                            f"BSSID {bssid} için medyan paket kaybı %{med_ap_loss:.1f} "
                            f"(eşik >= %{ap_min_loss}, komşu AP medyanı %{med_other_loss:.1f})"
                        ),
                        "metrics": {
                            "median_loss_pct": round(med_ap_loss, 2),
                            "neighbors_median_loss_pct": round(med_other_loss, 2),
                            "sample_count": len(ap_loss),
                        },
                    })

    return issues


def _group_consecutive_hours(hours: list[int]) -> list[tuple[int, int]]:
    """Ardışık saat listesini başlangıç ve bitiş aralıklarına gruplar."""
    if not hours:
        return []
    sorted_hours = sorted(set(hours))
    ranges = []
    start = sorted_hours[0]
    prev = sorted_hours[0]

    for h in sorted_hours[1:]:
        if h == prev + 1:
            prev = h
        else:
            ranges.append((start, prev))
            start = h
            prev = h
    ranges.append((start, prev))
    return ranges
