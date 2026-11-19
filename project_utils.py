"""Birden fazla modülde kullanılan küçük ortak yardımcılar."""


def parse_building_floor(zone_name: str) -> tuple[str, str]:
    """Bölge adından bina ve katı çıkarır; bulunmayan katı Bilinmiyor sayar."""
    parts = zone_name.split()
    building = parts[0] if parts else "Bilinmiyor"
    floor = "Bilinmiyor"

    for marker in ("1.", "2.", "3.", "4.", "Zemin", "Giriş"):
        if marker.lower() in zone_name.lower():
            floor = f"{marker} Kat"
            break

    return building, floor
