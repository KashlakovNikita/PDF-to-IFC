"""Задача 5 брифа: количественная сверка геометрии труб с эталонным IFC.

Зачем: до этого скрипта «совпадает / не совпадает» решалось на глаз. Здесь
считается число: какая доля длины сети лежит в допуске и какие именно участки
из него выпали.

Что с чем сравнивается
-----------------------
Эталон — `data/raw/ПРНС_ЛО_ТКР-ТС_У1_Э1_I2300.ifc`, реальная модель проекта.
Сравнение по IFC-классам невозможно в принципе:

- эталон в схеме IFC2X3, где нужного нам `IfcPipeSegment` попросту нет: все
  328 элементов там — `IfcBuildingElementProxy`, а тип объекта зашит в ИМЯ
  `IfcPropertySet` по-русски («Труба», «Неподвижная опора», «Колодец», ...);
- геометрия эталона — `IfcFacetedBrep` (полигональная сетка), наша —
  `IfcExtrudedAreaSolid` (цилиндр по DN).

Поэтому сравниваются не классы и не типы представлений, а ФАКТИЧЕСКАЯ
геометрия: через `ifcopenshell.geom` из обоих файлов извлекаются вершины тел
в мировых координатах, из вершин каждого тела восстанавливается осевая линия
трубы, и дальше работа идёт с осевыми линиями.

Как восстанавливается осевая линия
-----------------------------------
Труба — вытянутое тело вращения, поэтому первая главная компонента облака её
вершин (SVD по центрированному облаку) совпадает с осью с точностью до знака.
Концы оси — крайние проекции вершин на эту ось. Метод одинаков для обоих
файлов, что и делает сравнение честным: мы не сверяем «наш цилиндр с их
сеткой», мы сверяем две осевые линии, полученные одинаковым способом.

Ограничение метода: он верен для ПРЯМОГО участка трубы. В эталоне трубы
разбиты на прямые куски по 3-9 м (проверено: 130 труб систем Т1/Т2), у нас
после задачи 1 брифа тоже по одному телу на прямое звено ломаной — так что
ограничение не мешает. Если в файле появится изогнутое одним телом тело
(sweep по дуге), его осевая линия выродится в хорду; такие случаи скрипт
помечает отдельно (см. --report-thick).

Фильтр систем
--------------
В эталоне вперемешку лежат две инженерные системы: Т1/Т2/Т1/Т2 (наша
теплосеть, подача и обратка) и «Др» — дренаж, к этому проекту не относящийся
и в PDF-источнике отсутствующий. Берутся только системы из --systems
(по умолчанию Т1, Т2, Т1/Т2), «Др» отбрасывается.

Метрика и допуск
-----------------
Для каждого участка нашей модели его осевая линия дискретизируется на
--samples точек, и для каждой точки считается расстояние до БЛИЖАЙШЕЙ точки
эталонной сети (по всем эталонным осевым линиям, а не только по «парной» —
соответствие участков между файлами не задано и восстановить его по именам
нельзя: в эталоне у труб нет имён участков). Отклонение участка = максимум
по его точкам, то есть односторонняя хаусдорфова дистанция от участка до
эталонной сети.

Считается и обратное направление — от эталона к нам: это ловит не «наши
трубы не там», а «наших труб нет там, где они есть в эталоне» (пропущенные
участки). Обе величины в отчёте.

Допуск по умолчанию: отклонение <= min(--max-deviation, --max-relative *
длина участка), то есть строже из абсолютного и относительного. Абсолютное
значение по умолчанию 0.2 м — это критерий приёмки планового положения осей
из `pdf_to_ifc_roadmap.md` (раздел «Точность»), значение подтверждено
человеком при постановке задачи. Черновое значение 0.3 м из брифа заменено
на 0.2 м сознательно, чтобы в проекте не жило два разных порога на одно и то
же. Меняется флагом, но НЕ по итогам собственных прогонов: если 0.2 м
окажется неподходящим, это решение человека, а не скрипта.

Побитового совпадения файлов здесь никто не ждёт и ждать не может (плавающая
точка, дискретизация кривых, разный способ построения тел). Целевая метрика —
доля длины сети в пределах допуска.

Системы координат
------------------
Скрипт НИЧЕГО не выравнивает по умолчанию. Эталон — в местной системе
координат (X ~ 116000, Y ~ 110400), а координаты в data/samples — синтетика
0-600 из задачи 4, потому что в PDF читаемой координатной сетки не нашлось.
На таких данных отчёт закономерно покажет 0% в допуске — и это корректный
результат, а не поломка скрипта: файлы физически в разных местах пространства.
Флаг --align centroid совмещает центры масс осевых линий и позволяет отдельно
посмотреть на ФОРМУ трассы, не трогая вопрос привязки. Это диагностика, а не
режим приёмки, и в отчёте она подписана как таковая.

Сводка длин по DN (итерация 1 по п.6 брифа)
--------------------------------------------
Первый же прогон показал, что отклонение геометрии на текущих данных целиком
объясняется разными системами координат (см. выше) — то есть чинить по нему
генератор нечего, отчёт про это и говорит. Зато из тех же данных считается
величина, от системы координат НЕ зависящая: суммарная длина труб по каждому
условному проходу. Именно она стоит в критериях приёмки дорожной карты
(«Суммы длин по каждому Ду: расхождение с ведомостью объёмов <= 3 %»), и её
можно сверять уже сейчас, до появления привязки координат.

Вердикт по этой сводке скрипт не выносит: 3 % из дорожной карты — критерий
сверки с ВЕДОМОСТЬЮ ОБЪЁМОВ, а здесь сравнение идёт с эталонной моделью, и
переносить порог с одного на другое без человека нельзя. Печатаются числа.

Откуда берётся DN эталона (важно, тут была ошибка)
--------------------------------------------------
В эталоне DN лежит в ДВУХ местах, и полагаться на одно из них нельзя:

- свойство «Диаметр» набора «Труба» — в метрах, но у 18 труб систем Т1/Т2
  оно не заполнено вовсе;
- свойство «Наименование» — обозначение по ГОСТ вида
  "Ст 426х9,0/560 ППУ-ПЭ в изоляции по ГОСТ 30732-2020", где первое число и
  есть наружный диаметр стальной трубы в мм (второе — толщина стенки,
  третье — диаметр оболочки ППУ).

Первая версия сводки читала только «Диаметр», и все 18 труб без него
(214.17 м, по обозначению — все Ст 426) попадали в строку «не указан».
Из-за этого длина по DN 426 занижалась почти вдвое, а расхождение с нашим
файлом выглядело как +135 % вместо фактических +27.8 %. Теперь обозначение
разбирается как запасной источник, а «Диаметр» остаётся приоритетным: он
явное поле, а обозначение — строка, которую заполняет человек.

Запуск
-------
    python scripts/validate_geometry.py --generated out/parnas.ifc
    python scripts/validate_geometry.py --generated out/parnas.ifc --align centroid
    python scripts/validate_geometry.py --generated out/parnas.ifc --json out/geometry.json

Код возврата: 0 — вся длина сети в допуске; 1 — есть участки вне допуска
(чтобы скрипт можно было ставить в CI); 2 — ошибка входных данных.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pdf_to_ifc.ifc_export import PIPE_PSET_NAME  # noqa: E402  (после правки sys.path)

DEFAULT_REFERENCE = REPO_ROOT / "data" / "raw" / "ПРНС_ЛО_ТКР-ТС_У1_Э1_I2300.ifc"

# Имя IfcPropertySet, которым в эталоне помечены трубы, и имя свойства с
# системой. Русские строки здесь — не стиль, а факт формата эталонного файла.
REFERENCE_PIPE_PSET = "Труба"
REFERENCE_SYSTEM_PROPERTY = "Имя системы"
REFERENCE_NAME_PROPERTY = "Наименование"
DEFAULT_SYSTEMS = ("Т1", "Т2", "Т1/Т2")

# Обозначение трубы по ГОСТ в эталоне: "Ст 426х9,0/560 ППУ-ПЭ в изоляции по
# ГОСТ 30732-2020" — 426 наружный диаметр стали, 9,0 толщина стенки, 560
# оболочка ППУ. Берём первое число. Разделитель между диаметром и толщиной
# может быть русской "х", латинской "x" или знаком умножения "×" — в проектной
# документации встречаются все три, поэтому перечислены явно.
REFERENCE_DESIGNATION_RE = re.compile(r"(?:Ст|Сталь)?\s*(\d{2,4})\s*[хx×]\s*\d")

# Порог по умолчанию — критерий приёмки планового положения осей из
# pdf_to_ifc_roadmap.md; подтверждён человеком. См. докстринг модуля.
DEFAULT_MAX_DEVIATION_M = 0.2
DEFAULT_MAX_RELATIVE = 0.05
DEFAULT_SAMPLES = 20


@dataclass
class Centerline:
    """Осевая линия одного прямого участка трубы в мировых координатах."""

    name: str
    start: np.ndarray
    end: np.ndarray
    radius: float  # максимальное удаление вершин от оси, м — толщина тела
    source: str = ""
    dn: Optional[int] = None  # условный проход, мм (из свойств, а не из геометрии)

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.end - self.start))

    def sample(self, count: int) -> np.ndarray:
        """Равномерно дискретизировать ось на count точек (включая концы)."""
        t = np.linspace(0.0, 1.0, max(count, 2)).reshape(-1, 1)
        return self.start + t * (self.end - self.start)


@dataclass
class SectionResult:
    """Результат по одному участку: отклонение и вердикт по допуску."""

    name: str
    length: float
    deviation: float
    tolerance: float

    @property
    def within_tolerance(self) -> bool:
        return self.deviation <= self.tolerance

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "length_m": round(self.length, 3),
            "deviation_m": round(self.deviation, 3),
            "tolerance_m": round(self.tolerance, 3),
            "within_tolerance": self.within_tolerance,
        }


@dataclass
class DirectionReport:
    """Отчёт в одну сторону: от одного набора осевых линий к другому."""

    title: str
    sections: List[SectionResult] = field(default_factory=list)

    @property
    def total_length(self) -> float:
        return sum(s.length for s in self.sections)

    @property
    def length_within_tolerance(self) -> float:
        return sum(s.length for s in self.sections if s.within_tolerance)

    @property
    def share_within_tolerance(self) -> float:
        total = self.total_length
        return self.length_within_tolerance / total if total else 0.0

    def deviations(self) -> np.ndarray:
        return np.array([s.deviation for s in self.sections]) if self.sections else np.zeros(0)

    def to_dict(self) -> dict:
        deviations = self.deviations()
        return {
            "title": self.title,
            "sections_total": len(self.sections),
            "sections_out_of_tolerance": sum(1 for s in self.sections if not s.within_tolerance),
            "total_length_m": round(self.total_length, 3),
            "length_within_tolerance_m": round(self.length_within_tolerance, 3),
            "share_within_tolerance": round(self.share_within_tolerance, 6),
            "deviation_median_m": round(float(np.median(deviations)), 3) if len(deviations) else None,
            "deviation_p95_m": round(float(np.percentile(deviations, 95)), 3) if len(deviations) else None,
            "deviation_max_m": round(float(deviations.max()), 3) if len(deviations) else None,
            "sections": [s.to_dict() for s in self.sections],
        }


def _geom_settings() -> ifcopenshell.geom.settings:
    """Настройки извлечения геометрии: мировые координаты, без них сравнивать нечего."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    return settings


def _centerline_from_vertices(
    vertices: np.ndarray, name: str, source: str, dn: Optional[int] = None
) -> Optional[Centerline]:
    """Восстановить ось вытянутого тела из облака его вершин.

    Первая главная компонента (SVD) — направление оси; концы — крайние
    проекции вершин на неё. radius — максимальное удаление вершины от оси,
    он же характерная «толщина» тела: если она сопоставима с длиной, тело не
    вытянуто и осевую линию из него доставать бессмысленно (см. --report-thick).
    """
    if len(vertices) < 2:
        return None

    center = vertices.mean(axis=0)
    centered = vertices - center
    _, _, right = np.linalg.svd(centered, full_matrices=False)
    axis = right[0]

    projections = centered @ axis
    start = center + axis * projections.min()
    end = center + axis * projections.max()
    if np.linalg.norm(end - start) < 1e-9:
        return None

    residuals = centered - np.outer(projections, axis)
    radius = float(np.linalg.norm(residuals, axis=1).max())
    return Centerline(name=name, start=start, end=end, radius=radius, source=source, dn=dn)


def _element_vertices(settings, element) -> Optional[np.ndarray]:
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
    except Exception:  # тело может не строиться — это не повод падать целиком
        return None
    vertices = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
    return vertices if len(vertices) else None


def load_reference_centerlines(
    path: Path, systems: Sequence[str]
) -> Tuple[List[Centerline], Dict[str, int]]:
    """Осевые линии труб эталона, отфильтрованные по системе (Т1/Т2, без «Др»).

    Труба в эталоне опознаётся не по IFC-классу (там всё —
    IfcBuildingElementProxy), а по наличию IfcPropertySet с именем «Труба»;
    система — по свойству «Имя системы» в нём же.
    """
    file = ifcopenshell.open(str(path))
    settings = _geom_settings()
    wanted = set(systems)

    centerlines: List[Centerline] = []
    stats = {"proxy_total": 0, "pipes_total": 0, "pipes_selected": 0, "geometry_failed": 0}

    for element in file.by_type("IfcBuildingElementProxy"):
        stats["proxy_total"] += 1
        psets = ifcopenshell.util.element.get_psets(element)
        pipe_pset = psets.get(REFERENCE_PIPE_PSET)
        if pipe_pset is None:
            continue
        stats["pipes_total"] += 1
        if str(pipe_pset.get(REFERENCE_SYSTEM_PROPERTY)) not in wanted:
            continue
        stats["pipes_selected"] += 1

        vertices = _element_vertices(settings, element)
        if vertices is None:
            stats["geometry_failed"] += 1
            continue
        label = str(pipe_pset.get("Наименование", "")).strip()
        system = str(pipe_pset.get(REFERENCE_SYSTEM_PROPERTY))
        name = f"{system} #{pipe_pset.get('id', element.id())}"
        line = _centerline_from_vertices(
            vertices, name=name, source=label, dn=_reference_dn(pipe_pset)
        )
        if line is None:
            stats["geometry_failed"] += 1
            continue
        centerlines.append(line)

    return centerlines, stats


def load_generated_centerlines(path: Path) -> Tuple[List[Centerline], Dict[str, int]]:
    """Осевые линии труб нашего файла — тем же способом, что и у эталона.

    Намеренно НЕ читаются Depth/ObjectPlacement напрямую: сравнивать нужно то,
    что реально увидит вьюер, а не то, что мы записали в атрибуты.
    """
    file = ifcopenshell.open(str(path))
    settings = _geom_settings()

    centerlines: List[Centerline] = []
    stats = {"pipes_total": 0, "geometry_failed": 0}

    for element in file.by_type("IfcPipeSegment"):
        stats["pipes_total"] += 1
        vertices = _element_vertices(settings, element)
        if vertices is None:
            stats["geometry_failed"] += 1
            continue
        properties = ifcopenshell.util.element.get_psets(element).get(PIPE_PSET_NAME, {})
        # Свойства нашего Pset названы по-русски, как в эталоне (задача 9
        # переигрывается): «Условный проход» — мм, «Диаметр» — м. Читаем первое,
        # второе оставлено запасным на случай файлов, собранных до переименования
        # или сторонним инструментом.
        dn = properties.get("Условный проход")
        if dn is None and properties.get("Диаметр") is not None:
            dn = round(float(properties["Диаметр"]) * 1000.0)
        line = _centerline_from_vertices(
            vertices,
            name=element.Name or f"#{element.id()}",
            source="IfcPipeSegment",
            dn=int(dn) if dn is not None else None,
        )
        if line is None:
            stats["geometry_failed"] += 1
            continue
        centerlines.append(line)

    return centerlines, stats


def _reference_dn(pipe_pset: dict) -> Optional[int]:
    """DN трубы эталона в мм: сперва свойство «Диаметр», затем обозначение по ГОСТ.

    Свойство «Диаметр» в эталоне записано в МЕТРАХ и приоритетно — это явное
    числовое поле. Но у 18 из 130 труб систем Т1/Т2 оно не заполнено, при том
    что «Наименование» у них есть и содержит обозначение
    "Ст 426х9,0/560 ППУ-ПЭ ...", где 426 — тот самый диаметр. Пока разбирался
    только «Диаметр», эти 214.17 м попадали в строку «не указан», занижали
    длину по DN 426 почти вдвое и раздували расхождение с нашим файлом до
    +135 % вместо фактических +27.8 %.

    Восстанавливать DN по толщине BREP-тела по-прежнему нельзя: тело эталона
    построено по НАРУЖНОМУ диаметру оболочки (560 мм при DN 426), и подмена
    одного другим тихо исказила бы сводку длин. Обозначение — другое дело:
    это то же самое число, что и в спецификации, просто строкой.
    """
    raw = pipe_pset.get("Диаметр")
    try:
        millimetres = round(float(raw) * 1000.0)
    except (TypeError, ValueError):
        millimetres = 0
    if millimetres:
        return millimetres

    match = REFERENCE_DESIGNATION_RE.search(str(pipe_pset.get(REFERENCE_NAME_PROPERTY, "")))
    return int(match.group(1)) if match else None


def _length_by_dn(lines: List[Centerline]) -> Dict[Optional[int], float]:
    totals: Dict[Optional[int], float] = {}
    for line in lines:
        totals[line.dn] = totals.get(line.dn, 0.0) + line.length
    return totals


def _format_length_summary(
    generated: List[Centerline], reference: List[Centerline]
) -> List[str]:
    """Сводка длин по DN — сверка, не зависящая от системы координат."""
    ours = _length_by_dn(generated)
    theirs = _length_by_dn(reference)
    keys = sorted(set(ours) | set(theirs), key=lambda dn: (dn is None, dn))

    rows = ["Длины по DN (не зависят от системы координат):",
            f"    {'DN, мм':>8} {'наш файл, м':>13} {'эталон, м':>12} {'расхождение':>13}"]
    for dn in keys:
        our_length = ours.get(dn, 0.0)
        their_length = theirs.get(dn, 0.0)
        if their_length:
            difference = f"{(our_length - their_length) / their_length * 100:+.1f}%"
        else:
            difference = "нет в эталоне"
        label = str(dn) if dn is not None else "не указан"
        rows.append(f"    {label:>8} {our_length:13.2f} {their_length:12.2f} {difference:>13}")

    our_total = sum(ours.values())
    their_total = sum(theirs.values())
    total_difference = (
        f"{(our_total - their_total) / their_total * 100:+.1f}%" if their_total else "-"
    )
    rows.append(f"    {'всего':>8} {our_total:13.2f} {their_total:12.2f} {total_difference:>13}")
    rows.append(
        "    (вердикт не выносится: 3% из дорожной карты — критерий сверки с ведомостью "
        "объёмов,"
    )
    rows.append("     а здесь сравнение с эталонной моделью; перенос порога — решение человека)")
    return rows


def _distances_to_network(points: np.ndarray, network: List[Centerline]) -> np.ndarray:
    """Расстояние от каждой точки до ближайшей точки сети осевых линий.

    Классическая задача «точка — отрезок», векторизованная по всем отрезкам:
    проекция точки на отрезок зажимается в [0, 1], дальше берётся минимум по
    отрезкам. scipy не используется намеренно — directed_hausdorff из брифа
    считает расстояние между наборами ТОЧЕК, а нам нужно расстояние до
    непрерывных отрезков (иначе результат зависел бы от частоты дискретизации
    эталона), и ради этого тянуть в зависимости ещё один пакет незачем.
    """
    starts = np.array([line.start for line in network])
    ends = np.array([line.end for line in network])
    directions = ends - starts
    lengths_squared = np.einsum("ij,ij->i", directions, directions)
    lengths_squared[lengths_squared < 1e-12] = 1e-12

    delta = points[:, None, :] - starts[None, :, :]
    t = np.einsum("pij,ij->pi", delta, directions) / lengths_squared
    t = np.clip(t, 0.0, 1.0)
    closest = starts[None, :, :] + t[:, :, None] * directions[None, :, :]
    return np.linalg.norm(points[:, None, :] - closest, axis=2).min(axis=1)


def compare(
    source: List[Centerline],
    target: List[Centerline],
    *,
    title: str,
    samples: int,
    max_deviation: float,
    max_relative: float,
) -> DirectionReport:
    """Отклонение каждой осевой линии source от сети target."""
    report = DirectionReport(title=title)
    if not source or not target:
        return report

    for line in source:
        points = line.sample(samples)
        deviation = float(_distances_to_network(points, target).max())
        tolerance = min(max_deviation, max_relative * line.length)
        report.sections.append(
            SectionResult(
                name=line.name, length=line.length, deviation=deviation, tolerance=tolerance
            )
        )
    return report


def centroid(lines: Iterable[Centerline]) -> np.ndarray:
    points = np.array([p for line in lines for p in (line.start, line.end)])
    return points.mean(axis=0)


def shift(lines: List[Centerline], offset: np.ndarray) -> List[Centerline]:
    return [
        Centerline(
            name=line.name,
            start=line.start + offset,
            end=line.end + offset,
            radius=line.radius,
            source=line.source,
        )
        for line in lines
    ]


def _format_direction(report: DirectionReport, *, worst: int) -> List[str]:
    deviations = report.deviations()
    lines = [
        f"{report.title}:",
        f"  участков: {len(report.sections)}, суммарная длина: {report.total_length:.2f} м",
    ]
    if not len(deviations):
        lines.append("  нет данных для сравнения")
        return lines

    lines += [
        f"  длина в допуске: {report.share_within_tolerance * 100:.2f}% "
        f"({report.length_within_tolerance:.2f} м из {report.total_length:.2f} м)",
        f"  отклонение, м: медиана {np.median(deviations):.3f}, "
        f"p95 {np.percentile(deviations, 95):.3f}, максимум {deviations.max():.3f}",
    ]
    out = sorted(
        (s for s in report.sections if not s.within_tolerance),
        key=lambda s: s.deviation,
        reverse=True,
    )
    if out:
        lines.append(f"  вне допуска: {len(out)} участков, худшие {min(worst, len(out))}:")
        for section in out[:worst]:
            lines.append(
                f"    {section.name:<28} длина {section.length:7.2f} м  "
                f"отклонение {section.deviation:9.3f} м  (допуск {section.tolerance:.3f} м)"
            )
    else:
        lines.append("  вне допуска: нет")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Количественная сверка геометрии труб с эталонным IFC (задача 5 брифа)."
    )
    parser.add_argument("--generated", type=Path, required=True, help="сгенерированный нами IFC")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE, help="эталонный IFC")
    parser.add_argument("--systems", default=",".join(DEFAULT_SYSTEMS),
                        help="системы эталона через запятую (по умолчанию Т1,Т2,Т1/Т2; «Др» не берём)")
    parser.add_argument("--max-deviation", type=float, default=DEFAULT_MAX_DEVIATION_M,
                        help=f"абсолютный допуск, м (по умолчанию {DEFAULT_MAX_DEVIATION_M})")
    parser.add_argument("--max-relative", type=float, default=DEFAULT_MAX_RELATIVE,
                        help=f"относительный допуск, доля длины участка (по умолчанию {DEFAULT_MAX_RELATIVE})")
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES,
                        help="точек дискретизации на участок")
    parser.add_argument("--align", choices=("none", "centroid"), default="none",
                        help="'centroid' — совместить центры масс (ДИАГНОСТИКА формы, не приёмка)")
    parser.add_argument("--worst", type=int, default=15, help="сколько худших участков печатать")
    parser.add_argument("--report-thick", action="store_true",
                        help="показать тела, у которых толщина сопоставима с длиной (ось недостоверна)")
    parser.add_argument("--json", type=Path, help="куда сохранить отчёт в JSON")
    args = parser.parse_args(argv)

    for path in (args.generated, args.reference):
        if not path.exists():
            print(f"Файл не найден: {path}", file=sys.stderr)
            return 2

    systems = tuple(s.strip() for s in args.systems.split(",") if s.strip())
    reference, reference_stats = load_reference_centerlines(args.reference, systems)
    generated, generated_stats = load_generated_centerlines(args.generated)

    if not reference:
        print("В эталоне не нашлось труб выбранных систем — сравнивать не с чем.", file=sys.stderr)
        return 2
    if not generated:
        print("В сгенерированном файле нет IfcPipeSegment — сравнивать нечего.", file=sys.stderr)
        return 2

    offset = np.zeros(3)
    if args.align == "centroid":
        offset = centroid(reference) - centroid(generated)
        generated = shift(generated, offset)

    forward = compare(
        generated, reference,
        title="Наша геометрия относительно эталона",
        samples=args.samples, max_deviation=args.max_deviation, max_relative=args.max_relative,
    )
    backward = compare(
        reference, generated,
        title="Покрытие эталона нашей геометрией",
        samples=args.samples, max_deviation=args.max_deviation, max_relative=args.max_relative,
    )

    print(f"Сгенерированный файл: {args.generated}")
    print(f"Эталон:               {args.reference}")
    print(
        f"Эталон: {reference_stats['proxy_total']} элементов, из них труб "
        f"{reference_stats['pipes_total']}, систем {'/'.join(systems)} — "
        f"{reference_stats['pipes_selected']}, осевых линий получено {len(reference)}"
    )
    print(
        f"Наш файл: IfcPipeSegment {generated_stats['pipes_total']}, "
        f"осевых линий получено {len(generated)}"
    )
    print(
        f"Допуск: отклонение <= min({args.max_deviation} м, "
        f"{args.max_relative * 100:.0f}% длины участка); дискретизация {args.samples} точек"
    )
    if args.align == "centroid":
        print(
            f"ВЫРАВНИВАНИЕ (диагностика формы, не приёмка): наша геометрия сдвинута на "
            f"({offset[0]:.2f}, {offset[1]:.2f}, {offset[2]:.2f}) м до совпадения центров масс"
        )
    else:
        print("Выравнивание координат: не применялось (сравниваются координаты как есть)")
    print()
    for line in _format_direction(forward, worst=args.worst):
        print(line)
    print()
    for line in _format_direction(backward, worst=args.worst):
        print(line)
    print()
    for line in _format_length_summary(generated, reference):
        print(line)

    if args.report_thick:
        thick = [
            line for line in generated + reference
            if line.length > 0 and line.radius / line.length > 0.5
        ]
        print()
        print(f"Тела с недостоверной осью (толщина > половины длины): {len(thick)}")
        for line in thick[: args.worst]:
            print(f"    {line.name:<28} длина {line.length:7.2f} м  толщина {line.radius:7.3f} м")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated": str(args.generated),
            "reference": str(args.reference),
            "systems": list(systems),
            "max_deviation_m": args.max_deviation,
            "max_relative": args.max_relative,
            "samples": args.samples,
            "align": args.align,
            "align_offset_m": [round(float(v), 3) for v in offset],
            "reference_stats": reference_stats,
            "generated_stats": generated_stats,
            "forward": forward.to_dict(),
            "backward": backward.to_dict(),
            "length_by_dn": {
                "generated": {str(k): round(v, 3) for k, v in _length_by_dn(generated).items()},
                "reference": {str(k): round(v, 3) for k, v in _length_by_dn(reference).items()},
            },
        }
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print(f"JSON-отчёт: {args.json}")

    return 0 if forward.share_within_tolerance >= 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
