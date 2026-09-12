"""Тесты экстрактора координат из DWG/DXF (scripts/extract_from_dwg.py).

Проверяется логика, которая не зависит от наличия самого DXF: разбор марок,
сшивка отрезков оси в цепочки, проекция узла на ось и выбор точек изгиба.
Тесты на реальном чертеже сюда не тянутся намеренно — DXF получается из DWG
внешним конвертером (ODA File Converter), которого на машине может не быть,
и завязывать на него прогон тестов нельзя.
"""

import math

import pytest

import ezdxf

from extract_from_dwg import (
    _clean_label,
    build_parser,
    _mitre_normal,
    _normalise,
    build_model,
    chain_segments,
    load_thread_spacing,
    nearest_ground_level,
    offset_threads,
    project_on_chain,
    snap_to_chains,
    waypoints_between,
)


# --- разбор марок узлов ----------------------------------------------------


def test_clean_label_strips_notes_and_line_breaks():
    """В чертеже марка идёт вместе с пояснением: «УТ-1а (нов.)», «УП2\\P135°»."""
    assert _clean_label("УТ-1а (нов.)") == "УТ-1а"
    assert _clean_label("УТ-1\\P(сущ.)") == "УТ-1"
    assert _clean_label("УП2\\P135%%D") == "УП2"
    assert _clean_label("ТК-2") == "ТК-2"


def test_normalise_matches_the_same_node_written_differently():
    """На плане «УТ-1а», в профиле «УТ1а» — это один узел."""
    assert _normalise("УТ-1а") == _normalise("УТ1а") == _normalise("ут 1а")
    assert _normalise("ТК-2") != _normalise("ТК-3")


# --- сшивка оси ------------------------------------------------------------


def test_chain_segments_joins_segments_into_one_chain():
    segments = [
        ((0.0, 0.0), (10.0, 0.0)),
        ((10.0, 0.0), (10.0, 20.0)),
        ((10.0, 20.0), (30.0, 20.0)),
    ]

    chains = chain_segments(segments, min_length=5.0)

    assert len(chains) == 1
    assert chains[0][0] == (0.0, 0.0)
    assert chains[0][-1] == (30.0, 20.0)


def test_chain_segments_does_not_bridge_a_gap():
    """Линия прерывается в камерах — соединять через разрыв нельзя."""
    segments = [
        ((0.0, 0.0), (30.0, 0.0)),
        ((34.0, 0.0), (70.0, 0.0)),  # разрыв 4 м: камера
    ]

    chains = chain_segments(segments, min_length=5.0)

    assert len(chains) == 2
    assert sorted(round(sum(math.dist(a, b) for a, b in zip(c, c[1:]))) for c in chains) == [30, 36]


def test_chain_segments_drops_short_chains():
    """Условные знаки узлов лежат на том же слое — их отсекает длина."""
    segments = [((0.0, 0.0), (60.0, 0.0)), ((100.0, 100.0), (101.0, 100.0))]

    chains = chain_segments(segments, min_length=20.0)

    assert len(chains) == 1
    assert chains[0][-1] == (60.0, 0.0)


def test_chain_segments_handles_segments_given_in_reverse_order():
    segments = [((10.0, 0.0), (0.0, 0.0)), ((10.0, 0.0), (10.0, 30.0))]

    chains = chain_segments(segments, min_length=5.0)

    assert len(chains) == 1
    assert len(chains[0]) == 3


# --- привязка узла к оси ---------------------------------------------------


def test_project_on_chain_returns_station_offset_and_projection():
    chain = [(0.0, 0.0), (100.0, 0.0)]

    station, offset, projection = project_on_chain((30.0, 4.0), chain)

    assert station == pytest.approx(30.0)
    assert offset == pytest.approx(4.0)
    assert projection == pytest.approx((30.0, 0.0))


def test_snap_to_chains_picks_the_closest_chain():
    """Рядом с трассой идут другие сети — узел должен сесть на свою."""
    chains = [[(0.0, 0.0), (100.0, 0.0)], [(0.0, 50.0), (100.0, 50.0)]]

    index, station, offset, _ = snap_to_chains((40.0, 48.0), chains)

    assert index == 1
    assert station == pytest.approx(40.0)
    assert offset == pytest.approx(2.0)


# --- точки изгиба ----------------------------------------------------------


def make_node(chain, station, z=28.0):
    return {"chain": chain, "station": station, "z_pipe_bottom": z}


def test_waypoints_between_returns_drawn_vertices_in_order():
    chains = [[(0.0, 0.0), (10.0, 20.0), (30.0, 20.0), (50.0, 0.0)]]

    waypoints = waypoints_between(
        chains, make_node(0, 0.0), make_node(0, 70.0), z_start=28.0, z_end=27.0,
    )

    assert [(x, y) for x, y, _ in waypoints] == [(10.0, 20.0), (30.0, 20.0)]


def test_waypoints_between_interpolates_z_along_the_section():
    """Измеренных отметок в точках изгиба нет — z интерполируется между узлами."""
    chains = [[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]]

    waypoints = waypoints_between(
        chains, make_node(0, 0.0), make_node(0, 100.0), z_start=30.0, z_end=20.0,
    )

    assert waypoints == [(50.0, 0.0, 25.0)]


def test_waypoints_between_respects_direction_along_the_chain():
    """Участок может идти против направления отрисовки оси."""
    chains = [[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]]

    forward = waypoints_between(
        chains, make_node(0, 0.0), make_node(0, 100.0), z_start=30.0, z_end=20.0)
    backward = waypoints_between(
        chains, make_node(0, 100.0), make_node(0, 0.0), z_start=20.0, z_end=30.0)

    assert forward == [(50.0, 0.0, 25.0)]
    assert backward == [(50.0, 0.0, 25.0)]


def test_waypoints_between_is_empty_when_nodes_sit_on_different_chains():
    """Между узлами разрыв в чертеже — участок остаётся прямым, изгиб не выдумываем."""
    chains = [[(0.0, 0.0), (10.0, 20.0), (30.0, 0.0)], [(50.0, 0.0), (80.0, 0.0)]]

    waypoints = waypoints_between(
        chains, make_node(0, 0.0), make_node(1, 30.0), z_start=28.0, z_end=27.0,
    )

    assert waypoints == []


# --- отметки земли с плана (задача 33) -------------------------------------
#
# Отметки ЛОТКА в чертеже найти не удалось (см. докстринг скрипта), а вот
# съёмочные отметки земли на плане есть — их и берём.


def test_nearest_ground_level_picks_the_closest_label():
    levels = [((0.0, 0.0), 27.50), ((3.0, 0.0), 27.90), ((100.0, 0.0), 30.00)]

    value, distance = nearest_ground_level((2.0, 0.0), levels, radius=5.0)

    assert value == pytest.approx(27.90)
    assert distance == pytest.approx(1.0)


def test_nearest_ground_level_ignores_labels_beyond_the_radius():
    """Дальше — это уже соседняя отметка, а не отметка этого узла."""
    levels = [((0.0, 0.0), 27.50)]

    assert nearest_ground_level((20.0, 0.0), levels, radius=5.0) is None


def make_chain_and_labels():
    chains = [[(0.0, 0.0), (100.0, 0.0)]]
    labels = {"A": [(0.0, 0.0)], "B": [(100.0, 0.0)]}
    order = ["A", "B"]
    elevations = {"A": (27.00, 25.00, "chamber"), "B": (27.00, 24.50, "chamber")}
    return chains, labels, order, elevations, {}


def test_build_model_takes_ground_elevation_from_the_plan_when_it_is_near():
    chains, labels, order, elevations, diameters = make_chain_and_labels()
    ground = [((1.0, 0.0), 28.31)]

    model, _, _ = build_model(chains, labels, order, elevations, diameters, ground)

    assert model.nodes["A"].z_surface == pytest.approx(28.31)   # с плана
    assert model.nodes["B"].z_surface == pytest.approx(27.00)   # подписи рядом нет


def test_build_model_never_replaces_the_invert_elevation():
    """Отметку лотка с плана взять неоткуда — она должна остаться из датасета."""
    chains, labels, order, elevations, diameters = make_chain_and_labels()
    ground = [((1.0, 0.0), 28.31), ((99.0, 0.0), 28.40)]

    model, _, _ = build_model(chains, labels, order, elevations, diameters, ground)

    assert model.nodes["A"].z_pipe_bottom == pytest.approx(25.00)
    assert model.nodes["B"].z_pipe_bottom == pytest.approx(24.50)


def test_build_model_reports_where_each_ground_elevation_came_from():
    chains, labels, order, elevations, diameters = make_chain_and_labels()

    _, _, placed = build_model(chains, labels, order, elevations, diameters, [((1.0, 0.0), 28.31)])

    sources = {node["name"]: node["ground_source"] for node in placed}
    assert sources["A"].startswith("план")
    assert sources["B"] == "датасет"


# --- разнос ниток по данным сечений (задача 26) ----------------------------
#
# В плане нитки не разделены: там одна осевая. Расстояние между ними задано на
# листе сечений, где Т1 и Т2 подписаны отдельно и нарисованы окружностями.


def make_section_doc(diameter: int = 426, spacing_mm: float = 800.0):
    """Лист сечений в миниатюре: две подписи и две окружности труб."""
    doc = ezdxf.new()
    msp = doc.modelspace()
    radius = diameter / 2
    msp.add_text(f"Т1 Ø{diameter}х9,0").set_placement((0.0, 0.0))
    msp.add_circle((0.0, -200.0), radius)
    msp.add_text(f"Т2 Ø{diameter}х9,0").set_placement((spacing_mm, 0.0))
    msp.add_circle((spacing_mm, -200.0), radius)
    return doc


def test_thread_spacing_is_read_from_the_section_sheet():
    """Лист начерчен в миллиметрах — 800 мм между осями это 0.80 м."""
    spacing = load_thread_spacing(make_section_doc(426, 800.0))

    assert spacing == {426: 0.8}


def test_thread_spacing_is_kept_per_diameter():
    """У Ду 325 и Ду 426 расстояния разные, усреднять их нельзя."""
    doc = make_section_doc(426, 800.0)
    msp = doc.modelspace()
    msp.add_text("Т1 Ø325х8,0").set_placement((0.0, 5000.0))
    msp.add_circle((0.0, 4800.0), 162.5)
    msp.add_text("Т2 Ø325х8,0").set_placement((700.0, 5000.0))
    msp.add_circle((700.0, 4800.0), 162.5)

    spacing = load_thread_spacing(doc)

    assert spacing == {325: 0.7, 426: 0.8}


def test_thread_spacing_is_empty_when_the_sheet_has_no_thread_labels():
    """Без подписей Т1/Т2 расстояние не выдумывается."""
    doc = ezdxf.new()
    doc.modelspace().add_circle((0.0, 0.0), 213.0)

    assert load_thread_spacing(doc) == {}


def test_mitre_normal_is_a_unit_normal_on_a_straight_run():
    normal = _mitre_normal((0.0, 0.0), (10.0, 0.0), (20.0, 0.0))

    assert normal == pytest.approx((0.0, 1.0))


def test_mitre_normal_lengthens_on_a_corner_so_the_offset_does_not_cut_it():
    """На повороте 90° сдвиг по биссектрисе длиннее в 1/cos(45°) = 1.414 раза."""
    normal = _mitre_normal((0.0, 0.0), (10.0, 0.0), (10.0, 10.0))

    assert math.hypot(*normal) == pytest.approx(math.sqrt(2), rel=1e-6)


def make_two_branch_model():
    from pdf_to_ifc.model import NetworkEdge, NetworkNode, ThermalNetworkModel

    model = ThermalNetworkModel(project_name="Нитки")
    model.add_node(NetworkNode(name="A", x=0.0, y=0.0, z_surface=30.0,
                               z_pipe_bottom=28.0, node_type="chamber"))
    model.add_node(NetworkNode(name="B", x=100.0, y=0.0, z_surface=30.0,
                               z_pipe_bottom=27.0, node_type="chamber"))
    for branch in ("supply", "return"):
        model.add_edge(NetworkEdge(
            start_node="A", end_node="B", branch=branch, diameter=426, length=100.0,
            material="Steel", insulation="PPU+PE", laying_type="underground_ducted",
            waypoints=[(50.0, 0.0, 27.5)],
        ))
    return model


def test_offset_threads_puts_branches_on_opposite_sides_of_the_axis():
    separated = offset_threads(make_two_branch_model(), {426: 0.8})

    supply = separated.nodes["A@supply"]
    ret = separated.nodes["A@return"]

    assert supply.y == pytest.approx(-0.4)
    assert ret.y == pytest.approx(+0.4)
    assert abs(supply.y - ret.y) == pytest.approx(0.8)  # паспортное расстояние


def test_offset_threads_moves_waypoints_too():
    """Иначе нитка разойдётся с осью только в узлах, а на изгибах сойдётся обратно."""
    separated = offset_threads(make_two_branch_model(), {426: 0.8})

    supply = next(e for e in separated.edges if e.branch == "supply")

    assert supply.waypoints[0][1] == pytest.approx(-0.4)
    assert supply.waypoints[0][2] == pytest.approx(27.5)  # отметка не трогается


def test_offset_threads_keeps_the_model_unchanged_without_spacing():
    """Нет данных из сечений — нет и разноса: выдумывать расстояние нельзя."""
    model = make_two_branch_model()

    assert offset_threads(model, {}) is model


def test_offset_threads_falls_back_to_the_median_for_an_unknown_diameter():
    model = make_two_branch_model()

    separated = offset_threads(model, {325: 0.7})   # про Ду 426 сечения молчат

    assert abs(separated.nodes["A@supply"].y - separated.nodes["A@return"].y) == pytest.approx(0.7)


def test_thread_separation_is_on_by_default():
    """Решение по вопросу 14: разнос включён по умолчанию, без флага."""
    assert build_parser().parse_args([]).separate_threads is True


def test_thread_separation_can_be_switched_off():
    """Оставить обе нитки на общей оси — по-прежнему возможно, но это явный выбор."""
    assert build_parser().parse_args(["--no-separate-threads"]).separate_threads is False


def test_offset_threads_side_assignment_is_symmetric():
    """Сторона условная: важно, что нитки по разные стороны и на паспортном
    расстоянии, а какая именно слева — допущение, которое можно перевернуть."""
    separated = offset_threads(make_two_branch_model(), {426: 0.8})

    supply = separated.nodes["A@supply"].y
    ret = separated.nodes["A@return"].y

    assert supply == pytest.approx(-ret)          # симметрично относительно оси
    assert abs(supply - ret) == pytest.approx(0.8)
