"""Доменная модель тепловой сети.

Контракт между треками: то, что здесь описано (NetworkNode/NetworkEdge/
ThermalNetworkModel и метод .to_dict()/.from_dict()) — это вход, который
generate_ifc_from_network() (задача 7, Трек B) будет принимать. Если меняете
имя или тип поля — предупредите Трек B до того, как они закодируют задачу 7.

Метод validate() (проверка уклона и глубины, задача 3) сюда сознательно не
включён — это отдельная задача поверх этой модели.

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

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


NodeType = str  # 'chamber' (ТК), 'junction' (УТ), 'street_unit' (уличный узел)
LayingType = str  # 'underground', 'underground_ducted', 'in_casing', 'overhead'
Branch = str  # 'single' (ВК и т.п.), 'supply' / 'return' (ТС), при необходимости другие


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
    length: float  # м
    material: str
    insulation: str
    laying_type: LayingType
    branch: Branch = "single"
    slope: Optional[float] = None

    def calculate_slope(self, nodes: Dict[str, NetworkNode]) -> float:
        """Уклон нитки по отметкам лотка начального и конечного узлов."""
        start = nodes[self.start_node]
        end = nodes[self.end_node]
        self.slope = (start.z_pipe_bottom - end.z_pipe_bottom) / self.length
        return self.slope

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
