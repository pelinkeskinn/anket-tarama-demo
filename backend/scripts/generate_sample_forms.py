from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "sample-forms"
TEMPLATE_PATH = ROOT / "backend" / "templates" / "demo_form_v1.json"

PAGE_W = 2480
PAGE_H = 3508
MARKER_MARGIN = 140
MARKER_SIZE = 130
QUESTION_COUNT = 25
RADIUS = 45
BOX = 106
LEFT_X = 260
RIGHT_X = 1340
OPTION_OFFSETS = {"NEVER": 360, "SOMETIMES": 585, "ALWAYS": 810}
START_Y = 820
ROW_GAP = 145
LABELS = {"NEVER": "Hicbir zaman", "SOMETIMES": "Bazen", "ALWAYS": "Her zaman"}
V2_MARKER_IDS = {"topLeft": 10, "topRight": 11, "bottomRight": 12, "bottomLeft": 13}
V2_MARKER_SIZE = 180
V2_MARKER_MARGIN = 120
V2_BOX = 130
V2_RADIUS = 56
V2_LEFT_X = 220
V2_RIGHT_X = 1300
V2_OPTION_OFFSETS = {"NEVER": 390, "SOMETIMES": 640, "ALWAYS": 890}
V2_START_Y = 840
V2_ROW_GAP = 152


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def option_box(cx: int, cy: int) -> dict[str, int]:
    return {"x": cx - BOX // 2, "y": cy - BOX // 2, "width": BOX, "height": BOX}


def v2_option_box(cx: int, cy: int) -> dict[str, int]:
    return {"x": cx - V2_BOX // 2, "y": cy - V2_BOX // 2, "width": V2_BOX, "height": V2_BOX}


def question_position(question_no: int) -> tuple[int, int]:
    if question_no <= 13:
        row = question_no - 1
        return LEFT_X, START_Y + row * ROW_GAP
    row = question_no - 14
    return RIGHT_X, START_Y + row * ROW_GAP


def v2_question_position(question_no: int) -> tuple[int, int]:
    if question_no <= 13:
        row = question_no - 1
        return V2_LEFT_X, V2_START_Y + row * V2_ROW_GAP
    row = question_no - 14
    return V2_RIGHT_X, V2_START_Y + row * V2_ROW_GAP


def build_template() -> dict[str, object]:
    questions = []
    for question_no in range(1, QUESTION_COUNT + 1):
        column_x, y = question_position(question_no)
        options = {
            key: option_box(column_x + offset, y)
            for key, offset in OPTION_OFFSETS.items()
        }
        questions.append({"questionNo": question_no, "options": options})
    return {
        "templateCode": "DEMO_FORM_V1",
        "pageWidth": PAGE_W,
        "pageHeight": PAGE_H,
        "markerMargin": MARKER_MARGIN,
        "markerSize": MARKER_SIZE,
        "questionCount": QUESTION_COUNT,
        "questions": questions,
    }


def build_v2_template() -> dict[str, object]:
    questions = []
    for question_no in range(1, QUESTION_COUNT + 1):
        column_x, y = v2_question_position(question_no)
        options = {
            key: v2_option_box(column_x + offset, y)
            for key, offset in V2_OPTION_OFFSETS.items()
        }
        questions.append({"questionNo": question_no, "options": options})
    return {
        "templateCode": "OMR_SURVEY_V2",
        "pageWidth": PAGE_W,
        "pageHeight": PAGE_H,
        "markerMargin": V2_MARKER_MARGIN,
        "markerSize": V2_MARKER_SIZE,
        "markerType": "ARUCO_4X4_50",
        "markerIds": V2_MARKER_IDS,
        "questionCount": QUESTION_COUNT,
        "questions": questions,
    }


def draw_blank() -> Image.Image:
    image = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(image)
    draw_markers(draw)
    draw.text((260, 230), "Turk Kizilay Demo Anket Formu", fill="black", font=font(62))
    draw.text((260, 325), "Daireleri kursun kalemle tamamen doldurun. Kisisel bilgi yazmayin.", fill="black", font=font(36))
    draw.text((260, 430), "Secenekler", fill="black", font=font(34))

    for column_x in (LEFT_X, RIGHT_X):
        for key, offset in OPTION_OFFSETS.items():
            cx = column_x + offset
            draw.text((cx - 82, 600), LABELS[key], fill="black", font=font(28))

    for question_no in range(1, QUESTION_COUNT + 1):
        column_x, y = question_position(question_no)
        draw.text((column_x, y - 24), f"{question_no}. Soru metni", fill="black", font=font(32))
        for offset in OPTION_OFFSETS.values():
            cx = column_x + offset
            draw.ellipse((cx - RADIUS, y - RADIUS, cx + RADIUS, y + RADIUS), outline="black", width=6)
    return image


def draw_blank_v2() -> Image.Image:
    image = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(image)
    draw_aruco_markers(image)
    draw.text((260, 215), "Profesyonel OMR Anket Formu V2", fill="black", font=font(66))
    draw.text((260, 315), "Daireleri tamamen doldurun. Kose markerlarini kesmeyin.", fill="black", font=font(36))
    draw.text((260, 420), "Sablon: OMR_SURVEY_V2", fill="black", font=font(30))

    for column_x in (V2_LEFT_X, V2_RIGHT_X):
        for key, offset in V2_OPTION_OFFSETS.items():
            cx = column_x + offset
            draw.text((cx - 90, 620), LABELS[key], fill="black", font=font(30))

    for question_no in range(1, QUESTION_COUNT + 1):
        column_x, y = v2_question_position(question_no)
        draw.text((column_x, y - 24), f"{question_no}. Soru metni", fill="black", font=font(34))
        for offset in V2_OPTION_OFFSETS.values():
            cx = column_x + offset
            draw.ellipse((cx - V2_RADIUS, y - V2_RADIUS, cx + V2_RADIUS, y + V2_RADIUS), outline="black", width=7)
    return image


def draw_markers(draw: ImageDraw.ImageDraw) -> None:
    positions = [
        (MARKER_MARGIN, MARKER_MARGIN),
        (PAGE_W - MARKER_MARGIN - MARKER_SIZE, MARKER_MARGIN),
        (PAGE_W - MARKER_MARGIN - MARKER_SIZE, PAGE_H - MARKER_MARGIN - MARKER_SIZE),
        (MARKER_MARGIN, PAGE_H - MARKER_MARGIN - MARKER_SIZE),
    ]
    for x, y in positions:
        draw.rectangle((x, y, x + MARKER_SIZE, y + MARKER_SIZE), fill="black")


def draw_aruco_markers(image: Image.Image) -> None:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    positions = {
        "topLeft": (V2_MARKER_MARGIN, V2_MARKER_MARGIN),
        "topRight": (PAGE_W - V2_MARKER_MARGIN - V2_MARKER_SIZE, V2_MARKER_MARGIN),
        "bottomRight": (PAGE_W - V2_MARKER_MARGIN - V2_MARKER_SIZE, PAGE_H - V2_MARKER_MARGIN - V2_MARKER_SIZE),
        "bottomLeft": (V2_MARKER_MARGIN, PAGE_H - V2_MARKER_MARGIN - V2_MARKER_SIZE),
    }
    for key, (x, y) in positions.items():
        marker = cv2.aruco.generateImageMarker(dictionary, V2_MARKER_IDS[key], V2_MARKER_SIZE)
        marker_image = Image.fromarray(marker).convert("RGB")
        image.paste(marker_image, (x, y))


def fill_form(answers: dict[int, str | list[str]], faint: set[int] | None = None, erased: set[int] | None = None) -> Image.Image:
    image = draw_blank()
    draw = ImageDraw.Draw(image)
    faint = faint or set()
    erased = erased or set()
    for question_no, answer in answers.items():
        selected = answer if isinstance(answer, list) else [answer]
        column_x, y = question_position(question_no)
        for option in selected:
            if option == "BLANK":
                continue
            cx = column_x + OPTION_OFFSETS[option]
            if question_no in faint:
                fill = (205, 205, 205)
            else:
                fill = "black"
            draw.ellipse((cx - RADIUS + 8, y - RADIUS + 8, cx + RADIUS - 8, y + RADIUS - 8), fill=fill)
            if question_no in erased:
                draw.ellipse((cx - 22, y - 22, cx + 22, y + 22), fill=(230, 230, 230))
                draw.line((cx - 42, y + 34, cx + 42, y - 34), fill=(165, 165, 165), width=8)
    return image


def fill_form_v2(answers: dict[int, str | list[str]], faint: set[int] | None = None, erased: set[int] | None = None) -> Image.Image:
    image = draw_blank_v2()
    draw = ImageDraw.Draw(image)
    faint = faint or set()
    erased = erased or set()
    for question_no, answer in answers.items():
        selected = answer if isinstance(answer, list) else [answer]
        column_x, y = v2_question_position(question_no)
        for option in selected:
            if option == "BLANK":
                continue
            cx = column_x + V2_OPTION_OFFSETS[option]
            fill = (205, 205, 205) if question_no in faint else "black"
            draw.ellipse((cx - V2_RADIUS + 10, y - V2_RADIUS + 10, cx + V2_RADIUS - 10, y + V2_RADIUS - 10), fill=fill)
            if question_no in erased:
                draw.ellipse((cx - 26, y - 26, cx + 26, y + 26), fill=(230, 230, 230))
                draw.line((cx - 48, y + 38, cx + 48, y - 38), fill=(165, 165, 165), width=9)
    return image


def base_answers() -> dict[int, str]:
    cycle = ["NEVER", "SOMETIMES", "ALWAYS"]
    return {question_no: cycle[(question_no - 1) % 3] for question_no in range(1, QUESTION_COUNT + 1)}


def add_shadow(image: Image.Image) -> Image.Image:
    shadow = Image.new("L", image.size, 255)
    pixels = shadow.load()
    for y in range(image.height):
        for x in range(image.width):
            shade = int(255 - 70 * (x / image.width) * (y / image.height))
            pixels[x, y] = shade
    output = image.copy()
    output.putalpha(shadow)
    background = Image.new("RGB", image.size, (245, 245, 245))
    background.paste(output, mask=output.getchannel("A"))
    return background


def perspective(image: Image.Image) -> Image.Image:
    source = np.float32([[0, 0], [PAGE_W, 0], [PAGE_W, PAGE_H], [0, PAGE_H]])
    target = np.float32([[130, 60], [PAGE_W - 220, 160], [PAGE_W - 80, PAGE_H - 210], [250, PAGE_H - 80]])
    coeffs = _perspective_coefficients(target, source)
    return image.transform((PAGE_W, PAGE_H), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC, fillcolor="white")


def _perspective_coefficients(pa: np.ndarray, pb: np.ndarray) -> list[float]:
    matrix = []
    vector = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0] * p1[0], -p2[0] * p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1] * p1[0], -p2[1] * p1[1]])
        vector.extend([p2[0], p2[1]])
    return np.linalg.solve(np.array(matrix, dtype=float), np.array(vector, dtype=float)).tolist()


def save_all() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    template = build_template()
    TEMPLATE_PATH.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")

    blank = draw_blank()
    blank.save(SAMPLES / "blank-form.png")
    blank.save(SAMPLES / "blank-form.pdf", "PDF", resolution=300.0)

    clean_answers = base_answers()
    variants: dict[str, Image.Image] = {
        "filled-clean.png": fill_form(clean_answers),
    }

    with_blanks = dict(clean_answers)
    with_blanks[4] = "BLANK"
    with_blanks[19] = "BLANK"
    variants["filled-with-blanks.png"] = fill_form(with_blanks)

    double_mark = dict(clean_answers)
    double_mark[7] = ["NEVER", "SOMETIMES"]
    variants["filled-double-mark.png"] = fill_form(double_mark)

    variants["filled-faint-marks.png"] = fill_form(clean_answers, faint={5})
    variants["filled-erased-mark.png"] = fill_form(clean_answers, erased={8})
    variants["filled-perspective.png"] = perspective(variants["filled-clean.png"])
    variants["filled-shadow.png"] = add_shadow(variants["filled-clean.png"])
    variants["filled-blurry.png"] = variants["filled-clean.png"].filter(ImageFilter.GaussianBlur(radius=5))

    for name, image in variants.items():
        image.save(SAMPLES / name)

    expected = {
        "filled-clean.png": {str(k): v for k, v in clean_answers.items()},
        "filled-with-blanks.png": {str(k): v for k, v in with_blanks.items()},
        "filled-double-mark.png": {str(k): ("DOUBLE_MARK" if k == 7 else v) for k, v in clean_answers.items()},
        "filled-faint-marks.png": {str(k): v for k, v in clean_answers.items()},
        "filled-erased-mark.png": {str(k): v for k, v in clean_answers.items()},
    }
    (SAMPLES / "expected-results.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")

    save_v2()


def save_v2() -> None:
    blank = draw_blank_v2()
    blank.save(SAMPLES / "blank-form-v2.png")
    blank.save(SAMPLES / "blank-form-v2.pdf", "PDF", resolution=300.0)

    clean_answers = base_answers()
    fill_form_v2(clean_answers).save(SAMPLES / "filled-clean-v2.png")
    fill_form_v2(clean_answers, faint={5, 14}).save(SAMPLES / "filled-faint-v2.png")


if __name__ == "__main__":
    save_all()
