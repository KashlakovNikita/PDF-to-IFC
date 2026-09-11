"""Тесты демо-скрипта задачи 1 брифа (scripts/make_bend_demo.py).

Проверяется то, что в скрипте нетривиально: сборка отдельных прямых кусков в
упорядоченные ломаные и превращение ломаной в модель с waypoints. Сам факт
«генератор ставит отводы» покрыт тестами экспорта (tests/test_ifc_export.py),
здесь он не дублируется — проверяется только, что скрипт доводит данные до
генератора в правильном виде.
"""

import numpy as np
import pytest

from make_bend_demo import build_model, polylines
from validate_geometry import Centerline


def line(start, end) -> Centerline:
    return Centerline(name="", start=np.array(start, dtype=float),
                      end=np.array(end, dtype=float), radius=0.2)


def test_polylines_joins_pieces_sharing_an_endpoint():
    """Три куска встык дают одну ломаную из четырёх вершин."""
    pieces = [
        line((0, 0, 0), (10, 0, 0)),
        line((10, 0, 0), (10, 10, 0)),
        line((10, 10, 0), (20, 10, 0)),
    ]

    chains = polylines(pieces)

    assert len(chains) == 1
    assert [tuple(point) for point in chains[0]] == [
        (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (20.0, 10.0, 0.0)
    ]


def test_polylines_joins_pieces_given_in_arbitrary_order_and_direction():
    """Куски в файле лежат вперемешку и развёрнуты как попало — это нормально."""
    pieces = [
        line((10, 10, 0), (10, 0, 0)),
        line((20, 10, 0), (10, 10, 0)),
        line((0, 0, 0), (10, 0, 0)),
    ]

    chains = polylines(pieces)

    assert len(chains) == 1
    assert len(chains[0]) == 4


def test_polylines_keeps_broken_route_as_separate_chains():
    """Разрыв (в эталоне это арматура и компенсаторы) не сшивается.

    Сшить через зазор значило бы придумать геометрию, которой в эталоне нет.
    """
    pieces = [
        line((0, 0, 0), (10, 0, 0)),
        line((10, 0, 0), (20, 0, 0)),
        line((21.5, 0, 0), (30, 0, 0)),  # зазор 1.5 м
        line((30, 0, 0), (40, 0, 0)),
    ]

    chains = polylines(pieces)

    assert len(chains) == 2
    assert sorted(len(chain) for chain in chains) == [3, 3]


def test_polylines_drops_pieces_without_a_neighbour():
    """Одиночный отрезок для демонстрации waypoints бесполезен — отбрасывается."""
    pieces = [line((0, 0, 0), (10, 0, 0)), line((50, 50, 0), (60, 50, 0))]

    assert polylines(pieces) == []


def test_build_model_turns_intermediate_vertices_into_waypoints():
    """Каждая step-я вершина — узел, остальные — точки изгиба ребра."""
    chain = [np.array([float(i) * 10, 0.0, 28.0]) for i in range(5)]

    model = build_model([chain], step=4)
    edge = model.edges[0]

    assert set(model.nodes) == {"У1-1", "У1-2"}
    assert edge.waypoints == [(10.0, 0.0, 28.0), (20.0, 0.0, 28.0), (30.0, 0.0, 28.0)]
    assert edge.length == pytest.approx(40.0)


def test_build_model_creates_supply_and_return_on_the_same_points():
    """Обе нитки строятся по одним точкам: разнос ниток — открытый вопрос, не догадка."""
    chain = [np.array([float(i) * 10, 0.0, 28.0]) for i in range(5)]

    model = build_model([chain], step=2)
    branches = {(e.start_node, e.end_node, e.branch) for e in model.edges}

    assert len(model.edges) == 4  # два участка на две нитки
    assert branches == {
        ("У1-1", "У1-2", "supply"), ("У1-1", "У1-2", "return"),
        ("У1-2", "У1-3", "supply"), ("У1-2", "У1-3", "return"),
    }
    supply = next(e for e in model.edges if e.branch == "supply")
    ret = next(e for e in model.edges if e.branch == "return")
    assert supply.waypoints == ret.waypoints


def test_build_model_puts_chambers_at_the_ends_and_supports_between():
    chain = [np.array([float(i) * 10, 0.0, 28.0]) for i in range(7)]

    model = build_model([chain], step=2)

    assert model.nodes["У1-1"].node_type == "chamber"
    assert model.nodes["У1-4"].node_type == "chamber"
    assert model.nodes["У1-2"].node_type == "support"


def test_build_model_keeps_the_last_vertex_even_if_step_does_not_divide_evenly():
    """Хвост ломаной не теряется: последняя вершина всегда становится узлом.

    Шесть вершин при step=4 дают узлы на 0, 40 и 50 м. Остаток (40 -> 50)
    становится коротким прямым участком без точек изгиба — это и есть то самое
    поведение «пустой waypoints = как раньше», ради которого в задаче 1 брифа
    сохранялась обратная совместимость.
    """
    chain = [np.array([float(i) * 10, 0.0, 28.0]) for i in range(6)]

    model = build_model([chain], step=4)

    assert [node.x for node in model.nodes.values()] == pytest.approx([0.0, 40.0, 50.0])
    assert model.edges[0].waypoints == [
        (10.0, 0.0, 28.0), (20.0, 0.0, 28.0), (30.0, 0.0, 28.0)
    ]
    tail = next(e for e in model.edges if e.start_node == "У1-2")
    assert tail.waypoints == []
    assert tail.length == pytest.approx(10.0)
