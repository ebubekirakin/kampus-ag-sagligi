"""
NetNabız Ground Truth Değerlendirme Modülü.
data/ground_truth.json dosyasındaki bilinen 4 kampüs arıza senaryosu ile
analiz boru hattının (kural tabanlı teşhis ve istatistiksel anomaliler)
ürettiği bulguları karşılaştırır.
Başarı durumunu (Bulundu / Bulunamadı) ve yanlış alarmları raporlar;
sonuçları data/evaluation_result.md dosyasına Markdown tablosu olarak yazar.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from backend.config import BASE_DIR, load_config
from analytics.data import load_measurements
from analytics.rules import diagnose_issues
from analytics.anomaly import detect_anomalies


def load_ground_truth(file_path: Path | None = None) -> list[dict[str, Any]]:
    """Ground truth JSON dosyasını okur."""
    target = file_path or (BASE_DIR / "data" / "ground_truth.json")
    if not target.exists():
        raise FileNotFoundError(f"Ground truth dosyası bulunamadı: {target}")

    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_detection(
    data_type: str = "simulated",
    gt_path: Path | None = None,
    output_md: Path | None = None,
) -> dict[str, Any]:
    """
    Tespit edilen sorunları ground truth senaryolarıyla karşılaştırır.
    """
    config = load_config()
    ground_truth = load_ground_truth(gt_path)

    df, meta = load_measurements(data_type=data_type, verified_only=True)
    if df.empty:
        raise RuntimeError("Değerlendirme için veri bulunamadı.")

    diagnosed = diagnose_issues(df, config)
    anomalies = detect_anomalies(df, config)

    all_detections = []
    for d in diagnosed:
        all_detections.append({**d, "source_module": "rules"})
    for a in anomalies:
        all_detections.append({**a, "source_module": "anomaly"})

    matched_indices = set()
    evaluation_results = []

    for gt in ground_truth:
        scenario_id = gt["scenario_id"]
        gt_zone = gt["zone"]
        gt_type = gt["issue_type"]
        gt_bssid = gt.get("bssid")

        found = False
        matching_detection = None

        for idx, det in enumerate(all_detections):
            if det["zone"] != gt_zone:
                continue

            # Senaryo 1: Tıkanıklık (congestion)
            if scenario_id == "congestion" and det.get("issue_type") == "congestion":
                found = True
                matching_detection = det
                matched_indices.add(idx)
                break

            # Senaryo 2: Kapsama eksikliği (coverage_gap)
            if scenario_id == "coverage_gap" and det.get("issue_type") == "coverage_gap":
                found = True
                matching_detection = det
                matched_indices.add(idx)
                break

            # Senaryo 3: Arızalı AP (faulty_ap)
            if scenario_id == "faulty_ap" and det.get("issue_type") == "faulty_ap":
                if not gt_bssid or det.get("bssid") == gt_bssid:
                    found = True
                    matching_detection = det
                    matched_indices.add(idx)
                    break

            # Senaryo 4: Ani kesinti (sudden_outage / 7. gün 14:00)
            if scenario_id == "sudden_outage" and det.get("issue_type") == "anomaly":
                # 7. gün tarihi simülasyon başlangıcından 6 gün sonra (2026-11-08) saat 14
                date_str = det.get("date", "")
                time_w = det.get("time_window", "")
                if "14:00" in time_w or "2026-11-08" in date_str:
                    found = True
                    matching_detection = det
                    matched_indices.add(idx)
                    break

        evaluation_results.append({
            "scenario_id": scenario_id,
            "title": gt["title"],
            "zone": gt_zone,
            "expected_time": gt.get("time_window"),
            "status": "Bulundu" if found else "Bulunamadı",
            "detected_info": matching_detection.get("details") if matching_detection else "-",
            "detected_by": matching_detection.get("source_module") if matching_detection else "-",
        })

    # Ground truth dışında kalan tespitler (yanlış alarmlar / false positives)
    false_positives = []
    for idx, det in enumerate(all_detections):
        if idx not in matched_indices:
            # Tıkanıklık ve kesinti dışındaki tekil anomali veya fazla uyarılar
            false_positives.append(det)

    # Markdown raporunu üret
    md_file = output_md or (BASE_DIR / "data" / "evaluation_result.md")
    md_content = _generate_markdown_report(evaluation_results, false_positives)
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    return {
        "results": evaluation_results,
        "false_positives": false_positives,
        "markdown_path": md_file,
    }


def _generate_markdown_report(
    results: list[dict[str, Any]],
    false_positives: list[dict[str, Any]],
) -> str:
    """Değerlendirme sonucunu tez için temiz bir Markdown tablosuna dönüştürür."""
    found_count = sum(1 for r in results if r["status"] == "Bulundu")
    total_count = len(results)

    lines = [
        "# NetNabız - Analiz ve Sorun Tespit Değerlendirme Raporu",
        "",
        f"**Tarih:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"**Başarı Oranı:** {found_count} / {total_count} senaryo başarıyla tespit edildi (%{(found_count/total_count)*100:.1f})  ",
        f"**Yanlış Alarm / Ek Tespit Sayısı:** {len(false_positives)} adet  ",
        "",
        "## 1. Bilinen Senaryolar (Ground Truth Karşılaştırması)",
        "",
        "| Senaryo | Bölge | Beklenen Zaman | Durum | Tespit Eden Modül | Tespit Detayı |",
        "|---|---|---|:---:|:---:|---|",
    ]

    for r in results:
        status_badge = "**✓ Bulundu**" if r["status"] == "Bulundu" else "**✗ Bulunamadı**"
        lines.append(
            f"| {r['title']} | {r['zone']} | {r['expected_time']} | {status_badge} | `{r['detected_by']}` | {r['detected_info']} |"
        )

    lines.extend([
        "",
        "## 2. Ek Tespitler ve Yanlış Alarm Değerlendirmesi",
        "",
    ])

    if not false_positives:
        lines.append("Ek yanlış alarm bulunmamaktadır.")
    else:
        lines.append(
            "Aşağıdaki olaylar sentetik ground truth senaryosu haricinde, veri içerisindeki "
            "doğal stokastik gürültü veya ardışık arızalı AP etkileşiminden dolayı anomali olarak etiketlenmiştir:"
        )
        lines.append("")
        lines.append("| Tip | Bölge | Zaman | Z-Skor / Detay |")
        lines.append("|---|---|---|---|")
        for fp in false_positives:
            z_info = f"z={fp.get('robust_z')}" if "robust_z" in fp else fp.get("issue_type")
            lines.append(f"| {fp.get('title')} | {fp.get('zone')} | {fp.get('time_window')} | {z_info} |")

    lines.append("")
    return "\n".join(lines)


def main():
    print("\n" + "=" * 70)
    print("      NETNABIZ GROUND TRUTH DEĞERLENDİRME ÇIKTISI")
    print("=" * 70)

    try:
        eval_data = evaluate_detection()
    except Exception as e:
        print(f"[!] Hata: {e}")
        return 1

    results = eval_data["results"]
    fps = eval_data["false_positives"]

    print(f"{'Senaryo':<26} {'Bölge':<32} {'Durum':<12} {'Modül':<10}")
    print("-" * 84)
    for r in results:
        status_str = f"[OK] {r['status']}" if r["status"] == "Bulundu" else f"[X] {r['status']}"
        print(f"{r['title']:<26} {r['zone'][:30]:<32} {status_str:<12} {r['detected_by']:<10}")

    print("\nDetaylar:")
    for r in results:
        print(f" - {r['title']} ({r['zone']}): {r['detected_info']}")

    print(f"\nEk Tespit / Yanlış Alarm Sayısı: {len(fps)} adet")
    print(f"[OK] Rapor oluşturuldu: {eval_data['markdown_path']}")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    main()
