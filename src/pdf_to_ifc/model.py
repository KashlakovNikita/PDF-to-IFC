"""Доменная модель тепловой сети.

Контракт между треками: то, что здесь описано (NetworkNode/NetworkEdge/
ThermalNetworkModel и метод .to_dict()/.from_dict()) — это вход, который
generate_ifc_from_network() (задача 7, Трек B) будет принимать. Если меняете
имя или тип поля — предупредите Трек B до того, как они закодируют задачу 7.

Метод validate() (проверка уклона и глубины, задача 3) сюда сознательно не
включён — это отдельная задача поверх этой модели.

Расхождение с контрактом, который был на доске Miro (задача 2 брифа)
-------------------------------------------------------------------
Модель отросла дальше того контракта, и это осознанно. Явно фиксируем, чем
она от него отличается, чтобы расхождение не всплыло как сюрприз:

- `branch` ("single" / "supply" / "return") — двухниточная сеть; на доске
  было одно ребро на участок трассы, здесь их два (подача и обратка);
- `node_type` расширен с "chamber"/"junction" до
  "chamber" / "street_unit" / "support" / "compensator" (задача 4) и далее
  до "valve" / "casing" / "channel" / "connection_point" — это типы, которые
  реально есть в эталонном IFC проекта (см. ifc_export.NODE_TYPE_TO_IFC);
- `waypoints` у NetworkEdge — промежуточные точки изгиба трассы (см. ниже);
- `pressure_mpa` / `temperature_c` у NetworkEdge — рабочие параметры
  теплоносителя (задача 29), необязательные: None = неизвестно;
- `validate()` (задача 3) сюда сознательно не включён — см. BACKLOG.md.

Точки изгиба трассы (waypoints)
--------------------------------
NetworkEdge — это нитка между двумя УЗЛАМИ сети (камерами, опорами и т.п.),
а реальная трасса между двумя узлами не обязана быть прямой: она гнётся по
углам поворота, которые узлами сети не являются. Из-за этого `length`
(реальная длина трубы из спецификации) на изогнутом участке всегда БОЛЬШЕ,
чем прямое расстояние между координатами узлов.

`waypoints` — это точки (x, y, z) между start_node и end_node по порядку.
Пустой список (значение по умолчанию) = участок прямой, поведение модели и
IFC-экспорта в точности как до появления поля (обратная совместимость).

Что важно: waypoints задают ГЕОМЕТРИЮ трассы, а `length` остаётся числом из
спецификации. Эти две величины могут не совпадать (полилиния оцифрована по
плану с погрешностью, спецификация округлена) — модель их намеренно не
синхронизирует и не «чинит» одну по другой. Сравнить их можно методом
length_mismatch(); какая из величин главнее в каждом конкретном случае —
вопрос к инженеру, а не к коду.

Нитки (branch)
---------------
NetworkEdge представляет ОДНУ нитку трубы, а не физический участок трассы
целиком. Для однониточных сетей (водоснабжение) на осевой линии между двумя
узлами — одно ребро с branch="single" (значение по умолчанию). Для тепловых
сетей физическая трасса на плане — это две нитки (подача и обратка), значит
между теми же двумя узлами будет ДВА ребра: branch="supply" и branch="return".
Раздельные графы ниток (задача 26, решение ПРЕДВАРИТЕЛЬНОЕ)
------------------------------------------------------------
Изначально узел был один на обе нитки: камера общая, через неё проходят и
подача, и обратка. На реальных координатах выяснилось, почему так нельзя
оставлять: в эталонной модели проекта нитки Т1 и Т2 физически разведены на
0.70 м (диапазон 0.40..0.81), а одна общая осевая кладёт их в одно место.
Половина этого разноса — 0.35 м — уже больше допуска приёмки 0.2 м, то есть при
общем узле сверка не сойдётся никогда, как бы точно ни была оцифрована трасса.

Решение заказчика: подача и обратка — ПОЛНОСТЬЮ РАЗДЕЛЬНЫЕ графы, а не общий
узел с двумя ветками. Сделано так, чтобы не ломать существующие данные:

- у NetworkNode появился branch (по умолчанию "single" — узел общий, как было);
- узел с branch="supply"/"return" лежит в модели под ключом "имя@нитка", то
  есть узлы-двойники с одинаковым именем не конфликтуют;
- ребро ищет узел сначала среди узлов СВОЕЙ нитки и только потом среди общих,
  поэтому смешанные модели (общие камеры + разведённые участки) работают без
  переписывания;
- split_by_branch() разрезает модель на отдельные модели по ниткам,
  separate_branches() превращает общие узлы в узлы-двойники по нитке.

Чего решение НЕ делает: оно не разводит нитки в стороны. Величина разноса —
это данные (типовой узел прокладки, ширина канала), а не константа в коде, и
брать её из воздуха нельзя. separate_branches() строит раздельные графы в тех
же координатах, а сдвиг остаётся отдельным шагом.

Решение помечено как предварительное — оно может измениться после проверки на
реальных DWG-координатах. Раз так, обратная совместимость здесь не вежливость,
а способ откатиться, не переписывая датасеты.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union


# Полный список допустимых значений и их отображение в IFC-классы —
# в ifc_export.NODE_TYPE_TO_IFC (единственный источник правды по типам узлов).
NodeType = str  # 'chamber' (ТК), 'street_unit' (УТ), 'support', 'compensator',
                # 'valve', 'casing', 'channel', 'connection_point'
LayingType = str  # 'underground', 'underground_ducted', 'in_casing', 'overhead'
Branch = str  # 'single' (ВК и т.п.), 'supply' / 'return' (ТС), при необходимости другие


def _find_node(nodes: Dict[str, "NetworkNode"], name: str, branch: str) -> "NetworkNode":
    """Узел по имени: сначала свой по нитке («имя@нитка»), потом общий («имя»)."""
    own = f"{name}@{branch}"
    if own in nodes:
        return nodes[own]
    if name in nodes:
        return nodes[name]
    raise KeyError(f"Узел {name!r} не найден ни для нитки {branch!r}, ни как общий")


def _as_point(point: Sequence[float]) -> Tuple[float, float, float]:
    """Привести точку трассы к кортежу (x, y, z) из float с внятной ошибкой на мусоре."""
    values = tuple(point)
    if len(values) != 3:
        raise ValueError(
            f"Точка трассы должна быть тройкой (x, y, z), получено {values!r}"
        )
    return (float(values[0]), float(values[1]), float(values[2]))


@dataclass
class NetworkNode:
    """Узел сети: тепловая камера, колодец или уличный узел.

    Координаты и отметки — метры. z_pipe_bottom (отметка лотка трубы) —
    основная величина для IFC-геометрии; z_surface нужна для расчёта глубины
    заложения. Узел общий для всех ниток, проходящих через него.

    Сознательное упрощение: z_pipe_bottom одна на камеру, даже если подача и
    обратка физически заходят в неё на разной глубине. Решение принято
    осознанно (не забыто) — если точность по отметкам ниток станет критична,
    нужно будет переносить z_pipe_bottom/z_surface на уровень (узел, branch).
    """

    name: str
    x: float
    y: float
    z_surface: float
    z_pipe_bottom: float
    node_type: NodeType
    branch: Branch = "single"

    @property
    def key(self) -> str:
        """Ключ узла в модели (задача 26): «имя» для общего, «имя@нитка» для своего.

        Общий узел сохраняет прежний ключ, поэтому старые модели и датасеты
        читаются и ведут себя как раньше.
        """
        return self.name if self.branch == "single" else f"{self.name}@{self.branch}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkNode":
        return cls(**data)


@dataclass
class NetworkEdge:
    """Одна нитка трубы между двумя узлами (ребро графа сети).

    Для теплосети физический участок трассы разворачивается в два объекта
    NetworkEdge с одинаковыми (start_node, end_node) и разными branch —
    "supply" и "return". Комбинация (start_node, end_node, branch) уникальна
    в пределах модели — за это отвечает ThermalNetworkModel.add_edge().

    slope вычисляется автоматически при добавлении в ThermalNetworkModel
    (см. ThermalNetworkModel.add_edge) — руками его не заполняем.
    """

    start_node: str
    end_node: str
    diameter: int  # DN, мм
    length: float  # м, из спецификации (НЕ обязано совпадать с длиной полилинии)
    material: str
    insulation: str
    laying_type: LayingType
    branch: Branch = "single"
    slope: Optional[float] = None
    waypoints: List[Tuple[float, float, float]] = field(default_factory=list)
    # Задача 29: рабочие параметры теплоносителя. None означает «неизвестно» —
    # именно неизвестно, а не «ноль» и не «по умолчанию»: в спецификации они
    # есть в общих данных листа, но экстрактора под них пока нет, а придуманное
    # давление в IFC ничем не отличается на вид от измеренного.
    pressure_mpa: Optional[float] = None   # рабочее давление, МПа
    temperature_c: Optional[float] = None  # расчётная температура теплоносителя, °C

    def __post_init__(self) -> None:
        """Нормализовать waypoints к списку кортежей из трёх float.

        Нужно потому, что после JSON-раунд-трипа точки приходят списками
        ([x, y, z]), а из кода их удобнее задавать кортежами. Без нормализации
        to_dict() до и после сериализации давали бы разные структуры, и
        сравнение моделей ломалось бы на ровном месте.
        """
        self.waypoints = [_as_point(point) for point in self.waypoints]

    def resolve_nodes(self, nodes: Dict[str, NetworkNode]) -> Tuple[NetworkNode, NetworkNode]:
        """Узлы ребра: сначала свои по нитке, потом общие (задача 26).

        Такой порядок позволяет держать в одной модели и разведённые нитки, и
        общие камеры: если для подачи заведён свой «ТК-2», ребро подачи возьмёт
        его, а если нет — общий.
        """
        return (_find_node(nodes, self.start_node, self.branch),
                _find_node(nodes, self.end_node, self.branch))

    def calculate_slope(self, nodes: Dict[str, NetworkNode]) -> float:
        """Уклон нитки по отметкам лотка начального и конечного узлов.

        Считается по `length` (спецификация), а не по длине полилинии с
        waypoints: уклон — характеристика трубы, а не её оцифровки, и менять
        его от того, насколько точно оцифрован план, неправильно.
        """
        start, end = self.resolve_nodes(nodes)
        self.slope = (start.z_pipe_bottom - end.z_pipe_bottom) / self.length
        return self.slope

    def polyline(self, nodes: Dict[str, NetworkNode]) -> List[Tuple[float, float, float]]:
        """Геометрия нитки как ломаная: start_node -> waypoints -> end_node.

        Точки узлов берутся по отметке лотка (z_pipe_bottom) — той же, что
        используется в ObjectPlacement узлов в IFC-экспорте. Для прямого
        участка (waypoints пуст) возвращаются ровно две точки, то есть
        поведение прежнее.
        """
        start, end = self.resolve_nodes(nodes)
        return [
            (start.x, start.y, start.z_pipe_bottom),
            *self.waypoints,
            (end.x, end.y, end.z_pipe_bottom),
        ]

    def polyline_length(self, nodes: Dict[str, NetworkNode]) -> float:
        """Длина ломаной из polyline() — сумма расстояний между соседними точками.

        Это ГЕОМЕТРИЧЕСКАЯ длина трассы, в отличие от `length` из
        спецификации; см. раздел про waypoints в докстринге модуля.
        """
        points = self.polyline(nodes)
        return sum(math.dist(a, b) for a, b in zip(points, points[1:]))

    def length_mismatch(self, nodes: Dict[str, NetworkNode]) -> float:
        """`length` (спецификация) минус длина ломаной, м.

        Диагностика, а не проверка: положительное значение обычно означает,
        что трасса гнётся сильнее, чем оцифровано (или что waypoints ещё не
        проставлены), отрицательное — что оцифрованная ломаная длиннее
        спецификации. Порогов здесь намеренно нет, их подбирают на реальных
        данных (см. BACKLOG.md, задача 3).
        """
        return self.length - self.polyline_length(nodes)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkEdge":
        return cls(**data)


@dataclass
class ThermalNetworkModel:
    """Доменная модель тепловой сети: граф узлов и ниток + метаданные проекта."""

    project_name: str
    source: str = "не указан"
    nodes: Dict[str, NetworkNode] = field(default_factory=dict)
    edges: List[NetworkEdge] = field(default_factory=list)

    def add_node(self, node: NetworkNode) -> None:
        """Добавить узел. Ключ — node.key: «имя» для общего, «имя@нитка» для своего.

        Узлы-двойники подачи и обратки с одинаковым именем не конфликтуют —
        это и есть раздельные графы из задачи 26.
        """
        if node.key in self.nodes:
            raise ValueError(f"Узел {node.key!r} уже добавлен")
        self.nodes[node.key] = node

    def add_edge(self, edge: NetworkEdge) -> None:
        """Добавить нитку. Оба узла должны существовать; уклон считается автоматически.

        (start_node, end_node, branch) должна быть уникальна — это то, что
        отличает "две нитки одного участка" от случайного дубликата.
        """
        missing = [
            name for name in (edge.start_node, edge.end_node)
            if f"{name}@{edge.branch}" not in self.nodes and name not in self.nodes
        ]
        if missing:
            raise ValueError(f"Узлы не найдены в модели: {missing}")

        duplicate = any(
            e.start_node == edge.start_node
            and e.end_node == edge.end_node
            and e.branch == edge.branch
            for e in self.edges
        )
        if duplicate:
            raise ValueError(
                f"Нитка {edge.start_node}->{edge.end_node} branch={edge.branch!r} "
                "уже добавлена (для второй нитки того же участка используйте другой branch)"
            )

        edge.calculate_slope(self.nodes)
        self.edges.append(edge)

    def branches(self) -> List[Branch]:
        """Нитки, которые реально есть в модели, в порядке появления."""
        seen: List[Branch] = []
        for edge in self.edges:
            if edge.branch not in seen:
                seen.append(edge.branch)
        return seen

    def split_by_branch(self) -> Dict[Branch, "ThermalNetworkModel"]:
        """Разрезать модель на отдельные модели по ниткам (задача 26).

        В каждую попадают только её рёбра и только те узлы, которые эти рёбра
        используют, — включая общие камеры, если нитка ходит через них. Узлы
        копируются, а не переиспользуются: после разреза модели независимы, и
        правка координат подачи не двигает обратку. Это и есть «полностью
        раздельные графы» из решения заказчика.
        """
        result: Dict[Branch, "ThermalNetworkModel"] = {}
        for branch in self.branches():
            part = ThermalNetworkModel(
                project_name=f"{self.project_name} [{branch}]", source=self.source
            )
            for edge in self.edges:
                if edge.branch != branch:
                    continue
                for node in edge.resolve_nodes(self.nodes):
                    if node.key not in part.nodes:
                        part.nodes[node.key] = replace(node)
                part.edges.append(replace(edge, waypoints=list(edge.waypoints)))
            result[branch] = part
        return result

    def separate_branches(self) -> "ThermalNetworkModel":
        """Развести общие узлы в узлы-двойники по ниткам (задача 26).

        Возвращается НОВАЯ модель, в которой у каждой нитки свои узлы, даже если
        в исходной камера была общей. Координаты при этом не меняются: насколько
        разводить нитки в пространстве — вопрос данных (типовой узел прокладки),
        а не кода, и подставлять сюда число «чтобы сошлось» нельзя.

        Узлы, которые не используются ни одним ребром, остаются общими: гадать,
        к какой нитке их отнести, не на чем.
        """
        separated = ThermalNetworkModel(project_name=self.project_name, source=self.source)
        used: Dict[str, List[Branch]] = {}
        for edge in self.edges:
            for name in (edge.start_node, edge.end_node):
                used.setdefault(name, [])
                if edge.branch not in used[name]:
                    used[name].append(edge.branch)

        for node in self.nodes.values():
            branches = used.get(node.name, []) if node.branch == "single" else []
            if node.branch != "single" or not branches or branches == ["single"]:
                separated.nodes[node.key] = replace(node)
                continue
            for branch in branches:
                twin = replace(node, branch=branch)
                separated.nodes[twin.key] = twin

        for edge in self.edges:
            separated.edges.append(replace(edge, waypoints=list(edge.waypoints)))
        return separated

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "source": self.source,
            "nodes": {key: node.to_dict() for key, node in self.nodes.items()},
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ThermalNetworkModel":
        model = cls(project_name=data["project_name"], source=data.get("source", "не указан"))
        for node_data in data.get("nodes", {}).values():
            node = NetworkNode.from_dict(node_data)
            model.nodes[node.key] = node
        for edge_data in data.get("edges", []):
            model.edges.append(NetworkEdge.from_dict(edge_data))
        return model

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        """Сериализация в JSON-строку. Это и есть контракт с Треком B (задача 7)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, data: str) -> "ThermalNetworkModel":
        return cls.from_dict(json.loads(data))

    def save_json(self, path: Union[str, Path]) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load_json(cls, path: Union[str, Path]) -> "ThermalNetworkModel":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
