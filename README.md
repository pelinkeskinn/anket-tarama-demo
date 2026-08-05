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
SERVER_API_BASE_URL=http://localhost:8000
```

## Kamera ve telefon testi

Tarayıcı kamera erişimi HTTPS veya `localhost` ister. Telefonda test etmek için bilgisayar ve telefon aynı ağda olmalı, backend ve frontend `0.0.0.0` üzerinden çalıştırılmalı, telefondan bilgisayarın yerel IP adresine gidilmelidir.

Örnek:

```bash
cd frontend
npm run dev -- --hostname 0.0.0.0
```

Telefon tarayıcısında `http://BILGISAYAR_IP:3000` açılır. Bazı mobil tarayıcılar yerel HTTP adresinde kamera izni vermeyebilir; bu durumda HTTPS tüneli veya yerel sertifika gerekir.

Frontend, `/api` isteklerini backend'e proxy eder. Backend farklı bir portta veya adreste çalışıyorsa `frontend/.env.local` içinde server tarafı proxy hedefini ayarlayın:

```text
SERVER_API_BASE_URL=http://BILGISAYAR_IP:8000
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

Örnek değerler `backend/.env.example` dosyasındadır.

## API

- `POST /api/omr/analyze`: Fotoğrafı analiz eder, fotoğrafı saklamaz.
- `POST /api/demo/forms`: Nihai cevapları SQLite'a kaydeder.
- `GET /api/demo/forms`: Kayıt özetlerini listeler.
- `GET /api/demo/forms/{formId}`: 25 cevaplı kayıt detayını döndürür.
- `DELETE /api/demo/forms/{formId}`: Demo kaydını siler.

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

## Bilinen teknik sınırlamalar

- Bu prototip tek form şablonu destekler: `DEMO_FORM_V1`.
- Mobil kalite kontrolü ilk prototip seviyesindedir; gerçek marker algılama backend tarafında yapılır.
- Kesin mükerrer tespit iddiası yoktur; aynı oturumda cevap dizisi benzerliğiyle uyarı gösterilir.
- Fotoğraf arşivi, kullanıcı hesabı, admin paneli, okul entegrasyonu ve raporlama kapsam dışıdır.
- SQLite demo kalıcılığı tek cihaz geliştirme akışı içindir; üretim veritabanı değildir.
