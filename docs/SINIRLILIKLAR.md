# NetNabız Sınırlılıkları

## Simülasyon sınırı

Simüle veride gecikme, sinyal, paket kaybı ve hız değerleri belirli kurallarla üretilir; analiz de bu örüntüleri arar. Bu nedenle simülasyonda bulunan dört senaryonun tümü gerçek kampüs ağında aynı başarıyla bulunacak anlamına gelmez. Gerçek ağda farklı cihazlar, erişim noktaları, kullanıcı davranışları ve çevresel koşullar vardır.

## Kesinti senaryosu ve asgari örnek

Kesinti 14 günlük veri içinde belirli bir saat aralığına yerleştirilmiştir. Rastgele üretim, bu arıza bölgesi ve saatinde tek başına yeterli örnek oluşturmayabileceğinden üretici bu saate ayrıca üç ölçüm ekler. Analiz, `config.example.toml` içindeki `min_hour_samples = 2` şartını sağlamayan saatleri atlar; üç ek kayıt bu asgari sayıya ulaşmayı güvenceye alır. Yenilenen veride kesinti, saatlik gecikme medyanı 650.0 ms ve sağlam Z-skoru 427.22 ile bulundu.

## Tahmin

Son üç gün test dönemi olarak ayrıldığında, mevsimsel yöntemin gecikme MAE değeri Mühendislik B Blok 2. kat Derslik koridorunda 8.31 ms; tek medyan taban yönteminde 7.68 ms oldu. Öğrenci İşleri Giriş Kat için mevsimsel MAE 12.26 ms, tek medyan MAE 11.33 ms oldu. Bu iki bölgede basit tek medyan yöntemi daha düşük hata verdi; tüm bölgelerin toplamında ise mevsimsel yöntem 9.99 ms ile tek medyan yönteminin 19.50 ms değerinden daha iyi sonuç verdi.

## Ölçüm yöntemi

Gecikme, yapılandırılmış hedefe on TCP bağlantısı denenerek başarılı bağlantı sürelerinin medyanından hesaplanır. Başarısız bağlantı oranı paket kaybı için yaklaşık gösterge olarak kullanılır; ICMP ping ölçümü değildir. Windows sinyal yüzdesi `yüzde / 2 - 100` formülüyle dBm'e çevrilir ve yalnızca yaklaşık bir değerdir. İndirme/yükleme testi yapılandırılmış HTTP adresine yapılır; örnek ayarlar Cloudflare hız testi uç noktalarını kullanır, bu nedenle ölçüm kampüs içi sunucuyu değil internete giden yolu da kapsar.

## Saat dilimi

Simüle ölçüm zamanları UTC olarak üretilir ve `simulated` analizinde UTC kullanılır. Gerçek ölçüm analizinde `analytics.utc_offset_hours` uygulanır; örnek değer Türkiye için `3` saattir. `all` seçeneğinde seçilen tüm satırlar aynı yerel saat tabanına kaydırılır.

## Katılım yoğunluğu

Saatlik ölçüm sayısı, kullanıcıların ölçüm gönderme/katılım yoğunluğunu gösterir. Bu sayı ağın bant genişliği kullanımını veya gerçek kullanıcı sayısını ölçmez.

## SSID ve BSSID saklama

Veritabanı şemasında SSID ve BSSID alanları ham metin olarak tutulabilir. Analiz özeti BSSID yerine AP takma adı yazar ve terminal analiz çıktısı da takma ad kullanır; ancak bu, veritabanındaki ham alanları anonimleştirmez.

## SQLite ve Dağıtık Kullanım Sınırı

SQLite dosya tabanlı bir veritabanıdır ve tek bir sunucu/makine üzerinde çalışmak üzere tasarlanmıştır. Eşzamanlı yazma işlemlerinde WAL modu performansı artırsa da birden fazla sunucunun ortak veritabanı dosyasına yazması dosya kilidi sorunlarına yol açar. Çok sunuculu dağıtık mimariler için PostgreSQL gibi istemci-sunucu mimarili bir veritabanına geçilmelidir.

## Streamlit Paneli ve Eşzamanlı Kullanıcı Sınırı

Streamlit web arayüzü, yönetici analitiği ve hafif etkileşimli görselleştirme için uygundur; binlerce öğrencinin aynı anda bağlandığı yüksek trafikli web uygulamaları için tasarlanmamıştır. Çok kullanıcılı yoğun erişimlerde panel performansı düşebilir.

## Görünüm Yetkilendirme Değildir

Paneldeki "Öğrenci" ve "Yönetici" görünümleri yalnızca arayüz perspektifini değiştiren bir filtrelemedir; arkasında parola veya rol tabanlı gerçek bir yetkilendirme (RBAC) bulunmaz. Panel kampüs geneline veya internete açılacaksa önüne kurumsal bir kimlik doğrulama / giriş sistemi (SSO, OAuth2 vb.) eklenmelidir.

## Ölçümlerin Ağ Üzerindeki Kendi Yükü

İstemcinin yaptığı gecikme, paket kaybı ve özellikle bant genişliği (indirme/yükleme) hız testleri ağ üzerinde anlık bir veri trafiği oluşturur. Yüzlerce cihazın aynı anda hız testi yapması ağ sağlığını ölçerken ağın kendisini tıkayabilir. Bu nedenle istemci ölçüm sıklığı makul aralıklarda tutulmalıdır.

