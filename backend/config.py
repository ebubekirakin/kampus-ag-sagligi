"""
Yapılandırma ayarlarını yükleyen yardımcı modül.
config.toml varsa onu, yoksa config.example.toml dosyasını okur.
"""

from pathlib import Path
import tomllib

# Proje ana dizini
BASE_DIR = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    """TOML yapılandırma dosyasını okur ve sözlük olarak döner."""
    config_file = BASE_DIR / "config.toml"
    if not config_file.exists():
        config_file = BASE_DIR / "config.example.toml"

    with open(config_file, "rb") as f:
        return tomllib.load(f)
