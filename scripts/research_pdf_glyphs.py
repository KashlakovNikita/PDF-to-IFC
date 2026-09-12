# -*- coding: utf-8 -*-
"""Задача 25, подход 2: распознавание текста-в-кривых без OCR.

На листах плана и профиля (стр. 4-14) текста в PDF нет: он переведён в кривые
при печати из CAD. Но кривые — не произвольные. Это обводка конкретного
шрифта чертежа (ISOCPEUR), и этот же шрифт лежит встроенным в этом же файле
на листах спецификаций (стр. 1, 3, 15, 20). Значит, глифы можно не «узнавать»
статистически, как это делает OCR, а сопоставлять с эталонными контурами.

Что делает скрипт:

  1. достаёт из content stream залитые пути (get_drawings, тип "f") внутри
     фрагмента; на этих листах каждая буква нарисована НЕСКОЛЬКИМИ заливками —
     по одной на штрих, поэтому штрихи собираются в глифы по пересечению
     bbox (связные компоненты);
  2. глифы группируются в строки по базовой линии, строки — в слова по
     величине зазора;
  3. каждый глиф растрируется в нормированный битмап: масштаб берётся от
     высоты прописной буквы в строке, посадка — от базовой линии, поэтому
     «о» и «О» не сливаются;
  4. эталоны — глифы ISOCPEUR Italic, отрисованные в ту же сетку (полный
     шрифт из установки AutoCAD либо неполное подмножество из самого PDF);
  5. совпадение считается по XOR-расстоянию с поиском сдвига +-2 px и с
     подбором ширинного коэффициента (в CAD у текстового стиля он обычно не 1).

Запуск:

    python scripts/research_pdf_glyphs.py --frag f1_spec
    python scripts/research_pdf_glyphs.py --all --json tmp/ocr/glyph_result.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_pdf_text import (  # noqa: E402
    DEFAULT_PDF, FRAGMENTS, FRAG_BY_KEY, OUT_DIR, match_tokens, tokenize,
)

# Шрифт чертежа. Полный ISOCPEUR Italic ставится вместе с AutoCAD; подмножество,
# встроенное в сам PDF на листах спецификаций, неполное (нет Й, Х, Ъ, Ы, Ю) —
# оба варианта меряются отдельно, см. отчёт.
FONT_SYSTEM = Path(r"C:\Windows\Fonts\isocpeui.ttf")
FONT_EMBEDDED = OUT_DIR / "fonts" / "ISOCPEURItalic_p15.ttf"
FONT_PATH = FONT_SYSTEM if FONT_SYSTEM.exists() else FONT_EMBEDDED

# сетка нормировки глифа
CELL_W, CELL_H = 40, 40
CAP_PX = 24        # высота прописной в сетке
BASE_Y = 32        # базовая линия в сетке
LEFT_X = 8         # левый край глифа в сетке
WIDTH_FACTORS = (0.7, 0.8, 0.9, 1.0, 1.1)

# Алфавит чертежа. Полный ISOCPEUR несёт 600+ глифов, включая сербские и
# македонские (Ј, Ѕ, Џ, Ћ), неотличимые от латинских и кириллических и потому
# перехватывающие совпадения. На листах ТС встречается только это:
CHARSET = (
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "абвгдежзийклмнопрстуфхцчшщъыьэюя"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    ".,:;-+=/()[]%<>*\"'#^~&@!?_|"
    "№°ø–—Ø"
)


# --------------------------------------------------------------------------
# 1. пути -> глифы
# --------------------------------------------------------------------------

@dataclass
class Glyph:
    polys: List[List[Tuple[float, float]]]
    x0: float
    y0: float
    x1: float
    y1: float
    char: str = ""
    score: float = 0.0

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0


def _subpaths(path: dict, mat: fitz.Matrix) -> List[List[Tuple[float, float]]]:
    """Ломаные пути в отображаемых координатах (страница повёрнута)."""
    out: List[List[Tuple[float, float]]] = []
    cur: List[Tuple[float, float]] = []
    prev = None
    for it in path["items"]:
        if it[0] != "l":
            continue
        a, b = it[1], it[2]
        if prev is None or abs(a.x - prev.x) > 1e-6 or abs(a.y - prev.y) > 1e-6:
            if len(cur) >= 3:
                out.append(cur)
            pa = a * mat
            cur = [(pa.x, pa.y)]
        pb = b * mat
        cur.append((pb.x, pb.y))
        prev = b
    if len(cur) >= 3:
        out.append(cur)
    return out


def collect_glyphs(page: fitz.Page, clip_display: fitz.Rect,
                   max_glyph_pt: float = 30.0, rotate: int = 0) -> List[Glyph]:
    """Залитые пути внутри фрагмента, собранные в глифы.

    rotate — доворот фрагмента в читаемое положение: на профиле отметки
    подписаны вертикально, и без доворота они разбираются как строка из
    одной буквы.
    """
    uclip = clip_display * page.derotation_matrix
    uclip.normalize()
    rot = page.rotation_matrix
    if rotate:
        rot = rot * fitz.Matrix(rotate)

    items = []
    for p in page.get_drawings():
        if p["type"] != "f":
            continue
        if not uclip.contains(p["rect"]):
            continue
        r = p["rect"]
        # отсечь заливки заведомо не-буквенного размера (рамки, стрелки, штриховка)
        if r.width > max_glyph_pt or r.height > max_glyph_pt:
            continue
        polys = _subpaths(p, rot)
        if not polys:
            continue
        xs = [x for poly in polys for x, _ in poly]
        ys = [y for poly in polys for _, y in poly]
        items.append(Glyph(polys, min(xs), min(ys), max(xs), max(ys)))

    # связные компоненты по пересечению bbox: штрихи одной буквы перекрываются
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    eps = 0.12  # pt: штрихи буквы стыкуются впритык
    order = sorted(range(n), key=lambda i: items[i].x0)
    for ii, i in enumerate(order):
        gi = items[i]
        for j in order[ii + 1:]:
            gj = items[j]
            if gj.x0 > gi.x1 + eps:
                break
            if (gi.x0 - eps <= gj.x1 and gj.x0 - eps <= gi.x1
                    and gi.y0 - eps <= gj.y1 and gj.y0 - eps <= gi.y1):
                union(i, j)

    groups: Dict[int, List[Glyph]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i])

    glyphs = []
    for parts in groups.values():
        polys = [p for g in parts for p in g.polys]
        glyphs.append(Glyph(
            polys,
            min(g.x0 for g in parts), min(g.y0 for g in parts),
            max(g.x1 for g in parts), max(g.y1 for g in parts),
        ))
    return glyphs


# --------------------------------------------------------------------------
# 2. строки и слова
# --------------------------------------------------------------------------

LINE_TOL = 0.35  # доля медианной высоты глифа


def group_lines(glyphs: Sequence[Glyph], tol_frac: float = LINE_TOL) -> List[List[Glyph]]:
    """Строки по низу bbox (базовой линии).

    Допуск подобран прогоном (см. отчёт): он должен быть больше нижнего
    выноса у «р», «у», «щ» — иначе они отрываются в отдельную строку, — но
    меньше расстояния между строками дроби в спецификации, иначе числитель и
    знаменатель сливаются и обе строки распознаются мусором. Кластеризация по
    вертикальному перекрытию bbox, которая напрашивается первой, здесь не
    работает именно из-за дробей: их строки перекрываются.
    """
    if not glyphs:
        return []
    hs = sorted(g.h for g in glyphs)
    med_h = hs[len(hs) // 2]
    tol = max(med_h * tol_frac, 0.3)
    lines: List[List[Glyph]] = []
    for g in sorted(glyphs, key=lambda g: (g.y1, g.x0)):
        placed = False
        for ln in lines:
            if abs(ln[0].y1 - g.y1) <= tol:
                ln.append(g)
                placed = True
                break
        if not placed:
            lines.append([g])
    for ln in lines:
        ln.sort(key=lambda g: g.x0)
    lines.sort(key=lambda ln: (ln[0].y1, ln[0].x0))
    return lines


def cut_group(g: Glyph, k: int) -> List[Glyph]:
    """Разрезать группу штрихов на k частей по самым широким просветам.

    Штрих уходит влево или вправо целиком, пересобирать полигоны не нужно.
    """
    if k < 2 or len(g.polys) < k:
        return [g]
    cents = sorted(
        ((sum(x for x, _ in poly) / len(poly), poly) for poly in g.polys),
        key=lambda t: t[0],
    )
    gaps = sorted(
        range(1, len(cents)),
        key=lambda i: cents[i][0] - cents[i - 1][0],
        reverse=True,
    )
    cuts = sorted(gaps[:k - 1])
    if not cuts:
        return [g]
    out: List[Glyph] = []
    prev = 0
    for c in cuts + [len(cents)]:
        chunk = [poly for _, poly in cents[prev:c]]
        prev = c
        if not chunk:
            continue
        xs = [x for poly in chunk for x, _ in poly]
        ys = [y for poly in chunk for _, y in poly]
        out.append(Glyph(chunk, min(xs), min(ys), max(xs), max(ys)))
    return out or [g]


def line_metrics(line: Sequence[Glyph]) -> Tuple[float, float]:
    """Базовая линия (медиана низов) и высота прописной."""
    bottoms = sorted(g.y1 for g in line)
    base = bottoms[len(bottoms) // 2]
    heights = sorted(base - g.y0 for g in line)
    cap = heights[int(len(heights) * 0.9)] if heights else 1.0
    return base, max(cap, 1e-3)


# --------------------------------------------------------------------------
# 3. растеризация
# --------------------------------------------------------------------------

def raster_glyph(g: Glyph, base: float, cap: float, ss: int = 3) -> Image.Image:
    """Глиф в нормированную сетку: масштаб от прописной, посадка от базовой."""
    s = CAP_PX / cap
    img = Image.new("1", (CELL_W * ss, CELL_H * ss), 0)
    dr = ImageDraw.Draw(img)
    for poly in g.polys:
        pts = [((x - g.x0) * s + LEFT_X) * ss for x, _ in poly]
        ys = [((y - base) * s + BASE_Y) * ss for _, y in poly]
        dr.polygon(list(zip(pts, ys)), fill=1)
    return img.resize((CELL_W, CELL_H), Image.BILINEAR)


def raster_font(font_path: Path, ch: str, width_factor: float,
                cache: dict) -> Image.Image | None:
    """Эталонный глиф в той же сетке.

    Важно: PIL сажает текст по перу (origin), а не по краю краски. У наклонного
    шрифта левый вынос (lsb) у каждой буквы свой, поэтому после отрисовки глиф
    доводится по левому краю краски — иначе «О» уезжает вправо и опознаётся
    как «З», а «Т» как «Г».
    """
    key = (ch, width_factor)
    if key in cache:
        return cache[key]
    px = cache.get("_size")
    if px is None:
        px = _font_size_for_cap(font_path, CAP_PX)
        cache["_size"] = px
    ss = 3
    pad = CELL_W * ss  # запас слева/справа, чтобы наклон не обрезался
    try:
        font = ImageFont.truetype(str(font_path), int(round(px * ss)))
    except OSError:
        return None
    big = Image.new("L", (CELL_W * ss + 2 * pad, CELL_H * ss), 0)
    dr = ImageDraw.Draw(big)
    try:
        dr.text((pad, BASE_Y * ss), ch, font=font, fill=255, anchor="ls")
    except (ValueError, OSError):
        return None
    if width_factor != 1.0:
        # ширинный коэффициент — сжатие по горизонтали относительно пера
        left = big.crop((pad, 0, big.width, big.height))
        w = max(1, int(left.width * width_factor))
        left = left.resize((w, left.height), Image.BILINEAR)
        big = Image.new("L", big.size, 0)
        big.paste(left, (pad, 0))
    bbox = big.getbbox()
    if bbox is None:
        cache[key] = None
        return None
    # довести краску по левому краю; базовая линия уже на месте
    shift = LEFT_X * ss - bbox[0]
    canvas = Image.new("L", (CELL_W * ss, CELL_H * ss), 0)
    canvas.paste(big, (shift, 0))
    img = canvas.resize((CELL_W, CELL_H), Image.BILINEAR).point(
        lambda v: 255 if v > 90 else 0)
    out = img.convert("1")
    if out.getbbox() is None:
        out = None
    cache[key] = out
    return out


def _font_size_for_cap(font_path: Path, cap_px: int) -> float:
    """Кегль, при котором высота прописной = cap_px."""
    probe = 200
    font = ImageFont.truetype(str(font_path), probe)
    bbox = font.getbbox("Н")  # прописная без выносных
    cap_at_probe = bbox[3] - bbox[1]
    if cap_at_probe <= 0:
        return cap_px
    return probe * cap_px / cap_at_probe


# --------------------------------------------------------------------------
# 4. сопоставление
# --------------------------------------------------------------------------

def to_arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img, dtype=bool)


def _shifted_stack(a: np.ndarray, shifts: int = 2) -> np.ndarray:
    """Все сдвиги глифа одним массивом (n_shifts, H, W)."""
    out = []
    for dy in range(-shifts, shifts + 1):
        for dx in range(-shifts, shifts + 1):
            out.append(np.roll(np.roll(a, dy, axis=0), dx, axis=1))
    return np.stack(out)


def best_match(glyph: np.ndarray, tstack: np.ndarray,
               chars: Sequence[str], shifts: int = 2) -> Tuple[str, float]:
    """XOR-расстояние глифа до всех эталонов сразу.

    Считается векторно: (сдвиги, 1, H, W) против (1, эталоны, H, W). Поэлементный
    цикл на 300 глифов x 160 эталонов x 25 сдвигов шёл минутами.
    """
    g = _shifted_stack(glyph, shifts)[:, None, :, :]
    t = tstack[None, :, :, :]
    union = np.count_nonzero(g | t, axis=(2, 3))
    xor = np.count_nonzero(g ^ t, axis=(2, 3))
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(union > 0, xor / np.maximum(union, 1), 1.0)
    k = int(np.argmin(d))
    i_shift, i_char = divmod(k, d.shape[1])
    return chars[i_char], float(d[i_shift, i_char])


def build_templates(font_path: Path, width_factor: float) -> Dict[str, np.ndarray]:
    from fontTools.ttLib import TTFont
    t = TTFont(str(font_path))
    cmap = t.getBestCmap()
    cache: dict = {}
    out: Dict[str, np.ndarray] = {}
    for code in cmap:
        if code < 32 or code > 0x500:
            continue
        ch = chr(code)
        if ch not in CHARSET:
            continue
        img = raster_font(font_path, ch, width_factor, cache)
        if img is not None:
            out[ch] = to_arr(img)
    return out


def _score_one(g: Glyph, tstack: np.ndarray, chars: Sequence[str],
               base: float, cap: float) -> Tuple[str, float]:
    gi = raster_glyph(g, base, cap)
    if gi.getbbox() is None:
        return "", 1.0
    return best_match(to_arr(gi), tstack, chars)


def recognize(line: List[Glyph], templates: Dict[str, np.ndarray],
              base: float, cap: float) -> List[Glyph]:
    """Опознать глифы строки, при необходимости разрезая слипшиеся.

    Разрез решается не по ширине, а по результату: широкая группа режется
    только если части опознаются увереннее целого. Порог по ширине резал
    заодно и честно широкие буквы (К превращалась в «IQ», Ш в «Ш»+«I»).
    """
    chars = list(templates)
    tstack = np.stack([templates[c] for c in chars])
    # Ожидаемая ширина буквы берётся от высоты прописной, а не от медианы по
    # строке: строка вроде «ТК-3» целиком слипается в одну группу, и медиана
    # тогда равна ширине самой слипшейся группы — разрез не срабатывает.
    exp_w = 0.65 * cap

    out: List[Glyph] = []
    for g in line:
        ch, d = _score_one(g, tstack, chars, base, cap)
        best = ([g], d)
        if exp_w > 0 and g.w > exp_w * 1.35 and len(g.polys) >= 2:
            kmax = min(5, int(round(g.w / exp_w)) + 1)
            for k in range(2, max(3, kmax + 1)):
                if len(g.polys) < k:
                    break
                parts = cut_group(g, k)
                if len(parts) < 2:
                    continue
                scored = [_score_one(p, tstack, chars, base, cap) for p in parts]
                mean_d = sum(sd for _, sd in scored) / len(scored)
                # разрез принимается только при заметном выигрыше
                if mean_d < best[1] - 0.04:
                    for p, (pc, pd) in zip(parts, scored):
                        p.char, p.score = pc, pd
                    best = (parts, mean_d)
        if len(best[0]) == 1:
            g.char, g.score = ch, d
        out.extend(best[0])
    out.sort(key=lambda g: g.x0)
    return out


def assemble(lines: Sequence[Sequence[Glyph]]) -> str:
    out_lines = []
    for ln in lines:
        if not ln:
            continue
        # Пробел в этом шрифте — около половины высоты прописной, а зазоры
        # внутри слова (в том числе вокруг дефиса и запятой) заметно меньше.
        # Порог от медианы зазоров рвал «103-76» на «103- 76», поэтому он
        # считается от кегля строки.
        cap = max(g.h for g in ln)
        thr = cap * 0.45
        buf = [ln[0].char]
        for a, b in zip(ln, ln[1:]):
            if b.x0 - a.x1 > thr:
                buf.append(" ")
            buf.append(b.char)
        out_lines.append("".join(buf))
    return "\n".join(out_lines)


# --------------------------------------------------------------------------

def run_fragment(key: str, pdf: Path, font_path: Path = None,
                 width_factors=WIDTH_FACTORS,
                 orientations=(0, 90)) -> dict:
    """Разобрать фрагмент, перебрав ориентацию и ширинный коэффициент.

    Возвращает две оценки: best_recall — лучшая по эталону (верхняя граница
    метода) и auto — при выборе параметров без эталона, по среднему
    расстоянию совпадения. Для реального парсера значима вторая.
    """
    frag = FRAG_BY_KEY[key]
    font_path = font_path or FONT_PATH
    doc = fitz.open(pdf)
    page = doc[frag.page - 1]

    runs = []
    for orient in orientations:
        glyphs = collect_glyphs(page, fitz.Rect(*frag.bbox), rotate=orient)
        if not glyphs:
            continue
        lines = group_lines(glyphs)
        for wf in width_factors:
            templates = build_templates(font_path, wf)
            rec = []
            for ln in lines:
                base, cap = line_metrics(ln)
                rec.append(recognize(list(ln), templates, base, cap))
            flat = [g for ln in rec for g in ln]
            text = assemble(rec)
            got = tokenize(text)
            soft = match_tokens(frag.truth, got, normalize=True)
            strict = match_tokens(frag.truth, got, normalize=False)
            mean_d = (sum(g.score for g in flat) / len(flat)) if flat else 1.0
            runs.append({
                "frag": key, "orient": orient, "width_factor": wf,
                "font": font_path.name,
                "strict_recall": strict["recall"], "soft_recall": soft["recall"],
                "soft_precision": soft["precision"],
                "matched": soft["matched"], "truth_n": soft["truth_n"],
                "got_n": soft["got_n"], "spurious": soft["spurious"],
                "missed": soft["missed"], "mean_dist": mean_d, "text": text,
                "n_glyphs": len(flat), "n_lines": len(lines),
            })
            print("  поворот=%-3d wf=%.1f: strict=%5.1f%% soft=%5.1f%% (%d/%d), "
                  "ср. расстояние %.3f"
                  % (orient, wf, strict["recall"] * 100, soft["recall"] * 100,
                     soft["matched"], soft["truth_n"], mean_d), flush=True)
    doc.close()
    if not runs:
        return {"frag": key, "soft_recall": 0.0, "matched": 0,
                "truth_n": len(frag.truth), "missed": list(frag.truth),
                "text": "", "note": "залитых путей во фрагменте не найдено"}
    best = max(runs, key=lambda r: r["soft_recall"])
    auto = min(runs, key=lambda r: r["mean_dist"])
    best["auto_soft_recall"] = auto["soft_recall"]
    best["auto_strict_recall"] = auto["strict_recall"]
    best["auto_params"] = {"orient": auto["orient"], "wf": auto["width_factor"]}
    best["auto_text"] = auto["text"]
    print("  -> лучшее по эталону %.1f%%, автовыбор параметров %.1f%% "
          "(поворот=%d, wf=%.1f)"
          % (best["soft_recall"] * 100, auto["soft_recall"] * 100,
             auto["orient"], auto["width_factor"]))
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--frag", nargs="*", default=["f1_spec"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--show", action="store_true", help="печатать распознанный текст")
    ap.add_argument("--font", type=Path, default=None, help="шрифт-эталон (.ttf)")
    a = ap.parse_args()

    keys = [f.key for f in FRAGMENTS] if a.all else a.frag
    rows = []
    for k in keys:
        print(k)
        r = run_fragment(k, a.pdf, a.font)
        rows.append(r)
        if a.show:
            print("--- распознано ---")
            print(r["text"])
            print("--- не найдено:", " | ".join(r["missed"]))
        print()
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print("JSON:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
