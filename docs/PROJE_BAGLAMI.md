# NetNabız Proje Bağlamı

## Projenin Amacı
Üniversite kampüsündeki Wi-Fi sağlığını ölçen, ölçümleri anonimleştirip kaydeden, analiz eden, panelde gösteren ve sonuçları yerel bir yapay zekayla Türkçe açıklayan bir sistem. Bu bir bitirme projesidir; jüriye basit ve anlaşılır şekilde aktarılmalıdır.

## Kesin Kurallar
1. Her şey ÜCRETSİZ olmalı. Ücretli servis, API anahtarı, bulut hizmeti yok.
2. Her şey yerel bilgisayarda (lokal) çalışacak.
3. Mümkün olan en basit araçlar kullanılacak. Docker, mikroservis veya ağır kütüphaneler yok.
4. Kod kısa, okunaklı ve Türkçe yorumlu olmalı. Fonksiyon ve değişken adları İngilizce olmalı.
5. Her adım sonunda çalıştırılıp test edilebilir bir çıktı üretilmeli.
6. Büyük kararlarda kullanıcıya danışılmalı.
7. Yapılan işler 3-5 sade cümleyle ve çalıştırma adımlarıyla açıklanmalı.

## Teknoloji Yığını
- Dil: Python 3.11+
- Sunucu: FastAPI
- Veritabanı: SQLite (tek dosya)
- Panel: Streamlit
- Yerel Yapay Zeka: Ollama (qwen3:4b ana model, gemma3:4b ve qwen3:8b karşılaştırma)
- Ortam: Windows 11, PowerShell, 16 GB RAM, 4 GB VRAM

## Ölçüm Veri Şeması
- `device_hash`: Cihaz kimliğinin hash'i (ham kimlik ASLA saklanmaz)
- `source`: "desktop" | "web" | "android"
- `ssid`, `bssid`: Wi-Fi adı ve modem MAC adresi
- `rssi_dbm`: Sinyal gücü (dBm)
- `rtt_ms`: Gecikme (ping süresi ms)
- `loss_pct`: Paket kaybı yüzdesi
- `down_mbps`, `up_mbps`: İndirme ve yükleme hızı
- `building`, `floor`, `zone`: Bina, kat, bölge
- `campus_confidence`: 0-1 arası kampüs ağı güven skoru
- `is_verified`: 1 (doğrulanmış kampüs ölçümü) veya 0
- `is_simulated`: 1 (simüle ölçüm) veya 0 (gerçek ölçüm)
- `timestamp`: ISO formatında ölçüm zamanı

## Tasarım kuralı
Panele yeni sayfa/sekme eklerken `docs/TASARIM_REHBERI.md`'ye ve
`dashboard/theme.py` bileşenlerine uy; kendi CSS'ini yazma.
