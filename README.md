# NetNabız

NetNabız, üniversite kampüsündeki Wi-Fi bağlantısının sağlığını ölçmek ve anlaşılır biçimde göstermeyi amaçlayan bir bitirme projesidir. Ölçümler önce yerel bir API üzerinden alınacak ve SQLite veritabanında saklanacaktır. Proje ilerledikçe analizler bağlantı sorunlarını bulmaya yardımcı olacak ve Streamlit panelinde gösterilecektir. Yerel Ollama modeli, yalnızca anonim özetleri Türkçe açıklayacaktır. Proje ücretsiz araçlarla ve Windows 11 üzerinde yerel olarak geliştirilmektedir.

## Kurulum

PowerShell'i proje klasöründe aç ve sanal ortamı oluşturup etkinleştir:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
```

Gerekli paketleri kur:

```powershell
python -m pip install -r requirements.txt
```

## Sunucuyu çalıştırma

```powershell
uvicorn backend.main:app --reload --no-access-log
```

`--no-access-log` parametresi, HTTP isteklerini yapan kullanıcıların IP adreslerinin terminale veya log dosyalarına kaydedilmesini önleyerek kullanıcı gizliliğini korur.

Tarayıcıda API belgelerini `http://127.0.0.1:8000/docs` adresinden, sağlık kontrolünü `http://127.0.0.1:8000/health` adresinden aç. Sağlık kontrolü `{"status":"ok"}` yanıtını verir.

## Simüle ölçümler

Sunucu çalışırken, proje klasöründeki ikinci PowerShell penceresinde önce küçük bir deneme yap:

```powershell
python data/generate_simulated.py --days 1 --mode api
```

Ardından 14 günlük örnek veriyi üretmek için:

```powershell
python data/generate_simulated.py --days 14 --seed 42 --mode api
```

`--mode csv` seçeneği ölçümleri `data/simulated.csv` dosyasına yazar. Her çalıştırmada senaryo cevap anahtarı `data/ground_truth.json` dosyasına kaydedilir. Ölçüm listesi korumalıdır; `/docs` sayfasında `GET /measurements` isteğine `X-API-Key` başlığını ekleyerek görüntüleyebilirsin.

## Windows ölçüm istemcisi

Örnek istemci ayarını yerel dosyaya kopyala ve aç:

```powershell
Copy-Item client/client_config.example.toml client/client_config.toml
notepad client/client_config.toml
```

Sunucudaki `config.toml` ile istemci ayarındaki `api_key` aynı olmalı. Kampüs Wi-Fi adını ve erişim noktalarının BSSID değerlerini yalnızca yerel `client_config.toml` dosyasına ekle; ikisi de eşleşmedikçe istemci ölçümü doğrulanmış saymaz. Bir PowerShell penceresinde sunucuyu, ikinci pencerede istemciyi başlat:

Sunucuya ulaşılamazsa istemci, `client_config.example.toml` içindeki `zones` listesini kullanır; kendi yerel ayarındaki `zones` listesi bu örnek listeyi değiştirebilir.

```powershell
# Birinci pencere
uvicorn backend.main:app --reload --no-access-log

# İkinci pencere
python -m client.main --repeat 1
```

İstemci tekrarlarını `--repeat 5 --interval 60` ile ayarlayabilirsin. Gerçek ölçümleri `/docs` içindeki `GET /measurements` isteğinde `is_simulated=0` filtresi ve `X-API-Key` başlığıyla görüntüle. `GET /zones` bölge isimleri içerdiğinden anahtarsız kalır.
