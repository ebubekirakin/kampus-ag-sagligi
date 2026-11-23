"""
NetNabız - Kampüs Wi-Fi Sağlığı ve Sorun Analiz Paneli (Streamlit).
Öğrenci ve Yönetici görünümleriyle kampüs ağ sağlığını, kural tabanlı teşhisleri,
MAD anomalilerini ve mevsimsel tahmin sonuçlarını sunar.
Tamamen yerel çalışır, harici grafik kütüphanesi ve ücretli servis kullanmaz.
"""

import streamlit as st
import pandas as pd

from backend.config import load_config
from analytics.data import load_measurements
from analytics.rules import calculate_zone_scores, diagnose_issues
from analytics.anomaly import detect_anomalies
from analytics.forecast import evaluate_forecast, compute_participation_density
from dashboard.helpers import (
    get_score_badge,
    group_zones_by_hierarchy,
    find_best_spot,
    find_underperforming_forecast_zones,
    build_hourly_day_matrix,
    prepare_masked_issues_and_anomalies,
)

# Sayfa Temel Ayarları
st.set_page_config(
    page_title="NetNabız - Kampüs Ağ Sağlığı",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data
def get_cached_analytics(data_type: str):
    """
    Ölçüm verilerini ve analiz boru hattını çalıştırıp önbelleğe alır.
    API sunucusundan bağımsız, doğrudan salt okunur SQLite üzerinden çalışır.
    """
    df, meta = load_measurements(data_type=data_type, verified_only=True)
    config = load_config()

    if df.empty:
        return df, meta, config, [], [], [], {}, {}

    scores = calculate_zone_scores(df, config)
    raw_issues = diagnose_issues(df, config)
    raw_anomalies = detect_anomalies(df, config)
    forecast = evaluate_forecast(df, config)
    participation = compute_participation_density(df)

    all_bssids = df["bssid"].dropna().unique().tolist() if "bssid" in df.columns else []
    issues, anomalies = prepare_masked_issues_and_anomalies(raw_issues, raw_anomalies, all_bssids)

    return df, meta, config, scores, issues, anomalies, forecast, participation


# -------------------------------------------------------------
# KENAR ÇUBUĞU (SIDEBAR)
# -------------------------------------------------------------
st.sidebar.title("📡 NetNabız Kontrol")
data_type = st.sidebar.selectbox(
    "Veri Türü",
    options=["simulated", "real", "all"],
    index=0,
    format_func=lambda x: {
        "simulated": "Simüle Veri (simulated)",
        "real": "Gerçek Ölçümler (real)",
        "all": "Tüm Kayıtlar (all)",
    }.get(x, x),
)

view_mode = st.sidebar.radio(
    "Görünüm Seçimi",
    options=["Öğrenci", "Yönetici"],
    index=0,
    help="Öğrenciler için en iyi çalışma noktaları ve genel sağlık; yöneticiler için detaylı teşhis ve tahminler.",
)

st.sidebar.markdown("---")

# Öğrenci görünümü için gün tipi ve saat seçimi
is_weekend = False
selected_hour = 14
if view_mode == "Öğrenci":
    st.sidebar.subheader("🕒 Zaman Simülatörü")
    st.sidebar.caption("Simüle veriler sabit tarihli olduğundan çalışma zamanınızı seçebilirsiniz:")
    day_type = st.sidebar.selectbox("Gün Tipi", ["Hafta içi", "Hafta sonu"], index=0)
    is_weekend = (day_type == "Hafta sonu")
    selected_hour = st.sidebar.slider("Saat", min_value=0, max_value=23, value=14, step=1, format="%d:00")

# -------------------------------------------------------------
# VERİ YÜKLEME VE KONTROL
# -------------------------------------------------------------
try:
    df, meta, config, scores, issues, anomalies, forecast, participation = get_cached_analytics(data_type)
except Exception as e:
    st.error(f"Veri yüklenirken bir hata oluştu: {e}")
    st.stop()

# Simüle Veri Uyarı Bandı
if data_type in ("simulated", "all"):
    st.warning("⚠️ Bu panel **SİMÜLE** veriyle çalışmaktadır. Değerler sentetik kampüs modeline dayanır.")

# Boş Veri Durumu
if df.empty:
    st.info(f"Seçilen veri türünde ('{data_type}') henüz kayıtlı ölçüm bulunmuyor. İstemci ile ölçüm gönderdikten sonra yenileyebilirsiniz.")
    st.stop()


# -------------------------------------------------------------
# GÖRÜNÜM 1: ÖĞRENCİ GÖRÜNÜMÜ
# -------------------------------------------------------------
if view_mode == "Öğrenci":
    st.title("🎓 Kampüs Wi-Fi Sağlık Rehberi")
    st.markdown("Ders çalışmak, araştırma yapmak ve kampüste en verimli bağlantıyı bulmak için anlık ağ durumu.")

    # A) Şu an en iyi nokta
    st.subheader("🎯 Seçilen Saatte En İyi Çalışma Noktası")
    best_spot = find_best_spot(df, is_weekend, selected_hour, scores)

    if best_spot:
        col_rec1, col_rec2, col_rec3 = st.columns([2, 1, 1])
        with col_rec1:
            st.success(f"**Önerilen Bölge:** {best_spot['zone']}")
            st.caption(f"{'Hafta sonu' if is_weekend else 'Hafta içi'} saat {selected_hour:02d}:00 için en düşük tahmini gecikme.")
        with col_rec2:
            st.metric(
                label="Ağ Sağlık Skoru",
                value=f"{best_spot['score']:.1f} / 100",
                delta=f"{best_spot['status'].capitalize()} ({best_spot['color']})",
            )
        with col_rec3:
            st.metric(
                label="Tahmini Gecikme",
                value=f"{best_spot['estimated_rtt_ms']:.1f} ms",
                delta="Hızlı" if best_spot['estimated_rtt_ms'] < 40 else "Normal",
                delta_color="normal",
            )
    else:
        st.info("Bu saat dilimi için yeterli veriye sahip önerilebilir bir bölge bulunamadı.")

    st.markdown("---")

    # B) Kampüs Kartları (Bina -> Kat -> Bölge)
    st.subheader("🏢 Kampüs Wi-Fi Sağlık Kartları")
    st.caption("Bina ve katlara göre güncel sağlık skorları:")

    hierarchy = group_zones_by_hierarchy(scores)

    for building, floors in hierarchy.items():
        with st.expander(f"🏛️ {building}", expanded=True):
            for floor, zone_items in floors.items():
                st.markdown(f"**📍 {floor}**")
                cols = st.columns(min(len(zone_items), 3))
                for idx, z_item in enumerate(zone_items):
                    col = cols[idx % len(cols)]
                    with col:
                        score_val = z_item.get("score")
                        color_name, label_text, hex_code = get_score_badge(score_val, config)

                        rtt_str = f"{z_item['median_rtt_ms']:.1f} ms" if z_item.get("median_rtt_ms") is not None else "-"
                        down_str = f"{z_item['median_down_mbps']:.1f} Mbps" if z_item.get("median_down_mbps") is not None else "-"
                        score_str = f"{score_val:.1f}" if score_val is not None else "-"

                        # Renk körlüğü için belirgin etiketli kart
                        st.markdown(
                            f"""
                            <div style="
                                border-left: 6px solid {hex_code};
                                padding: 12px 14px;
                                border-radius: 8px;
                                background-color: rgba(128, 128, 128, 0.08);
                                margin-bottom: 12px;
                            ">
                                <h4 style="margin: 0 0 6px 0; font-size: 15px;">{z_item['zone']}</h4>
                                <div style="font-size: 13px; font-weight: bold; color: {hex_code}; margin-bottom: 6px;">
                                    Skor: {score_str} — {label_text} ({color_name.upper()})
                                </div>
                                <div style="font-size: 12px; color: #aaa;">
                                    ⚡ Gecikme: <b>{rtt_str}</b> &nbsp;|&nbsp; 📥 Hız: <b>{down_str}</b><br>
                                    📊 Örnek: {z_item['sample_count']} ölçüm
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

    st.markdown("---")

    # C) Seçilen bölge için saatlik gecikme çizgisi
    st.subheader("📈 Bölge Saatlik Gecikme Karşılaştırması")
    zone_names = [s["zone"] for s in scores if s.get("score") is not None]
    if zone_names:
        selected_zone_student = st.selectbox("Grafiğini incelemek istediğiniz bölgeyi seçin:", zone_names, index=0)

        z_df = df[df["zone"] == selected_zone_student].copy()
        if not z_df.empty and "rtt_ms" in z_df.columns:
            weekday_series = z_df[~z_df["is_weekend"]].groupby("hour")["rtt_ms"].median()
            weekend_series = z_df[z_df["is_weekend"]].groupby("hour")["rtt_ms"].median()

            chart_data = pd.DataFrame(index=[f"{h:02d}:00" for h in range(24)])
            chart_data["Hafta içi Gecikme (ms)"] = [weekday_series.get(h) for h in range(24)]
            chart_data["Hafta sonu Gecikme (ms)"] = [weekend_series.get(h) for h in range(24)]

            st.line_chart(chart_data)
            st.caption(f"*{selected_zone_student}* için hafta içi ve hafta sonu saatlik medyan gecikme (ms).")


# -------------------------------------------------------------
# GÖRÜNÜM 2: YÖNETİCİ GÖRÜNÜMÜ
# -------------------------------------------------------------
else:
    st.title("🛠️ Ağ Yönetim ve Sağlık Analiz Paneli")
    st.markdown("Kampüs Wi-Fi ağ altyapısının genel sağlık metrikleri, kural tabanlı sorun teşhisleri ve istatistiksel anomaliler.")

    tab_overview, tab_issues, tab_trends, tab_forecast, tab_privacy = st.tabs([
        "📊 Genel Bakış",
        "⚠️ Sorunlar",
        "📈 Trendler",
        "🔮 Tahmin",
        "🔒 Veri ve Gizlilik",
    ])

    # 1. SEKME: GENEL BAKIŞ
    with tab_overview:
        st.subheader("Kampüs Ağ Sağlığı Özeti")
        total_records = len(df)
        verified_count = int(df["is_verified"].sum()) if "is_verified" in df.columns else 0
        verified_ratio = (verified_count / total_records * 100) if total_records > 0 else 0.0

        sim_count = int(df["is_simulated"].sum()) if "is_simulated" in df.columns else 0
        real_count = total_records - sim_count

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Toplam Ölçüm", f"{total_records:,}")
        c2.metric("Doğrulanmış Kayıt", f"%{verified_ratio:.1f}", f"{verified_count:,} adet")
        c3.metric("Simüle / Gerçek", f"{sim_count:,} / {real_count:,}")
        c4.metric("İzlenen Bölge", len(scores))

        st.markdown("### Bölge Sağlık Skorları Tablosu")
        table_rows = []
        for s in scores:
            score_val = s.get("score")
            color_name, label_text, _ = get_score_badge(score_val, config)
            table_rows.append({
                "Bölge": s["zone"],
                "Skor": f"{score_val:.1f}" if score_val is not None else "-",
                "Durum": f"{label_text} ({color_name.upper()})",
                "Medyan RTT (ms)": s.get("median_rtt_ms"),
                "%90 RTT (ms)": s.get("p90_rtt_ms"),
                "Kayıp (%)": s.get("median_loss_pct"),
                "İndirme (Mbps)": s.get("median_down_mbps"),
                "Sinyal (dBm)": s.get("median_signal_dbm"),
                "Örnek": s.get("sample_count", 0),
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # 2. SEKME: SORUNLAR
    with tab_issues:
        st.subheader("Tespit Edilen Ağ Sorunları ve Anomaliler")
        st.caption("Veriye dayalı istatistiksel kurallar ve sağlam Z-skoru ile tespit edilmiş kronik sorunlar ve ani sıçramalar.")

        st.markdown("#### 1. Kural Tabanlı Kronik Teşhisler")
        if issues:
            for idx, iss in enumerate(issues, start=1):
                with st.container():
                    st.markdown(f"**{idx}. [{iss['title'].upper()}] — {iss['zone']}**")
                    st.markdown(f"- **Zaman Penceresi:** `{iss['time_window']}`")
                    if iss.get("bssid"):
                        st.markdown(f"- **İlgili Erişim Noktası:** `{iss['bssid']}` *(Gizlilik için takma ad kullanılmıştır)*")
                    st.markdown(f"- **Sayısal Kanıt:** {iss['details']}")
                    st.markdown("---")
        else:
            st.success("Aktif kural ihlali veya kronik arıza tespit edilmedi.")

        st.markdown("#### 2. İstatistiksel Anomaliler (MAD Robust Z-Skor > 4.0)")
        if anomalies:
            anom_rows = []
            for a in anomalies:
                anom_rows.append({
                    "Zaman Aralığı": a.get("time_window"),
                    "Bölge": a.get("zone"),
                    "Ölçüt": a.get("metric"),
                    "Yön": "Yüksek" if a.get("direction") == "high" else "Düşük",
                    "Gözlem": a.get("observed_median"),
                    "Taban Değer": a.get("baseline_median"),
                    "Sağlam Z-Skor": a.get("robust_z"),
                    "Örnek": a.get("sample_count", 0),
                })
            st.dataframe(pd.DataFrame(anom_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Eşik değerini (|z| > 4.0) aşan istatistiksel anomali bulunamadı.")

    # 3. SEKME: TRENDLER
    with tab_trends:
        st.subheader("Bölge Bazlı Zaman Serisi ve Yoğunluk Trendleri")
        all_zone_list = sorted(list(df["zone"].dropna().unique()))
        selected_zone_admin = st.selectbox("Detaylı trend analizi için bölge seçin:", all_zone_list, key="admin_zone")

        z_admin_df = df[df["zone"] == selected_zone_admin].copy()

        if not z_admin_df.empty:
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.markdown("**Günlük Medyan Gecikme (ms)**")
                daily_rtt = z_admin_df.groupby("day_str")["rtt_ms"].median()
                st.line_chart(daily_rtt)

            with col_t2:
                st.markdown("**Saatlik Medyan Gecikme (ms)**")
                hourly_rtt = z_admin_df.groupby("hour")["rtt_ms"].median()
                st.line_chart(hourly_rtt)

            col_t3, col_t4 = st.columns(2)
            with col_t3:
                st.markdown("**Günlük Paket Kaybı (%)**")
                daily_loss = z_admin_df.groupby("day_str")["loss_pct"].median()
                st.line_chart(daily_loss)

            with col_t4:
                st.markdown("**Günlük İndirme Hızı (Mbps)**")
                daily_down = z_admin_df.groupby("day_str")["down_mbps"].median()
                st.line_chart(daily_down)

            st.markdown("#### Saat × Hafta Günü Ortalama Gecikme Matrisi (ms)")
            matrix_df = build_hourly_day_matrix(df, selected_zone_admin)
            st.dataframe(matrix_df, use_container_width=True)
            st.caption(f"*{selected_zone_admin}* için gün ve saatlere göre medyan gecikme dağılımı.")

    # 4. SEKME: TAHMİN
    with tab_forecast:
        st.subheader("Mevsimsel Tahmin ve Model Performans Kıyaslaması")
        st.markdown(
            "Son 3 gün test kümesi olarak ayrılmış; eğitim kümesindeki mevsimsel medyanlar "
            "`(bölge, hafta içi/sonu, saat)` ile tekil bölge medyanı taban çizgisi (baseline) "
            "Ortalama Mutlak Hata (MAE) metriğiyle sınanmıştır."
        )

        if forecast.get("status") == "basarili":
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Test Örnek Sayısı", forecast["test_sample_count"])
            m2.metric("Eğitim Örnek Sayısı", forecast["train_sample_count"])
            m3.metric("Taban Model MAE", f"{forecast['mae_baseline']:.2f} ms")
            m4.metric("Mevsimsel Model MAE", f"{forecast['mae_seasonal']:.2f} ms", f"%{forecast['improvement_pct']:.1f} iyileşme")

            st.markdown("#### Bölge Bazında Tahmin Hatası Karşılaştırması")
            comp_df = pd.DataFrame(forecast.get("zone_comparison", []))
            if not comp_df.empty:
                comp_df = comp_df.rename(columns={
                    "zone": "Bölge",
                    "test_samples": "Test Örnek",
                    "mae_seasonal": "Mevsimsel MAE (ms)",
                    "mae_baseline": "Taban Model MAE (ms)",
                    "mae_difference": "Fark (Taban - Mevsimsel)",
                })
                st.dataframe(comp_df, use_container_width=True, hide_index=True)

            # Mevsimsel yöntemin basit yöntemden DAHA KÖTÜ olduğu bölgeleri VERİDEN dinamik hesapla
            underperforming = find_underperforming_forecast_zones(forecast)
            if underperforming:
                st.error("⚠️ **Mevsimsel Yöntemin Taban Çizgisinden Daha Yüksek Hata Verdiği Bölgeler:**")
                for u in underperforming:
                    st.markdown(
                        f"- **{u['zone']}**: Mevsimsel MAE **{u['mae_seasonal']:.2f} ms** > Taban MAE **{u['mae_baseline']:.2f} ms** "
                        f"(Hata artışı: +{u['mae_difference']:.2f} ms, Test örneği: {u['test_samples']})"
                    )
                st.markdown(
                    "> **Açıklama:** Bu bölgelerde belirgin bir saatlik insan/yoğunluk döngüsü bulunmamakta veya sabit fiziksel sinyal kısıtı "
                    "(kapsama boşluğu) mevcuttur. Döngüsel olmayan sabit örüntülere saatlik mevsimsellik eklemek modelin varyansını artırarak "
                    "tahmin hatasını yükseltmektedir."
                )

        else:
            st.info(f"Tahmin değerlendirmesi durumu: {forecast.get('status')}")

        st.markdown("---")
        # Zorunlu Notlar
        st.info("ℹ️ **Metodolojik Not 1:** Katılım yoğunluğu ağ yoğunluğu değildir; kullanıcıların ilgili saatte ölçüm gönderme/katılım sıklığını gösterir.")
        st.info("ℹ️ **Metodolojik Not 2:** Tahmin simüle veride değerlendirildi, gerçek veride aynı başarı garanti değildir.")

    # 5. SEKME: VERİ VE GİZLİLİK
    with tab_privacy:
        st.subheader("Veri Güvenliği, Anonimleştirme ve Gizlilik İlkeleri")

        st.markdown("""
        NetNabız platformu, kullanıcı gizliliğini tasarım gereği korumak (Privacy by Design) üzere yapılandırılmıştır.
        Panel hiçbir aşamada ham cihaz kimliği veya hassas kullanıcı izi barındırmaz.
        """)

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown("#### ✅ Toplanan ve Saklanan Alanlar")
            st.markdown("""
            - **Ağ Metrikleri:** TCP RTT gecikmesi (ms), paket kaybı (%), indirme/yükleme hızı (Mbps), RSSI sinyal seviyesi (dBm).
            - **Konum Bilgisi:** Sadece seçilen bina, kat ve bölge adı.
            - **Güven Skoru:** IP aralığı karşılaştırmasıyla üretilen kampüs doğrulama bayrağı (`is_verified`).
            - **Zaman Damgası:** Ölçümün alındığı UTC zaman damgası.
            """)

        with col_p2:
            st.markdown("#### ❌ Kesinlikle Saklanmayan Bilgiler")
            st.markdown("""
            - **Ham IP Adresi:** Sunucu belleğinde kampüs aralığıyla kıyaslanır ve anında imha edilir, DB'ye yazılmaz.
            - **Ham Cihaz Kimliği (MAC/IMEI):** Saklanmaz; istemci hash üretir, sunucu bunu gizli tuz (`hash_salt`) ile HMAC-SHA256 yapar.
            - **Kişisel Veri:** İsim, soyisim, öğrenci numarası veya web tarama geçmişi toplanmaz.
            - **Ham BSSID:** Arayüz ve analiz çıktılarında takma adlarla (`AP-1`, `AP-2`) maskelenir.
            """)

        st.markdown("---")
        st.markdown("#### 📅 Analize Dahil Edilen Veri Aralığı")
        st.markdown(f"- **İlk Ölçüm:** `{meta.get('min_time')}`")
        st.markdown(f"- **Son Ölçüm:** `{meta.get('max_time')}`")
        st.markdown(f"- **Referans Zaman:** `{meta.get('reference_time')}`")
        st.markdown(f"- **Doğrulanmış Kayıt Sayısı:** `{meta.get('total_records')} adet`")

        st.markdown("---")
        st.markdown("#### 🔒 Yerel Yapay Zeka Entegrasyon Güvencesi")
        st.info(
            "Yapay zeka (ileride) ham veriyi değil, yalnızca anonim özeti görecek. "
            "Sistemde yerel olarak koşacak olan açık kaynaklı büyük dil modelleri (Ollama / Qwen / Gemma), "
            "SQLite veritabanındaki tekil ölçüm satırlarına doğrudan erişmeyecektir. "
            "Model yalnızca `analysis_summary.json` dosyasında derlenen; cihaz hash'leri, SSID'ler ve ham BSSID'lerden "
            "tamamen arındırılmış istatistiksel özetleri (bölge puanları, tespit edilen arıza türleri ve MAE hataları) "
            "okuyarak kullanıcıya ve jüriye Türkçe açıklamalar üretecektir."
        )
