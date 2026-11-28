# NetNabız Depolama Katmanı (Storage Layer)

Bu doküman, NetNabız projesindeki veritabanı soyutlama mimarisini, arayüz sözleşmesini ve yeni veritabanı motorlarının sisteme nasıl ekleneceğini açıklar.

## 1. Mimari Amaç ve Tasarım

NetNabız başlangıçta hafif, dosya tabanlı ve harici sunucu kurulumu gerektirmeyen SQLite üzerine inşa edilmiştir. Ancak sistemin ileride PostgreSQL, MySQL veya bulut tabanlı bir veritabanına taşınabilmesi amacıyla veri erişimi `storage/` paketi altında toplanmış ve `MeasurementStore` soyut sözleşmesi ile sınırlandırılmıştır.

```
                      +-------------------+
                      |   Uygulama/API    |
                      |  (backend/main)   |
                      +---------+---------+
                                |
                                v
                      +-------------------+
                      | MeasurementStore  |  <--- (Soyut Protokol / Interface)
                      |  (storage/base)   |
                      +---------+---------+
                                |
           +--------------------+--------------------+
           |                                         |
           v                                         v
+------------------------+               +------------------------+
| SQLiteMeasurementStore |               | (Gelecekte: Postgres)  |
| (WAL modu, salt okunur)|               | (Connection Pool vb.)  |
+------------------------+               +------------------------+
```

### Temel Prensipler
- **İş Mantığı ve Depolama Ayrımı:** HMAC hash hesaplaması, IP güven skoru, doğrulama kuralları ve Pydantic modelleri `backend/` katmanında kalır. Depolama katmanı yalnızca ham veriyi alır, doğrular, kaydeder ve sorgular.
- **Parametreli Sorgular:** Depolama katmanındaki tüm sorgular parametreli (`?` veya motorun parametre biçimi) çalışır. Asla SQL string birleştirmesi yapılmaz.
- **Okuma ve Yazma İzolasyonu:** Analiz ve gösterge paneli (Streamlit) sorguları salt okunur bağlantı (`mode=ro`) ile açılır. Yazma işlemlerinde ise eşzamanlı kilitlenmeleri önlemek için `WAL (Write-Ahead Logging)` modu ve `busy_timeout` (5000 ms) kullanılır.
- **Harici sqlite3 Bağımlılığı Yasağı:** `storage/` paketi haricindeki hiçbir modülde doğrudan `import sqlite3` yapılamaz (mimari test ile güvence altına alınmıştır).

---

## 2. Depolama Sözleşmesi (`MeasurementStore`)

Her depolama motoru `storage/base.py` dosyasındaki şu 5 temel yöntemi uygulamak zorundadır:

```python
class MeasurementStore(Protocol):
    def init_schema(self) -> None:
        """Tabloları, indeksleri oluşturur ve şema geçişlerini uygular."""
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
```

---

## 3. Yeni Bir Veritabanı Nasıl Eklenir? (Örn: PostgreSQL)

1. `storage/postgres_store.py` dosyası oluşturulur ve `MeasurementStore` sınıfı uygulanır (`init_schema`, `insert_measurement`, `fetch_measurements`, `load_dataframe`, `count_summary`).
2. `storage/__init__.py` içerisindeki `get_store()` fabrikasına yeni backend seçeneği eklenir:
   ```python
   elif backend_type == "postgres":
       return PostgresMeasurementStore(connection_url=storage_cfg["url"])
   ```
3. `config.toml` dosyasına `[storage] backend = "postgres"` yapılandırması girilir.

### Veritabanı Geçiş Notları ve Değerlendirmeler

- **PostgreSQL'e Geçiş (Kolay / Önerilen):**
  PostgreSQL ilişkisel bir veritabanı olduğu için SQL şeması, sütun türleri, indeksler ve `pandas.read_sql` desteği birebir uyumludur. Eşzamanlı yazma kapasitesi SQLite'tan çok daha yüksektir ve kampüs geneli canlı kullanımda ilk tercih olmalıdır.
  
- **Firestore / MongoDB Doküman Tabanlı Veritabanlarına Geçiş (Dikkat Gerektirir):**
  - **Maliyet ve Analiz Hızı:** Analiz modülü (`analytics/`), mevsimsel gecikme matrisleri ve anomali tespiti için tüm doğrulanmış veriyi hafızaya (`DataFrame`) yükler. Firestore gibi belge başına okuma ücreti alan sistemlerde binlerce ölçümü her analizde baştan çekmek yüksek bulut maliyetine ve gecikmeye yol açar.
  - **Veri Mahremiyeti ve Güvenlik:** Firebase/Firestore kullanıldığında kampüs Wi-Fi ölçüm verileri kurum dışındaki bulut sunucularına aktarılmış olur; bu durum yerel ağ sağlığı ve gizlilik prensipleri açısından yeniden değerlendirilmelidir.
