"""NetNabız arayüzü için güvenli HTML bileşenleri ve ortak CSS teması."""

from html import escape
import math
from typing import Any, Iterable

from dashboard.helpers import get_score_badge, group_zones_by_hierarchy


PALETTE = {
    "background": "#0b1220",
    "background_bottom": "#111a2e",
    "surface": "#131c31",
    "surface_raised": "#19243b",
    "text": "#e6edf7",
    "muted": "#94a3b8",
    "primary": "#2dd4bf",
    "secondary": "#8b5cf6",
    "good": "#22c55e",
    "medium": "#f59e0b",
    "bad": "#ef4444",
    "empty": "#64748b",
}

_STATUS_TOKENS = {
    "yeşil": "good",
    "sarı": "medium",
    "kırmızı": "bad",
    "gri": "empty",
}


def inject_css() -> str:
    """Uygulamanın bütün görsel kurallarını tek noktadan ekler."""
    css = """<style>
    :root {
      --bg-top: __background__; --bg-bottom: __background_bottom__; --surface: __surface__;
      --surface-raised: __surface_raised__; --text: __text__; --muted: __muted__;
      --primary: __primary__; --secondary: __secondary__; --good: __good__;
      --medium: __medium__; --bad: __bad__; --empty: __empty__;
      --border: color-mix(in srgb,var(--muted) 20%,transparent);
      --line-soft: color-mix(in srgb,var(--muted) 20%,transparent);
      --line-faint: color-mix(in srgb,var(--muted) 16%,transparent);
      --aqua-soft: color-mix(in srgb,var(--primary) 12%,transparent);
      --aqua-faint: color-mix(in srgb,var(--primary) 6%,transparent);
      --purple-soft: color-mix(in srgb,var(--secondary) 12%,transparent);
      --warning-soft: color-mix(in srgb,var(--medium) 15%,transparent);
      --ring-track: color-mix(in srgb,var(--muted) 20%,transparent);
      --card-wash: color-mix(in srgb,var(--muted) 8%,transparent);
      --shadow: 0 16px 36px color-mix(in srgb,var(--bg-top) 80%,transparent);
      color-scheme: dark;
    }
    html,body,[class*="css"] { font-family:system-ui,"Segoe UI",Roboto,sans-serif; }
    .stApp { background: linear-gradient(180deg,var(--bg-top),var(--bg-bottom)); color:var(--text); }
    [data-testid="stHeader"] { background:color-mix(in srgb,var(--bg-top) 25%,transparent); }
    [data-testid="stToolbar"] { right:1rem; }
    #MainMenu, footer { visibility:hidden; }
    [data-testid="stSidebar"] { background:var(--bg-bottom); border-right:1px solid var(--border); }
    .block-container { max-width:1440px; padding-top:2.2rem; padding-bottom:4rem; }
    h1,h2,h3,h4,p,label,small { color:var(--text); }
    a { color:var(--primary); }
    [data-testid="stTabs"] [role="tablist"] { gap:.55rem; border-bottom:0; }
    [data-testid="stTabs"] button[role="tab"] { border:1px solid var(--border); border-radius:999px; padding:.55rem 1rem; color:var(--muted); background:var(--surface); }
    [data-testid="stTabs"] button[aria-selected="true"] { color:var(--text); background:var(--surface-raised); border-color:var(--primary); box-shadow:0 0 0 1px color-mix(in srgb,var(--primary) 20%,transparent); }
    [data-testid="stMetric"] { background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:1rem 1.1rem; box-shadow:var(--shadow); }
    [data-testid="stMetricValue"] { color:var(--text); font-size:1.8rem; }
    [data-testid="stDataFrame"], [data-testid="stTable"] { border:1px solid var(--border); border-radius:14px; overflow:hidden; }
    [data-testid="stExpander"] { background:color-mix(in srgb,var(--surface) 72%,transparent); border:1px solid var(--border); border-radius:15px; }
    .np-hero,.np-card,.np-kpi,.np-issue,.np-building,.np-note,.np-ribbon { background:var(--surface); border:1px solid var(--border); border-radius:16px; box-shadow:var(--shadow); }
    .np-hero { display:flex; align-items:center; justify-content:space-between; gap:2rem; padding:1.6rem 2rem; margin-bottom:1rem; background:linear-gradient(120deg,var(--aqua-soft),var(--purple-soft)),var(--surface); animation:np-enter .45s ease-out both; }
    .np-brand { color:var(--primary); font-size:.85rem; font-weight:750; letter-spacing:.16em; text-transform:uppercase; }
    .np-hero h1 { margin:.35rem 0; font-size:clamp(2rem,4vw,3.3rem); line-height:1.08; }
    .np-hero p { margin:.35rem 0 0; color:var(--muted); font-size:1rem; }
    .np-hero-side { display:flex; align-items:center; gap:1.2rem; }
    .np-sim-badge { padding:.55rem .85rem; border:1px solid color-mix(in srgb,var(--medium) 55%,transparent); border-radius:999px; background:var(--warning-soft); color:var(--medium); font-weight:800; letter-spacing:.06em; white-space:nowrap; }
    .np-ring { display:grid; justify-items:center; gap:.3rem; min-width:130px; }
    .np-ring svg { width:104px; height:104px; transform:rotate(-90deg); }
    .np-ring-track,.np-ring-value { fill:none; stroke-width:9; }
    .np-ring-track { stroke:var(--ring-track); }
    .np-ring-value { stroke:var(--ring-color); stroke-linecap:round; transition:stroke-dashoffset .5s ease; }
    .np-ring-number { fill:var(--text); font-size:22px; font-weight:800; text-anchor:middle; dominant-baseline:middle; transform:rotate(90deg); transform-origin:52px 52px; }
    .np-ring-label { color:var(--muted); font-size:.78rem; text-align:center; }
    .np-ribbon { display:flex; flex-wrap:wrap; gap:.65rem; padding:.8rem 1rem; margin:1rem 0 1.5rem; }
    .np-insight { flex:1 1 220px; padding:.7rem .85rem; border-left:3px solid var(--primary); background:var(--aqua-faint); border-radius:8px; color:var(--text); }
    .np-section { margin:1.6rem 0 .9rem; }
    .np-section h2 { margin:0 0 .25rem; font-size:1.45rem; }
    .np-section p { margin:0; color:var(--muted); }
    .np-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:1rem; }
    .np-kpi,.np-card,.np-issue,.np-note { padding:1rem 1.1rem; transition:transform .18s ease,border-color .18s ease; animation:np-enter .35s ease-out both; }
    .np-kpi:hover,.np-card:hover,.np-issue:hover { transform:translateY(-3px); border-color:color-mix(in srgb,var(--primary) 48%,transparent); }
    .np-kpi-label,.np-card-sub { color:var(--muted); font-size:.86rem; }
    .np-kpi-value { display:block; margin:.35rem 0; font-size:2rem; font-weight:800; letter-spacing:-.04em; }
    .np-card { border-top:3px solid var(--status-color); }
    .np-card-head { display:flex; justify-content:space-between; align-items:flex-start; gap:.7rem; }
    .np-card h3 { margin:0; font-size:1rem; }
    .np-status,.np-severity { display:inline-flex; border:1px solid var(--status-color); color:var(--status-color); border-radius:999px; padding:.25rem .55rem; font-size:.75rem; font-weight:800; white-space:nowrap; }
    .np-score { margin:.65rem 0 .1rem; font-size:1.8rem; font-weight:800; }
    .np-metric-line { display:flex; justify-content:space-between; gap:.5rem; margin-top:.65rem; color:var(--muted); font-size:.8rem; }
    .np-progress { height:6px; margin-top:.35rem; overflow:hidden; border-radius:99px; background:var(--line-faint); }
    .np-progress span { display:block; height:100%; border-radius:inherit; background:var(--status-color); }
    .np-hero-card { padding:1.5rem; border-radius:18px; border:1px solid color-mix(in srgb,var(--primary) 30%,transparent); background:linear-gradient(115deg,var(--aqua-soft),var(--purple-soft)),var(--surface); box-shadow:var(--shadow); }
    .np-hero-card h2 { margin:.35rem 0; font-size:clamp(1.5rem,3vw,2.4rem); }
    .np-hero-metrics { display:flex; flex-wrap:wrap; gap:2rem; margin-top:1rem; }
    .np-hero-metrics strong { display:block; font-size:1.5rem; }
    .np-hero-metrics span,.np-hero-card p { color:var(--muted); }
    .np-map-note { color:var(--muted); font-size:.82rem; margin:.2rem 0 .8rem; }
    .np-map { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:.85rem; }
    .np-building { padding:.85rem; }
    .np-building h3 { margin:.1rem 0 .7rem; font-size:1rem; }
    .np-floor { padding:.55rem 0; border-top:1px solid var(--border); }
    .np-floor-name { display:block; color:var(--muted); font-size:.76rem; margin-bottom:.45rem; }
    .np-tiles { display:flex; flex-wrap:wrap; gap:.45rem; }
    .np-tile { display:grid; place-items:center; min-width:44px; height:42px; padding:0 .5rem; color:var(--text); background:color-mix(in srgb,var(--status-color) 18%,var(--surface)); border:1px solid color-mix(in srgb,var(--status-color) 55%,transparent); border-radius:10px; font-weight:800; }
    .np-legend { display:flex; flex-wrap:wrap; gap:1rem; margin:.7rem 0; color:var(--muted); font-size:.8rem; }
    .np-legend i { display:inline-block; width:9px; height:9px; border-radius:50%; background:var(--status-color); margin-right:.3rem; }
    .np-issue { margin:.55rem 0; border-left:3px solid var(--status-color); }
    .np-issue-top { display:flex; align-items:center; justify-content:space-between; gap:1rem; }
    .np-issue-title { font-weight:800; }
    .np-issue p { margin:.55rem 0 0; color:var(--muted); }
    .np-note { margin:.55rem 0; border-left:3px solid var(--primary); }
    .np-note.warning { border-left-color:var(--medium); }
    .np-note.error { border-left-color:var(--bad); }
    .np-note.success { border-left-color:var(--good); }
    .np-spark { width:100%; height:38px; margin-top:.4rem; }
    @keyframes np-enter { from { opacity:0; transform:translateY(7px); } to { opacity:1; transform:translateY(0); } }
    @media (max-width:700px) { .np-hero { align-items:flex-start; flex-direction:column; padding:1.2rem; } .np-hero-side { width:100%; justify-content:space-between; } .np-hero h1 { font-size:2rem; } }
    @media (prefers-reduced-motion:reduce) { *,*::before,*::after { animation-duration:.01ms !important; animation-iteration-count:1 !important; scroll-behavior:auto !important; transition-duration:.01ms !important; } }
    </style>"""
    for key, value in PALETTE.items():
        css = css.replace(f"__{key}__", value)
    return css


def score_ring(score: float | None, config: dict | None = None) -> str:
    """Skoru durum rengi ve metin etiketiyle halka göstergede sunar."""
    color_name, label, _ = get_score_badge(score, config)
    token = _STATUS_TOKENS[color_name]
    shown_label = "Veri yok" if score is None else label
    safe_score = 0.0 if score is None else max(0.0, min(100.0, float(score)))
    offset = 100.0 - safe_score
    number = "—" if score is None else f"{safe_score:.0f}"
    return (
        f'<div class="np-ring" style="--ring-color:var(--{token})" role="img" '
        f'aria-label="Kampüs skoru {escape(number)} / 100, {escape(shown_label)}">'
        '<svg viewBox="0 0 104 104" aria-hidden="true">'
        '<circle class="np-ring-track" cx="52" cy="52" r="43" pathLength="100"/>'
        f'<circle class="np-ring-value" cx="52" cy="52" r="43" pathLength="100" stroke-dasharray="100" stroke-dashoffset="{offset:.1f}"/>'
        f'<text class="np-ring-number" x="52" y="52">{escape(number)}</text></svg>'
        f'<span class="np-ring-label">Kampüs Nabzı · {escape(shown_label)}</span></div>'
    )


def hero(
    title: str,
    subtitle: str,
    data_label: str,
    campus_score: float | None,
    config: dict | None = None,
) -> str:
    """Ürün başlığını, veri rozetini ve genel kampüs skorunu gösterir."""
    badge = ""
    if data_label.casefold() in {"simulated", "all", "simüle", "tümü"}:
        badge = '<span class="np-sim-badge">⚠ SİMÜLE VERİ</span>'
    safe_title = escape(title)
    safe_subtitle = escape(subtitle)
    return (
        '<section class="np-hero"><div><div class="np-brand">NetNabız · Kampüs Wi-Fi\'ının nabzı</div>'
        f'<h1>{safe_title}</h1><p>{safe_subtitle}</p></div><div class="np-hero-side">'
        f'{badge}{score_ring(campus_score, config)}</div></section>'
    )


def _sparkline(values: Iterable[Any] | None) -> str:
    """Yalnızca sayısal değerlerden güvenli, küçük SVG çizgi üretir."""
    if values is None:
        return ""
    numbers = []
    for value in values:
        try:
            number = float(value)
            if math.isfinite(number):
                numbers.append(number)
        except (TypeError, ValueError):
            continue
    if len(numbers) < 2:
        return ""
    low, high = min(numbers), max(numbers)
    span = high - low or 1.0
    points = " ".join(
        f"{i * 100 / (len(numbers) - 1):.1f},{32 - (value - low) / span * 28:.1f}"
        for i, value in enumerate(numbers)
    )
    return f'<svg class="np-spark" viewBox="0 0 100 36" aria-hidden="true"><polyline points="{points}" fill="none" stroke="var(--primary)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def kpi_card(title: str, value: Any, detail: str = "", mini_line: Iterable[Any] | None = None) -> str:
    """Başlık, büyük değer ve isteğe bağlı sparkline içeren özet kartı üretir."""
    return (
        f'<article class="np-kpi"><span class="np-kpi-label">{escape(str(title))}</span>'
        f'<strong class="np-kpi-value">{escape(str(value))}</strong>'
        f'<span class="np-card-sub">{escape(str(detail))}</span>{_sparkline(mini_line)}</article>'
    )


def _score_status(score: float | None, config: dict | None = None) -> tuple[str, str, str]:
    color_name, label, hex_color = get_score_badge(score, config)
    return _STATUS_TOKENS[color_name], ("Veri yok" if score is None else label), hex_color


def zone_card(
    zone: str,
    score: float | None,
    latency: float | None,
    speed: float | None,
    sample_count: int,
    config: dict | None = None,
) -> str:
    """Bölge skorunu, gecikme/hız bilgilerini ve görsel ölçüm çubuklarını sunar."""
    token, label, _ = _score_status(score, config)
    score_text = "—" if score is None else f"{float(score):.1f}"
    latency_text = "—" if latency is None else f"{float(latency):.1f} ms"
    speed_text = "—" if speed is None else f"{float(speed):.1f} Mbps"
    latency_width = 0 if latency is None else max(0, min(100, (1 - float(latency) / 200) * 100))
    speed_width = 0 if speed is None else max(0, min(100, float(speed)))
    return (
        f'<article class="np-card" style="--status-color:var(--{token})"><div class="np-card-head">'
        f'<h3>{escape(str(zone))}</h3><span class="np-status">{escape(label)}</span></div>'
        f'<div class="np-score">{escape(score_text)}<span class="np-card-sub"> / 100</span></div>'
        f'<div class="np-metric-line"><span>Gecikme</span><b>{escape(latency_text)}</b></div>'
        f'<div class="np-progress" title="Görsel ölçek: 0–200 ms"><span style="width:{latency_width:.1f}%"></span></div>'
        f'<div class="np-metric-line"><span>İndirme</span><b>{escape(speed_text)}</b></div>'
        f'<div class="np-progress" title="Görsel ölçek: 0–100 Mbps"><span style="width:{speed_width:.1f}%"></span></div>'
        f'<p class="np-card-sub">{int(sample_count)} ölçüm</p></article>'
    )


def best_spot_card(
    zone: str,
    score: float | None,
    latency: float | None,
    sentence: str,
    config: dict | None = None,
) -> str:
    """Öğrenci görünümündeki önerilen bölgeyi ana kartta vurgular."""
    token, label, _ = _score_status(score, config)
    score_text = "Veri yok" if score is None else f"{float(score):.1f} / 100 · {label}"
    latency_text = "—" if latency is None else f"{float(latency):.1f} ms"
    return (
        f'<section class="np-hero-card" style="--status-color:var(--{token})">'
        '<span class="np-brand">✦ Şu an önerilen nokta</span>'
        f'<h2>{escape(str(zone))}</h2><p>{escape(str(sentence))}</p>'
        f'<div class="np-hero-metrics"><div><span>Ağ sağlık skoru</span><strong>{escape(score_text)}</strong></div>'
        f'<div><span>Tahmini gecikme</span><strong>{escape(latency_text)}</strong></div></div></section>'
    )


def campus_map(zones: list[dict[str, Any]], config: dict | None = None) -> str:
    """Bölge skorlarını adlardan dinamik bina/kat şematik planına dönüştürür."""
    if not zones:
        return '<p class="np-note">Gösterilecek kampüs bölgesi yok.</p>'
    hierarchy = group_zones_by_hierarchy(zones)
    building_blocks = []
    for building, floors in hierarchy.items():
        floor_blocks = []
        for floor, items in floors.items():
            tiles = []
            for item in items:
                zone = str(item.get("zone", ""))
                score = item.get("score")
                token, label, _ = _score_status(score, config)
                number = "—" if score is None else f"{float(score):.0f}"
                title = escape(f"{zone}: skor {number}, durum {label}", quote=True)
                tiles.append(
                    f'<span class="np-tile" style="--status-color:var(--{token})" title="{title}">'
                    f'<svg viewBox="0 0 24 24" width="18" height="18" role="img" aria-label="{title}">'
                    f'<title>{title}</title><rect x="3" y="3" width="18" height="18" rx="5" fill="var(--status-color)"/></svg>'
                    f'<span>{escape(number)}</span></span>'
                )
            floor_blocks.append(
                f'<div class="np-floor"><span class="np-floor-name">{escape(str(floor))}</span>'
                f'<div class="np-tiles">{"".join(tiles)}</div></div>'
            )
        building_blocks.append(
            f'<section class="np-building"><h3>⌂ {escape(str(building))}</h3>{"".join(floor_blocks)}</section>'
        )
    return (
        '<p class="np-map-note">Şematik plan, ölçeksiz · Karelerin üzerine gelerek skor ve durumu görün.</p>'
        f'<div class="np-map">{"".join(building_blocks)}</div>'
        '<div class="np-legend">'
        '<span><i style="--status-color:var(--good)"></i>İyi</span>'
        '<span><i style="--status-color:var(--medium)"></i>Orta</span>'
        '<span><i style="--status-color:var(--bad)"></i>Zayıf</span>'
        '<span><i style="--status-color:var(--empty)"></i>Veri yok</span></div>'
    )


def issue_card(issue_type: str, zone: str, time: str, evidence: str, severity: str) -> str:
    """Yönetici görünümü için güvenli, ciddiyet rozetli sorun kartı üretir."""
    levels = {"yüksek": "bad", "orta": "medium", "düşük": "good"}
    token = levels.get(str(severity).casefold(), "empty")
    safe_type = escape(str(issue_type))
    icon = {"anomali": "◈", "tıkanıklık": "⌁", "kapsama eksikliği": "◌", "arızalı erişim noktası": "⌘"}.get(str(issue_type).casefold(), "⚠")
    return (
        f'<article class="np-issue" style="--status-color:var(--{token})"><div class="np-issue-top">'
        f'<span class="np-issue-title">{icon} {safe_type} · {escape(str(zone))}</span>'
        f'<span class="np-severity">{escape(str(severity).capitalize())}</span></div>'
        f'<p><b>Zaman:</b> {escape(str(time))}</p><p><b>Kanıt:</b> {escape(str(evidence))}</p></article>'
    )


def insight_ribbon(sentences: list[str]) -> str:
    """Kodun ürettiği kısa analiz bulgularını üst şeritte listeler."""
    if not sentences:
        sentences = ["Bu veri seçimi için öne çıkan bulgu yok."]
    items = "".join(f'<div class="np-insight">✦ {escape(str(sentence))}</div>' for sentence in sentences)
    return f'<section class="np-ribbon" aria-label="Öne çıkanlar">{items}</section>'


def section_title(text: str, subtitle: str = "") -> str:
    """Bölüm başlıklarında ortak tipografi kullanır."""
    return f'<div class="np-section"><h2>{escape(str(text))}</h2><p>{escape(str(subtitle))}</p></div>'


def note_box(text: str, kind: str = "info") -> str:
    """Bilgi, uyarı veya hata metnini temalı kutuda gösterir."""
    safe_kind = kind if kind in {"info", "warning", "error", "success"} else "info"
    icon = {"info": "ℹ", "warning": "⚠", "error": "!", "success": "✓"}[safe_kind]
    return f'<aside class="np-note {safe_kind}">{icon} {escape(str(text))}</aside>'
