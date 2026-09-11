"""Демонстрация задачи 1 брифа: экспорт трассы с waypoints и отводами BEND.

Зачем нужен отдельный скрипт
-----------------------------
На тестовом датасете (data/samples/parnas_*) точек изгиба нет вовсе: координаты
там синтетические, строго по прямой с шагом 50 м. Поэтому на нём не видно ни
разбиения нитки на под-сегменты, ни фитингов изгиба — то есть ровно того, что
чинила задача 1 брифа. `export_sample_ifc.py --demo-bend` ставит одну
искусственную точку излома, чего хватает, чтобы посмотреть на механику в
вьюере, но не хватает, чтобы что-то доказать числом.

Здесь берётся другой вход: узлы и точки изгиба снимаются с ЭТАЛОННОЙ трассы
(data/raw/ПРНС_...I2300.ifc, система Т1), а дальше всё штатно — обычная
ThermalNetworkModel и обычный generate_ifc_from_network(). Это проверка
ГЕНЕРАТОРА на заведомо правильных входных данных, отдельно от вопроса «откуда
взять координаты» (это задача 18, оцифровка плана из PDF).

Что важно понимать про результат: 100 % длины в допуске здесь не означает, что
инструмент готов. Означает ровно одно — если подать правильные waypoints,
геометрия ложится на эталон с точностью до миллиметра, и виновата в текущем
расхождении не генерация, а отсутствие оцифрованных координат.

Датасет не трогается: модель строится в памяти, IFC пишется в out/ (в .gitignore).

Как собирается маршрут
-----------------------
В эталоне трасса Т1 — это 65 отдельных прямых тел, а не полилиния. 86 концов из
130 стыкуются точно (расхождение < 1 мм), остальные разорваны арматурой и
компенсаторами с зазорами 1-2 м. Поэтому куски собираются по совпадающим концам
в НЕСКОЛЬКО цепочек (15 штук на текущем файле), а не в одну: сшивать через
зазоры значило бы придумывать геометрию, которой в эталоне нет.

Каждая --step-я вершина цепочки становится узлом сети, вершины между узлами —
точками изгиба ребра. При --step 4 это 2-3 waypoints на участок, как и будет
после оцифровки плана.

Запуск
-------
    python scripts/make_bend_demo.py
    python scripts/make_bend_demo.py --step 6 --output out/demo6.ifc
    python scripts/make_bend_demo.py --json out/bend_demo.json

Код возврата: 0 — файл собран; 2 — нет эталона или из него не собралось ни одной
цепочки длиной хотя бы в три вершины.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import ifcopenshell.util.placement

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdf_to_ifc.ifc_export import generate_ifc_from_network, save  # noqa: E402
from pdf_to_ifc.model import NetworkEdge, NetworkNode, ThermalNetworkModel  # noqa: E402
from validate_geometry import (  # noqa: E402
    DEFAULT_MAX_DEVIATION_M,
    DEFAULT_MAX_RELATIVE,
    DEFAULT_REFERENCE,
    Centerline,
    _distances_to_network,
    load_generated_centerlines,
    load_reference_centerlines,
)

DEFAULT_OUTPUT = REPO_ROOT / "out" / "parnas_waypoints_demo.ifc"
DEFAULT_STEP = 4
# Диаметр и изоляция берутся одни на всю демо-трассу: скрипт демонстрирует
# ГЕОМЕТРИЮ, а раскладка диаметров по участкам — вопрос к данным (см. открытый
# вопрос 4 в REPORT_geometry_fix.md), и подставлять её здесь наугад незачем.
DEMO_DIAMETER = 426
DEMO_MATERIAL = "Steel"
DEMO_INSULATION = "PPU+PE"
DEMO_LAYING_TYPE = "underground_ducted"
# Глубина заложения для z_surface: отметка лотка плюс типовое заглубление.
# Число условное и в сверке геометрии не участвует — z_pipe_bottom берётся из
# эталона, а z_surface модель требует заполнить.
DEMO_COVER_M = 1.8


def _key(point: Sequence[float]) -> Tuple[float, float, float]:
    """Вершина, огрублённая до миллиметра — ключ для склейки кусков."""
    return tuple(round(float(c), 3) for c in point)


def polylines(lines: List[Centerline]) -> List[List[np.ndarray]]:
    """Сложить отдельные прямые куски в упорядоченные ломаные по общим концам.

    Возвращаются цепочки длиной хотя бы в три вершины (то есть с минимум одной
    точкой изгиба), от длинной к короткой. Куски, у которых общих концов нет,
    отбрасываются: одиночный отрезок для демонстрации waypoints бесполезен.
    """
    adjacency: Dict[Tuple[float, float, float], List[int]] = defaultdict(list)
    for index, line in enumerate(lines):
        adjacency[_key(line.start)].append(index)
        adjacency[_key(line.end)].append(index)

    used: set = set()

    def walk(start: Tuple[float, float, float]) -> List[np.ndarray]:
        chain = [np.array(start, dtype=float)]
        current = start
        while True:
            following = next((i for i in adjacency[current] if i not in used), None)
            if following is None:
                return chain
            used.add(following)
            line = lines[following]
            other = _key(line.end) if _key(line.start) == current else _key(line.start)
            chain.append(np.array(other, dtype=float))
            current = other

    chains: List[List[np.ndarray]] = []
    # Сперва от свободных концов (вершина принадлежит одному куску) — так
    # цепочка получается целиком, а не с середины. Потом всё, что осталось.
    for start, incident in sorted(adjacency.items(), key=lambda item: len(item[1])):
        if len(incident) != 1 or incident[0] in used:
            continue
        chain = walk(start)
        if len(chain) > 2:
            chains.append(chain)
    for start, incident in adjacency.items():
        if all(index in used for index in incident):
            continue
        chain = walk(start)
        if len(chain) > 2:
            chains.append(chain)

    return sorted(chains, key=len, reverse=True)


def build_model(chains: List[List[np.ndarray]], *, step: int) -> ThermalNetworkModel:
    """Собрать доменную модель: каждая step-я вершина — узел, промежуточные — waypoints.

    Нитки supply и return строятся по одним и тем же точкам — так же, как это
    делает основной датасет. В эталоне Т1 и Т2 разнесены на 0.4-0.8 м, и это
    расхождение здесь сознательно не имитируется: разнос ниток в геометрии —
    открытый вопрос 3 отчёта, а не то, что скрипт вправе решить сам.
    """
    model = ThermalNetworkModel(
        project_name="Демо waypoints (узлы сняты с эталона)",
        source="data/raw/ПРНС_ЛО_ТКР-ТС_У1_Э1_I2300.ifc, система Т1",
    )

    for chain_number, chain in enumerate(chains, start=1):
        indices = list(range(0, len(chain) - 1, step))
        if indices[-1] != len(chain) - 1:
            indices.append(len(chain) - 1)
        if len(indices) < 2:
            continue

        names = []
        for position, index in enumerate(indices):
            point = chain[index]
            name = f"У{chain_number}-{position + 1}"
            model.add_node(NetworkNode(
                name=name,
                x=float(point[0]),
                y=float(point[1]),
                z_surface=float(point[2]) + DEMO_COVER_M,
                z_pipe_bottom=float(point[2]),
                node_type="chamber" if position in (0, len(indices) - 1) else "support",
            ))
            names.append(name)

        for position in range(len(indices) - 1):
            first, last = indices[position], indices[position + 1]
            waypoints = [tuple(float(c) for c in chain[i]) for i in range(first + 1, last)]
            points = [chain[i] for i in range(first, last + 1)]
            length = sum(float(np.linalg.norm(b - a)) for a, b in zip(points, points[1:]))
            for branch in ("supply", "return"):
                model.add_edge(NetworkEdge(
                    start_node=names[position],
                    end_node=names[position + 1],
                    branch=branch,
                    diameter=DEMO_DIAMETER,
                    length=round(length, 2),
                    material=DEMO_MATERIAL,
                    insulation=DEMO_INSULATION,
                    laying_type=DEMO_LAYING_TYPE,
                    waypoints=waypoints,
                ))

    return model


def bend_points(file) -> List[Tuple[float, float, float]]:
    """Координаты фитингов изгиба из готового файла, без повторов.

    Точка изгиба одна на обе нитки, а фитингов в файле два (по одному на
    supply и return), поэтому список схлопывается по координате.
    """
    bends = [f for f in file.by_type("IfcPipeFitting") if f.PredefinedType == "BEND"]
    return sorted({
        tuple(round(float(v), 3) for v in
              ifcopenshell.util.placement.get_local_placement(bend.ObjectPlacement)[:3, 3])
        for bend in bends
    })


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE,
                        help="эталонный IFC, с которого снимается трасса")
    parser.add_argument("--system", default="Т1",
                        help="система эталона, по которой строится маршрут (по умолчанию Т1)")
    parser.add_argument("--step", type=int, default=DEFAULT_STEP,
                        help=f"каждая step-я вершина становится узлом (по умолчанию {DEFAULT_STEP})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"куда писать IFC (по умолчанию {DEFAULT_OUTPUT})")
    parser.add_argument("--json", type=Path, help="сохранить осевые линии и точки изгиба в JSON")
    args = parser.parse_args(argv)

    if not args.reference.exists():
        print(f"Эталон не найден: {args.reference}", file=sys.stderr)
        return 2
    if args.step < 2:
        print("--step должен быть не меньше 2, иначе точек изгиба не остаётся", file=sys.stderr)
        return 2

    source_lines, _ = load_reference_centerlines(args.reference, (args.system,))
    chains = polylines(source_lines)
    if not chains:
        print(
            f"Из системы {args.system} не собралось ни одной цепочки длиной в три вершины",
            file=sys.stderr,
        )
        return 2

    model = build_model(chains, step=args.step)
    file = generate_ifc_from_network(model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(file, args.output)

    bends = bend_points(file)
    generated, _ = load_generated_centerlines(args.output)

    # Сверяемся со ВСЕЙ теплосетью эталона, а не только с системой-источником:
    # именно так работает validate_geometry.py, и цифры должны быть сравнимы.
    reference, _ = load_reference_centerlines(args.reference, ("Т1", "Т2", "Т1/Т2"))
    deviations = np.array([
        float(_distances_to_network(line.sample(20), reference).max()) for line in generated
    ])
    tolerances = np.array([
        min(DEFAULT_MAX_DEVIATION_M, DEFAULT_MAX_RELATIVE * line.length) for line in generated
    ])
    lengths = np.array([line.length for line in generated])
    within = float(lengths[deviations <= tolerances].sum())
    total = float(lengths.sum())

    print(f"Эталон:  {args.reference} (система {args.system})")
    print(f"Записан: {args.output}")
    print(f"Цепочек собрано: {len(chains)}, вершин в них: {[len(c) for c in chains]}")
    print(f"Узлов: {len(model.nodes)}, ниток: {len(model.edges)}, "
          f"IfcPipeSegment: {len(file.by_type('IfcPipeSegment'))}, точек изгиба: {len(bends)}")
    print(f"Суммарная длина: {total:.2f} м")
    print(f"Отклонение от эталона, м: медиана {np.median(deviations):.3f}, "
          f"p95 {np.percentile(deviations, 95):.3f}, максимум {deviations.max():.3f}")
    print(f"Длина в допуске: {within / total * 100:.2f}% ({within:.2f} из {total:.2f} м)")

    if args.json:
        payload = {
            "segments": [
                {
                    "n": line.name,
                    "dn": line.dn,
                    "l": round(line.length, 3),
                    "a": [round(float(v), 3) for v in line.start],
                    "b": [round(float(v), 3) for v in line.end],
                    "dev": round(float(deviation), 3),
                }
                for line, deviation in zip(generated, deviations)
            ],
            "bends": [list(point) for point in bends],
            "stats": {
                "nodes": len(model.nodes),
                "edges": len(model.edges),
                "segments": len(generated),
                "bends": len(bends),
                "totalLength": round(total, 2),
                "shareWithin": round(within / total, 4),
                "devMedian": round(float(np.median(deviations)), 3),
                "devMax": round(float(deviations.max()), 3),
            },
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        print(f"JSON: {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
