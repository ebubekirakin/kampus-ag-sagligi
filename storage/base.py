"""Depolama katmanı soyut sözleşmesi (MeasurementStore)."""

from typing import Any, Literal, Protocol, runtime_checkable
import pandas as pd


@runtime_checkable
class MeasurementStore(Protocol):
    """Farklı veritabanı motorlarının uygulaması gereken ortak depolama arayüzü."""

    def init_schema(self) -> None:
        """Veritabanı şemasını başlatır ve gerekli geçişleri uygular."""
        ...

    def insert_measurement(self, record: dict[str, Any]) -> int:
        """Yeni bir ölçüm kaydeder ve üretilen kayıt kimliğini döner."""
        ...

    def fetch_measurements(
        self,
        *,
        is_simulated: int | None = None,
        zone: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """API listelemesi için ölçüm satırlarını döner."""
        ...

    def load_dataframe(
        self,
        data_kind: Literal["simulated", "real", "all"] = "simulated",
        verified_only: bool = True,
    ) -> pd.DataFrame:
        """Analiz modülleri için salt okunur bir pandas DataFrame yükler."""
        ...

    def count_summary(self, data_kind: Literal["simulated", "real", "all"] = "all") -> dict[str, int]:
        """Kayıt sayıları özetini (toplam, doğrulanmış, doğrulanmamış, simüle, gerçek) döner."""
        ...
