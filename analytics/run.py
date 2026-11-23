"""
NetNabız Analiz Çalıştırma Komut Satırı Arayüzü (CLI).
Kullanım:
    python -m analytics.run --data simulated
    python -m analytics.run --data real
    python -m analytics.run --data all
"""

import argparse
import sys
from backend.config import load_config
from analytics.data import load_measurements
from analytics.rules import calculate_zone_scores, diagnose_issues
from analytics.anomaly import detect_anomalies
from analytics.forecast import evaluate_forecast, compute_participation_density
from analytics.summary import generate_ap_aliases, build_analysis_summary, save_summary_files


def run_pipeline(data_type: str = "simulated", verified_only: bool = True) -> int:
    """Tam analiz boru hattını çalıştırır ve terminale okunabilir rapor basar."""
    config = load_config()

    print("\n" + "=" * 70)
    print("      NETNABIZ KAMPÜS AĞ SAĞLIĞI ANALİZ RAPORU")
    print("=" * 70)
    print(f"[*] Veri kaynağı: {data_type.upper()} (Doğrulanmış: {'Evet' if verified_only else 'Tümü'})")

    try:
        df, meta = load_measurements(data_type=data_type, verified_only=verified_only)
    except Exception as e:
        print(f"[!] Veri yükleme hatası: {e}")
        return 1

    total = meta["total_records"]
    if total == 0:
        print("[!] Seçilen kriterde analiz edilecek kayıt bulunamadı.")
        return 0

    print(f"[*] Toplam kayıt: {total:,} adet")
    print(f"[*] Zaman aralığı: {meta['min_time']} -> {meta['max_time']}")
    print(f"[*] Referans zamanı: {meta['reference_time']}")
    print("-" * 70)

    # 1. Bölge Skorları
    zone_scores = calculate_zone_scores(df, config)
    print("\n[1] BÖLGE SAĞLIK SKORLARI (0-100)")
    print(f"{'Bölge':<38} {'Skor':<7} {'Durum':<10} {'RTT(ms)':<9} {'Kayıp%':<8} {'Hız':<8} {'Örnek':<6}")
    print("-" * 92)
    for z in zone_scores:
        score_str = f"{z['score']:.1f}" if z["score"] is not None else "-"
        rtt_str = f"{z['median_rtt_ms']:.1f}" if z["median_rtt_ms"] is not None else "-"
        loss_str = f"{z['median_loss_pct']:.2f}%" if z["median_loss_pct"] is not None else "-"
        down_str = f"{z['median_down_mbps']:.1f}" if z["median_down_mbps"] is not None else "-"
        status_disp = f"[{z['color'].upper()}] {z['status']}"
        print(f"{z['zone']:<38} {score_str:<7} {status_disp:<10} {rtt_str:<9} {loss_str:<8} {down_str:<8} {z['sample_count']:<6}")

    # 2. Kural Tabanlı Sorun Teşhisi
    issues = diagnose_issues(df, config)
    print(f"\n[2] KURAL TABANLI TESPİT EDİLEN SORUNLAR ({len(issues)} adet)")
    print("-" * 70)
    if not issues:
        print("  Belirgin bir kural ihlali veya kronik sorun tespit edilmedi.")
    else:
        for idx, iss in enumerate(issues, start=1):
            print(f"  {idx}. [{iss['title'].upper()}] - {iss['zone']}")
            print(f"     Zaman Aralığı: {iss['time_window']}")
            if iss.get("bssid"):
                print(f"     İlgili AP (Ham BSSID): {iss['bssid']}")
            print(f"     Açıklama: {iss['details']}")
            print()

    # 3. İstatistiksel Anomali Tespiti (MAD / Robust Z)
    anomalies = detect_anomalies(df, config)
    print(f"[3] İSTATİSTİKSEL ANOMALİLER (MAD Robust Z-Skor > 4.0) ({len(anomalies)} adet)")
    print("-" * 70)
    if not anomalies:
        print("  Eşik değerini (|z| > 4.0) aşan anomali bulunamadı.")
    else:
        for idx, anom in enumerate(anomalies, start=1):
            print(f"  {idx}. {anom['title']}")
            print(f"     Zaman: {anom['time_window']} | Z-Skor: {anom['robust_z']}")
            print(f"     Detay: {anom['details']}")
            print()

    # 4. Mevsimsel Tahmin Değerlendirmesi
    forecast = evaluate_forecast(df, config)
    print("[4] MEVSİMSEL TAHMİN VE TABAN MODEL KIYASLAMASI (MAE)")
    print("-" * 70)
    if forecast.get("status") == "basarili":
        print(f"  Test Örnek Sayısı (Son {config.get('analytics', {}).get('forecast_test_days', 3)} Gün): {forecast['test_sample_count']}")
        print(f"  Eğitim Örnek Sayısı: {forecast['train_sample_count']}")
        print(f"  Taban Çizgisi (Tekil Medyan) MAE : {forecast['mae_baseline']:.2f} ms")
        print(f"  Mevsimsel Medyan Modeli MAE      : {forecast['mae_seasonal']:.2f} ms")
        print(f"  Hata İyileşme Oranı             : %{forecast['improvement_pct']:.1f}")
    else:
        print(f"  Tahmin durumu: {forecast.get('status')}")

    # 5. Katılım Yoğunluğu
    participation = compute_participation_density(df)
    print("\n[5] SAATLİK ÖLÇÜM KATILIM DAĞILIMI")
    print("-" * 70)
    print(f"  En yoğun katılım saati : {participation.get('peak_hour')}")
    print(f"  En sakin katılım saati : {participation.get('quiet_hour')}")
    print(f"  Metodolojik Not: {participation.get('methodological_note')}")

    # 6. Gizlilik ve Dışa Aktarma
    all_bssids = df["bssid"].dropna().tolist() if "bssid" in df.columns else []
    alias_map = generate_ap_aliases(all_bssids)

    summary_data = build_analysis_summary(
        metadata=meta,
        zone_scores=zone_scores,
        issues=issues,
        anomalies=anomalies,
        forecast=forecast,
        participation=participation,
        alias_map=alias_map,
    )

    sum_path, map_path = save_summary_files(summary_data, alias_map)
    print("\n" + "=" * 70)
    print(f"[OK] Analiz tamamlandı. Gizlilik kurallarına uygun özet dosyalar yazıldı:")
    print(f"     - Özet Rapor  : {sum_path.resolve()}")
    print(f"     - AP Maskeleri: {map_path.resolve()}")
    print("=" * 70 + "\n")
    return 0


def main():
    parser = argparse.ArgumentParser(description="NetNabız Kampüs Ağ Analiz Aracı")
    parser.add_argument(
        "--data",
        choices=["simulated", "real", "all"],
        default="simulated",
        help="Analiz edilecek veri tipi (varsayılan: simulated)",
    )
    parser.add_argument(
        "--include-unverified",
        action="store_true",
        default=False,
        help="Doğrulanmamış (is_verified=0) kayıtları da analize dahil et",
    )
    args = parser.parse_args()
    sys.exit(run_pipeline(data_type=args.data, verified_only=not args.include_unverified))


if __name__ == "__main__":
    main()
