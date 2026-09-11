"""Задача 28: измерить типовые габариты объектов по эталонному IFC.

Зачем
------
Узлы сети (арматура, футляры, каналы, точки подключения) до сих пор попадали в
IFC без формы — только точкой размещения. В вьюере это выглядит как пустое
место: объект есть в дереве, а посмотреть не на что. Габариты неоткуда было
взять, но эталонная модель проекта — это ровно те же объекты, построенные
проектировщиком, и её можно измерить.

Как измеряется
---------------
Два источника, в порядке доверия:

1. **Свойства эталона.** У «Канала», «Камеры», «Неподвижной опоры» есть
   «Ширина» / «Длина» / «Высота», у «Футляра» и «Колодца» — «Диаметр» и
   «Длина». Это то, что проектировщик написал сам, и оно точнее любого обмера.
2. **Геометрия**, если свойств нет (так у «Трубопроводной арматуры» и «Точки
   подключения к внешним сетям»). Габарит берётся не по осям мира, а по
   СОБСТВЕННЫМ осям объекта: облако вершин центрируется, раскладывается по
   SVD, и размеры считаются вдоль главных направлений. Разница принципиальная:
   канал, идущий под 30° к осям координат, в мировом габаритном ящике даёт
   20.02 x 8.91 м вместо реальных 13.98 x 1.74 м — то есть измерение по осям
   мира завышает размер вдвое и больше.

Что на выходе
--------------
Таблица «тип объекта -> габариты» в консоль и (с --json) в файл. Значения —
медианы по всем объектам своего типа: единичный объект может быть нетиповым,
а медиана переживает выбросы. Эти же числа зашиты в
src/pdf_to_ifc/node_sizes.py — модуль ссылается на этот скрипт, чтобы их можно
было перепроверить и пересчитать, а не принимать на веру.

Запуск
-------
    python scripts/measure_reference_sizes.py
    python scripts/measure_reference_sizes.py --json data/derived/reference_node_sizes.json
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_geometry import DEFAULT_REFERENCE, _geom_settings  # noqa: E402

# Имена свойств габаритов в эталоне и порядок, в котором их складывать в
# (длина, ширина, высота).
SIZE_PROPERTIES = ("Длина", "Ширина", "Высота")


def oriented_extents(vertices: np.ndarray) -> Tuple[float, float, float]:
    """Габарит по собственным осям объекта: (длина, ширина, высота).

    По вертикали берётся честная разница отметок — здание не «наклонено», а вот
    в плане объект может идти под любым углом, поэтому горизонтальные размеры
    считаются вдоль главных направлений облака вершин, а не вдоль осей мира.
    """
    height = float(vertices[:, 2].max() - vertices[:, 2].min())
    flat = vertices[:, :2] - vertices[:, :2].mean(axis=0)
    if len(flat) < 2:
        return (0.0, 0.0, height)
    _, _, right = np.linalg.svd(flat, full_matrices=False)
    projected = flat @ right.T
    length = float(projected[:, 0].max() - projected[:, 0].min())
    width = float(projected[:, 1].max() - projected[:, 1].min())
    return (max(length, width), min(length, width), height)


def measure(path: Path) -> Dict[str, dict]:
    """Габариты по типам объектов эталона: медианы плюс источник значений."""
    file = ifcopenshell.open(str(path))
    settings = _geom_settings()

    measured: Dict[str, List[Tuple[float, float, float]]] = collections.defaultdict(list)
    declared: Dict[str, List[Tuple[float, float, float]]] = collections.defaultdict(list)
    diameters: Dict[str, List[float]] = collections.defaultdict(list)

    for element in file.by_type("IfcBuildingElementProxy"):
        psets = ifcopenshell.util.element.get_psets(element)
        kind = next((name for name in psets if name != "id"), None)
        if kind is None:
            continue
        properties = psets[kind]

        stated = []
        for name in SIZE_PROPERTIES:
            try:
                stated.append(float(properties.get(name)))
            except (TypeError, ValueError):
                stated = []
                break
        if stated:
            declared[kind].append(tuple(stated))  # type: ignore[arg-type]

        try:
            diameters[kind].append(float(properties["Диаметр"]))
        except (KeyError, TypeError, ValueError):
            pass

        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
        except Exception:
            continue
        vertices = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
        if len(vertices) >= 2:
            measured[kind].append(oriented_extents(vertices))

    result: Dict[str, dict] = {}
    for kind in sorted(set(measured) | set(declared), key=lambda k: -len(measured.get(k, []))):
        rows = declared.get(kind) or measured.get(kind) or []
        if not rows:
            continue
        array = np.array(rows)
        entry = {
            "count": len(rows),
            "source": "свойства эталона" if kind in declared else "геометрия (собственные оси)",
            "length_m": round(float(np.median(array[:, 0])), 2),
            "width_m": round(float(np.median(array[:, 1])), 2),
            "height_m": round(float(np.median(array[:, 2])), 2),
        }
        if diameters.get(kind):
            entry["diameter_m"] = round(float(np.median(diameters[kind])), 3)
        if measured.get(kind) and kind in declared:
            box = np.array(measured[kind])
            entry["geometry_length_m"] = round(float(np.median(box[:, 0])), 2)
        result[kind] = entry
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--json", type=Path, help="куда сохранить таблицу")
    args = parser.parse_args(argv)

    if not args.reference.exists():
        print(f"Нет эталона: {args.reference}", file=sys.stderr)
        return 2

    table = measure(args.reference)
    print(f"Эталон: {args.reference.name}")
    print(f"{'тип объекта':<34} {'шт':>4} {'длина':>7} {'ширина':>7} {'высота':>7} "
          f"{'Ø, м':>6}  источник")
    for kind, entry in table.items():
        diameter = f"{entry['diameter_m']:6.3f}" if "diameter_m" in entry else "     -"
        print(f"{kind:<34} {entry['count']:4d} {entry['length_m']:7.2f} {entry['width_m']:7.2f} "
              f"{entry['height_m']:7.2f} {diameter}  {entry['source']}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
