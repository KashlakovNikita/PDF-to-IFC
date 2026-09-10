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

Задача 1 брифа (эта): изгибы трассы — waypoints
------------------------------------------------
Найденная причина расхождения геометрии с эталоном: труба вытягивалась на
edge.length (реальная длина трубы из спецификации) вдоль ПРЯМОГО направления
start_node -> end_node. На изогнутом участке length всегда больше прямого
расстояния между узлами, поэтому цилиндр проезжал мимо конечного узла ровно
на величину изгиба трассы. На синтетическом датасете (data/samples/parnas_*,
координаты-placeholder'ы строго по прямой) это не проявлялось.

Теперь одно ребро (NetworkEdge) разворачивается в ломаную
start_node -> waypoints -> end_node (NetworkEdge.polyline) и генерируется:

- по одному IfcPipeSegment на каждое ЗВЕНО ломаной, Depth = фактическое
  расстояние между двумя соседними точками звена (а не edge.length целиком
  на каждое звено — иначе каждый под-сегмент промахивался бы отдельно);
- по одному IfcPipeFitting с PredefinedType="BEND" в каждой промежуточной
  точке (в самих waypoints; в узлах сети фитинги не ставим — там уже стоят
  объекты узлов из задачи 7).

Сознательное решение по Depth для ПРЯМЫХ участков (waypoints пуст): остаётся
edge.length, как было до этой задачи. Причина — требование обратной
совместимости из брифа («пустой список = поведение без изменений»): пока
трасса не оцифрована, спецификационная длина — единственный источник длины
трубы, и подменять её прямым расстоянием между узлами значило бы молча
терять данные спецификации. Как следствие, для прямого участка возможно
расхождение length с геометрией; оно измеримо через
NetworkEdge.length_mismatch() и попадает в отчёт scripts/validate_geometry.py.

Задача 9 (эта): свойства труб — IfcPropertySet
-----------------------------------------------
На каждый IfcPipeSegment вешается один набор свойств PSET_NAME (см. константу
ниже) со всем, что есть в доменной модели по этой нитке: DN, материал,
изоляция, тип прокладки, нитка (подача/обратка), уклон, длины и — для
разбитых по waypoints ниток — номер под-сегмента.

Имена свойств — КИРИЛЛИЦА, как в эталонном файле проекта (решение заказчика,
задача 9 переигрывается). Первая версия писала их латиницей в расчёте на
IDS-проверку, но приёмка идёт по эталону, и свойство «Диаметр» должно
называться «Диаметр», а не Diameter, иначе инженер сверяет два файла глазами и
видит разные наборы.

Важная деталь про единицы: в эталоне «Диаметр» записан в МЕТРАХ (0.426), а в
спецификации диаметр называют условным проходом в миллиметрах (Ду 426). Поэтому
пишутся оба свойства: «Диаметр» в метрах — как в эталоне, с тем же смыслом и в
тех же единицах, и «Условный проход» в миллиметрах — как в спецификации. Дать
свойству эталонное имя, но чужую единицу означало бы соврать в самом названии.

Давление и температура (задача 29) пишутся, если заданы в модели, и не
пишутся, если нет: «неизвестно» выражается отсутствием свойства. Ввести их
можно руками через pdf_to_ifc.manual_input, пока нет экстрактора спецификации.
Обозначение трубы по ГОСТ (задача 30) пишется в свойство «Наименование» —
так оно называется в эталоне ("Ст 426х9,0/560 ППУ-ОЦ в изоляции по ГОСТ
30732-2020"). В модели под него отдельное поле gost_designation, живущее
рядом с material/insulation, а не вместо них.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Tuple, Union

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
# Задача 2 брифа: типы узлов расширены под то, что реально есть в эталонном
# файле data/raw/ПРНС_ЛО_ТКР-ТС_У1_Э1_I2300.ifc. Там все 328 элементов —
# IfcBuildingElementProxy (IFC2X3), а тип зашит в имя IfcPropertySet:
# Труба (165), Неподвижная опора (70), Колодец (23), Трубопроводная арматура (18),
# Канал (12), Точка подключения к внешним сетям (11), Футляр (10), Камера (3).
# Прежняя таблица покрывала только камеры/уличные узлы/опоры/компенсаторы —
# арматуры, каналов, футляров и точек подключения в ней не было вовсе.
# Решение расширить модель принято человеком при постановке этой задачи
# (эталон в proxy-классы мы при этом НЕ повторяем: генерируем осмысленные
# IFC-классы, а сверка с эталоном идёт по геометрии, см. validate_geometry.py).
#
# Выбор классов:
# - "valve" -> IfcValve: арматура в разрыве трассы, ровно как в дорожной карте (Ш1);
# - "casing" -> IfcPipeFitting: футляр — не труба сети (через него труба проходит),
#   отдельной сущности под футляр/кожух в IFC4.3 нет; помечаем ObjectType;
# - "channel" -> IfcDistributionChamberElement: непроходной канал — это
#   строительная конструкция вокруг трассы, ближайший осмысленный класс тот же,
#   что у камер (в эталоне это тоже отдельный объект со своими габаритами);
# - "connection_point" -> IfcDistributionPort — точка подключения к внешним
#   сетям, это именно порт, а не элемент; см. оговорку в generate_ifc_from_network().
NODE_TYPE_TO_IFC: Dict[str, tuple] = {
    "chamber": ("IfcDistributionChamberElement", "Камера"),
    "street_unit": ("IfcDistributionChamberElement", "Уличный узел"),
    "support": ("IfcPipeFitting", "Опора"),
    "compensator": ("IfcPipeFitting", "Компенсатор"),
    "valve": ("IfcValve", "Трубопроводная арматура"),
    "casing": ("IfcPipeFitting", "Футляр"),
    "channel": ("IfcDistributionChamberElement", "Канал"),
    "connection_point": ("IfcDistributionPort", "Точка подключения к внешним сетям"),
}

# PredefinedType узла по умолчанию — "USERDEFINED" (пояснение выше). Здесь
# перечислены типы узлов, где у IFC-класса свой осмысленный перечислитель:
# у IfcDistributionPort PredefinedType — это тип ПЕРЕНОСИМОЙ СРЕДЫ
# (IfcDistributionPortTypeEnum: PIPE / DUCT / CABLE / ...), а не "тип объекта",
# поэтому "USERDEFINED" был бы здесь потерей смысла: точка подключения
# теплосети — это трубопроводный порт.
NODE_TYPE_PREDEFINED_TYPE: Dict[str, str] = {
    "connection_point": "PIPE",
}


# Имя набора свойств труб (задача 9). Собственное, не из стандартных Pset_*:
# стандартный Pset_PipeSegmentTypeCommon описывает ТИП трубы, а не конкретный
# участок, и не покрывает нужные нам поля (тип прокладки, нитка, изоляция
# в терминах проекта). Префикс PdfToIfc — чтобы в вьюере было видно, что набор
# сгенерирован этим инструментом, а не пришёл из исходной модели.
PIPE_PSET_NAME = "Pset_PdfToIfc_PipeSegment"


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

    Опорный вектор — та ось глобальной системы координат, вдоль которой
    unit_axis выражен слабее всего. Так проекция гарантированно не вырождается:
    у единичного вектора минимальная по модулю компонента не превышает
    1/sqrt(3), поэтому длина результата до нормировки >= sqrt(2/3) ~ 0.82.

    Так было не всегда: до задачи 1 брифа опорный вектор выбирался обратным
    условием — (1, 0, 0) при |unit_axis.x| > 0.999, то есть ровно тогда, когда
    он почти совпадает с осью. Для трубы, идущей строго вдоль X, проекция
    обращалась в ноль, и экспорт падал с "Нулевая длина направления трубы",
    хотя направление было задано корректно. Тестовый датасет промахивался
    мимо этого случая: шаг 50 м по X при перепаде отметок 0.1 м даёт
    |unit_axis.x| = 0.9999980, то есть вырожденный, но всё же ненулевой
    RefDirection. На реальной трассе с горизонтальными участками падало бы.
    """
    smallest_axis = min(range(3), key=lambda i: abs(unit_axis[i]))
    reference = tuple(1.0 if i == smallest_axis else 0.0 for i in range(3))
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


def _assign_pipe_pset(
    file: ifcopenshell.file,
    pipe: "ifcopenshell.entity_instance",
    edge,
    *,
    segment_index: int,
    segment_count: int,
    segment_length_m: float,
) -> "ifcopenshell.entity_instance":
    """Повесить на трубу набор свойств PIPE_PSET_NAME (задача 9).

    Что пишем и почему именно так:
    - «Диаметр» — в МЕТРАХ, ровно как в эталоне (0.426), чтобы значения двух
      файлов сравнивались напрямую;
    - «Условный проход» — то же число в МИЛЛИМЕТРАХ (426), как его называют в
      спецификации и на выносках чертежа. Это обозначение, а не измеренная
      длина, и путать его с метровым радиусом геометрии нельзя;
    - «Длина по спецификации» — длина всей нитки (одна на все под-сегменты);
    - «Длина сегмента» — длина ЭТОГО под-сегмента по геометрии; для неразбитой
      нитки совпадает с Depth экструзии;
    - «Номер сегмента» / «Всего сегментов» — какой это по счёту под-сегмент
      нитки, чтобы разбиение по waypoints читалось в вьюере, а не только в
      имени объекта;
    - «Участок» — "A->B", исходное ребро доменной модели.

    Давление и температура (задача 29) пишутся из edge.pressure_mpa и
    edge.temperature_c, если они заданы. Экстрактора под них по-прежнему нет
    (в спецификации они в общих данных листа), но теперь их можно ввести
    руками — см. pdf_to_ifc.manual_input. Если значения нет, свойство не
    пишется вовсе: пустое свойство в IFC хуже отсутствующего, вьюер покажет
    его как заполненное.

    Обозначение по ГОСТ (задача 30) берётся из edge.gost_designation и пишется
    в «Наименование» — под тем же именем, что в эталоне. Если поле не заполнено,
    свойства нет: собирать обозначение из material и insulation нельзя, там нет
    ни толщины стенки, ни диаметра оболочки, ни номера ГОСТа.
    """
    pset = ifcopenshell.api.run("pset.add_pset", file, product=pipe, name=PIPE_PSET_NAME)
    properties = {
        "Диаметр": float(edge.diameter) / 1000.0,     # м, как в эталоне
        "Условный проход": int(edge.diameter),        # мм, как в спецификации
        "Материал": str(edge.material),
        "Изоляция": str(edge.insulation),
        "Тип прокладки": str(edge.laying_type),
        "Нитка": str(edge.branch),
        "Длина по спецификации": float(edge.length),
        "Длина сегмента": float(segment_length_m),
        "Номер сегмента": int(segment_index),
        "Всего сегментов": int(segment_count),
        "Участок": f"{edge.start_node}->{edge.end_node}",
    }
    if edge.slope is not None:
        properties["Уклон"] = float(edge.slope)
    # Задача 29: давление и температура пишутся, только если они known. Пустое
    # свойство в вьюере неотличимо от заполненного, поэтому «неизвестно»
    # выражается отсутствием свойства, а не нулём или прочерком.
    if edge.pressure_mpa is not None:
        properties["Давление"] = float(edge.pressure_mpa)
    if edge.temperature_c is not None:
        properties["Температура"] = float(edge.temperature_c)
    # Задача 30: обозначение по ГОСТ пишется под тем же именем, что в эталоне
    # («Наименование»), — там лежит ровно эта строка вида
    # "Ст 426х9,0/560 ППУ-ОЦ в изоляции по ГОСТ 30732-2020".
    if edge.gost_designation:
        properties["Наименование"] = str(edge.gost_designation)
    ifcopenshell.api.run("pset.edit_pset", file, pset=pset, properties=properties)
    return pset


def _create_edge_products(
    file: ifcopenshell.file,
    body_context: "ifcopenshell.entity_instance",
    model: "ThermalNetworkModel",
    edge,
) -> List["ifcopenshell.entity_instance"]:
    """Развернуть одну нитку (NetworkEdge) в IFC-объекты: трубы + фитинги изгибов.

    Ломаная берётся из edge.polyline(model.nodes) — это start_node, затем
    waypoints по порядку, затем end_node. Для прямого участка (waypoints пуст)
    в ломаной ровно две точки, значит создаётся один IfcPipeSegment с прежним
    именем и прежним Depth=edge.length — поведение до задачи 1 брифа
    сохраняется байт в байт.

    Для изогнутого участка:
    - на каждое звено ломаной свой IfcPipeSegment, Depth = длина ЭТОГО звена;
      имя получает суффикс " [i/n]", чтобы под-сегменты одной нитки было видно
      в вьюере как одну нитку, а не как n безымянных труб;
    - в каждой промежуточной точке — IfcPipeFitting с PredefinedType="BEND".
      Фитинги ставятся только в waypoints: в узлах сети (start_node/end_node)
      уже стоят объекты узлов из задачи 7, дублировать их фитингом нельзя.
    """
    points = edge.polyline(model.nodes)
    segment_count = len(points) - 1
    suffix = "" if edge.branch == "single" else f" ({edge.branch})"
    base_name = f"{edge.start_node}->{edge.end_node}{suffix}"
    radius_m = edge.diameter / 1000.0 / 2.0

    products: List["ifcopenshell.entity_instance"] = []

    for index, (segment_start, segment_end) in enumerate(zip(points, points[1:]), start=1):
        direction = tuple(b - a for a, b in zip(segment_start, segment_end))
        # Для прямого участка длина берётся из спецификации (обратная
        # совместимость, см. докстринг модуля), для звена ломаной — фактическое
        # расстояние между его концами.
        depth_m = edge.length if segment_count == 1 else math.dist(segment_start, segment_end)
        name = base_name if segment_count == 1 else f"{base_name} [{index}/{segment_count}]"

        pipe = ifcopenshell.api.run(
            "root.create_entity", file, ifc_class="IfcPipeSegment", name=name
        )
        pipe.PredefinedType = "USERDEFINED"
        pipe.ObjectType = "Труба"
        pipe.ObjectPlacement = _oriented_placement(file, segment_start, direction)
        pipe.Representation = _pipe_body_representation(
            file, body_context, radius_m=radius_m, depth_m=depth_m
        )
        _assign_pipe_pset(
            file,
            pipe,
            edge,
            segment_index=index,
            segment_count=segment_count,
            segment_length_m=depth_m,
        )
        products.append(pipe)

    for index, waypoint in enumerate(edge.waypoints, start=1):
        bend = ifcopenshell.api.run(
            "root.create_entity",
            file,
            ifc_class="IfcPipeFitting",
            name=f"{base_name} изгиб {index}",
        )
        bend.PredefinedType = "BEND"
        bend.ObjectType = "Поворот трассы"
        bend.ObjectPlacement = _local_placement(file, *waypoint)
        products.append(bend)

    return products


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
    вдоль звена трассы. Камеры и фитинги — только ObjectPlacement, без формы
    (геометрия камер не входит ни в задачу 7, ни в задачу 8).

    Нитка с waypoints (задача 1 брифа) разворачивается в несколько
    IfcPipeSegment по звеньям ломаной плюс IfcPipeFitting BEND в точках
    изгиба — см. _create_edge_products().

    Оговорка по "connection_point": он отображается в IfcDistributionPort,
    а порт по схеме не является IfcProduct-элементом пространственной
    структуры — в IfcRelContainedInSpatialStructure он не попадает и
    привязывается к площадке только косвенно. Полноценная привязка порта к
    элементу (IfcRelConnectsPortToElement) появится тогда, когда в модели
    будет, к чему его привязывать, — сейчас такой связи в доменной модели нет.
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

    node_entities: Dict[str, "ifcopenshell.entity_instance"] = {}  # ключ — node.key
    new_products = []

    for node in model.nodes.values():
        if node.node_type not in NODE_TYPE_TO_IFC:
            raise ValueError(
                f"Неизвестный node_type={node.node_type!r} у узла {node.name!r}. "
                f"Известные типы: {sorted(NODE_TYPE_TO_IFC)}"
            )
        ifc_class, object_type = NODE_TYPE_TO_IFC[node.node_type]

        # Узлы-двойники раздельных ниток (задача 26) носят одно имя, поэтому в
        # IFC к нему добавляется нитка — иначе в вьюере две «ТК-2» без признака,
        # какая из них подача. Общий узел (branch="single") имя не меняет.
        suffix = "" if node.branch == "single" else f" ({node.branch})"
        entity = ifcopenshell.api.run(
            "root.create_entity", file, ifc_class=ifc_class, name=f"{node.name}{suffix}"
        )
        entity.ObjectType = object_type
        entity.PredefinedType = NODE_TYPE_PREDEFINED_TYPE.get(node.node_type, "USERDEFINED")
        entity.ObjectPlacement = _local_placement(file, node.x, node.y, node.z_pipe_bottom)

        node_entities[node.key] = entity
        new_products.append(entity)

    for edge in model.edges:
        new_products.extend(_create_edge_products(file, body_context, model, edge))

    # IfcDistributionPort не является элементом пространственной структуры —
    # spatial.assign_container на нём падает по схеме, поэтому порты сюда не
    # попадают (см. оговорку в докстринге).
    containable = [p for p in new_products if not p.is_a("IfcPort")]
    if containable:
        ifcopenshell.api.run(
            "spatial.assign_container",
            file,
            relating_structure=site,
            products=containable,
        )

    return file


def save(file: ifcopenshell.file, path: Union[str, Path]) -> None:
    file.write(str(path))
