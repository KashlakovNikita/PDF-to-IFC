"""Ш0 (дорожная карта): разведка исходного PDF — что в нём вообще лежит.

Это НЕ экстрактор. Задача скрипта — ответить на вопросы, от которых зависят
решения по экстракторам (задачи 12-20), фактами из файла, а не догадками:

1. Сколько страниц какого типа (план / профиль / спецификация / ведомость /
   общие данные) — по ключевым словам в тексте страницы.
2. Векторный слой или скан: сколько на странице векторных путей и сколько
   растровых изображений. Если путей тысячи, а картинок нет — это печать из
   CAD, и координаты берутся из content stream, а не через OCR (поправка 3.2
   дорожной карты).
3. Есть ли на листе ШРИФТЫ. Это отдельный от п.2 вопрос и, как показал прогон,
   решающий: чертёж может быть векторным, но с текстом, переведённым в кривые
   при печати. Тогда путей десятки тысяч, а извлекаемого текста ноль — ни
   марок узлов, ни отметок, ни диаметров с выносок взять из PDF нельзя, и
   поправка 3.2 дорожной карты («берём текст с позициями из content stream»)
   на таких листах не работает.
4. Сохранились ли слои (OCG) с именами слоёв AutoCAD.
5. **Главный вопрос для сверки с эталоном**: в какой системе координат план.
   Эталонный IFC — в местной системе (X ~ 116000-116900, Y ~ 110200-110500).
   Скрипт ищет в тексте страниц числа, попадающие в эти диапазоны: подписи
   координатной сетки, если они есть, выглядят именно так. Если такие числа
   находятся — координаты плана можно сверять с эталоном напрямую; если нет —
   между планом и эталоном потребуется привязка, и до неё validate_geometry.py
   будет показывать расхождение из-за смещения систем координат, а не из-за
   ошибок геометрии.

Запуск:

    python scripts/inspect_pdf.py
    python scripts/inspect_pdf.py --pdf "data/raw/Раздел РД №1_ТС_Парнас_Проект.pdf" --pages 1-20
"""

from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = REPO_ROOT / "data" / "raw" / "Раздел РД №1_ТС_Парнас_Проект.pdf"

# Диапазоны координат эталонного IFC (data/raw/ПРНС_...I2300.ifc), м.
# Числа с запасом: интересует не точное попадание, а порядок величины.
REFERENCE_X_RANGE = (110_000.0, 120_000.0)
REFERENCE_Y_RANGE = (105_000.0, 115_000.0)

SHEET_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "план": ("план трассы", "план сети", "план м 1:", "ситуационный план"),
    "профиль": ("продольный профиль", "профиль трассы"),
    "спецификация": ("спецификация",),
    "ведомость": ("ведомость",),
    "общие данные": ("общие данные", "общие указания"),
    "схема": ("схема",),
}

NUMBER_RE = re.compile(r"\d{5,6}(?:[.,]\d+)?")


def classify_sheet(text: str) -> List[str]:
    lowered = text.lower()
    return [name for name, keys in SHEET_KEYWORDS.items() if any(k in lowered for k in keys)]


def coordinate_candidates(text: str) -> Tuple[List[float], List[float]]:
    """Числа из текста страницы, похожие на подписи координатной сетки МСК."""
    x_values, y_values = [], []
    for token in NUMBER_RE.findall(text):
        value = float(token.replace(",", "."))
        if REFERENCE_X_RANGE[0] <= value <= REFERENCE_X_RANGE[1]:
            x_values.append(value)
        if REFERENCE_Y_RANGE[0] <= value <= REFERENCE_Y_RANGE[1]:
            y_values.append(value)
    return x_values, y_values


def parse_pages(spec: Optional[str], page_count: int) -> range:
    if not spec:
        return range(page_count)
    first, _, last = spec.partition("-")
    start = int(first) - 1
    stop = int(last) if last else int(first)
    return range(max(start, 0), min(stop, page_count))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--pages", help="диапазон страниц, например 1-20 (по умолчанию все)")
    parser.add_argument("--max-rows", type=int, default=60, help="сколько страниц печатать построчно")
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"Файл не найден: {args.pdf}")
        print("Исходный PDF лежит в data/raw/ и в .gitignore — проверьте, что он есть на диске.")
        return 2

    document = fitz.open(args.pdf)
    pages = parse_pages(args.pages, document.page_count)

    print(f"Файл: {args.pdf}")
    print(f"Страниц: {document.page_count}, разбирается: {len(pages)}")
    layers = document.get_layers()
    print(f"Слои (OCG): {len(layers)}" + (f" — {[l.get('name') for l in layers]}" if layers else ""))
    print()

    kinds = collections.Counter()
    rows = []
    all_x, all_y = [], []
    pages_with_coordinates = []
    vectorized_text_pages: List[int] = []

    for number in pages:
        page = document[number]
        text = page.get_text()
        drawings = len(page.get_drawings())
        images = len(page.get_images(full=True))
        kind = classify_sheet(text)
        for k in kind or ["не опознан"]:
            kinds[k] += 1

        x_values, y_values = coordinate_candidates(text)
        if x_values or y_values:
            pages_with_coordinates.append(number + 1)
            all_x += x_values
            all_y += y_values

        width_mm = page.rect.width / 72 * 25.4
        height_mm = page.rect.height / 72 * 25.4
        fonts = len(page.get_fonts(full=True))
        if drawings > 1000 and fonts == 0:
            vectorized_text_pages.append(number + 1)
        rows.append(
            (number + 1, f"{width_mm:.0f}x{height_mm:.0f}", drawings, images, fonts,
             len(text), ",".join(kind) or "-", len(x_values), len(y_values))
        )

    print(f"{'стр':>4} {'формат,мм':>10} {'путей':>7} {'растр':>6} {'шрифт':>6} {'текст':>7} "
          f"{'тип листа':<24} {'X~МСК':>6} {'Y~МСК':>6}")
    for row in rows[: args.max_rows]:
        print(f"{row[0]:>4} {row[1]:>10} {row[2]:>7} {row[3]:>6} {row[4]:>6} {row[5]:>7} "
              f"{row[6]:<24} {row[7]:>6} {row[8]:>6}")
    if len(rows) > args.max_rows:
        print(f"... ещё {len(rows) - args.max_rows} страниц (увеличьте --max-rows)")

    print()
    print("Типы листов:", dict(kinds))
    print()
    print("Текст в кривых (листы с тысячами путей и без единого шрифта):")
    if vectorized_text_pages:
        print(f"  страницы: {vectorized_text_pages}")
        print("  => на этих листах извлекаемого текста нет вообще: марки узлов, отметки,")
        print("     диаметры с выносок в PDF лежат как контуры букв, а не как текст.")
        print("     Значит, для планов и профилей нужен либо DWG (там текст остался текстом),")
        print("     либо распознавание по векторному слою — «текст с позициями из")
        print("     content stream» (поправка 3.2 дорожной карты) здесь не сработает.")
    else:
        print("  таких листов не найдено — текст на чертежах извлекается штатно.")
    print()
    print("Координатная сетка (главный вопрос Ш0):")
    if all_x or all_y:
        print(f"  найдены числа в диапазонах эталона на страницах: {pages_with_coordinates}")
        if all_x:
            print(f"  похожих на X: {len(all_x)}, от {min(all_x):.1f} до {max(all_x):.1f}")
        if all_y:
            print(f"  похожих на Y: {len(all_y)}, от {min(all_y):.1f} до {max(all_y):.1f}")
        print("  => координаты плана, похоже, в той же местной системе, что и эталонный IFC;")
        print("     это надо подтвердить глазами по самому листу перед тем, как на это опираться.")
    else:
        print("  чисел, похожих на подписи координатной сетки МСК, в тексте не найдено.")
        print("  => привязка плана к системе координат эталона не выводится из текста PDF;")
        print("     до её появления сверка координат с эталоном покажет расхождение")
        print("     из-за смещения систем координат, а не из-за ошибок геометрии.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
