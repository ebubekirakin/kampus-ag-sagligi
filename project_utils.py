"""Birden fazla modülde kullanılan küçük ortak yardımcılar."""


def parse_building_floor(zone_name: str) -> tuple[str, str]:
    """Bölge adından bina ve katı çıkarır; bulunmayan katı Bilinmiyor sayar."""
    parts = zone_name.split()
    building = parts[0] if parts else "Bilinmiyor"
    floor = "Bilinmiyor"

    floor_markers = {"1.", "2.", "3.", "4.", "zemin", "giriş"}
    for index, part in enumerate(parts):
        if part.casefold() in floor_markers:
            building = " ".join(parts[:index]) or "Bilinmiyor"
            floor = f"{part} Kat"
            break

    return building, floor
