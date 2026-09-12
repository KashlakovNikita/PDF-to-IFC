"""Задача 19: тесты сборки модели из нескольких источников.

Главное, что здесь проверяется, — поведение на НЕПОЛНЫХ данных. В реальном
проекте это норма: координаты есть, отметок нет; спецификация пришла, а
геометрия ещё нет. Сборка обязана отдать модель из того, что есть, и честно
перечислить, чего не хватило, а не падать и не подставлять нули.
"""

import pytest

from pdf_to_ifc.assembly import (
    EdgeData,
    NodeData,
    Source,
    assemble,
    source_from_model,
)
from pdf_to_ifc.manual_input import parse_manual_text
from pdf_to_ifc.model import NetworkEdge, NetworkNode, ThermalNetworkModel


def coordinates_source() -> Source:
    """Что даёт DWG: координаты и точки изгиба, без отметок и спецификации."""
    return Source(
        name="DWG л.2",
        nodes=[
            NodeData(name="ТК-1", x=116320.8, y=110434.3, node_type="chamber"),
            NodeData(name="ТК-2", x=116355.8, y=110420.5, node_type="chamber"),
        ],
        edges=[EdgeData(start_node="ТК-1", end_node="ТК-2",
                        waypoints=[(116340.0, 110428.0, 28.6)])],
    )


def elevations_source() -> Source:
    """Что даёт профиль, снятый человеком: только отметки."""
    return Source(
        name="профиль л.5",
        nodes=[
            NodeData(name="ТК-1", z_surface=30.1, z_pipe_bottom=28.62),
            NodeData(name="ТК-2", z_surface=29.8, z_pipe_bottom=28.40),
        ],
    )


def specification_source() -> Source:
    """Что даёт спецификация: диаметр, материал, изоляция, длина."""
    return Source(
        name="спецификация л.1",
        edges=[EdgeData(start_node="ТК-1", end_node="ТК-2", diameter=426, length=38.1,
                        material="Сталь", insulation="ППУ-ОЦ", laying_type="underground",
                        gost_designation="Ст 426х9,0/560 ППУ-ОЦ")],
    )


# --- слияние по полям -------------------------------------------------------


def test_three_partial_sources_make_one_complete_model():
    """Ни один источник сам по себе модель не даёт — вместе дают."""
    result = assemble([coordinates_source(), elevations_source(), specification_source()])

    assert len(result.model.nodes) == 2
    assert len(result.model.edges) == 1
    assert result.gaps == []

    node = result.model.nodes["ТК-1"]
    assert (node.x, node.z_pipe_bottom, node.node_type) == (116320.8, 28.62, "chamber")


def test_fields_of_one_object_can_come_from_different_sources():
    """Источник, знающий только координаты, не затирает чужие отметки."""
    result = assemble([coordinates_source(), elevations_source(), specification_source()])

    where = result.sources_of("ТК-1")

    assert where["x"] == "DWG л.2"
    assert where["z_pipe_bottom"] == "профиль л.5"


def test_edge_collects_geometry_and_specification_from_two_sources():
    result = assemble([coordinates_source(), elevations_source(), specification_source()])

    edge = result.model.edges[0]
    where = result.sources_of("ТК-1->ТК-2")

    assert edge.waypoints == [(116340.0, 110428.0, 28.6)]
    assert edge.diameter == 426
    assert where["waypoints"] == "DWG л.2"
    assert where["diameter"] == "спецификация л.1"


def test_first_source_wins_and_the_order_is_the_order_of_trust():
    first = Source(name="точный", nodes=[NodeData(name="A", x=10.0)])
    second = Source(name="грубый", nodes=[NodeData(name="A", x=99.0)])
    rest = Source(name="остальное", nodes=[
        NodeData(name="A", y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber")])

    result = assemble([first, second, rest])

    assert result.model.nodes["A"].x == 10.0
    assert result.sources_of("A")["x"] == "точный"


# --- расхождения ------------------------------------------------------------


def test_disagreement_between_sources_is_recorded_not_swallowed():
    first = Source(name="DWG", nodes=[NodeData(name="A", x=10.0, y=0.0, z_surface=30.0,
                                               z_pipe_bottom=28.0, node_type="chamber")])
    second = Source(name="ручной ввод", nodes=[NodeData(name="A", x=12.5)])

    result = assemble([first, second])

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert (conflict.obj, conflict.field_name) == ("A", "x")
    assert (conflict.kept, conflict.rejected) == (10.0, 12.5)
    assert result.model.nodes["A"].x == 10.0  # сборка не остановилась


def test_numbers_within_tolerance_are_not_a_conflict():
    """Источники округляют по-разному; миллиметр — не разногласие."""
    first = Source(name="DWG", nodes=[NodeData(name="A", x=116320.800, y=0.0, z_surface=30.0,
                                               z_pipe_bottom=28.0, node_type="chamber")])
    second = Source(name="выгрузка", nodes=[NodeData(name="A", x=116320.8004)])

    assert assemble([first, second]).conflicts == []


def test_conflict_message_names_both_sources():
    first = Source(name="DWG", nodes=[NodeData(name="A", x=10.0, y=0.0, z_surface=30.0,
                                               z_pipe_bottom=28.0, node_type="chamber")])
    second = Source(name="ручной ввод", nodes=[NodeData(name="A", x=12.5)])

    text = str(assemble([first, second]).conflicts[0])

    assert "DWG" in text and "ручной ввод" in text


# --- неполные данные --------------------------------------------------------


def test_node_without_elevations_is_skipped_and_reported():
    """Отметок нет — узел не строится, но и молча не исчезает."""
    result = assemble([coordinates_source()])

    assert result.model.nodes == {}
    assert [gap.obj for gap in result.gaps] == ["ТК-1", "ТК-2", "ТК-1->ТК-2"]
    assert "z_pipe_bottom" in result.gaps[0].missing


def test_edge_without_diameter_is_skipped_but_nodes_survive():
    """Дыра в спецификации не должна уносить с собой геометрию узлов."""
    result = assemble([coordinates_source(), elevations_source()])

    assert len(result.model.nodes) == 2
    assert result.model.edges == []
    assert [gap.obj for gap in result.gaps] == ["ТК-1->ТК-2"]
    assert set(result.gaps[0].missing) >= {"diameter", "length"}


def test_edge_referring_to_a_missing_node_is_reported_separately():
    nodes = Source(name="узлы", nodes=[
        NodeData(name="A", x=0.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber")])
    edges = Source(name="участки", edges=[
        EdgeData(start_node="A", end_node="НЕТ", diameter=100, length=10.0,
                 material="Сталь", insulation="нет", laying_type="underground")])

    result = assemble([nodes, edges])

    assert result.model.edges == []
    gap = next(g for g in result.gaps if g.obj == "A->НЕТ")
    assert gap.reason == "нет узлов"
    assert gap.missing == ["НЕТ"]


def test_defaults_fill_text_attributes_and_are_marked_as_such():
    """Умолчание — решение вызывающего, поэтому в провенансе оно подписано."""
    result = assemble(
        [coordinates_source(), elevations_source(),
         Source(name="ведомость", edges=[EdgeData(start_node="ТК-1", end_node="ТК-2",
                                                  diameter=426, length=38.1)])],
        defaults={"material": "Сталь", "insulation": "не указана",
                  "laying_type": "underground"},
    )

    assert result.model.edges[0].material == "Сталь"
    assert result.sources_of("ТК-1->ТК-2")["material"] == "по умолчанию"


def test_defaults_do_not_override_real_data():
    result = assemble([coordinates_source(), elevations_source(), specification_source()],
                      defaults={"material": "ЧУГУН"})

    assert result.model.edges[0].material == "Сталь"


def test_report_lists_gaps_and_conflicts_in_plain_words():
    result = assemble([coordinates_source()])

    text = result.report()

    assert "Не собрано объектов: 3" in text
    assert "z_pipe_bottom" in text


def test_report_says_so_when_everything_is_clean():
    result = assemble([coordinates_source(), elevations_source(), specification_source()])

    assert "Дыр и расхождений нет" in result.report()


# --- нитки ------------------------------------------------------------------


def test_nodes_of_different_branches_are_separate_objects():
    """После задачи 26 «ТК-2 подачи» и «ТК-2 обратки» — разные узлы."""
    source = Source(name="DWG", nodes=[
        NodeData(name="ТК-1", branch="supply", x=0.0, y=-0.4, z_surface=30.0,
                 z_pipe_bottom=28.0, node_type="chamber"),
        NodeData(name="ТК-1", branch="return", x=0.0, y=+0.4, z_surface=30.0,
                 z_pipe_bottom=28.0, node_type="chamber"),
    ])

    result = assemble([source])

    assert set(result.model.nodes) == {"ТК-1@supply", "ТК-1@return"}
    assert result.model.nodes["ТК-1@supply"].y == -0.4


def test_edge_of_a_branch_can_lean_on_a_shared_node():
    """Смешанный случай: общая камера и разведённые нитки — как в модели."""
    shared = Source(name="общие узлы", nodes=[
        NodeData(name="A", x=0.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber"),
        NodeData(name="B", x=50.0, y=0.0, z_surface=30.0, z_pipe_bottom=27.0, node_type="chamber"),
    ])
    edges = Source(name="участки", edges=[
        EdgeData(start_node="A", end_node="B", branch="supply", diameter=325, length=50.0,
                 material="Сталь", insulation="ППУ", laying_type="underground")])

    result = assemble([shared, edges])

    assert len(result.model.edges) == 1
    assert result.gaps == []


# --- источники ---------------------------------------------------------------


def test_source_from_model_lets_a_ready_model_take_part_in_the_merge():
    """Выгрузка из DWG уже строит модель целиком — она тоже должна быть источником."""
    model = ThermalNetworkModel(project_name="DWG")
    model.add_node(NetworkNode(name="A", x=1.0, y=2.0, z_surface=30.0,
                               z_pipe_bottom=28.0, node_type="chamber"))
    model.add_node(NetworkNode(name="B", x=51.0, y=2.0, z_surface=30.0,
                               z_pipe_bottom=27.0, node_type="chamber"))
    model.add_edge(NetworkEdge(start_node="A", end_node="B", diameter=325, length=50.0,
                               material="Сталь", insulation="ППУ", laying_type="underground",
                               waypoints=[(25.0, 5.0, 27.5)]))

    result = assemble([source_from_model(model, "DWG л.2")])

    assert len(result.model.nodes) == 2
    assert result.model.edges[0].waypoints == [(25.0, 5.0, 27.5)]
    assert result.sources_of("A->B")["diameter"] == "DWG л.2"


def test_manual_text_and_dwg_model_merge_together():
    """Тот самый случай, ради которого всё: геометрия из DWG, параметры руками."""
    dwg = ThermalNetworkModel(project_name="DWG")
    dwg.add_node(NetworkNode(name="ТК-1", x=116320.8, y=110434.3, z_surface=30.1,
                             z_pipe_bottom=28.62, node_type="chamber"))
    dwg.add_node(NetworkNode(name="ТК-2", x=116355.8, y=110420.5, z_surface=29.8,
                             z_pipe_bottom=28.40, node_type="chamber"))
    dwg.add_edge(NetworkEdge(start_node="ТК-1", end_node="ТК-2", diameter=426, length=38.1,
                             material="Сталь", insulation="ППУ-ОЦ",
                             laying_type="underground"))

    manual = parse_manual_text("""узел ТК-1: x=116320.8 y=110434.3 земля=30.1 лоток=28.62 тип=chamber
узел ТК-2: x=116355.8 y=110420.5 земля=29.8 лоток=28.40 тип=chamber
участок ТК-1 -> ТК-2: ду=426 длина=38.1 давление=1,6 температура=130""")

    result = assemble([source_from_model(dwg, "DWG"),
                       source_from_model(manual, "ручной ввод")])

    edge = result.model.edges[0]
    assert edge.pressure_mpa == pytest.approx(1.6)
    assert edge.temperature_c == pytest.approx(130.0)
    assert result.sources_of("ТК-1->ТК-2")["pressure_mpa"] == "ручной ввод"
    assert result.conflicts == []


def test_assembling_nothing_gives_an_empty_model_not_an_error():
    result = assemble([])

    assert result.model.nodes == {} and result.model.edges == []
    assert "Дыр и расхождений нет" in result.report()


def test_placeholder_text_from_manual_input_is_not_treated_as_data():
    """«не указан» — это отсутствие знания, а не значение.

    Ручной ввод обязан чем-то заполнить материал: модель требует поле непустым.
    Если считать заглушку данными, она вступает в ложное расхождение с
    источником, где материал реально известен, и отчёт засоряется конфликтами
    на ровном месте.
    """
    known = ThermalNetworkModel(project_name="спецификация")
    manual = parse_manual_text("""узел A: x=0 y=0 земля=30 лоток=28 тип=chamber
узел B: x=50 y=0 земля=30 лоток=27 тип=chamber
участок A -> B: ду=325 длина=50""")
    for model, material in ((known, "Сталь"),):
        model.add_node(NetworkNode(name="A", x=0.0, y=0.0, z_surface=30.0,
                                   z_pipe_bottom=28.0, node_type="chamber"))
        model.add_node(NetworkNode(name="B", x=50.0, y=0.0, z_surface=30.0,
                                   z_pipe_bottom=27.0, node_type="chamber"))
        model.add_edge(NetworkEdge(start_node="A", end_node="B", diameter=325, length=50.0,
                                   material=material, insulation="ППУ",
                                   laying_type="underground"))

    result = assemble([source_from_model(manual, "ручной ввод"),
                       source_from_model(known, "спецификация")])

    assert result.conflicts == []
    assert result.model.edges[0].material == "Сталь"
    assert result.sources_of("A->B")["material"] == "спецификация"


def test_placeholder_only_source_reports_a_gap_rather_than_a_fake_value():
    """Если материал не знает никто, это дыра, а не «не указан» в модели."""
    manual = parse_manual_text("""узел A: x=0 y=0 земля=30 лоток=28 тип=chamber
узел B: x=50 y=0 земля=30 лоток=27 тип=chamber
участок A -> B: ду=325 длина=50""")

    result = assemble([source_from_model(manual, "ручной ввод")])

    assert result.model.edges == []
    gap = next(g for g in result.gaps if g.obj == "A->B")
    assert set(gap.missing) == {"material", "insulation", "laying_type"}
