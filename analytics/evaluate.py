"""
NetNabız Ground Truth Değerlendirme Modülü.
data/ground_truth.json dosyasındaki bilinen 4 kampüs arıza senaryosu ile
analiz boru hattının (kural tabanlı teşhis ve istatistiksel anomaliler)
ürettiği bulguları karşılaştırır.
Başarı durumunu (Bulundu / Bulunamadı) ve yanlış alarmları raporlar;
sonuçları data/evaluation_result.md dosyasına Markdown tablosu olarak yazar.
"""

from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import re
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
    first_time = meta.get("min_time")
    first_date = first_time.date() if first_time is not None else None
    utc_offset = meta.get("utc_offset_hours", 0)

    for gt in ground_truth:
        scenario_id = gt["scenario_id"]
        gt_zone = gt["zone"]
        gt_bssid = gt.get("bssid")

        found = False
        matching_detection = None

        for idx, det in enumerate(all_detections):
            if det["zone"] != gt_zone:
                continue

            if scenario_id == "congestion" and _matches_congestion(
                gt, det, utc_offset
            ):
                found = True
                matching_detection = det
                matched_indices.add(idx)
                break

            if scenario_id == "coverage_gap" and det.get("issue_type") == "coverage_gap":
                found = True
                matching_detection = det
                matched_indices.add(idx)
                break

            if scenario_id == "faulty_ap" and det.get("issue_type") == "faulty_ap":
                if gt_bssid and det.get("bssid") == gt_bssid:
                    found = True
                    matching_detection = det
                    matched_indices.add(idx)
                    break

            if scenario_id == "sudden_outage" and det.get("issue_type") == "anomaly":
                expected_interval = _expected_outage_interval(
                    gt, first_date, utc_offset
                )
                if expected_interval and _intervals_overlap(
                    expected_interval, _detection_interval(det)
                ):
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
            "possible_reason": None if found else _miss_reason(scenario_id),
            "matched_detection": matching_detection,
        })

    # Bilinen senaryoların zamanında görülen ek ölçüt anomalilerini tekrar alarm sayma.
    found_scenarios = [
        (gt, result)
        for gt, result in zip(ground_truth, evaluation_results)
        if result["status"] == "Bulundu"
    ]
    false_positives = []
    for idx, det in enumerate(all_detections):
        if idx in matched_indices:
            continue
        if any(
            _is_explained_by_scenario(gt, det, first_date, utc_offset)
            for gt, _ in found_scenarios
        ):
            continue
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


def _clock_range(value: str) -> tuple[time, time] | None:
    """Bir zaman metninden başlangıç ve bitiş saatini çıkarır."""
    match = re.search(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", value)
    if not match:
        return None
    return tuple(time.fromisoformat(part) for part in match.groups())


def _expected_outage_interval(
    scenario: dict[str, Any], first_date, utc_offset: int
) -> tuple[datetime, datetime] | None:
    """Ground truth'taki gün/saat aralığını analiz saat tabanına dönüştürür."""
    if first_date is None:
        return None
    day_match = re.search(r"(\d+)\. gün", scenario.get("time_window", ""), re.IGNORECASE)
    clocks = _clock_range(scenario.get("time_window", ""))
    if not day_match or not clocks:
        return None

    date = first_date + timedelta(days=int(day_match.group(1)) - 1)
    start = datetime.combine(date, clocks[0]) + timedelta(hours=utc_offset)
    end_date = date + timedelta(days=1) if clocks[1] <= clocks[0] else date
    end = datetime.combine(end_date, clocks[1]) + timedelta(hours=utc_offset)
    return start, end


def _detection_interval(detection: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Anomali kaydındaki tarih ve saat aralığını zaman aralığına çevirir."""
    date_text = detection.get("date")
    clocks = _clock_range(detection.get("time_window", ""))
    if not date_text or not clocks:
        return None
    date = datetime.fromisoformat(date_text).date()
    start = datetime.combine(date, clocks[0])
    end_date = date + timedelta(days=1) if clocks[1] <= clocks[0] else date
    return start, datetime.combine(end_date, clocks[1])


def _intervals_overlap(expected, detected) -> bool:
    """İki yarı açık saat aralığı gerçekten çakışıyorsa True döndürür."""
    return bool(detected and detected[0] < expected[1] and detected[1] > expected[0])


def _matches_congestion(
    scenario: dict[str, Any], detection: dict[str, Any], utc_offset: int
) -> bool:
    """Tıkanıklık teşhisinin beklenen saat aralığıyla örtüşmesini denetler."""
    expected = _clock_range(scenario.get("time_window", ""))
    detected = _clock_range(detection.get("time_window", ""))
    if expected:
        monday = datetime(2024, 1, 1)
        expected_start = datetime.combine(monday.date(), expected[0]) + timedelta(hours=utc_offset)
        expected_end = datetime.combine(monday.date(), expected[1]) + timedelta(hours=utc_offset)
        expected = (expected_start.time(), expected_end.time())
    return bool(
        detection.get("issue_type") == "congestion"
        and expected
        and detected
        and detected[0] < expected[1]
        and detected[1] > expected[0]
    )


def _is_explained_by_scenario(
    scenario: dict[str, Any],
    detection: dict[str, Any],
    first_date,
    utc_offset: int,
) -> bool:
    """Eşleşmiş bir arızanın aynı belirti ve zamanda ürettiği ek alarmı ayıklar."""
    if detection.get("issue_type") != "anomaly" or detection.get("zone") != scenario.get("zone"):
        return False

    if scenario.get("scenario_id") == "congestion":
        interval = _detection_interval(detection)
        clocks = _clock_range(scenario.get("time_window", ""))
        if not interval or not clocks or interval[0].weekday() >= 5:
            return False
        expected = (
            datetime.combine(interval[0].date(), clocks[0]) + timedelta(hours=utc_offset),
            datetime.combine(interval[0].date(), clocks[1]) + timedelta(hours=utc_offset),
        )
        return detection.get("metric") == "rtt_ms" and detection.get("direction") == "high" and _intervals_overlap(expected, interval)

    if scenario.get("scenario_id") == "faulty_ap":
        return detection.get("zone") == scenario.get("zone") and detection.get("direction") == "high"

    if scenario.get("scenario_id") == "sudden_outage":
        expected = _expected_outage_interval(scenario, first_date, utc_offset)
        return bool(expected and _intervals_overlap(expected, _detection_interval(detection)))

    return False


def _miss_reason(scenario_id: str) -> str:
    """Bulunamayan senaryolar için olası nedenleri rapora ekler."""
    if scenario_id == "sudden_outage":
        return "Anomali eşiği, saat dilimi veya saatlik asgari örnek koşulu sağlanmamış olabilir."
    return "Teşhis eşiği veya asgari örnek sayısı koşulu sağlanmamış olabilir."


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
        "| Senaryo | Bölge | Beklenen Zaman | Durum | Tespit Eden Modül | Tespit Detayı / Olası Neden |",
        "|---|---|---|:---:|:---:|---|",
    ]

    for r in results:
        status_badge = "**✓ Bulundu**" if r["status"] == "Bulundu" else "**✗ Bulunamadı**"
        explanation = r["detected_info"] if r["status"] == "Bulundu" else r["possible_reason"]
        lines.append(
            f"| {r['title']} | {r['zone']} | {r['expected_time']} | {status_badge} | `{r['detected_by']}` | {explanation} |"
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
            "Aşağıdaki bulgular eşleşmiş bilinen senaryoların belirti ve zaman aralığıyla açıklanamayan ek teşhislerdir:"
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
