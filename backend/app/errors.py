from __future__ import annotations

from fastapi import HTTPException


ERROR_MESSAGES: dict[str, str] = {
    "CAMERA_PERMISSION_DENIED": "Kamera izni verilmedi.",
    "INVALID_FILE": "Yüklenen dosya geçerli bir görüntü değil.",
    "IMAGE_TOO_DARK": "Görüntü çok karanlık. Daha aydınlık bir ortamda tekrar deneyin.",
    "IMAGE_BLURRY": "Görüntü bulanık. Telefonu sabit tutup tekrar deneyin.",
    "MARKERS_NOT_FOUND": "Formun dört referans işareti bulunamadı.",
    "ALIGNMENT_FAILED": "Form referans şablonla güvenilir biçimde hizalanamadı.",
    "INVALID_TEMPLATE": "Yüklenen belge beklenen form şablonuyla eşleşmiyor.",
    "TOO_MANY_UNCERTAIN": "Bu formda çok fazla cevap güvenilir biçimde okunamadı. Formu yeniden taratın.",
    "UPLOAD_FAILED": "Görüntü yüklenemedi.",
    "PROCESSING_FAILED": "Form işlenirken hata oluştu.",
}


class OmrError(Exception):
    def __init__(self, code: str):
        self.code = code
        self.message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["PROCESSING_FAILED"])
        super().__init__(self.message)


def http_error(code: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": {"code": code, "message": ERROR_MESSAGES[code]}})

