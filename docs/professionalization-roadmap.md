# Profesyonelleştirme Yol Haritasi

## Tamamlanan Temel

- FastAPI uygulama fabrikasi ve alan bazli router'lar
- SQLite ve PostgreSQL destekli SQLAlchemy veri katmani
- Alembic migration altyapisi
- Idempotent form kaydi
- Sablon koduna gore dinamik soru sayisi dogrulamasi
- Readiness endpoint'i, istek kimligi ve temel guvenlik basliklari
- Render Static Site frontend ve Render Free backend ayrimi
- Gecici Render diski yerine harici `DATABASE_URL`

## Tamamlanan (2026-08-20)

1. Excel sayisal puanlama (`SCORE_MAP` 1/2/3/4), belirsiz hucre boyama, Toplam Puan, Yanitlanan Soru Sayisi, Ozet sekmesi; `format=numeric|text`
2. Frontend Excel menusu (sayisal / metin) ve "Excel hazirlaniyor" gostergesi
3. Render Free cold start: `/healthz` retry/backoff, UI uyarisi
4. Analyze istegi 45 sn timeout; asama mesajlari; `processing.totalMs` basari ekraninda
5. OMR `run_in_threadpool`; uvicorn `--workers 2`; JPEG uzun kenar 2000 / kalite 0.8
6. `GET /api/forms` sayfalama (`items`/`total`); export 500'luk batch
7. `analysis_id` unique; `form_answers` normalize tablo; `deleted_at` soft delete; audit log
8. Gecici `X-Admin-Token` korumasi; 5 dk ayni cevap dizisi `possibleDuplicate`; production'da `/openapi.json` kapali
9. SQLite `scripts/backup_db.py`; haftalik export GitHub Actions taslagi; README yedekleme notlari

## Siradaki Asamalar

1. Supabase Auth ile oturum acma — canli katilimci verisinden once zorunlu
2. `ADMIN` ve `OPERATOR` rol ayrimi (token yerine gercek roller)
3. Kayitlari kullanici ve kurumla iliskilendirme
4. Listeleme, silme ve Excel aktarimini yalnizca admin rolune acma (tam Auth)
5. Frontend'i ozellik bazli bilesenlere ve API istemcisine ayirma
6. Silinen kayitlari admin icin listeleme / geri alma arayuzu
7. Playwright ile mobil kamera akisinin uçtan uca testi
8. Otomatik Excel yedegini S3 / Drive / e-posta hedefine baglama

Gercek katilimci verisiyle yayin icin ilk dort madde zorunludur.
