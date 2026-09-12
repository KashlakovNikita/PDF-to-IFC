# -*- coding: utf-8 -*-
"""Задача 25: можно ли достать текст с листов плана и профиля из data/raw/*.pdf.

Скрипт НЕ парсер спецификации и не трогает геометрию. Он меряет, сколько
текста и с какой точностью снимается с листов, где текст переведён в кривые,
двумя способами:

  1. OCR (pytesseract/tesseract) по растрированной странице — свипы по DPI,
     psm и повороту;
  2. векторный разбор — см. scripts/research_pdf_glyphs.py: контуры глифов из
     content stream сопоставляются с контурами шрифта чертежа (ISOCPEUR,
     встроен в этот же PDF на листах спецификаций).

Точность считается по четырём фрагментам с эталоном, вычитанным глазами с
рендера 200-600 dpi (см. FRAGMENTS): таблица спецификации на узел "А",
отметки продольного профиля, выноски узлов на плане и плотная зона плана с
подписями существующих сетей.

Запуск:

    python scripts/research_pdf_text.py ocr --json tmp/ocr/ocr_sweep.json
    python scripts/research_pdf_text.py render --dpi 300
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import fitz  # PyMuPDF

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = REPO_ROOT / "data" / "raw" / "Раздел РД №1_ТС_Парнас_Проект.pdf"
OUT_DIR = REPO_ROOT / "tmp" / "ocr"

# Tesseract стоит в системе, но не в PATH, и в комплекте у него только eng+osd.
# rus.traineddata (tessdata_best) скачан отдельно в tmp/ocr/tessdata — см. отчёт.
TESSERACT_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA_DIR = OUT_DIR / "tessdata"


@dataclass
class Fragment:
    key: str
    title: str
    page: int  # 1-based
    bbox: Tuple[float, float, float, float]
    truth: List[str]  # эталонные токены, вычитаны глазами с рендера
    note: str = ""


FRAGMENTS: List[Fragment] = [
    Fragment(
        key="f1_spec",
        title="Спецификация на узел А (лист 7, узел УТ-1)",
        page=11,
        bbox=(1252, 325, 1612, 597),
        note="горизонтальный текст, крупный, на чистом белом фоне — лучший случай",
        truth=(
            "п/п Обозначение Наименование Ед. изм. Кол-во".split()
            + "1 Полоса 40х4,0 ГОСТ 103-76 Ст3 ГОСТ 380-88 Хомут стяжной м 1,6".split()
            + "2 Лист 0,8 ГОСТ 8075-56 Ст3 ГОСТ 380-88 Козырек м2 0,8".split()
            + "3 Лист 3 ГОСТ 19903-74 Ст3 ГОСТ 380-71 Фартук м2 0,226".split()
            + "4 Лист 10 ГОСТ 19903-74 Ст3 ГОСТ 380-71 Плита перекрытия м2 1,90".split()
            + "5 ГОСТ 5915-70 Гайка М14 шт. 2".split()
            + "6 ГОСТ 7798-70 Болт М14х45 шт. 4".split()
            + "7 ГОСТ 28961-91 Шайба 12 шт. 4".split()
        ),
    ),
    Fragment(
        key="f2_profile",
        title="Отметки продольного профиля (лист 5, левая часть таблицы)",
        page=9,
        bbox=(1150, 595, 1800, 898),
        note="числа повёрнуты на 90°, шаг строк плотный — основной рабочий случай",
        truth=(
            "4,00 22,20 14,14 1,03 4,97 1,00 4,50 30,67 30,49".split()
            + "27,91 28,06 27,89 27,73 27,72 27,72 27,87".split()
            + "27,91 28,06 27,89 27,73 27,72 27,72 27,87".split()
            + "27,31 27,29 27,15 27,07 26,99 26,95 27,00 26,82".split()
            + "28,83 26,87 26,85 26,71 26,63 26,59 26,56 26,38".split()
            + "26,40 26,38 26,24 26,16 26,27 26,23 26,09 25,91".split()
            + "82,00 6 62,42".split()
        ),
    ),
    Fragment(
        key="f3a_plan_labels",
        title="Выноски узлов на плане (лист 2, район ТК-3)",
        page=6,
        bbox=(850, 455, 1165, 545),
        note="горизонтальные выноски на чистом фоне — то, что реально нужно парсеру",
        truth="ТК-3 Граница проектирования ДК13 Т1, Т2 Ф325х8,0/450-ППУ 7".split(),
    ),
    Fragment(
        key="f3b_plan_dense",
        title="Плотная зона плана: подписи существующих сетей (лист 2)",
        page=6,
        bbox=(772, 466, 868, 552),
        note="текст повёрнут на ~40°, поверх цветных линий подосновы",
        truth="ст.57 ст.108 пар конд. плм 150 2 ст.325 27.42".split(),
    ),
    Fragment(
        key="f4_scan",
        title="Технические условия, строки 1-9 таблицы (скан, стр. 30)",
        page=30,
        bbox=(45, 88, 585, 292),
        note="контрольный фрагмент: обычный наборный текст в скане, "
             "не чертёж — показывает, что OCR настроен верно",
        truth=(
            "1 Основание для проектирования".split()
            + "Адресная инвестиционная программа г. Санкт-Петербурга.".split()
            + "2 Заказчик СПб ГКУ «Управление заказчика»".split()
            + "3 Генпроектировщик По результатам конкурсных процедур".split()
            + "4 Генподрядчик По результатам конкурсных процедур".split()
            + "5 Вид строительства Реконструкция".split()
            + "6 Особые условия строительства".split()
            + "В условиях действующего предприятия".split()
            + "7 Источник финансирования Бюджет Санкт-Петербурга".split()
            + "8 Стадийность проектирования".split()
            + "Проектная и рабочая документации".split()
            + "9 Требования к вариантной и конкурсной разработке".split()
            + "Не требуется".split()
        ),
    ),
]

FRAG_BY_KEY = {f.key: f for f in FRAGMENTS}


# --------------------------------------------------------------------------
# нормализация и метрика
# --------------------------------------------------------------------------

# Кириллица/латиница, неразличимые в начертании. tesseract с rus+eng регулярно
# отдаёт латинского близнеца; для разбора чертежа это одно и то же, поэтому
# точность считается в двух режимах — строгом и с приведением близнецов.
HOMOGLYPHS = str.maketrans({
    "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О",
    "P": "Р", "C": "С", "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х",
})


def norm_token(tok: str) -> str:
    """Мягкая нормализация: близнецы, тире, десятичный разделитель."""
    t = unicodedata.normalize("NFKC", tok)
    t = t.translate(HOMOGLYPHS)
    for dash in ("\u2013", "\u2014", "\u2212", "\u2012"):
        t = t.replace(dash, "-")
    t = t.replace(".", ",")  # 27.42 и 27,42 — одно число
    return t


def tokenize(text: str) -> List[str]:
    return [t for t in text.split() if t.strip()]


def match_tokens(truth: Sequence[str], got: Sequence[str], normalize: bool) -> dict:
    """Мультимножественное сопоставление без учёта порядка.

    Порядок чтения OCR на чертеже произвольный, поэтому CER по склеенной
    строке неинформативен: считаем, сколько эталонных токенов найдено.
    """
    key = norm_token if normalize else (lambda s: s)
    pool: Dict[str, int] = {}
    for t in got:
        k = key(t)
        pool[k] = pool.get(k, 0) + 1
    matched = 0
    missed: List[str] = []
    for t in truth:
        k = key(t)
        if pool.get(k, 0) > 0:
            pool[k] -= 1
            matched += 1
        else:
            missed.append(t)
    spurious = sum(pool.values())
    recall = matched / len(truth) if truth else 0.0
    precision = matched / len(got) if got else 0.0
    return {
        "matched": matched,
        "truth_n": len(truth),
        "got_n": len(got),
        "recall": recall,
        "precision": precision,
        "missed": missed,
        "spurious": spurious,
    }


# --------------------------------------------------------------------------
# рендер фрагментов
# --------------------------------------------------------------------------

def render(frag: Fragment, dpi: int, pdf: Path, rotate: int = 0) -> Path:
    doc = fitz.open(pdf)
    page = doc[frag.page - 1]
    z = dpi / 72.0
    mat = fitz.Matrix(z, z)
    if rotate:
        mat = mat * fitz.Matrix(rotate)
    pix = page.get_pixmap(matrix=mat, clip=fitz.Rect(*frag.bbox))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_rot%d" % rotate if rotate else ""
    out = OUT_DIR / ("%s_%d%s.png" % (frag.key, dpi, suffix))
    pix.save(out)
    doc.close()
    return out


# --------------------------------------------------------------------------
# подход 1: OCR
# --------------------------------------------------------------------------

def run_tesseract(img: Path, psm: int, lang: str = "rus+eng") -> str:
    cmd = [
        str(TESSERACT_EXE), str(img), "stdout",
        "-l", lang, "--psm", str(psm),
        "--tessdata-dir", str(TESSDATA_DIR),
    ]
    env = dict(os.environ, TESSDATA_PREFIX=str(TESSDATA_DIR))
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600, env=env)
        return r.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return ""


def sweep_ocr(pdf: Path, dpis: Sequence[int], psms: Sequence[int],
              keys: Sequence[str] | None = None) -> List[dict]:
    rows = []
    frags = [f for f in FRAGMENTS if not keys or f.key in keys]
    for frag in frags:
        # профиль подписан вертикально: поворот листа — штатный приём, меряем оба
        rotations = (0, 90) if frag.key == "f2_profile" else (0,)
        for dpi in dpis:
            for rot in rotations:
                img = render(frag, dpi, pdf, rotate=rot)
                for psm in psms:
                    txt = run_tesseract(img, psm)
                    got = tokenize(txt)
                    strict = match_tokens(frag.truth, got, normalize=False)
                    soft = match_tokens(frag.truth, got, normalize=True)
                    rows.append({
                        "frag": frag.key, "dpi": dpi, "rot": rot, "psm": psm,
                        "strict_recall": strict["recall"],
                        "soft_recall": soft["recall"],
                        "soft_precision": soft["precision"],
                        "matched": soft["matched"], "truth_n": soft["truth_n"],
                        "got_n": soft["got_n"], "spurious": soft["spurious"],
                        "missed": soft["missed"],
                        "raw": txt,
                    })
                    print("%-18s dpi=%-4d rot=%-3d psm=%-3d strict=%5.1f%%  soft=%5.1f%%  (%d/%d, лишних %d)"
                          % (frag.key, dpi, rot, psm,
                             strict["recall"] * 100, soft["recall"] * 100,
                             soft["matched"], soft["truth_n"], soft["spurious"]),
                          flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["ocr", "render"])
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--dpi", type=int, nargs="*", default=[150, 300, 600])
    ap.add_argument("--psm", type=int, nargs="*", default=[6, 11])
    ap.add_argument("--frag", nargs="*", default=None)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()

    if a.mode == "render":
        for f in FRAGMENTS:
            if a.frag and f.key not in a.frag:
                continue
            for dpi in a.dpi:
                print(render(f, dpi, a.pdf))
        return 0

    rows = sweep_ocr(a.pdf, a.dpi, a.psm, a.frag)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print("\nJSON:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
