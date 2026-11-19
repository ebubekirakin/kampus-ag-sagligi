"""
Yapılandırma ayarlarını yükleyen yardımcı modül.
config.toml varsa onu, yoksa config.example.toml dosyasını okur.
"""

from pathlib import Path
from functools import lru_cache
import tomllib

# Proje ana dizini
BASE_DIR = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def load_config() -> dict:
    """TOML ayarlarını bir kez okur; sorun varsa düzeltme yolunu açıklar."""
    config_file = BASE_DIR / "config.toml"
    if not config_file.exists():
        config_file = BASE_DIR / "config.example.toml"

    try:
        with open(config_file, "rb") as file:
            return tomllib.load(file)
    except FileNotFoundError as error:
        raise RuntimeError(
            "Ayar dosyası bulunamadı. Proje kökünde config.toml oluşturun "
            "veya config.example.toml dosyasını geri yükleyin."
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(
            f"{config_file.name} okunamadı. TOML yazımını kontrol edin: {error}"
        ) from error
    except OSError as error:
        raise RuntimeError(f"{config_file.name} açılamadı: {error}") from error
