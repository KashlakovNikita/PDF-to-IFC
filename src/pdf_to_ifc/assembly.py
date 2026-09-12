"""Задача 19: сборка модели из нескольких источников данных.

Чего не хватало
----------------
Данные приходят кусками и из разных мест: координаты узлов — из DWG, отметки
лотка — с бумаги руками, спецификация — из PDF (когда экстрактор будет), а на
объекте инженер что-то поправит через веб-форму. Между «данные есть» и
«модель построена» до сих пор ничего не было: каждый поставщик собирал
`ThermalNetworkModel` сам и целиком. Это работает ровно до первого случая,
когда один источник знает координаты, а другой — отметки: их приходится
сливать вручную, каждый раз заново и каждый раз по-своему.

Здесь этот шов сделан один раз. Поставщики дают ЧАСТИЧНЫЕ данные, сборщик
сливает их в одну модель, а откуда что взялось — сохраняет.

Слияние по ПОЛЯМ, а не по объектам
-----------------------------------
Ключевое решение. Источник, знающий про узел только координаты, не должен
затирать его отметки, пришедшие из другого места. Поэтому объединяются не
записи целиком, а каждое поле по отдельности: у одного узла x/y могут быть из
DWG, отметка земли — с плана, отметка лотка — из ручного ввода, тип — из
датасета. Провенанс (что откуда) остаётся в результате, его видно в отчёте.

Порядок источников — это порядок доверия: первый, кто дал непустое значение,
его и определяет. Если следующий источник даёт ДРУГОЕ значение, это не
молчаливая перезапись, а зафиксированный конфликт: оба значения попадают в
`AssemblyResult.conflicts`, а решать, кто прав, — человеку. Числа сравниваются
с допуском (координаты в миллиметрах совпадать не обязаны), строки — точно.

Чего сборщик не делает
-----------------------
Не выдумывает недостающее. Если у узла нет отметки, а у ребра — диаметра, такой
объект в модель не попадает, и это записывается в `AssemblyResult.gaps` с
перечнем недостающих полей. Неполные данные — норма, а не сбой: в реальном
проекте часть узлов известна не полностью, и лучше отдать модель из того, что
есть, вместе со списком дыр, чем упасть или подставить нули.

Единственное исключение — параметр `defaults`: им вызывающий может явно
сказать, чем заполнять текстовые атрибуты вроде материала. Это осознанное
решение вызывающего, а не догадка сборщика, поэтому в провенансе такие поля
помечены источником «по умолчанию».

Как этим пользоваться
----------------------
    from pdf_to_ifc.assembly import Source, assemble, source_from_model
    from pdf_to_ifc.manual_input import parse_manual_text

    result = assemble([
        source_from_model(dwg_model, "DWG л.2"),          # координаты, изгибы
        source_from_model(manual_model, "ручной ввод"),   # отметки, давление
    ], project_name="Парнас")

    result.model      # ThermalNetworkModel — то, что уйдёт в IFC-экспорт
    result.gaps       # чего не хватило и у каких объектов
    result.conflicts  # где источники разошлись
    result.report()   # то же самое человеческим текстом
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pdf_to_ifc.manual_input import UNKNOWN_TEXT_VALUES
from pdf_to_ifc.model import NetworkEdge, NetworkNode, ThermalNetworkModel

# Координаты и отметки, совпавшие с этой точностью, конфликтом не считаются:
# источники округляют по-разному, и миллиметр расхождения — не разногласие.
NUMERIC_TOLERANCE = 0.001

# Поля, без которых объект в модель не построить.
REQUIRED_NODE_FIELDS = ("x", "y", "z_surface", "z_pipe_bottom", "node_type")
REQUIRED_EDGE_FIELDS = ("diameter", "length", "material", "insulation", "laying_type")


@dataclass
class NodeData:
    """Частичные данные об узле: заполнено то, что источник знает.

    `name` и `branch` — не данные, а адрес: по ним записи разных источников
    узнают друг друга. Всё остальное необязательно.
    """

    name: str
    branch: str = "single"
    x: Optional[float] = None
    y: Optional[float] = None
    z_surface: Optional[float] = None
    z_pipe_bottom: Optional[float] = None
    node_type: Optional[str] = None

    @property
    def key(self) -> Tuple[str, str]:
        return (self.name, self.branch)


@dataclass
class EdgeData:
    """Частичные данные об участке. Адрес — (начало, конец, нитка)."""

    start_node: str
    end_node: str
    branch: str = "single"
    diameter: Optional[int] = None
    length: Optional[float] = None
    material: Optional[str] = None
    insulation: Optional[str] = None
    laying_type: Optional[str] = None
    pressure_mpa: Optional[float] = None
    temperature_c: Optional[float] = None
    gost_designation: Optional[str] = None
    waypoints: Optional[List[Tuple[float, float, float]]] = None

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.start_node, self.end_node, self.branch)


@dataclass
class Source:
    """Один поставщик данных: имя (для провенанса) и то, что он знает."""

    name: str
    nodes: List[NodeData] = field(default_factory=list)
    edges: List[EdgeData] = field(default_factory=list)


@dataclass
class Conflict:
    """Два источника дали разное значение одного поля."""

    obj: str
    field_name: str
    kept: Any
    kept_source: str
    rejected: Any
    rejected_source: str

    def __str__(self) -> str:
        return (f"{self.obj}: {self.field_name} = {self.kept!r} ({self.kept_source}), "
                f"но {self.rejected_source} даёт {self.rejected!r}")


@dataclass
class Gap:
    """Объекту не хватило полей, поэтому он в модель не попал."""

    obj: str
    missing: List[str]
    reason: str = "нет обязательных полей"

    def __str__(self) -> str:
        return f"{self.obj}: {self.reason} — {', '.join(self.missing)}"


@dataclass
class AssemblyResult:
    """Собранная модель плюс всё, что стоит знать о том, как она собралась."""

    model: ThermalNetworkModel
    provenance: Dict[str, Dict[str, str]] = field(default_factory=dict)
    conflicts: List[Conflict] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)

    def sources_of(self, obj: str) -> Dict[str, str]:
        """Откуда взялось каждое поле объекта."""
        return self.provenance.get(obj, {})

    def report(self) -> str:
        lines = [
            f"Собрано: узлов {len(self.model.nodes)}, участков {len(self.model.edges)}",
        ]
        if self.gaps:
            lines.append(f"Не собрано объектов: {len(self.gaps)}")
            lines += [f"    {gap}" for gap in self.gaps]
        if self.conflicts:
            lines.append(f"Расхождения между источниками: {len(self.conflicts)}")
            lines += [f"    {conflict}" for conflict in self.conflicts]
        if not self.gaps and not self.conflicts:
            lines.append("Дыр и расхождений нет")
        return "\n".join(lines)


def _same(first: Any, second: Any, *, tolerance: float = NUMERIC_TOLERANCE) -> bool:
    """Считаются ли два значения одинаковыми (числа — с допуском)."""
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return math.isclose(float(first), float(second), abs_tol=tolerance)
    if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)):
        return len(first) == len(second) and all(
            _same(a, b, tolerance=tolerance) for a, b in zip(first, second)
        )
    return first == second


def _merge_records(
    records: Sequence[Tuple[str, Any]],
    data_fields: Sequence[str],
    label: str,
    conflicts: List[Conflict],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Слить записи об одном объекте по полям, в порядке доверия источников.

    Первое непустое значение поля выигрывает. Отличающееся значение из
    следующего источника не затирает его молча, а попадает в conflicts — при
    этом сборка продолжается: остановиться на расхождении хуже, чем собрать
    модель и показать, где источники разошлись.
    """
    merged: Dict[str, Any] = {}
    provenance: Dict[str, str] = {}

    for source_name, record in records:
        for name in data_fields:
            value = getattr(record, name, None)
            if value is None:
                continue
            if name not in merged:
                merged[name] = value
                provenance[name] = source_name
            elif not _same(merged[name], value):
                conflicts.append(Conflict(
                    obj=label, field_name=name,
                    kept=merged[name], kept_source=provenance[name],
                    rejected=value, rejected_source=source_name,
                ))
    return merged, provenance


def _data_field_names(data_class) -> List[str]:
    """Поля-данные записи (адресные не считаются)."""
    address = {"name", "branch", "start_node", "end_node"}
    return [f.name for f in fields(data_class) if f.name not in address]


def assemble(
    sources: Sequence[Source],
    *,
    project_name: str = "Сборка из нескольких источников",
    defaults: Optional[Dict[str, Any]] = None,
) -> AssemblyResult:
    """Слить источники в одну модель.

    Источники перечисляются в порядке убывания доверия. `defaults` — явное
    решение вызывающего, чем заполнять недостающие текстовые атрибуты
    (например `{"material": "Сталь"}`); без него такие поля считаются дырой.
    """
    defaults = defaults or {}
    conflicts: List[Conflict] = []
    gaps: List[Gap] = []
    provenance: Dict[str, Dict[str, str]] = {}

    node_records: Dict[Tuple[str, str], List[Tuple[str, NodeData]]] = {}
    edge_records: Dict[Tuple[str, str, str], List[Tuple[str, EdgeData]]] = {}
    for source in sources:
        for node in source.nodes:
            node_records.setdefault(node.key, []).append((source.name, node))
        for edge in source.edges:
            edge_records.setdefault(edge.key, []).append((source.name, edge))

    model = ThermalNetworkModel(
        project_name=project_name,
        source="; ".join(source.name for source in sources) or "не указан",
    )

    node_fields = _data_field_names(NodeData)
    built_nodes: set = set()
    for (name, branch), records in node_records.items():
        label = name if branch == "single" else f"{name}@{branch}"
        merged, where = _merge_records(records, node_fields, label, conflicts)
        for key, value in defaults.items():
            if key in node_fields and key not in merged:
                merged[key] = value
                where[key] = "по умолчанию"

        missing = [f for f in REQUIRED_NODE_FIELDS if f not in merged]
        if missing:
            gaps.append(Gap(obj=label, missing=missing))
            continue

        model.add_node(NetworkNode(
            name=name, branch=branch,
            x=float(merged["x"]), y=float(merged["y"]),
            z_surface=float(merged["z_surface"]),
            z_pipe_bottom=float(merged["z_pipe_bottom"]),
            node_type=str(merged["node_type"]),
        ))
        built_nodes.add((name, branch))
        provenance[label] = where

    edge_fields = _data_field_names(EdgeData)
    for (start, end, branch), records in edge_records.items():
        label = f"{start}->{end}" + ("" if branch == "single" else f" ({branch})")
        merged, where = _merge_records(records, edge_fields, label, conflicts)
        for key, value in defaults.items():
            if key in edge_fields and key not in merged:
                merged[key] = value
                where[key] = "по умолчанию"

        missing = [f for f in REQUIRED_EDGE_FIELDS if f not in merged]
        if missing:
            gaps.append(Gap(obj=label, missing=missing))
            continue

        # Узел ищется сначала свой по нитке, потом общий — так же, как это
        # делает сама модель (задача 26).
        absent = [
            node for node in (start, end)
            if (node, branch) not in built_nodes and (node, "single") not in built_nodes
        ]
        if absent:
            gaps.append(Gap(obj=label, missing=absent, reason="нет узлов"))
            continue

        model.add_edge(NetworkEdge(
            start_node=start, end_node=end, branch=branch,
            diameter=int(merged["diameter"]), length=float(merged["length"]),
            material=str(merged["material"]), insulation=str(merged["insulation"]),
            laying_type=str(merged["laying_type"]),
            pressure_mpa=merged.get("pressure_mpa"),
            temperature_c=merged.get("temperature_c"),
            gost_designation=merged.get("gost_designation"),
            waypoints=list(merged.get("waypoints") or []),
        ))
        provenance[label] = where

    return AssemblyResult(model=model, provenance=provenance,
                          conflicts=conflicts, gaps=gaps)


def _known(value: Any) -> Any:
    """Заглушка — это не значение.

    Ручной ввод обязан чем-то заполнить материал, изоляцию и тип прокладки:
    модель требует их непустыми. Он ставит «не указан», и для сборки это
    отсутствие знания, а не данные. Без такой очистки источник с заглушкой
    вступал бы в ложное расхождение с источником, где материал реально известен,
    и в отчёте появлялись бы конфликты на ровном месте.
    """
    if isinstance(value, str) and value.strip() in UNKNOWN_TEXT_VALUES:
        return None
    return value


def source_from_model(model: ThermalNetworkModel, name: str) -> Source:
    """Обернуть готовую модель в источник — чтобы её можно было слить с другими.

    Так подключается всё, что уже умеет строить модель целиком: выгрузка из DWG
    (`scripts/extract_from_dwg.py`), текст ручного ввода (`manual_input`),
    сохранённый JSON. Источнику не нужно ничего знать про сборку — он просто
    отдаёт то, что знает.
    """
    return Source(
        name=name,
        nodes=[
            NodeData(
                name=node.name, branch=node.branch, x=node.x, y=node.y,
                z_surface=node.z_surface, z_pipe_bottom=node.z_pipe_bottom,
                node_type=node.node_type,
            )
            for node in model.nodes.values()
        ],
        edges=[
            EdgeData(
                start_node=edge.start_node, end_node=edge.end_node, branch=edge.branch,
                diameter=edge.diameter, length=edge.length,
                material=_known(edge.material), insulation=_known(edge.insulation),
                laying_type=_known(edge.laying_type),
                pressure_mpa=edge.pressure_mpa, temperature_c=edge.temperature_c,
                gost_designation=edge.gost_designation,
                waypoints=list(edge.waypoints) or None,
            )
            for edge in model.edges
        ],
    )
