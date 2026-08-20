# Türk Kızılay Demo OMR Tarama Prototipi

Bu proje mobil anket tarama sisteminin ilk teknik prototipidir. Uygulama login olmadan doğrudan tarama ekranına açılır, A4 demo formunu kamera veya test görseliyle FastAPI backend'e gönderir, OpenCV ile 25 cevabı okur, belirsiz cevapları manuel düzeltmeye alır ve nihai cevapları SQLite veritabanına kaydeder.

Fotoğraflar kalıcı olarak saklanmaz. Görüntü yalnızca analiz sırasında bellekte tutulur. Kalıcı veri dosyası `backend/data/demo.db` içindeki çıkarılmış anket cevaplarıdır.

## Mimari

- `frontend/`: Next.js, React, TypeScript App Router mobil tarama arayüzü.
- `backend/`: FastAPI, OpenCV, NumPy ve SQLite tabanlı OMR API.
- `sample-forms/`: Yazdırılabilir boş form ve yapay test formları.
- `backend/templates/demo_form_v1.json`: A4 standart koordinat sistemi ve 75 cevap bölgesi.

## Gereksinimler

- Node.js 20 veya üzeri
- Python 3.12 veya üzeri
- Docker kullanımı opsiyoneldir

## Docker ile çalıştırma
Windows: Önce Docker Desktop'ı çalıştır, sonra terminalde aşağıdaki komutu gir:
```bash
docker compose up --build
```

Frontend: `http://localhost:3000`
Backend: `http://localhost:8000`

## Backend kurulumu

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONPATH=(Get-Location).Path
python scripts/generate_sample_forms.py
uvicorn app.main:app --reload
```

Linux/macOS için aktivasyon komutu:

```bash
source .venv/bin/activate
```

## Frontend kurulumu

```bash
cd frontend
npm install
npm run dev
```

Gerekirse `frontend/.env.local` içine şunu ekleyin:

```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Kamera ve telefon testi

Tarayıcı kamera erişimi HTTPS veya `localhost` ister. Telefonda test etmek için bilgisayar ve telefon aynı ağda olmalı, backend ve frontend `0.0.0.0` üzerinden çalıştırılmalı, telefondan bilgisayarın yerel IP adresine gidilmelidir.

Örnek:

```bash
cd frontend
npm run dev -- --hostname 0.0.0.0
```

Telefon tarayıcısında `http://BILGISAYAR_IP:3000` açılır. Bazı mobil tarayıcılar yerel HTTP adresinde kamera izni vermeyebilir; bu durumda HTTPS tüneli veya yerel sertifika gerekir.

Telefonla en sorunsuz kullanım için HTTPS tüneli önerilir. Tünel açınca kamerayı güvenli bağlamda kullanabilirsiniz; frontend ekranı açıldıktan sonra gerekirse `Kamerayı Başlat` düğmesine dokunun.

Örnek yaklaşım:

```bash
cd frontend
npm run dev -- --hostname 0.0.0.0
```

Sonra Cloudflare Tunnel veya ngrok ile `http://localhost:3000` adresini dışarı açın ve telefonda tünel URL’sini kullanın.

Frontend API'ye doğrudan bağlanır. Backend farklı bir portta veya adreste çalışıyorsa `frontend/.env.local` içinde genel API adresini ayarlayın:

```text
NEXT_PUBLIC_API_BASE_URL=http://BILGISAYAR_IP:8000
```

## Örnek form

Yazdırılacak form:

```text
sample-forms/blank-form.pdf
```

Form A4 kağıda yüzde 100 ölçekte basılmalıdır. Yazdırma penceresinde "sayfaya sığdır" veya otomatik ölçekleme kapatılmalıdır. Köşelerdeki siyah referans kareleri kesilmemelidir.

## Demo görseller

Tarama ekranındaki `Demo Görseller` alanı kamera kullanmadan hızlı test içindir. Örnekler:

- `filled-clean.png`
- `filled-with-blanks.png`
- `filled-double-mark.png`
- `filled-faint-marks.png`
- `filled-erased-mark.png`
- `filled-perspective.png`
- `filled-shadow.png`
- `filled-blurry.png`

Beklenen cevaplar `sample-forms/expected-results.json` dosyasındadır.

## OMR eşikleri

Eşikler `backend/app/config.py` içinde ortam değişkenlerinden okunur:

- `OMR_EMPTY_THRESHOLD`
- `OMR_MARK_THRESHOLD`
- `OMR_UNCERTAIN_MARGIN`
- `OMR_DOUBLE_MARK_THRESHOLD`
- `MAX_MANUAL_REVIEW_QUESTIONS`

Sağlıklı Beslenme formu genel OMR eşiklerini kullanmaz. Bu formun PDF'den bir kez kalibre edilen
26 soru / 104 dairelik normalize koordinatları
`backend/templates/healthy_nutrition_survey_v1.json` ve `healthy_nutrition_survey_v2.json` dosyalarındadır.
Satır aralıkları farklı olan iki PDF revizyonu daire iç geometrisiyle otomatik ayrılır. Tam ve dengeli dolgu `MARKED`;
tik, X, tek çizgi, küçük nokta ve yarım dolgu `INVALID`; iki dolu daire `MULTIPLE` döner.

4.000–5.000 kayıt ölçeğinde doğruluk/performans: eşikleri sıkılaştırmak (`OMR_MARK_THRESHOLD` yükseltmek)
daha çok manuel kontrole, gevşetmek daha çok otomatik ama hatalı okumaya yol açar. `MAX_MANUAL_REVIEW_QUESTIONS=4`
üretim için makul bir üst sınırdır. Kamera görüntüsü uzun kenarı 2000 px / JPEG 0.8 ile sınırlanır; bu, yükleme
ve OpenCV süresini kısaltır, daire tespiti için yeterli çözünürlüğü korur.

Tek sayfalı PDF veya görüntü yüklenebilir. Debug görsellerini açmak için:

```text
OMR_DEBUG_ENABLED=1
OMR_DEBUG_DIR=backend/debug
```

Her analiz için orijinal, marker, perspektif, ROI, threshold ve nihai overlay görselleri ayrı bir
`analysisId` klasörüne yazılır. Production ortamında fotoğraf saklama politikası nedeniyle varsayılan kapalıdır;
`render.yaml` bu değişkeni set etmez.

Örnek değerler `backend/.env.example` dosyasındadır.

## Excel puanlama

Sayısal aktarım (`/api/forms/export.xlsx?format=numeric`, varsayılan) Likert 1–4 kullanır. Eşleme
`backend/app/scoring.py` içindeki `SCORE_MAP` sabitindedir:

- NEVER (Hiçbir zaman) = 1
- SOMETIMES (Ara sıra / 1-2 kez/hafta) = 2
- OFTEN (Sık sık / 3-4 kez/hafta) = 3
- ALWAYS (Her zaman / 5+ kez/hafta) = 4
- BLANK = boş hücre (0 yazılmaz)
- Belirsiz cevaplar = boş hücre + turuncu dolgu

`format=text` eski metin etiketlerini üretir. Ters madde yoktur; tüm sorular aynı yönde puanlanır.

## API

- `POST /api/omr/analyze`: Fotoğrafı analiz eder, fotoğrafı saklamaz.
- `POST /api/forms`: Nihai cevapları kaydeder.
- `GET /api/forms?limit=&offset=`: Kayıt özetlerini sayfalı listeler (`items`, `total`). Varsayılan `limit=50`, en fazla 200.
- `GET /api/forms/{formId}`: Kayıt detayını döndürür.
- `DELETE /api/forms/{formId}`: Kaydı yumuşak siler (`deleted_at`).
- `GET /api/forms/export.xlsx?format=numeric|text`: Tüm aktif kayıtları Excel'e aktarır.
- `GET /readyz`: Veritabanı bağlantısıyla birlikte servis hazırlığını denetler.

`ADMIN_TOKEN` ortam değişkeni set edildiğinde listeleme, detay, silme ve Excel aktarımı `X-Admin-Token`
başlığı (veya `token` query) ister. Frontend için `NEXT_PUBLIC_ADMIN_TOKEN` kullanılabilir.

## Yedekleme

SQLite (yerel):

```bash
cd backend
$env:PYTHONPATH=(Get-Location).Path
python scripts/backup_db.py
```

Komut WAL modunda `sqlite3` backup API kullanır; kopyalar `backend/data/backups/` altına yazılır.

Postgres (Supabase / Neon): panelden otomatik yedeklemeyi açın.

- Supabase: Project Settings → Database → Backups (Pro planda Point in Time Recovery).
- Neon: dashboard → Backup & restore; zamanlanmış yedek varsayılan olarak açıktır.

Haftalık Excel kopyası için taslak iş akışı: `.github/workflows/weekly-export.yml` (`BACKEND_URL` ve `ADMIN_TOKEN` secret).

## Testler

Backend:

```bash
cd backend
$env:PYTHONPATH=(Get-Location).Path
pytest
```

Frontend:

```bash
cd frontend
npm test
```

## Render ile dağıtım

Bu proje Render’a doğrudan yüklenebilir şekilde hazırlanmıştır. Kök dizindeki [render.yaml](render.yaml) dosyası backend ve frontend servislerini tanımlar.

1. Render hesabı açın ve GitHub reposunu bağlayın.
2. Yeni bir Render Web Service oluşturup bu repoyu seçin.
3. Render, [render.yaml](render.yaml) dosyasını otomatik algılayacaktır.
4. Supabase veya Neon üzerinde ücretsiz bir PostgreSQL veritabanı oluşturun.
5. Backend servisinde `DATABASE_URL` değerini PostgreSQL bağlantı adresi olarak tanımlayın.
6. Backend servisinde `CORS_ORIGINS` değerini frontend Render adresi olarak tanımlayın.
7. Frontend servisinde `NEXT_PUBLIC_API_BASE_URL` değerini backend Render adresi olarak tanımlayın.
8. Backend `ADMIN_TOKEN` ve frontend `NEXT_PUBLIC_ADMIN_TOKEN` değerlerini aynı gizli anahtarla tanımlayın.

Render Free plandaki backend soğuk başlar: ilk tarama 20–25 saniye sürebilir. Arayüz `/healthz` ile sunucuyu
uyandırır ve asıl analizi ondan sonra gönderir.

Render üzerindeki backend dosya sistemi kalıcı veri için kullanılmaz. Yerel geliştirmede SQLite, dağıtımda harici PostgreSQL kullanılır. Alembic migration'ları backend başlarken uygulanır.

## Bilinen teknik sınırlamalar

- Mobil kalite kontrolü ilk prototip seviyesindedir; gerçek marker algılama backend tarafında yapılır.
- Kesin mükerrer tespit iddiası yoktur; backend 5 dakika içinde birebir aynı cevap dizisi için `possibleDuplicate` bayrağı basar, frontend ayrıca oturum içi uyarı gösterir.
- Fotoğraf arşivi, tam kullanıcı hesabı, okul entegrasyonu kapsam dışıdır.
- Tam Supabase Auth ve rol ayrımı henüz yoktur; geçici koruma `ADMIN_TOKEN` / `X-Admin-Token` ile sağlanır. Gerçek katılımcı verisiyle yayına alınmadan önce Auth tamamlanmalıdır.
