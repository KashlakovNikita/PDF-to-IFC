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
Узел (камера/колодец) при этом один и тот же для обеих ниток — не дублируем.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union


# Полный список допустимых значений и их отображение в IFC-классы —
# в ifc_export.NODE_TYPE_TO_IFC (единственный источник правды по типам узлов).
NodeType = str  # 'chamber' (ТК), 'street_unit' (УТ), 'support', 'compensator',
                # 'valve', 'casing', 'channel', 'connection_point'
LayingType = str  # 'underground', 'underground_ducted', 'in_casing', 'overhead'
Branch = str  # 'single' (ВК и т.п.), 'supply' / 'return' (ТС), при необходимости другие


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

    def __post_init__(self) -> None:
        """Нормализовать waypoints к списку кортежей из трёх float.

        Нужно потому, что после JSON-раунд-трипа точки приходят списками
        ([x, y, z]), а из кода их удобнее задавать кортежами. Без нормализации
        to_dict() до и после сериализации давали бы разные структуры, и
        сравнение моделей ломалось бы на ровном месте.
        """
        self.waypoints = [_as_point(point) for point in self.waypoints]

    def calculate_slope(self, nodes: Dict[str, NetworkNode]) -> float:
        """Уклон нитки по отметкам лотка начального и конечного узлов.

        Считается по `length` (спецификация), а не по длине полилинии с
        waypoints: уклон — характеристика трубы, а не её оцифровки, и менять
        его от того, насколько точно оцифрован план, неправильно.
        """
        start = nodes[self.start_node]
        end = nodes[self.end_node]
        self.slope = (start.z_pipe_bottom - end.z_pipe_bottom) / self.length
        return self.slope

    def polyline(self, nodes: Dict[str, NetworkNode]) -> List[Tuple[float, float, float]]:
        """Геометрия нитки как ломаная: start_node -> waypoints -> end_node.

        Точки узлов берутся по отметке лотка (z_pipe_bottom) — той же, что
        используется в ObjectPlacement узлов в IFC-экспорте. Для прямого
        участка (waypoints пуст) возвращаются ровно две точки, то есть
        поведение прежнее.
        """
        start = nodes[self.start_node]
        end = nodes[self.end_node]
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
        if node.name in self.nodes:
            raise ValueError(f"Узел {node.name!r} уже добавлен")
        self.nodes[node.name] = node

    def add_edge(self, edge: NetworkEdge) -> None:
        """Добавить нитку. Оба узла должны существовать; уклон считается автоматически.

        (start_node, end_node, branch) должна быть уникальна — это то, что
        отличает "две нитки одного участка" от случайного дубликата.
        """
        missing = [n for n in (edge.start_node, edge.end_node) if n not in self.nodes]
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

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "source": self.source,
            "nodes": {name: node.to_dict() for name, node in self.nodes.items()},
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ThermalNetworkModel":
        model = cls(project_name=data["project_name"], source=data.get("source", "не указан"))
        for node_data in data.get("nodes", {}).values():
            model.nodes[node_data["name"]] = NetworkNode.from_dict(node_data)
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
