"""Задача 31: реальные координаты трассы из DWG (через DXF) вместо placeholder'ов.

Что решает
-----------
До этого скрипта координаты X/Y в проекте были синтетическими: в задаче 4 их
проставили шагом 50 м вдоль прямой, потому что в PDF читаемой координатной сетки
нет (см. Ш0, scripts/inspect_pdf.py). Из-за этого scripts/validate_geometry.py
показывал расхождение с эталоном в 160 км — то есть мерил расстояние между двумя
точками пространства, а не ошибку геометрии.

Заказчик передал исходные DWG (data/reference/dwg). Отсюда берётся:

- координаты узлов — из выносок (MULTILEADER) на листе плана: марка узла
  («ТК-2», «УТ-1а», «Н1», «УК1», «УП2», ...) и точка, на которую указывает
  остриё выноски;
- порядок узлов вдоль трассы — с листа профилей, где марки выписаны подряд по
  ходу трассы (Н1 -> УК1 -> Н2 -> УТ1 -> УП2 -> Н3 -> ... -> ТК-4);
- точки изгиба (waypoints задачи 1 брифа) — вершины нарисованной оси между
  соседними узлами.

Почему координата берётся из острия выноски, а не из положения подписи: подпись
отодвинута от трассы на 10-18 м, и если взять её, узел уедет на всю эту величину.
Порядок вершин выноски в DXF не гарантирован, поэтому берётся та вершина, что
ближе к оси.

Как выбран слой оси
--------------------
Теплосеть нарисована на нескольких слоях, и похожих линий рядом несколько:
`_ПР_Теплосеть` (проектируемая), `32_Теплосеть` (существующая, топооснова),
`_ПР_Теплосеть_1_ВТС` (вынос ВТС). Слой выбран не по названию, а измерением:
осевые линии эталонного IFC (он построен по этому же проекту) легли на
`_ПР_Теплосеть` со 100 % точек ближе 1 м, на `32_Теплосеть` — медиана 0.14 м,
а на `_ПР_Теплосеть_1_ВТС` — 7.86 м, то есть это вообще другая линия. Взят
`_ПР_Теплосеть`: проектируемая сеть, а не топооснова. Выбор подтверждается
марками узлов: 33 из 35 указывают на эту ось с расстоянием 0.00 м.

Ось нарисована не одной полилинией, а девятью десятками отрезков (LINE) и
мультилиниями (MLINE — так рисуют двухниточную трассу: хранится одна осевая,
на экране две нитки). Отрезки сшиваются в цепочки по совпадающим концам, но в
ОДНУ цепочку они не собираются: линия прерывается в камерах и на врезках, а
местами нитки нарисованы раздельно. Через разрывы ничего не сшивается — точки
изгиба берутся из той цепочки, на которой лежат ОБА соседних узла; если такой
цепочки нет, участок остаётся прямым, и это видно в отчёте скрипта.

Разнос ниток: в плане его нет, в сечениях есть
------------------------------------------------
Отдельный вопрос — различает ли чертёж подачу и обратку. Измерено, а не
предположено:

- на проектном слое `_ПР_Теплосеть` все 31 отрезков, идущих параллельно трассе,
  лежат на НУЛЕВОМ отступе от неё: это одна осевая линия, двух контуров нет;
- эталонные нитки Т1 и Т2 стоят симметрично относительно этой же оси, по 0.35 м
  в каждую сторону (Т1 преимущественно слева, Т2 справа) — то есть проектная
  ось проходит ровно между ними;
- на топооснове `32_Теплосеть` параллельные отрезки размазаны от −1.5 до +1.5 м
  без двух чётких пиков, и это существующая сеть до реконструкции, а не наша;
- MLINE на слое теплосети рисует две линии с расстоянием 1.28/1.64/1.74 м — это
  СТЕНКИ КАНАЛА (совпадает с шириной «Канала» в эталоне), а не нитки.

Зато на листе сечений нитки подписаны раздельно: «Т1 Ø426х9,0» и «Т2 Ø426х9,0»,
каждая со своей окружностью. Лист начерчен в миллиметрах (радиусы 162.5 и 213.0
при Ду 325 и Ду 426), и расстояние между центрами ниток читается прямо оттуда:
**700 мм при Ду 325 и 800 мм при Ду 426**. Это данные чертежа, а не подобранное
число, и совпадение с эталоном (медиана 0.70 м, диапазон 0.40..0.81) —
независимое подтверждение, а не источник.

Разнос включён ПО УМОЛЧАНИЮ (решение по вопросу 14). Отключается флагом
--no-separate-threads, если нужно посмотреть на голую осевую.

Чего в данных всё-таки нет: КАКАЯ нитка идёт слева, а какая справа. В сечении
порядок есть, но чтобы перенести его на план, нужно знать направление взгляда
разреза — это отдельная работа. Поэтому СТОРОНА НАЗНАЧЕНА УСЛОВНО: supply
кладётся влево по ходу трассы, return вправо. Чертёж этого не задаёт, и это
допущение, а не факт. Если появится источник (лист «Схема» или другой), сторону
придётся поправить — но геометрия сети от этого не изменится: нитки в любом
случае стоят на паспортном расстоянии друг от друга, поменяться местами могут
только подписи Т1/Т2.

Система координат
------------------
Плановые координаты DWG лежат в диапазоне X 115751..117130, Y 108074..110563 —
это та же местная система, что и в эталонном IFC (X ~116300, Y ~110430), оси не
переставлены. Координаты плана сравнимы с эталоном напрямую, без привязки. Это
ответ на открытый вопрос 1 отчёта, полученный измерением, а не предположением.

Отметки высот: земля берётся с плана, лоток — нет
--------------------------------------------------
Отметки искались отдельно (задача 33), результат разный для двух величин.

**Отметка земли (z_surface) — берётся из чертежа.** На плане есть слой
«61_Отметки высоты поверхности» с 611 подписями съёмки, из них 146 лежат ближе
5 м к трассе. Сверка с отметками, снятыми человеком: расхождение в пределах
десятых долей метра (у ТК-3 подпись 28.32 при 28.30 в датасете). Скрипт берёт
ближайшую подпись к узлу, если она не дальше --ground-radius (по умолчанию 5 м),
иначе оставляет отметку из датасета.

**Отметка лотка (z_pipe_bottom) — в DXF не нашлась.** Проверены все пять
чертежей целиком: пространство модели, листы (paper space), определения блоков,
атрибуты вхождений и тексты размеров. Что есть и почему не подходит:

- лист профилей: значения лежат в атрибутах LEVEL блоков-указателей, в
  определении блока заглушка "0.000", у 109 вхождений атрибут пуст. Это
  динамические поля AutoCAD: они вычисляются при открытии чертежа и в DXF не
  материализуются. Текстом выписаны 5 отметок из нескольких сотен;
- на плане есть 48 подписей отметок на слое «32_Теплосеть» — но это
  СУЩЕСТВУЮЩАЯ сеть (топооснова), и они систематически на 0.4..1.1 м выше
  нашего лотка, то есть это верх или ось существующих труб, а не лоток
  проектируемых;
- на листе ТК есть отметки на слое «Pipe», но лист собран в собственных
  координатах узлов, и связать их с планом автоматически не на чем.

Вывод: отметки лотка нужно вводить руками (pdf_to_ifc.manual_input) либо
восстанавливать калибровкой профиля по вертикальному масштабу (Мв 1:100) — это
отдельная задача, и делать её походя, без сверки с бумагой, нельзя: цифра
получится правдоподобной и непроверяемой. Поэтому z_pipe_bottom по-прежнему
берётся из data/samples/parnas_nodes.csv, а узлы, которых там нет, в выгрузку
не попадают.

Что на выходе
--------------
Три файла в --out-dir (по умолчанию data/derived; data/samples не трогается):

- `parnas_dwg_nodes.csv` — узлы с реальными X/Y и отметками из датасета;
- `parnas_dwg_edges.csv` — нитки supply/return с waypoints;
- `parnas_dwg_model.json` — та же модель в формате ThermalNetworkModel.

Подготовка DXF
---------------
DWG читается не напрямую, нужен ODA File Converter (бесплатный):

    & "C:\\Program Files\\ODA\\ODAFileConverter 27.1.0\\ODAFileConverter.exe" `
        "data\\reference\\dwg" "out\\dxf" "ACAD2018" "DXF" "0" "1" "*.DWG"

Запуск
-------
    python scripts/extract_from_dwg.py
    python scripts/extract_from_dwg.py --plan "out/dxf/...План ТС.dxf" --out-dir data/derived

Код возврата: 0 — выгрузка собрана; 2 — нет DXF или в нём не нашлось трассы.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import ezdxf  # noqa: E402

from pdf_to_ifc.model import NetworkEdge, NetworkNode, ThermalNetworkModel  # noqa: E402

from dataclasses import replace  # noqa: E402

DEFAULT_PLAN = REPO_ROOT / "out" / "dxf" / "04_2_115-23-ТС_л.2_План ТС.dxf"
DEFAULT_PROFILE = REPO_ROOT / "out" / "dxf" / "06_2_115-23-ТС_л.5-6_Профили_изм.dxf"
DEFAULT_SECTIONS = REPO_ROOT / "out" / "dxf" / "05_2_115-23-ТС_л.4_Сечения.dxf"
DEFAULT_ELEVATIONS = REPO_ROOT / "data" / "samples" / "parnas_nodes.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "derived"

ROUTE_LAYER = "_ПР_Теплосеть"
LABEL_LAYERS = ("_ПР_Теплосеть_1", "_ПР_Теплосеть", "_ПР_Теплосеть_1_ВТС")
# Слой съёмочных отметок земли (задача 33). Отметок лотка такого слоя нет —
# см. раздел про отметки в докстринге.
GROUND_LEVEL_LAYER = "61_Отметки высоты поверхности"
# Подпись отметки относится к узлу, если лежит не дальше этого. 5 м — это
# примерно половина шага съёмочных точек вдоль трассы: дальше уже соседняя
# отметка, и брать её значит подменить измерение соседним измерением.
GROUND_RADIUS_M = 5.0
# Лист сечений: подписи ниток и окружности труб. Лист начерчен в миллиметрах.
SECTION_THREAD_RE = re.compile(r"^(Т1|Т2)\s*[Ø∅%%C]*\s*(\d{2,4})", re.IGNORECASE)
SECTION_UNITS_PER_M = 1000.0
# Подписи двух ниток одного сечения стоят рядом; дальше — уже другое сечение.
SECTION_PAIR_RADIUS = 3000.0
# Отметки на плане пишут двумя-тремя знаками: 27.74, 28,30. Диапазон ограничен,
# чтобы не поймать длины, диаметры и номера.
LEVEL_TEXT_RE = re.compile(r"^\s*(\d{2}[.,]\d{1,2})\s*$")
LEVEL_MIN_M, LEVEL_MAX_M = 10.0, 45.0

# Марка узла на чертеже: ТК-2, УТ-1а, Н1, УК1, УП2 и т.п.
NODE_MARK_RE = re.compile(r"^(ТК|УТ|УП|УК|Н)\s?-?\s?\d+[а-яa-z]?$", re.IGNORECASE)
NODE_MARK_PREFIX_RE = re.compile(r"^(ТК|УТ|УП|УК|Н)\s?-?\s?\d", re.IGNORECASE)

# Концы отрезков оси совпадают точно; допуск нужен только на округление.
JOIN_TOLERANCE_M = 0.05
# Цепочки короче — не трасса, а условные знаки узлов на том же слое.
MIN_CHAIN_LENGTH_M = 20.0
# Остриё выноски у большинства марок лежит ровно НА оси (0.00 м), но у камер
# оно указывает на контур камеры, а не на осевую линию: ТК-2 отстоит на 1.31 м,
# ТК-3 — на 2.27 м. Камера физически имеет размер (в эталоне 4.3 x 5.8 м),
# поэтому допуск задан её половиной, а не нулём. Всё, что дальше, — марка
# чужого объекта, и такие узлы скрипт отбрасывает с явной причиной.
NODE_SNAP_TOLERANCE_M = 3.0

Point = Tuple[float, float]


def _clean_label(text: str) -> str:
    """Марка узла из текста выноски: «УТ-1а (нов.)» -> «УТ-1а», «УП2\\P135°» -> «УП2»."""
    text = text.replace("\\P", "\n").replace("%%D", "°")
    return re.split(r"[\n(]", text, maxsplit=1)[0].strip().strip(",")


def _normalise(name: str) -> str:
    """Ключ сопоставления марок: «УТ-1а», «УТ1а» и «ут 1а» — один узел."""
    return re.sub(r"[\s\-]", "", name).upper()


def load_route_segments(doc, layer: str) -> List[Tuple[Point, Point]]:
    """Отрезки оси трассы со слоя layer: LINE и осевые MLINE.

    У MLINE берутся вершины осевой линии, а не отрисованные параллельные нитки:
    нужна ось участка, нитки из неё разворачивает уже доменная модель.
    """
    segments: List[Tuple[Point, Point]] = []
    for entity in doc.modelspace():
        if entity.dxf.layer != layer:
            continue
        if entity.dxftype() == "LINE":
            points = [
                (float(entity.dxf.start[0]), float(entity.dxf.start[1])),
                (float(entity.dxf.end[0]), float(entity.dxf.end[1])),
            ]
        elif entity.dxftype() == "MLINE":
            try:
                points = [
                    (float(vertex.location[0]), float(vertex.location[1]))
                    for vertex in entity.vertices
                ]
            except Exception:
                continue
        else:
            continue
        segments.extend((a, b) for a, b in zip(points, points[1:]) if math.dist(a, b) > 1e-6)
    return segments


def chain_segments(
    segments: List[Tuple[Point, Point]],
    *,
    tolerance: float = JOIN_TOLERANCE_M,
    min_length: float = MIN_CHAIN_LENGTH_M,
) -> List[List[Point]]:
    """Сшить отрезки в ломаные по совпадающим концам, от длинной к короткой.

    Через разрывы не сшивается ничего: линия прерывается в камерах и на врезках,
    и соединять «по смыслу» значило бы придумывать геометрию, которой в чертеже
    нет. Поэтому на выходе несколько цепочек, а не одна.
    """
    def key(point: Point) -> Point:
        return (round(point[0] / tolerance) * tolerance, round(point[1] / tolerance) * tolerance)

    adjacency: Dict[Point, List[int]] = {}
    for index, (first, second) in enumerate(segments):
        adjacency.setdefault(key(first), []).append(index)
        adjacency.setdefault(key(second), []).append(index)

    used: set = set()

    def walk(start: Point) -> List[Point]:
        chain = [start]
        current = start
        while True:
            following = next((i for i in adjacency.get(key(current), []) if i not in used), None)
            if following is None:
                return chain
            used.add(following)
            first, second = segments[following]
            chain.append(second if key(first) == key(current) else first)
            current = chain[-1]

    chains: List[List[Point]] = []
    for start, incident in sorted(adjacency.items(), key=lambda item: len(item[1])):
        if len(incident) != 1 or incident[0] in used:
            continue
        first, second = segments[incident[0]]
        chains.append(walk(first if key(first) == start else second))
    for start, incident in adjacency.items():
        if all(index in used for index in incident):
            continue
        chains.append(walk(start))

    def length(chain: List[Point]) -> float:
        return sum(math.dist(a, b) for a, b in zip(chain, chain[1:]))

    return sorted([c for c in chains if length(c) >= min_length], key=length, reverse=True)


def load_node_labels(doc, layers: Sequence[str] = LABEL_LAYERS) -> Dict[str, List[Point]]:
    """Марки узлов с плана и все вершины их выносок — кандидаты на положение узла."""
    labels: Dict[str, List[Point]] = {}
    for entity in doc.modelspace():
        if entity.dxftype() != "MULTILEADER" or entity.dxf.layer not in layers:
            continue
        try:
            raw = entity.get_mtext_content() or ""
        except Exception:
            continue
        name = _clean_label(raw)
        if not name or not NODE_MARK_PREFIX_RE.match(name):
            continue
        candidates: List[Point] = []
        try:
            for leader in entity.context.leaders:
                for line in leader.lines:
                    for vertex in line.vertices:
                        candidates.append((float(vertex[0]), float(vertex[1])))
        except Exception:
            continue
        if candidates:
            labels.setdefault(name, candidates)
    return labels


def load_node_order(doc) -> List[str]:
    """Порядок узлов вдоль трассы с листа профилей.

    На профиле марки выписаны в один ряд по ходу трассы, поэтому порядок — это
    сортировка по горизонтали. Ряд выбирается как строка с наибольшим числом
    марок: на листе есть и другие подписи, но столько марок подряд стоит только
    в шапке профиля.
    """
    rows: Dict[int, List[Tuple[float, str]]] = {}
    for entity in doc.modelspace():
        if entity.dxftype() not in ("TEXT", "MTEXT"):
            continue
        raw = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
        name = raw.strip().split("\n")[0].strip()
        if not NODE_MARK_RE.match(name):
            continue
        position = entity.dxf.insert
        rows.setdefault(round(float(position[1])), []).append((float(position[0]), name))

    if not rows:
        return []
    _, row = max(rows.items(), key=lambda item: len(item[1]))
    order: List[str] = []
    seen: set = set()
    for _, name in sorted(row):
        key = _normalise(name)
        if key not in seen:
            seen.add(key)
            order.append(name)
    return order


def project_on_chain(point: Point, chain: List[Point]) -> Tuple[float, float, Point]:
    """Проекция точки на ломаную: (расстояние вдоль неё, отступ, точка проекции)."""
    best = (0.0, float("inf"), chain[0])
    travelled = 0.0
    for first, second in zip(chain, chain[1:]):
        span = math.dist(first, second)
        if span < 1e-9:
            continue
        tx = (second[0] - first[0]) / span
        ty = (second[1] - first[1]) / span
        along = max(0.0, min(span, (point[0] - first[0]) * tx + (point[1] - first[1]) * ty))
        projection = (first[0] + tx * along, first[1] + ty * along)
        offset = math.dist(point, projection)
        if offset < best[1]:
            best = (travelled + along, offset, projection)
        travelled += span
    return best


def snap_to_chains(
    point: Point, chains: List[List[Point]]
) -> Tuple[Optional[int], float, float, Point]:
    """Ближайшая цепочка к точке: (индекс цепочки, станция, отступ, проекция)."""
    best: Tuple[Optional[int], float, float, Point] = (None, 0.0, float("inf"), point)
    for index, chain in enumerate(chains):
        station, offset, projection = project_on_chain(point, chain)
        if offset < best[2]:
            best = (index, station, offset, projection)
    return best


def load_diameters(path: Path) -> Dict[Tuple[str, str], int]:
    """Диаметры участков из существующего датасета по паре узлов.

    Диаметр в DWG подписан выносками и в таблице профиля, но привязка подписи к
    участку — отдельная задача (Ш3 дорожной карты). Пока берём то, что уже
    считано человеком со спецификации: пара (узел, узел) -> DN. Участки, которых
    в датасете нет, наследуют диаметр предыдущего по ходу трассы — переход
    диаметра случается в узле, а не посреди участка.
    """
    diameters: Dict[Tuple[str, str], int] = {}
    if not path.exists():
        return diameters
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (_normalise(row["start_node"]), _normalise(row["end_node"]))
            diameters[key] = int(row["diameter"])
            diameters[(key[1], key[0])] = int(row["diameter"])
    return diameters


def load_ground_levels(doc, layer: str = GROUND_LEVEL_LAYER) -> List[Tuple[Point, float]]:
    """Съёмочные отметки земли с плана: (точка подписи, значение).

    Берутся только подписи, которые целиком состоят из числа в правдоподобном
    диапазоне отметок: на том же слое попадаются выноски и служебные надписи, и
    выдёргивать из них числа регуляркой — верный способ намерить ерунды.
    """
    levels: List[Tuple[Point, float]] = []
    for entity in doc.modelspace():
        if entity.dxf.layer != layer or entity.dxftype() not in ("TEXT", "MTEXT"):
            continue
        raw = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
        match = LEVEL_TEXT_RE.match(raw or "")
        if not match:
            continue
        value = float(match.group(1).replace(",", "."))
        if not LEVEL_MIN_M <= value <= LEVEL_MAX_M:
            continue
        position = entity.dxf.insert
        levels.append(((float(position[0]), float(position[1])), value))
    return levels


def nearest_ground_level(
    point: Point, levels: List[Tuple[Point, float]], *, radius: float = GROUND_RADIUS_M
) -> Optional[Tuple[float, float]]:
    """Ближайшая отметка земли к точке: (значение, расстояние) или None."""
    best: Optional[Tuple[float, float]] = None
    for position, value in levels:
        distance = math.dist(point, position)
        if distance <= radius and (best is None or distance < best[1]):
            best = (value, distance)
    return best


def load_thread_spacing(doc) -> Dict[int, float]:
    """Расстояние между осями ниток по листу сечений: {диаметр, мм: расстояние, м}.

    На сечении каждая нитка подписана отдельно («Т1 Ø426х9,0», «Т2 Ø426х9,0») и
    нарисована окружностью. Берутся пары подписей Т1/Т2 одного сечения, к каждой
    подбирается ближайшая окружность, и меряется расстояние между центрами.
    Лист начерчен в миллиметрах — это видно по радиусам (162.5 при Ду 325,
    213.0 при Ду 426), поэтому результат делится на 1000.

    По каждому диаметру берётся медиана: сечений несколько, и одно из них может
    быть нетиповым (например, в футляре или на повороте).
    """
    labels: List[Tuple[str, int, Point]] = []
    for entity in doc.modelspace():
        if entity.dxftype() not in ("TEXT", "MTEXT"):
            continue
        raw = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
        match = SECTION_THREAD_RE.match((raw or "").strip().replace("\n", " "))
        if not match:
            continue
        position = entity.dxf.insert
        labels.append((match.group(1).upper(), int(match.group(2)),
                       (float(position[0]), float(position[1]))))

    circles = [
        ((float(c.dxf.center[0]), float(c.dxf.center[1])), float(c.dxf.radius))
        for c in doc.modelspace() if c.dxftype() == "CIRCLE"
    ]
    if not circles or not labels:
        return {}

    measured: Dict[int, List[float]] = {}
    labels.sort(key=lambda item: (round(item[2][1], -1), item[2][0]))
    for first, second in zip(labels, labels[1:]):
        if first[0] == second[0] or first[1] != second[1]:
            continue
        if math.dist(first[2], second[2]) > SECTION_PAIR_RADIUS:
            continue
        centre_a = min(circles, key=lambda c: math.dist(c[0], first[2]))[0]
        centre_b = min(circles, key=lambda c: math.dist(c[0], second[2]))[0]
        spacing = math.dist(centre_a, centre_b) / SECTION_UNITS_PER_M
        if 0.2 <= spacing <= 3.0:
            measured.setdefault(first[1], []).append(spacing)

    return {
        diameter: round(sorted(values)[len(values) // 2], 3)
        for diameter, values in measured.items()
    }


def _unit_normal(first: Point, second: Point) -> Tuple[float, float]:
    """Единичная нормаль слева от направления first -> second."""
    dx, dy = second[0] - first[0], second[1] - first[1]
    length = math.hypot(dx, dy) or 1.0
    return (-dy / length, dx / length)


def _mitre_normal(before: Point, corner: Point, after: Point) -> Tuple[float, float]:
    """Направление сдвига в точке поворота — «ус» (mitre), а не простая нормаль.

    Если сдвигать вершину поворота по нормали одного из звеньев или по их
    усреднённому направлению, параллельная нитка срежет угол: она пройдёт ближе
    к вершине, чем нужно, и на повороте сойдётся с осью. Правильная точка —
    пересечение двух сдвинутых звеньев, а это сдвиг по биссектрисе на
    shift / cos(половина угла поворота). В векторном виде это
    (n1 + n2) / (1 + n1·n2), что и возвращается.
    """
    first = _unit_normal(before, corner)
    second = _unit_normal(corner, after)
    denominator = 1.0 + first[0] * second[0] + first[1] * second[1]
    if denominator < 1e-6:   # разворот на 180°, «уса» не существует
        return first
    return ((first[0] + second[0]) / denominator, (first[1] + second[1]) / denominator)


def offset_threads(model: ThermalNetworkModel, spacing: Dict[int, float]) -> ThermalNetworkModel:
    """Развести supply и return на паспортное расстояние по обе стороны от оси.

    Возвращается НОВАЯ модель с узлами-двойниками по ниткам (см. задачу 26):
    каждая нитка сдвигается перпендикулярно трассе на половину расстояния из
    сечений. Расстояние берётся по диаметру участка, а если для него сечения нет
    — по медиане известных; узлы, у которых обе величины неизвестны, остаются на
    оси.

    ВНИМАНИЕ, НЕПРОВЕРЕННОЕ ДОПУЩЕНИЕ: сторона назначена условно — supply влево
    по ходу трассы, return вправо. Чертёж стороны не задаёт: в плане одна
    осевая, а порядок ниток в сечении без направления взгляда разреза на план
    не переносится. Если появится источник (лист «Схема» или другой), это
    потребует правки. Геометрия сети при этом не изменится — нитки в любом
    случае стоят на паспортном расстоянии друг от друга, — поменяться местами
    могут только подписи Т1/Т2.
    """
    if not spacing:
        return model

    default = sorted(spacing.values())[len(spacing) // 2]
    # Знак стороны — то самое условное допущение (см. докстринг функции):
    # −1 это «влево по ходу трассы», +1 «вправо». Поменять местами безопасно,
    # геометрия сети не изменится.
    sides = {"supply": -1.0, "return": 1.0}
    separated = ThermalNetworkModel(
        project_name=f"{model.project_name} [нитки разведены]", source=model.source
    )

    directions: Dict[str, Tuple[float, float]] = {}
    diameters: Dict[str, int] = {}
    for edge in model.edges:
        points = edge.polyline(model.nodes)
        start, end = edge.resolve_nodes(model.nodes)
        for node, (first, second) in ((start, (points[0], points[1])),
                                      (end, (points[-2], points[-1]))):
            directions.setdefault(node.name, (second[0] - first[0], second[1] - first[1]))
            diameters.setdefault(node.name, edge.diameter)

    for edge in model.edges:
        for node in edge.resolve_nodes(model.nodes):
            twin_key = f"{node.name}@{edge.branch}"
            if twin_key in separated.nodes:
                continue
            dx, dy = directions.get(node.name, (1.0, 0.0))
            normal = _unit_normal((0.0, 0.0), (dx, dy))
            half = spacing.get(diameters.get(node.name, 0), default) / 2.0
            shift = sides.get(edge.branch, 0.0) * half
            separated.add_node(NetworkNode(
                name=node.name,
                x=round(node.x + normal[0] * shift, 3),
                y=round(node.y + normal[1] * shift, 3),
                z_surface=node.z_surface, z_pipe_bottom=node.z_pipe_bottom,
                node_type=node.node_type, branch=edge.branch,
            ))

    for edge in model.edges:
        half = spacing.get(edge.diameter, default) / 2.0
        shift = sides.get(edge.branch, 0.0) * half
        # Точку изгиба сдвигаем перпендикулярно ЕЁ ЗВЕНУ ломаной, а не участку
        # целиком: на повороте направление трассы меняется, и общий для участка
        # перпендикуляр увёл бы нитку внутрь или наружу угла.
        points = edge.polyline(model.nodes)
        waypoints = []
        for index, (x, y, z) in enumerate(edge.waypoints, start=1):
            before, after = points[index - 1], points[index + 1]
            normal = _mitre_normal((before[0], before[1]), (x, y), (after[0], after[1]))
            waypoints.append((round(x + normal[0] * shift, 3),
                              round(y + normal[1] * shift, 3), z))
        separated.edges.append(replace(edge, waypoints=waypoints))

    return separated


def load_elevations(path: Path) -> Dict[str, Tuple[float, float, str]]:
    """Отметки узлов из датасета: ключ -> (z_surface, z_pipe_bottom, node_type)."""
    elevations: Dict[str, Tuple[float, float, str]] = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            elevations[_normalise(row["name"])] = (
                float(row["z_surface"]), float(row["z_pipe_bottom"]), row["node_type"],
            )
    return elevations


def waypoints_between(
    chains: List[List[Point]], start: dict, end: dict, *, z_start: float, z_end: float,
) -> List[Tuple[float, float, float]]:
    """Вершины нарисованной оси между двумя узлами — точки изгиба участка.

    Берутся, только если оба узла легли на ОДНУ цепочку: тогда между ними
    действительно нарисована линия и её вершины — настоящие углы поворота. Если
    узлы на разных цепочках (в чертеже между ними разрыв), участок остаётся
    прямым: придумывать изгиб нельзя.

    Z у точек изгиба интерполируется линейно между отметками соседних узлов —
    измеренных отметок в этих точках нет ни в DWG, ни в датасете.
    """
    if start["chain"] is None or start["chain"] != end["chain"]:
        return []

    chain = chains[start["chain"]]
    stations = [0.0]
    for first, second in zip(chain, chain[1:]):
        stations.append(stations[-1] + math.dist(first, second))

    low, high = sorted((start["station"], end["station"]))
    span = high - low
    if span < 1e-6:
        return []

    points: List[Tuple[float, float, float]] = []
    for point, station in zip(chain, stations):
        if low + 0.05 < station < high - 0.05:
            ratio = (station - low) / span
            if start["station"] > end["station"]:
                ratio = 1.0 - ratio
            points.append((round(point[0], 3), round(point[1], 3),
                           round(z_start + ratio * (z_end - z_start), 3)))
    if start["station"] > end["station"]:
        points.reverse()
    return points


def build_model(
    chains: List[List[Point]],
    labels: Dict[str, List[Point]],
    order: List[str],
    elevations: Dict[str, Tuple[float, float, str]],
    diameters: Dict[Tuple[str, str], int],
    ground_levels: Optional[List[Tuple[Point, float]]] = None,
    *,
    snap_tolerance: float = NODE_SNAP_TOLERANCE_M,
    ground_radius: float = GROUND_RADIUS_M,
) -> Tuple[ThermalNetworkModel, List[dict]]:
    """Собрать модель: узлы с плана, порядок с профиля, изгибы из нарисованной оси.

    Узел попадает в модель, если выполнены три условия: он есть на плане
    (выноска), лежит на оси трассы и его отметка есть в датасете. Всё, что не
    прошло, возвращается вторым значением со внятной причиной — молча терять
    узлы нельзя, иначе сеть окажется короче, чем на чертеже, и никто не заметит.
    """
    placed: Dict[str, dict] = {}
    skipped: List[dict] = []

    for name, candidates in labels.items():
        chain_index, station, offset, projection = min(
            (snap_to_chains(point, chains) for point in candidates),
            key=lambda item: item[2],
        )
        key = _normalise(name)
        if offset > snap_tolerance:
            skipped.append({"name": name, "reason": "выноска не указывает на ось трассы",
                            "detail": f"отступ {offset:.2f} м"})
            continue
        if key not in elevations:
            skipped.append({"name": name, "reason": "нет отметки в датасете", "detail": ""})
            continue
        z_surface, z_pipe_bottom, node_type = elevations[key]
        # Задача 33: отметку земли, если она есть на плане, берём из чертежа —
        # это измерение, а не переписанное из датасета число. Отметка лотка
        # такой замены не получает: её в чертеже нет (см. докстринг модуля).
        ground_source = "датасет"
        ground = nearest_ground_level(projection, ground_levels or [], radius=ground_radius)
        if ground is not None:
            ground_source = f"план, подпись в {ground[1]:.1f} м"
            z_surface = ground[0]
        placed[key] = {
            "ground_source": ground_source,
            "name": name, "chain": chain_index, "station": station,
            "x": projection[0], "y": projection[1], "offset": offset,
            "z_surface": z_surface, "z_pipe_bottom": z_pipe_bottom, "node_type": node_type,
        }

    sequence = [placed[_normalise(name)] for name in order if _normalise(name) in placed]
    if not sequence:
        return ThermalNetworkModel(project_name="Парнас (координаты из DWG)"), skipped, []

    model = ThermalNetworkModel(
        project_name="Парнас (координаты из DWG)",
        source="XY — DWG л.2 «План ТС»; порядок — л.5-6 «Профили»; Z — data/samples/parnas_nodes.csv",
    )
    for node in sequence:
        model.add_node(NetworkNode(
            name=node["name"], x=round(node["x"], 3), y=round(node["y"], 3),
            z_surface=node["z_surface"], z_pipe_bottom=node["z_pipe_bottom"],
            node_type=node["node_type"],
        ))

    diameter = 426  # головной участок; дальше наследуется до узла, где меняется
    for start, end in zip(sequence, sequence[1:]):
        diameter = diameters.get(
            (_normalise(start["name"]), _normalise(end["name"])), diameter
        )
        waypoints = waypoints_between(
            chains, start, end, z_start=start["z_pipe_bottom"], z_end=end["z_pipe_bottom"],
        )
        points = ([(start["x"], start["y"])]
                  + [(x, y) for x, y, _ in waypoints]
                  + [(end["x"], end["y"])])
        length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        for branch in ("supply", "return"):
            model.add_edge(NetworkEdge(
                start_node=start["name"], end_node=end["name"], branch=branch,
                diameter=diameter,
                length=round(length, 2), material="Steel", insulation="PPU+PE",
                laying_type="underground_ducted", waypoints=list(waypoints),
            ))

    return model, skipped, list(placed.values())


def write_csv(model: ThermalNetworkModel, out_dir: Path) -> Tuple[Path, Path]:
    nodes_path = out_dir / "parnas_dwg_nodes.csv"
    edges_path = out_dir / "parnas_dwg_edges.csv"

    with open(nodes_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        # branch обязателен: после разноса ниток в выгрузке два узла с одним
        # именем и разными координатами, и без этой колонки их не различить.
        writer.writerow(["name", "branch", "node_type", "x", "y",
                         "z_surface", "z_pipe_bottom", "source"])
        for node in model.nodes.values():
            writer.writerow([
                node.name, node.branch, node.node_type, f"{node.x:.3f}", f"{node.y:.3f}",
                f"{node.z_surface:.2f}", f"{node.z_pipe_bottom:.2f}",
                "XY — DWG л.2 (остриё выноски); Z — профиль л.5 через data/samples",
            ])

    with open(edges_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["start_node", "end_node", "branch", "diameter", "length",
                         "material", "insulation", "laying_type", "waypoints", "source"])
        for edge in model.edges:
            waypoints = ";".join(f"{x:.3f},{y:.3f},{z:.3f}" for x, y, z in edge.waypoints)
            writer.writerow([
                edge.start_node, edge.end_node, edge.branch, edge.diameter, f"{edge.length:.2f}",
                edge.material, edge.insulation, edge.laying_type, waypoints,
                f"ось трассы — DWG л.2, слой {ROUTE_LAYER}",
            ])

    return nodes_path, edges_path


def build_parser() -> argparse.ArgumentParser:
    """Разбор аргументов отдельно от работы — чтобы умолчания можно было проверить тестом."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN, help="DXF листа плана")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE,
                        help="DXF листа профилей (нужен для порядка узлов вдоль трассы)")
    parser.add_argument("--route-layer", default=ROUTE_LAYER, help="слой с осью трассы")
    parser.add_argument("--elevations", type=Path, default=DEFAULT_ELEVATIONS,
                        help="CSV с отметками узлов (только читается)")
    parser.add_argument("--ground-radius", type=float, default=GROUND_RADIUS_M,
                        help="радиус поиска отметки земли на плане, м "
                             f"(по умолчанию {GROUND_RADIUS_M}; 0 — не брать с плана)")
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS,
                        help="DXF листа сечений (оттуда берётся расстояние между нитками)")
    parser.add_argument("--separate-threads", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="развести supply/return на расстояние из сечений (по умолчанию да; "
                             "--no-separate-threads оставит обе нитки на общей оси). Сторона "
                             "назначена условно, чертёж её не задаёт — см. докстринг")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="куда класть выгрузку")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    for path in (args.plan, args.profile):
        if not path.exists():
            print(f"Нет DXF: {path}", file=sys.stderr)
            print("Сконвертируйте DWG через ODA File Converter — см. докстринг скрипта.",
                  file=sys.stderr)
            return 2

    plan = ezdxf.readfile(str(args.plan))
    chains = chain_segments(load_route_segments(plan, args.route_layer))
    if not chains:
        print(f"На слое {args.route_layer} не нашлось оси трассы", file=sys.stderr)
        return 2

    labels = load_node_labels(plan)
    order = load_node_order(ezdxf.readfile(str(args.profile)))
    elevations = load_elevations(args.elevations)
    diameters = load_diameters(args.elevations.with_name("parnas_edges.csv"))
    ground_levels = load_ground_levels(plan)
    model, skipped, placed_report = build_model(
        chains, labels, order, elevations, diameters, ground_levels,
        ground_radius=args.ground_radius,
    )

    if not model.nodes:
        print("Ни один узел не удалось поставить на ось", file=sys.stderr)
        return 2

    spacing: Dict[int, float] = {}
    if args.sections.exists():
        spacing = load_thread_spacing(ezdxf.readfile(str(args.sections)))
    if args.separate_threads:
        model = offset_threads(model, spacing)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    nodes_path, edges_path = write_csv(model, args.out_dir)
    model_path = args.out_dir / "parnas_dwg_model.json"
    model.save_json(model_path)

    lengths = [sum(math.dist(a, b) for a, b in zip(c, c[1:])) for c in chains]
    coordinates = [(node.x, node.y) for node in model.nodes.values()]
    supply = [edge for edge in model.edges if edge.branch == "supply"]

    print(f"План:    {args.plan.name}")
    print(f"Профиль: {args.profile.name}")
    print(f"Ось: цепочек {len(chains)}, длины {[round(l, 1) for l in lengths]} м")
    print(f"Габарит узлов: X {min(x for x, _ in coordinates):.1f}..{max(x for x, _ in coordinates):.1f}"
          f"  Y {min(y for _, y in coordinates):.1f}..{max(y for _, y in coordinates):.1f}")
    print(f"Марок на плане: {len(labels)}, порядок с профиля: {len(order)}, "
          f"узлов в модели: {len(model.nodes)}")
    from_plan = sum(1 for node in placed_report if node["ground_source"] != "датасет")
    print(f"Отметок земли: с плана {from_plan} из {len(placed_report)}, "
          f"остальные из датасета; отметки лотка в чертеже отсутствуют (см. докстринг)")
    print(f"Участков: {len(supply)} (x2 нитки = {len(model.edges)}), "
          f"точек изгиба: {sum(len(e.waypoints) for e in supply)}, "
          f"без изгибов: {sum(1 for e in supply if not e.waypoints)}")
    if spacing:
        print("Расстояние между нитками по сечениям: "
              + ", ".join(f"Ду {d} — {s:.2f} м" for d, s in sorted(spacing.items()))
              + (" (применено; сторона условная, см. докстринг)" if args.separate_threads
                 else " (НЕ применено: --no-separate-threads)"))
    else:
        print("Расстояние между нитками: в сечениях не найдено")
    print(f"Длина сети: {sum(e.length for e in model.edges):.2f} м "
          f"(по одной нитке {sum(e.length for e in supply):.2f} м)")
    if skipped:
        reasons: Dict[str, int] = {}
        for item in skipped:
            reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
        print(f"Пропущено марок: {len(skipped)} — {reasons}")
        for item in skipped[:8]:
            print(f"    {item['name']:<10} {item['reason']} {item['detail']}")
    print(f"Записано в {args.out_dir}: {nodes_path.name}, {edges_path.name}, {model_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
