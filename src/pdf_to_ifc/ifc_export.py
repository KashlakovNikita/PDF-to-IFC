"""Генерация IFC из доменной модели (src/pdf_to_ifc/model.py).

Контракт с Треком A: generate_ifc_from_network() (задача 7) принимает
ThermalNetworkModel (из model.py — то, что Трек A строит из CSV/JSON) на входе.
На синхронизации 1 (задача 11) собираем JSON из задачи 5 (Трек A) —
ThermalNetworkModel.load_json(...) — и результат скармливаем сюда; если
по дороге что-то не сойдётся по именам полей, это и есть тот самый шов.

Задача 6: минимальный каркас — IFCPROJECT + IFCSITE, единицы измерения
и геометрический контекст (create_minimal_project).

Задача 7 (эта): generate_ifc_from_network() — камеры/опоры/компенсаторы и
трубы поверх каркаса из задачи 6, без геометрии (BREP/оси труб — задача 8,
PropertySet с диаметром/материалом/изоляцией — задача 9). Здесь только
корректные IFC-классы, размещение в пространстве (ObjectPlacement по x/y/
z_pipe_bottom) и включение в пространственную структуру площадки.

Решение по типам узлов (зафиксировано с пользователем при взятии задачи 7):
- node_type "chamber"/"street_unit" -> IfcDistributionChamberElement
  (это узлы трассы в буквальном смысле — камеры/колодцы/уличные узлы);
- node_type "support"/"compensator" -> IfcFlowFitting
  (это не камеры, а опоры и компенсаторы теплотрассы — добавлены в задаче 4
  как реальные точки трассы, но семантически это фитинги трассы, не камеры).
Оба класса не имеют точного предопределённого типа под наши узлы в IFC4.3,
поэтому используется PredefinedType="USERDEFINED" + ObjectType с человеко-
читаемым названием — так это остаётся видно и в вьюере, и в экспорте
свойств, а не теряется в обобщённом USERDEFINED без подписи.

Труба: одна нитка (NetworkEdge) = один IfcPipeSegment. Для тепловой сети
с branch="supply"/"return" это два отдельных объекта на одном участке трассы,
как и в доменной модели — никакого объединения ниток в этой задаче нет.

Задача 8 (эта): базовая геометрия труб — без BREP. "Без BREP" означает не
произвольную полигональную сетку (IfcFacetedBrep/tessellation), а простую
параметрическую форму: цилиндр как IfcExtrudedAreaSolid (SweptSolid) с
круглым профилем IfcCircleProfileDef, вытянутый вдоль оси трубы на её длину.
Радиус берётся из edge.diameter (условный проход DN, мм, — используется как
внешний диаметр трубы; более точная зависимость DN -> реальный наружный
диаметр по ГОСТ намеренно не вводится, это не входит в задачу 8). Камеры и
фитинги геометрии не получают — это не в задаче 8 и не в дорожной карте
явно, у них остаётся только ObjectPlacement из задачи 7.

Труба размещается так: ObjectPlacement.Location = координаты start_node,
ось Z локальной системы координат (Axis) направлена на end_node — тогда
Depth extrusion'а вдоль локального Z корректно укладывает цилиндр между
двумя узлами в глобальных координатах без ручного пересчёта вершин.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Tuple, Union

import ifcopenshell
import ifcopenshell.api

if TYPE_CHECKING:
    from pdf_to_ifc.model import ThermalNetworkModel


# node_type -> (IFC-класс, человекочитаемое название для ObjectType)
#
# Важно: IfcFlowFitting в IFC4.3 — абстрактный супертип без атрибута
# PredefinedType; конкретный occurrence-класс для трассовых фитингов —
# IfcPipeFitting (подтип IfcFlowFitting, так что file.by_type("IfcFlowFitting")
# всё равно находит их через иерархию типов).
NODE_TYPE_TO_IFC: Dict[str, tuple] = {
    "chamber": ("IfcDistributionChamberElement", "Камера"),
    "street_unit": ("IfcDistributionChamberElement", "Уличный узел"),
    "support": ("IfcPipeFitting", "Опора"),
    "compensator": ("IfcPipeFitting", "Компенсатор"),
}


def create_minimal_project(
    project_name: str = "PDF to IFC",
    site_name: str = "Площадка",
    *,
    schema: str = "IFC4X3",
) -> ifcopenshell.file:
    """Создать пустой IFC-файл с IFCPROJECT -> IFCSITE, метрическими единицами
    и геометрическим контекстом Model/Body.

    Дальше (задача 7) в этот файл будут добавляться камеры (IfcDistributionChamberElement
    или аналог) и трубы (IfcPipeSegment) как дочерние элементы IFCSITE.
    """
    file = ifcopenshell.api.run("project.create_file", version=schema)

    project = ifcopenshell.api.run(
        "root.create_entity", file, ifc_class="IfcProject", name=project_name
    )

    # Метрические единицы: без этого длины/диаметры труб будут не в метрах,
    # а IFC-вьюеры (и задача 10 — тест открытия) не смогут это проверить.
    ifcopenshell.api.run(
        "unit.assign_unit",
        file,
        length={"is_metric": True, "raw": "METERS"},
    )

    model_context = ifcopenshell.api.run(
        "context.add_context", file, context_type="Model"
    )
    ifcopenshell.api.run(
        "context.add_context",
        file,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_context,
    )

    site = ifcopenshell.api.run(
        "root.create_entity", file, ifc_class="IfcSite", name=site_name
    )
    ifcopenshell.api.run(
        "aggregate.assign_object",
        file,
        relating_object=project,
        products=[site],
    )

    return file


def _local_placement(file: ifcopenshell.file, x: float, y: float, z: float) -> "ifcopenshell.entity_instance":
    """IfcLocalPlacement в абсолютных координатах площадки (без вложенности)."""
    point = file.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(y), float(z)))
    axis2placement = file.create_entity("IfcAxis2Placement3D", Location=point)
    return file.create_entity("IfcLocalPlacement", RelativePlacement=axis2placement)


def _unit_vector(vector: Tuple[float, float, float]) -> Tuple[float, float, float]:
    length = math.sqrt(sum(c * c for c in vector))
    if length < 1e-9:
        raise ValueError(
            "Нулевая длина направления трубы — start_node и end_node имеют "
            "совпадающие координаты (x, y, z_pipe_bottom)"
        )
    return tuple(c / length for c in vector)


def _perpendicular_direction(unit_axis: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Произвольный, но детерминированный вектор, перпендикулярный unit_axis —
    нужен как RefDirection для IfcAxis2Placement3D (для цилиндра ориентация
    вокруг своей оси не важна, важна только сама ось).
    """
    reference = (1.0, 0.0, 0.0) if abs(unit_axis[0]) > 0.999 else (0.0, 0.0, 1.0)
    dot = sum(a * b for a, b in zip(unit_axis, reference))
    raw = tuple(r - dot * a for r, a in zip(reference, unit_axis))
    return _unit_vector(raw)


def _oriented_placement(
    file: ifcopenshell.file,
    origin: Tuple[float, float, float],
    direction: Tuple[float, float, float],
) -> "ifcopenshell.entity_instance":
    """IfcLocalPlacement в origin, локальная ось Z направлена вдоль direction."""
    unit_axis = _unit_vector(direction)
    ref_direction = _perpendicular_direction(unit_axis)

    point = file.create_entity("IfcCartesianPoint", Coordinates=tuple(float(c) for c in origin))
    axis = file.create_entity("IfcDirection", DirectionRatios=unit_axis)
    ref = file.create_entity("IfcDirection", DirectionRatios=ref_direction)
    axis2placement = file.create_entity(
        "IfcAxis2Placement3D", Location=point, Axis=axis, RefDirection=ref
    )
    return file.create_entity("IfcLocalPlacement", RelativePlacement=axis2placement)


def _pipe_body_representation(
    file: ifcopenshell.file,
    body_context: "ifcopenshell.entity_instance",
    radius_m: float,
    depth_m: float,
) -> "ifcopenshell.entity_instance":
    """Цилиндр (SweptSolid, без BREP): круглый профиль, вытянутый вдоль
    локальной оси Z на depth_m. Ориентация в пространстве задаётся не здесь,
    а через ObjectPlacement трубы (_oriented_placement) — сам солид всегда
    строится в локальных координатах (0, 0, 0) -> (0, 0, depth_m).
    """
    profile_origin = file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0))
    profile_position = file.create_entity("IfcAxis2Placement2D", Location=profile_origin)
    profile = file.create_entity(
        "IfcCircleProfileDef",
        ProfileType="AREA",
        ProfileName=None,
        Position=profile_position,
        Radius=float(radius_m),
    )

    extrusion_origin = file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    extrusion_position = file.create_entity("IfcAxis2Placement3D", Location=extrusion_origin)
    extruded_direction = file.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))

    solid = file.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=extrusion_position,
        ExtrudedDirection=extruded_direction,
        Depth=float(depth_m),
    )

    shape_representation = file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body_context,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=[solid],
    )
    return file.create_entity("IfcProductDefinitionShape", Representations=[shape_representation])


def _find_body_context(file: ifcopenshell.file) -> "ifcopenshell.entity_instance":
    body_contexts = [
        c for c in file.by_type("IfcGeometricRepresentationSubContext")
        if c.ContextIdentifier == "Body"
    ]
    if not body_contexts:
        raise ValueError(
            "В файле нет геометрического подконтекста 'Body' — передайте file "
            "из create_minimal_project() (задача 6) или создайте его сами."
        )
    return body_contexts[0]


def generate_ifc_from_network(
    model: "ThermalNetworkModel",
    *,
    file: ifcopenshell.file = None,
    site_name: str = "Площадка",
) -> ifcopenshell.file:
    """Собрать IFC-файл из доменной модели: узлы -> камеры/фитинги, рёбра -> трубы.

    Если file не передан, создаётся новый через create_minimal_project()
    (задача 6) с именем проекта model.project_name. Если передан — ожидается,
    что в нём уже есть ровно один IfcSite (например, из create_minimal_project),
    в который добавляются новые элементы.

    Трубы получают геометрию (задача 8) — цилиндр по DN, ориентированный
    от start_node к end_node. Камеры и фитинги — только ObjectPlacement,
    без формы (геометрия камер не входит ни в задачу 7, ни в задачу 8).
    """
    if file is None:
        file = create_minimal_project(project_name=model.project_name, site_name=site_name)

    sites = file.by_type("IfcSite")
    if len(sites) != 1:
        raise ValueError(
            f"Ожидается ровно один IfcSite в файле, найдено {len(sites)}. "
            "Передайте file из create_minimal_project() (задача 6)."
        )
    site = sites[0]
    body_context = _find_body_context(file)

    node_entities: Dict[str, "ifcopenshell.entity_instance"] = {}
    new_products = []

    for node in model.nodes.values():
        if node.node_type not in NODE_TYPE_TO_IFC:
            raise ValueError(
                f"Неизвестный node_type={node.node_type!r} у узла {node.name!r}. "
                f"Известные типы: {sorted(NODE_TYPE_TO_IFC)}"
            )
        ifc_class, object_type = NODE_TYPE_TO_IFC[node.node_type]

        entity = ifcopenshell.api.run(
            "root.create_entity", file, ifc_class=ifc_class, name=node.name
        )
        entity.ObjectType = object_type
        entity.PredefinedType = "USERDEFINED"
        entity.ObjectPlacement = _local_placement(file, node.x, node.y, node.z_pipe_bottom)

        node_entities[node.name] = entity
        new_products.append(entity)

    for edge in model.edges:
        start = model.nodes[edge.start_node]
        end = model.nodes[edge.end_node]
        origin = (start.x, start.y, start.z_pipe_bottom)
        direction = (
            end.x - start.x,
            end.y - start.y,
            end.z_pipe_bottom - start.z_pipe_bottom,
        )

        suffix = "" if edge.branch == "single" else f" ({edge.branch})"
        pipe = ifcopenshell.api.run(
            "root.create_entity",
            file,
            ifc_class="IfcPipeSegment",
            name=f"{edge.start_node}->{edge.end_node}{suffix}",
        )
        pipe.PredefinedType = "USERDEFINED"
        pipe.ObjectType = "Труба"
        pipe.ObjectPlacement = _oriented_placement(file, origin, direction)
        pipe.Representation = _pipe_body_representation(
            file, body_context, radius_m=edge.diameter / 1000.0 / 2.0, depth_m=edge.length
        )

        new_products.append(pipe)

    ifcopenshell.api.run(
        "spatial.assign_container",
        file,
        relating_structure=site,
        products=new_products,
    )

    return file


def save(file: ifcopenshell.file, path: Union[str, Path]) -> None:
    file.write(str(path))
