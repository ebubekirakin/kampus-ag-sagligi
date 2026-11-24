"""NetNabız Streamlit paneli; hesaplamaları analytics modüllerinden alır."""

import sys
from html import escape
from pathlib import Path
from statistics import median

# Proje kök dizinini Python yoluna ekle (dosya doğrudan Streamlit ile açılır).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st

from analytics.anomaly import detect_anomalies
from analytics.data import load_measurements
from analytics.forecast import compute_participation_density, evaluate_forecast
from analytics.rules import calculate_zone_scores, diagnose_issues
from backend.config import load_config
from dashboard import theme
from dashboard.helpers import (
    build_hourly_day_matrix,
    find_best_spot,
    find_underperforming_forecast_zones,
    get_record_counts,
    get_score_badge,
    prepare_masked_issues_and_anomalies,
)


st.set_page_config(
    page_title="NetNabız · Kampüs Wi-Fi Sağlığı",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data
def get_cached_analytics(data_type: str):
    """Analizi salt okunur SQLite verisinden bir kez hesaplayıp önbelleğe alır."""
    df, meta = load_measurements(data_type=data_type, verified_only=True)
    config = load_config()
    if df.empty:
        return df, meta, config, [], [], [], {}, {}

    scores = calculate_zone_scores(df, config)
    raw_issues = diagnose_issues(df, config)
    raw_anomalies = detect_anomalies(df, config)
    forecast = evaluate_forecast(df, config)
    participation = compute_participation_density(df)
    bssids = df["bssid"].dropna().unique().tolist() if "bssid" in df.columns else []
    issues, anomalies = prepare_masked_issues_and_anomalies(raw_issues, raw_anomalies, bssids)
    return df, meta, config, scores, issues, anomalies, forecast, participation


def _render(markup: str) -> None:
    """Theme bileşenlerini Streamlit HTML alanında gösterir."""
    st.markdown(markup, unsafe_allow_html=True)


def _campus_score(scores: list[dict]) -> float | None:
    """Hesaplanmış bölge skorlarının medyanını genel kampüs skoru yapar."""
    values = [item["score"] for item in scores if item.get("score") is not None]
    return round(float(median(values)), 1) if values else None


def _insights(scores: list[dict], issues: list[dict], participation: dict, config: dict) -> list[str]:
    """Üst şerit cümlelerini yalnızca mevcut analiz sonuçlarından hazırlar."""
    lines = []
    scored = [item for item in scores if item.get("score") is not None]
    if scored:
        best = max(scored, key=lambda item: item["score"])
        lines.append(f"En iyi skor: {best['zone']} ({best['score']:.1f})")
        weak = [item for item in scored if get_score_badge(item["score"], config)[0] == "kırmızı"]
        if weak:
            lines.append(f"Dikkat: {weak[0]['zone']} bölgesi zayıf durumda.")
    peak = participation.get("peak_hour")
    if peak:
        lines.append(f"En yoğun katılım saati: {peak} (ölçüm katılımı)")
    if issues:
        lines.append(f"İncelenmesi gereken {len(issues)} kural tabanlı bulgu var.")
    return lines


def _score_table_style(row: pd.Series, config: dict) -> list[str]:
    """Skor tablosunda metin etiketinin yanında durum rengini de kullanır."""
    result = get_score_badge(row.get("_score"), config)
    color = result[2]
    return [f"color: {color}; font-weight: 700" if column == "Durum" else "" for column in row.index]


def _matrix_style(matrix: pd.DataFrame) -> pd.DataFrame:
    """Matris hücrelerini paletin CSS değişkenleriyle hafifçe renklendirir."""
    numeric = matrix.stack().dropna()
    low = float(numeric.min()) if not numeric.empty else 0.0
    span = float(numeric.max() - low) if not numeric.empty else 0.0

    def style_value(value):
        if pd.isna(value):
            return "color: var(--muted); background: var(--surface)"
        intensity = 35 if span == 0 else int(12 + 35 * (float(value) - low) / span)
        return f"color: var(--text); background: color-mix(in srgb, var(--secondary) {intensity}%, var(--surface))"

    return matrix.style.map(style_value)


def _chart(data: pd.Series | pd.DataFrame, color: str | list[str]) -> None:
    """Streamlit'in yerleşik çizgi grafiğini tema renkleriyle çizer."""
    st.line_chart(data, color=color, height=260)


_render(theme.inject_css())
st.sidebar.title("📡 NetNabız")
data_type = st.sidebar.selectbox(
    "Veri türü",
    options=["simulated", "real", "all"],
    format_func=lambda value: {
        "simulated": "Simüle veri",
        "real": "Gerçek ölçüm",
        "all": "Tüm kayıtlar",
    }[value],
)
view_mode = st.sidebar.radio("Görünüm", ["Öğrenci", "Yönetici"])

is_weekend = False
selected_hour = 14
if view_mode == "Öğrenci":
    st.sidebar.markdown("#### Zaman seçimi")
    st.sidebar.caption("Simüle verinin sabit tarihlerini kullanarak öneriyi inceleyin.")
    is_weekend = st.sidebar.selectbox("Gün türü", ["Hafta içi", "Hafta sonu"]) == "Hafta sonu"
    selected_hour = st.sidebar.slider("Saat", 0, 23, 14, format="%d:00")

try:
    df, meta, config, scores, issues, anomalies, forecast, participation = get_cached_analytics(data_type)
except Exception as error:
    st.error(f"Veri yüklenemedi: {error}")
    st.stop()

campus_score = _campus_score(scores)
_render(theme.hero(
    "Kampüs Wi-Fi Sağlık Rehberi" if view_mode == "Öğrenci" else "Ağ Yönetim Paneli",
    "Bağlantı sağlığını anlayın, doğru çalışma alanını bulun." if view_mode == "Öğrenci" else "Kampüs ağındaki eğilimleri ve sorunları izleyin.",
    data_type,
    campus_score,
    config,
))
_render(theme.insight_ribbon(_insights(scores, issues, participation, config)))

if df.empty:
    _render(theme.note_box(
        f"Seçilen veri türünde ({data_type}) henüz kayıtlı ölçüm bulunmuyor.", "warning"
    ))
    st.stop()


if view_mode == "Öğrenci":
    _render(theme.section_title("Şu an önerilen nokta", "Seçtiğiniz zaman için mevsimsel gecikme tahmini"))
    best_spot = find_best_spot(df, is_weekend, selected_hour, scores)
    if best_spot:
        period = "Hafta sonu" if is_weekend else "Hafta içi"
        _render(theme.best_spot_card(
            best_spot["zone"], best_spot["score"], best_spot["estimated_rtt_ms"],
            f"{period} saat {selected_hour:02d}:00 diliminde en düşük tahmini gecikmeye sahip bölge.", config,
        ))
    else:
        _render(theme.note_box("Bu zaman diliminde önerilebilecek yeterli veriye sahip bölge yok.", "warning"))

    _render(theme.section_title("Kampüs planı", "Bina ve katlardaki bağlantı durumları"))
    _render(theme.campus_map(scores, config))
    _render(theme.section_title("Bölge kartları", "Renklerin yanında durum etiketleri de gösterilir."))
    cards = "".join(
        theme.zone_card(
            item["zone"], item.get("score"), item.get("median_rtt_ms"),
            item.get("median_down_mbps"), item.get("sample_count", 0), config,
        )
        for item in scores
    )
    _render(f'<div class="np-grid">{cards}</div>')

    _render(theme.section_title("Saatlik gecikme", "Seçilen bölge için hafta içi/hafta sonu karşılaştırması"))
    zone_names = [item["zone"] for item in scores if item.get("score") is not None]
    if zone_names:
        selected_zone = st.selectbox("Bölge seçin", zone_names)
        zone_df = df[df["zone"] == selected_zone]
        weekday = zone_df[~zone_df["is_weekend"]].groupby("hour")["rtt_ms"].mean()
        weekend = zone_df[zone_df["is_weekend"]].groupby("hour")["rtt_ms"].mean()
        chart = pd.DataFrame(index=[f"{hour:02d}:00" for hour in range(24)])
        chart["Hafta içi"] = [weekday.get(hour) for hour in range(24)]
        chart["Hafta sonu"] = [weekend.get(hour) for hour in range(24)]
        _chart(chart, [theme.PALETTE["primary"], theme.PALETTE["secondary"]])
        st.caption(f"{escape(selected_zone)} için saatlik ortalama gecikme (ms).")

else:
    tabs = st.tabs(["Genel bakış", "Sorunlar", "Trendler", "Tahmin", "Veri ve gizlilik"])
    tab_overview, tab_issues, tab_trends, tab_forecast, tab_privacy = tabs

    with tab_overview:
        _render(theme.section_title("Kampüsün genel durumu", "Seçilen veri türündeki kayıtların kısa özeti"))
        counts = get_record_counts(data_type)
        total = counts["total"]
        verified_pct = counts["verified"] / total * 100 if total else 0
        unverified_pct = counts["unverified"] / total * 100 if total else 0
        kpis = [
            theme.kpi_card("Toplam ölçüm", f"{total:,}", "Seçilen veri türü"),
            theme.kpi_card("Doğrulanmış", f"%{verified_pct:.1f}", f"{counts['verified']:,} kayıt"),
            theme.kpi_card("Doğrulanmamış", f"%{unverified_pct:.1f}", f"{counts['unverified']:,} kayıt"),
            theme.kpi_card("Simüle / gerçek", f"{counts['simulated']:,} / {counts['real']:,}", "Kayıt sayısı"),
            theme.kpi_card("İzlenen bölge", len(scores), "Yapılandırılmış kampüs alanları"),
        ]
        _render(f'<div class="np-grid">{"".join(kpis)}</div>')
        _render(theme.section_title("Bölge sağlık skorları", "Skorlar analiz modülünün eşiklerini kullanır."))
        rows = []
        for item in scores:
            _, label, _ = get_score_badge(item.get("score"), config)
            if item.get("score") is None:
                label = "Veri yok"
            rows.append({
                "Bölge": item["zone"], "_score": item.get("score"),
                "Skor": item.get("score"), "Durum": label,
                "Medyan RTT (ms)": item.get("median_rtt_ms"),
                "%90 RTT (ms)": item.get("p90_rtt_ms"),
                "Kayıp (%)": item.get("median_loss_pct"),
                "İndirme (Mbps)": item.get("median_down_mbps"),
                "Sinyal (dBm)": item.get("median_signal_dbm"),
                "Örnek": item.get("sample_count", 0),
            })
        table = pd.DataFrame(rows)
        if not table.empty:
            styled = table.style.apply(lambda row: _score_table_style(row, config), axis=1).hide(
                subset=["_score"], axis="columns"
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

    with tab_issues:
        _render(theme.section_title("Tespit edilen bulgular", "AP adresleri arayüzde yalnızca takma adlarıyla gösterilir."))
        if not issues and not anomalies:
            _render(theme.note_box("Bu veri aralığında gösterilecek bulgu yok.", "success"))
        for issue in issues:
            _render(theme.issue_card(
                issue.get("title", "Ağ bulgusu"), issue.get("zone", "Bölge belirtilmedi"),
                issue.get("time_window", "Zaman belirtilmedi"), issue.get("details", "Kanıt yok"), "İnceleme",
            ))
        for anomaly in anomalies:
            _render(theme.issue_card(
                f"Anomali · {anomaly.get('metric', 'ölçüm')}", anomaly.get("zone", "Bölge belirtilmedi"),
                anomaly.get("time_window", "Zaman belirtilmedi"), anomaly.get("details", "Kanıt yok"), "Yüksek",
            ))

    with tab_trends:
        _render(theme.section_title("Zaman içindeki değişim", "Günlük ve saatlik ölçüm eğilimleri"))
        zones = sorted(df["zone"].dropna().unique().tolist())
        selected_zone = st.selectbox("Bölge seçin", zones, key="admin_zone")
        zone_df = df[df["zone"] == selected_zone]
        if not zone_df.empty:
            chart_groups = [
                ("Günlük medyan gecikme (ms)", zone_df.groupby("day_str")["rtt_ms"].median(), theme.PALETTE["primary"]),
                ("Saatlik medyan gecikme (ms)", zone_df.groupby("hour")["rtt_ms"].median(), theme.PALETTE["secondary"]),
                ("Günlük medyan paket kaybı (%)", zone_df.groupby("day_str")["loss_pct"].median(), theme.PALETTE["medium"]),
                ("Saatlik medyan paket kaybı (%)", zone_df.groupby("hour")["loss_pct"].median(), theme.PALETTE["bad"]),
                ("Günlük medyan indirme (Mbps)", zone_df.groupby("day_str")["down_mbps"].median(), theme.PALETTE["primary"]),
                ("Saatlik medyan indirme (Mbps)", zone_df.groupby("hour")["down_mbps"].median(), theme.PALETTE["secondary"]),
            ]
            for index in range(0, len(chart_groups), 2):
                columns = st.columns(2)
                for column, (title, series, color) in zip(columns, chart_groups[index:index + 2]):
                    with column:
                        _render(theme.section_title(title))
                        _chart(series, color)
            _render(theme.section_title("Saat × hafta günü ortalama gecikme matrisi", "Açık tonlar düşük, mor tonlar yüksek gecikmeyi gösterir."))
            st.dataframe(_matrix_style(build_hourly_day_matrix(df, selected_zone)), use_container_width=True)

    with tab_forecast:
        _render(theme.section_title("Tahmin performansı", "Son dönem test verisiyle karşılaştırma"))
        _render(theme.note_box(
            "Mevsimsel yöntem (bölge, hafta içi/sonu ve saat) tek medyan taban yöntemiyle MAE üzerinden karşılaştırılır.",
        ))
        if forecast.get("status") == "basarili":
            kpis = [
                theme.kpi_card("Test ölçümü", forecast["test_sample_count"], "Son üç günlük dönem"),
                theme.kpi_card("Eğitim ölçümü", forecast["train_sample_count"], "Önceki dönem"),
                theme.kpi_card("Tek medyan MAE", f"{forecast['mae_baseline']:.2f} ms", "Düşük olması daha iyidir"),
                theme.kpi_card("Mevsimsel MAE", f"{forecast['mae_seasonal']:.2f} ms", f"İyileşme %{forecast['improvement_pct']:.1f}"),
            ]
            _render(f'<div class="np-grid">{"".join(kpis)}</div>')
            comparison = pd.DataFrame(forecast.get("zone_comparison", [])).rename(columns={
                "zone": "Bölge", "test_samples": "Test örneği",
                "mae_seasonal": "Mevsimsel MAE (ms)",
                "mae_baseline": "Tek medyan MAE (ms)",
                "mae_difference": "Fark (tek medyan - mevsimsel)",
            })
            st.dataframe(comparison, use_container_width=True, hide_index=True)
            underperforming = find_underperforming_forecast_zones(forecast)
            if underperforming:
                _render(theme.note_box("Mevsimsel tahminin tek medyan yönteminden daha yüksek hata verdiği bölgeler:", "warning"))
                for item in underperforming:
                    _render(theme.note_box(
                        f"{item['zone']}: mevsimsel MAE {item['mae_seasonal']:.2f} ms, "
                        f"tek medyan MAE {item['mae_baseline']:.2f} ms; fark +{item['mae_difference']:.2f} ms.", "warning",
                    ))
        else:
            _render(theme.note_box(f"Tahmin sonucu: {forecast.get('status', 'bilinmiyor')}", "warning"))
        _render(theme.note_box("Katılım yoğunluğu ağ yoğunluğu değildir."))
        _render(theme.note_box("Tahmin simüle veride değerlendirildi; gerçek veride aynı başarı garanti değildir."))

    with tab_privacy:
        _render(theme.section_title("Veri ve gizlilik", "Panel yalnızca yerel, doğrulanmış ölçümler üzerinde analiz yapar."))
        _render('<div class="np-grid">'
            + theme.note_box("Saklanabilen alanlar: ağ ölçümleri, seçilen bölge, zaman, doğrulama ve simülasyon bilgileri.")
            + theme.note_box("Ham IP veritabanına yazılmaz; ham cihaz kimliği yerine sunucuda HMAC özeti saklanır.")
            + theme.note_box("SSID ve BSSID veritabanında ham bulunabilir. Panel SSID göstermez; BSSID yerine AP takma adı gösterir.", "warning")
            + theme.note_box("Panel tekil ölçüm satırlarını göstermez ve veri indirme sunmaz.")
            + '</div>')
        _render(theme.note_box(
            f"Analiz dönemi: {meta.get('min_time')} — {meta.get('max_time')} ({meta.get('total_records')} doğrulanmış kayıt)."
        ))
        _render(theme.note_box(
            "Yapay zeka (ileride) ham veriyi değil, yalnızca anonim özeti görecek. Modelin veritabanına erişimi olmayacak."
        ))
