# NetNabız Tasarım Rehberi

## Görsel dil ve palet

Panel koyu lacivertten laciverte uzanan bir arka plan, koyu mavi yüzeyler,
yarı saydam kenarlıklar ve yuvarlatılmış kartlar kullanır. Birincil vurgu
camgöbeği (`#2dd4bf`), ikincil vurgu mor (`#8b5cf6`) rengidir. Durum
renkleri iyi için `#22c55e`, orta için `#f59e0b`, zayıf için `#ef4444` ve
veri yok için `#64748b` değerleridir. Metinler açık ve ikincil metinler
soluk mavi-gri olmalıdır. Renk tek başına anlam taşımaz; her durumda metin
etiketi de kullanılır.

## Bileşenler

- `hero`: ürün başlığı, kısa açıklama, simüle veri rozeti ve kampüs skor halkası.
- `kpi_card`: büyük değerli özet kartı, gerekirse küçük SVG çizgisi.
- `score_ring`: skor, durum rengi ve durum metni.
- `zone_card`: bölge sağlık kartı ve ölçüm göstergeleri.
- `best_spot_card`: öğrenci görünümündeki önerilen alan.
- `campus_map`: yapılandırmadaki bölge adlarından üretilen şematik bina/kat planı.
- `issue_card`: takma adlı erişim noktalarıyla sorun kartı.
- `insight_ribbon`: kodun mevcut analiz sonuçlarından ürettiği öne çıkanlar.
- `section_title` ve `note_box`: ortak bölüm başlığı ve bilgi/uyarı kutuları.
- `inject_css`: tüm CSS kuralları, renk değişkenleri ve mobil düzen.

## Güvenlik ve erişilebilirlik kuralları

- Yeni harici font, görsel, ikon, JavaScript veya CDN yüklenmez; sistem fontu,
  emoji ve satır içi SVG kullanılır.
- Bölge, kanıt ve diğer dinamik metinler HTML içine eklenmeden önce kaçışlanır.
- Ham cihaz kimliği, SSID, BSSID ve tekil ölçüm satırları panelde gösterilmez;
  veri dışa aktarma düğmesi eklenmez. Erişim noktaları takma adla görünür.
- Skor eşikleri `get_score_badge` ve analytics yapılandırmasından alınır.
  Tasarım bileşenlerinde ayrı skor eşikleri tanımlanmaz.
- Renkli durumların yanında metin etiketi bulunur. Metin/zemin kontrastı
  okunaklı tutulur.
- Animasyonlar kısa ve hafiftir; `prefers-reduced-motion` açık olduğunda
  hareketler kapatılır.
- Kartlar dar ekranlarda `auto-fit` ızgarasıyla alt alta akar.

Yeni görsel bileşen gerekiyorsa önce `dashboard/theme.py` içindeki mevcut
fonksiyonlar genişletilir; sayfalara ayrı, tekrarlanan CSS eklenmez.
