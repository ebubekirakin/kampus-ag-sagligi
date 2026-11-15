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
uvicorn backend.main:app --reload
```

Tarayıcıda API belgelerini `http://127.0.0.1:8000/docs` adresinden, sağlık kontrolünü `http://127.0.0.1:8000/health` adresinden aç. Sağlık kontrolü `{"status":"ok"}` yanıtını verir.
