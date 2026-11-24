"""Tema bileşenlerinin güvenli HTML ve skor etiketlerini sınar."""

import inspect
import pytest

from dashboard import theme


def _all_components():
    """Her görsel bileşenden örnek HTML alır."""
    return [
        theme.inject_css(),
        theme.hero("Başlık", "Alt başlık", "simulated", 80),
        theme.kpi_card("Kayıt", 12, "ölçüm", [1, 3, 2]),
        theme.score_ring(80),
        theme.zone_card("Bölge", 80, 20, 30, 25),
        theme.best_spot_card("Bölge", 80, 20, "Öneri"),
        theme.campus_map([{"zone": "Kütüphane 1. kat Salon", "score": 80}]),
        theme.issue_card("Anomali", "Bölge", "10:00", "kanıt", "Yüksek"),
        theme.insight_ribbon(["Öne çıkan bulgu"]),
        theme.section_title("Başlık", "Alt yazı"),
        theme.note_box("Bilgi"),
    ]


def test_all_components_return_html_without_script_or_external_urls():
    components = _all_components()
    assert all(isinstance(item, str) for item in components)
    combined = "\n".join(components).casefold()
    assert "<script" not in combined
    assert "http" not in combined
    assert "//cdn" not in combined
    assert "fonts.googleapis" not in combined
    assert "xmlns" not in combined


@pytest.mark.parametrize("component", [
    lambda value: theme.hero(value, "Alt", "real", 70),
    lambda value: theme.zone_card(value, 70, 30, 20, 5),
    lambda value: theme.best_spot_card(value, 70, 30, "Öneri"),
    lambda value: theme.campus_map([{"zone": value, "score": 70}]),
    lambda value: theme.issue_card("Sorun", value, "Zaman", "Kanıt", "Orta"),
])
def test_dynamic_html_text_is_escaped(component):
    result = component("<script>alert(1)</script>")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
    assert "<script>alert(1)</script>" not in result


@pytest.mark.parametrize("score,label,color", [
    (75, "İyi", "#22c55e"),
    (50, "Orta", "#f59e0b"),
    (49.9, "Zayıf", "#ef4444"),
    (None, "Veri yok", "#64748b"),
])
def test_ring_and_zone_card_use_same_score_badge(score, label, color):
    ring = theme.score_ring(score)
    card = theme.zone_card("Bölge", score, 20, 30, 4)
    token = {
        "#22c55e": "good", "#f59e0b": "medium", "#ef4444": "bad", "#64748b": "empty"
    }[color]
    assert label in ring
    assert label in card
    assert f"--{token}: {color}" in theme.inject_css()
    assert f"--ring-color:var(--{token})" in ring
    assert f"--status-color:var(--{token})" in card


def test_score_boundaries_follow_config_thresholds():
    config = {"analytics": {"score_green": 90, "score_yellow": 60}}
    assert "İyi" in theme.score_ring(90, config)
    assert "Orta" in theme.score_ring(60, config)
    assert "Zayıf" in theme.score_ring(59, config)


@pytest.mark.parametrize("zones,building_count", [([], 0), ([{"zone": "Kütüphane 1. kat Salon", "score": 80}], 1)])
def test_campus_map_handles_empty_and_single_zone(zones, building_count):
    html = theme.campus_map(zones)
    assert html.count('class="np-building"') == building_count


def test_campus_map_buildings_are_derived_from_zone_names():
    html = theme.campus_map([
        {"zone": "Kütüphane 1. kat Okuma salonu", "score": 80},
        {"zone": "Mühendislik B Blok 2. kat Koridor", "score": 55},
    ])
    assert html.count('class="np-building"') == 2
    assert "Kütüphane" in html and "Mühendislik B Blok" in html
    assert "Şematik plan, ölçeksiz" in html


def test_component_signatures_do_not_accept_private_identifiers():
    for name in (
        "hero", "kpi_card", "score_ring", "zone_card", "best_spot_card",
        "campus_map", "issue_card", "insight_ribbon", "section_title", "note_box",
    ):
        parameters = inspect.signature(getattr(theme, name)).parameters
        assert not {"device_hash", "ssid", "bssid"}.intersection(parameters)

