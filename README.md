# NetNabız

NetNabız, üniversite kampüsündeki Wi-Fi bağlantısının durumunu ölçüp sonuçları anlaşılır biçimde göstermeyi amaçlayan bir bitirme projesidir. Sistem ölçümleri kaydedecek, ağ sorunlarını inceleyecek ve sonuçları Türkçe açıklayacaktır.

Proje geliştirme aşamasındadır. Aşağıdaki yol haritasını küçük ve çalıştırılabilir adımlarla izleyeceğiz.

## Nasıl çalışacak?

1. Bir ölçüm istemcisi bağlantı kalitesi bilgilerini toplayacak. İlk aşamalarda gerçek ağ yerine örnek (simüle) veriler kullanacağız.
2. FastAPI tabanlı sunucu ölçümleri doğrulayacak, anonimleştirecek ve tek bir SQLite veritabanına kaydedecek.
3. Analiz bölümü sinyal, gecikme, paket kaybı ve hız değerlerinden ağ sağlığı göstergeleri üretecek.
4. Streamlit paneli ölçümleri ve analiz sonuçlarını grafiklerle gösterecek.
5. Yerel Ollama modeli, yalnızca anonim ve özetlenmiş analizleri Türkçe açıklayacak. Hesaplamaları model yapmayacak.

## Teknolojiler

- **Python 3.11 veya üstü:** Projenin ana programlama dili.
- **FastAPI:** Ölçümleri alan ve sunan yerel API.
- **SQLite:** Bilgisayarda tek dosyada çalışan veritabanı.
- **Streamlit:** Tarayıcıda açılan yerel kontrol paneli.
- **Ollama:** Yapay zekâyı internet servisi yerine bilgisayarda çalıştırmak için.
  - Ana model: `qwen3:4b`
  - Karşılaştırma modelleri: `gemma3:4b` ve `qwen3:8b`

## Geliştirme ortamı

Proje **Windows 11**, **PowerShell**, **16 GB RAM** ve **4 GB VRAM'li ekran kartı** bulunan bilgisayarda geliştirilecektir. Kurulum ve çalıştırma yönergeleri PowerShell komutlarıyla verilecektir.

## Yol haritası

- [ ] Proje klasörlerini ve temel Python ortamını hazırlama
- [ ] Örnek ölçüm verisi üretme
- [ ] SQLite veritabanını ve ölçüm şemasını oluşturma
- [ ] FastAPI ile ölçüm alma ve doğrulama
- [ ] Cihaz kimliğini hash'leyerek anonimleştirme
- [ ] Ağ sağlığı skoru ve basit analizler
- [ ] Streamlit panelinde ölçüm ve sonuçları gösterme
- [ ] Ollama ile anonim analiz özetlerini Türkçe açıklama
- [ ] Bileşenleri yerel ortamda birlikte çalıştırma ve proje dokümantasyonu

Her adımı ayrı ayrı ele alacağız; her adımın sonunda çalıştırıp deneyebileceğin bir sonuç olacak.

## Gizlilik ve güvenlik ilkeleri

- Ham cihaz kimliği kaydedilmez; saklanması gerekiyorsa önce hash'lenir.
- Ham IP adresi veritabanına yazılmaz.
- Gerçek ölçüm verileri, IP aralıkları ve BSSID listeleri Git deposuna eklenmez.
- Yapay zekâ yalnızca anonimleştirilmiş ve toplulaştırılmış özetleri alır; ham ölçümlere veya veritabanına erişmez.
- Ölçümleri ve skorları kod hesaplar; yapay zekâ yalnızca sonuçları açıklar.
- Kullanıcıdan gelen serbest metin güvenilir talimat sayılmaz.
- Proje ücretsiz, yerel ve bulut hizmeti ya da ücretli API gerektirmeyecek şekilde tasarlanır.

## Proje klasörleri

```text
backend/      API, doğrulama, anonimleştirme ve veritabanı
client/       Ölçüm istemcisi
analytics/    Skor, tahmin ve anomali analizi
dashboard/    Streamlit paneli
llm/          Ollama bağlantısı ve açıklama istemleri
data/         Simüle veri üreticisi (gerçek ölçüm verisi değil)
docs/         Proje notları
config.example.toml  Örnek ayarlar
```

Klasör ve dosyalar ilgili geliştirme adımlarında oluşturulacaktır.
