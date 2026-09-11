import pytest

from pdf_to_ifc.model import NetworkNode, NetworkEdge, ThermalNetworkModel


def make_model_with_edge() -> ThermalNetworkModel:
    model = make_two_node_model()
    model.add_edge(NetworkEdge(
        start_node="УТ-1а", end_node="ТК-2",
        diameter=400, length=145.30, material="Steel",
        insulation="PPU+PE", laying_type="underground", branch="supply",
    ))
    return model


def make_two_node_model() -> ThermalNetworkModel:
    model = ThermalNetworkModel(project_name="Тест", source="Котельная-1")
    model.add_node(NetworkNode(
        name="УТ-1а", x=116763.09, y=110258.78,
        z_surface=150.50, z_pipe_bottom=138.80, node_type="street_unit",
    ))
    model.add_node(NetworkNode(
        name="ТК-2", x=116850.15, y=110200.45,
        z_surface=149.80, z_pipe_bottom=138.30, node_type="chamber",
    ))
    return model


def test_add_node_rejects_duplicate():
    model = make_two_node_model()
    with pytest.raises(ValueError):
        model.add_node(NetworkNode(
            name="УТ-1а", x=0, y=0, z_surface=0, z_pipe_bottom=0, node_type="chamber",
        ))


def test_add_edge_rejects_unknown_nodes():
    model = make_two_node_model()
    with pytest.raises(ValueError):
        model.add_edge(NetworkEdge(
            start_node="УТ-1а", end_node="НЕТ-ТАКОГО",
            diameter=400, length=100.0, material="Steel",
            insulation="PPU+PE", laying_type="underground",
        ))


def test_add_edge_calculates_slope_automatically():
    model = make_two_node_model()
    edge = NetworkEdge(
        start_node="УТ-1а", end_node="ТК-2",
        diameter=400, length=145.30, material="Steel",
        insulation="PPU+PE", laying_type="underground",
    )
    model.add_edge(edge)

    expected_slope = (138.80 - 138.30) / 145.30
    assert edge.slope == pytest.approx(expected_slope)


def test_single_branch_default_for_water_style_networks():
    model = make_two_node_model()
    edge = NetworkEdge(
        start_node="УТ-1а", end_node="ТК-2",
        diameter=200, length=145.30, material="Steel",
        insulation="none", laying_type="underground",
    )
    model.add_edge(edge)
    assert edge.branch == "single"


def test_thermal_network_allows_supply_and_return_between_same_nodes():
    model = make_two_node_model()
    supply = NetworkEdge(
        start_node="УТ-1а", end_node="ТК-2",
        diameter=400, length=145.30, material="Steel",
        insulation="PPU+PE", laying_type="underground", branch="supply",
    )
    return_pipe = NetworkEdge(
        start_node="УТ-1а", end_node="ТК-2",
        diameter=400, length=145.30, material="Steel",
        insulation="PPU+PE", laying_type="underground", branch="return",
    )
    model.add_edge(supply)
    model.add_edge(return_pipe)

    assert len(model.edges) == 2
    assert {e.branch for e in model.edges} == {"supply", "return"}


def test_duplicate_branch_between_same_nodes_is_rejected():
    model = make_two_node_model()
    edge_kwargs = dict(
        start_node="УТ-1а", end_node="ТК-2",
        diameter=400, length=145.30, material="Steel",
        insulation="PPU+PE", laying_type="underground", branch="supply",
    )
    model.add_edge(NetworkEdge(**edge_kwargs))

    with pytest.raises(ValueError):
        model.add_edge(NetworkEdge(**edge_kwargs))


def test_roundtrip_to_dict_from_dict():
    model = make_two_node_model()
    model.add_edge(NetworkEdge(
        start_node="УТ-1а", end_node="ТК-2",
        diameter=400, length=145.30, material="Steel",
        insulation="PPU+PE", laying_type="underground", branch="supply",
    ))

    restored = ThermalNetworkModel.from_dict(model.to_dict())

    assert restored.project_name == model.project_name
    assert restored.nodes.keys() == model.nodes.keys()
    assert len(restored.edges) == len(model.edges)
    assert restored.edges[0].branch == "supply"
    assert restored.edges[0].slope == pytest.approx(model.edges[0].slope)


def test_to_json_roundtrips_through_from_json():
    model = make_model_with_edge()

    restored = ThermalNetworkModel.from_json(model.to_json())

    assert restored.to_dict() == model.to_dict()


def test_to_json_is_valid_json_with_expected_top_level_keys():
    import json

    model = make_model_with_edge()
    data = json.loads(model.to_json())

    assert set(data.keys()) == {"project_name", "source", "nodes", "edges"}


def test_save_json_and_load_json_roundtrip(tmp_path):
    model = make_model_with_edge()
    path = tmp_path / "model.json"

    model.save_json(path)
    restored = ThermalNetworkModel.load_json(path)

    assert restored.to_dict() == model.to_dict()
    assert path.read_text(encoding="utf-8") == model.to_json()


def test_empty_model_roundtrips_through_json():
    model = ThermalNetworkModel(project_name="Пустая модель")

    restored = ThermalNetworkModel.from_json(model.to_json())

    assert restored.to_dict() == model.to_dict()
    assert restored.nodes == {}
    assert restored.edges == []


# ---------------------------------------------------------------------------
# Задача 1 брифа: waypoints — точки изгиба трассы между узлами
#
# Кейс, которого раньше не было в покрытии: length (спецификация) заведомо
# БОЛЬШЕ прямого расстояния между узлами. В существующих тестах датасета они
# намеренно совпадают (координаты-placeholder'ы строго по прямой с шагом 50 м),
# поэтому промах геометрии мимо конечного узла в тесты не попадал.
# ---------------------------------------------------------------------------


def make_bent_edge_model() -> ThermalNetworkModel:
    """Г-образный участок: прямая между узлами 100 м, реальная трасса 140 м.

    УТ-1а (0, 0) -> угол (0, 70) -> ТК-2 (100, 0): по спецификации 140.0 м
    (70 + sqrt(100^2 + 70^2) ≈ 192.2 м по ломаной — цифры условные, важно
    только то, что length != прямое расстояние и != длине ломаной).
    """
    model = ThermalNetworkModel(project_name="Изогнутый участок")
    model.add_node(NetworkNode(
        name="УТ-1а", x=0.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="street_unit",
    ))
    model.add_node(NetworkNode(
        name="ТК-2", x=100.0, y=0.0, z_surface=30.0, z_pipe_bottom=27.0, node_type="chamber",
    ))
    model.add_edge(NetworkEdge(
        start_node="УТ-1а", end_node="ТК-2", branch="supply",
        diameter=325, length=140.0, material="Steel", insulation="PPU+PE",
        laying_type="underground", waypoints=[(0.0, 70.0, 27.5)],
    ))
    return model


def test_waypoints_default_to_empty_list_for_straight_edges():
    model = make_model_with_edge()
    assert model.edges[0].waypoints == []


def test_polyline_of_straight_edge_is_just_two_node_points():
    model = make_model_with_edge()
    points = model.edges[0].polyline(model.nodes)

    assert points == [(116763.09, 110258.78, 138.80), (116850.15, 110200.45, 138.30)]


def test_polyline_includes_waypoints_in_order_between_nodes():
    model = make_bent_edge_model()
    points = model.edges[0].polyline(model.nodes)

    assert points == [(0.0, 0.0, 28.0), (0.0, 70.0, 27.5), (100.0, 0.0, 27.0)]


def test_polyline_length_is_longer_than_straight_distance_on_bent_edge():
    model = make_bent_edge_model()
    edge = model.edges[0]

    straight = ((100.0 - 0.0) ** 2 + (0.0 - 0.0) ** 2 + (27.0 - 28.0) ** 2) ** 0.5
    expected = (70.0 ** 2 + 0.5 ** 2) ** 0.5 + (100.0 ** 2 + 70.0 ** 2 + 0.5 ** 2) ** 0.5

    assert edge.polyline_length(model.nodes) == pytest.approx(expected)
    assert edge.polyline_length(model.nodes) > straight


def test_length_mismatch_reports_difference_between_spec_and_geometry():
    model = make_bent_edge_model()
    edge = model.edges[0]

    assert edge.length_mismatch(model.nodes) == pytest.approx(
        140.0 - edge.polyline_length(model.nodes)
    )


def test_slope_is_computed_from_spec_length_not_from_polyline():
    """Уклон осознанно считается по length, а не по длине ломаной (см. докстринг)."""
    model = make_bent_edge_model()
    edge = model.edges[0]

    assert edge.slope == pytest.approx((28.0 - 27.0) / 140.0)


def test_waypoints_are_normalized_to_float_tuples():
    """Точки, заданные списками int (типичный вход после JSON), нормализуются."""
    edge = NetworkEdge(
        start_node="A", end_node="B", diameter=100, length=10.0, material="Steel",
        insulation="none", laying_type="underground", waypoints=[[1, 2, 3]],
    )

    assert edge.waypoints == [(1.0, 2.0, 3.0)]
    assert all(isinstance(c, float) for c in edge.waypoints[0])


def test_waypoint_with_wrong_number_of_coordinates_is_rejected():
    with pytest.raises(ValueError):
        NetworkEdge(
            start_node="A", end_node="B", diameter=100, length=10.0, material="Steel",
            insulation="none", laying_type="underground", waypoints=[(1.0, 2.0)],
        )


def test_waypoints_survive_json_roundtrip_unchanged():
    model = make_bent_edge_model()

    restored = ThermalNetworkModel.from_json(model.to_json())

    assert restored.to_dict() == model.to_dict()
    assert restored.edges[0].waypoints == [(0.0, 70.0, 27.5)]


# ---------------------------------------------------------------------------
# Задача 26: раздельные графы подачи и обратки (решение предварительное)
#
# Причина: в эталоне Т1 и Т2 разведены на 0.70 м, а общий узел кладёт обе нитки
# в одну точку — половина разноса (0.35 м) больше допуска приёмки 0.2 м.
# ---------------------------------------------------------------------------


def make_two_branch_model() -> ThermalNetworkModel:
    """Две нитки на общих узлах — то, как модель выглядела до задачи 26."""
    model = make_two_node_model()
    for branch in ("supply", "return"):
        model.add_edge(NetworkEdge(
            start_node="УТ-1а", end_node="ТК-2", branch=branch,
            diameter=400, length=145.30, material="Steel",
            insulation="PPU+PE", laying_type="underground",
        ))
    return model


def test_node_key_keeps_the_plain_name_for_a_shared_node():
    """Общий узел не меняет ключ — старые датасеты читаются как раньше."""
    node = NetworkNode(name="ТК-2", x=0, y=0, z_surface=30, z_pipe_bottom=28, node_type="chamber")

    assert node.branch == "single"
    assert node.key == "ТК-2"


def test_twin_nodes_with_the_same_name_live_in_the_model_side_by_side():
    model = ThermalNetworkModel(project_name="Раздельные нитки")
    for branch in ("supply", "return"):
        model.add_node(NetworkNode(
            name="ТК-2", x=10.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0,
            node_type="chamber", branch=branch,
        ))

    assert set(model.nodes) == {"ТК-2@supply", "ТК-2@return"}


def test_duplicate_node_in_the_same_branch_is_still_rejected():
    model = ThermalNetworkModel(project_name="Раздельные нитки")
    node = NetworkNode(name="ТК-2", x=0, y=0, z_surface=30, z_pipe_bottom=28,
                       node_type="chamber", branch="supply")
    model.add_node(node)

    with pytest.raises(ValueError):
        model.add_node(NetworkNode(name="ТК-2", x=5, y=5, z_surface=30, z_pipe_bottom=28,
                                   node_type="chamber", branch="supply"))


def test_edge_prefers_its_own_branch_node_over_the_shared_one():
    """Смешанная модель: общая камера и свой узел подачи — ребро берёт свой."""
    model = ThermalNetworkModel(project_name="Смешанная")
    model.add_node(NetworkNode(name="A", x=0, y=0, z_surface=30, z_pipe_bottom=28,
                               node_type="chamber"))
    model.add_node(NetworkNode(name="B", x=100, y=0, z_surface=30, z_pipe_bottom=27,
                               node_type="chamber"))
    model.add_node(NetworkNode(name="B", x=100, y=5, z_surface=30, z_pipe_bottom=26,
                               node_type="chamber", branch="supply"))
    edge = NetworkEdge(start_node="A", end_node="B", branch="supply", diameter=325,
                       length=100.0, material="Steel", insulation="none",
                       laying_type="underground")
    model.add_edge(edge)

    start, end = edge.resolve_nodes(model.nodes)

    assert start.branch == "single"      # общий узел, своего для подачи нет
    assert (end.branch, end.y) == ("supply", 5)  # свой узел подачи


def test_edge_falls_back_to_the_shared_node_when_the_branch_has_none():
    model = make_two_branch_model()

    start, end = model.edges[0].resolve_nodes(model.nodes)

    assert start.name == "УТ-1а" and start.branch == "single"
    assert end.name == "ТК-2" and end.branch == "single"


def test_unknown_node_is_reported_for_the_branch_it_was_looked_up_for():
    model = ThermalNetworkModel(project_name="Пустая")
    edge = NetworkEdge(start_node="НЕТ", end_node="ТОЖЕ НЕТ", branch="supply",
                       diameter=100, length=10.0, material="Steel",
                       insulation="none", laying_type="underground")

    with pytest.raises(KeyError):
        edge.resolve_nodes(model.nodes)


def test_split_by_branch_gives_one_independent_model_per_branch():
    model = make_two_branch_model()

    parts = model.split_by_branch()

    assert set(parts) == {"supply", "return"}
    assert all(len(part.edges) == 1 for part in parts.values())
    assert all(len(part.nodes) == 2 for part in parts.values())


def test_split_by_branch_copies_nodes_so_the_parts_do_not_share_state():
    """Раздельные графы: правка подачи не должна двигать обратку."""
    model = make_two_branch_model()

    parts = model.split_by_branch()
    parts["supply"].nodes["УТ-1а"].y += 0.35

    assert parts["return"].nodes["УТ-1а"].y == model.nodes["УТ-1а"].y
    assert parts["supply"].nodes["УТ-1а"].y != model.nodes["УТ-1а"].y


def test_separate_branches_turns_a_shared_node_into_twins():
    model = make_two_branch_model()

    separated = model.separate_branches()

    assert set(separated.nodes) == {
        "УТ-1а@supply", "УТ-1а@return", "ТК-2@supply", "ТК-2@return",
    }
    assert len(separated.edges) == 2


def test_separate_branches_does_not_move_anything():
    """Насколько разводить нитки — вопрос данных; код координаты не выдумывает."""
    model = make_two_branch_model()

    separated = model.separate_branches()

    original = model.nodes["ТК-2"]
    for branch in ("supply", "return"):
        twin = separated.nodes[f"ТК-2@{branch}"]
        assert (twin.x, twin.y, twin.z_pipe_bottom) == (original.x, original.y, original.z_pipe_bottom)


def test_separate_branches_keeps_single_branch_networks_untouched():
    """Однониточная сеть (ВК) раздваиваться не должна."""
    model = make_model_with_edge()
    model.edges[0].branch = "single"

    separated = model.separate_branches()

    assert set(separated.nodes) == set(model.nodes)


def test_edges_of_separated_model_still_resolve_and_compute_slope():
    model = make_two_branch_model().separate_branches()

    for edge in model.edges:
        start, end = edge.resolve_nodes(model.nodes)
        assert start.branch == end.branch == edge.branch
        assert edge.calculate_slope(model.nodes) == pytest.approx(
            (start.z_pipe_bottom - end.z_pipe_bottom) / edge.length
        )


def test_separated_model_survives_json_roundtrip():
    model = make_two_branch_model().separate_branches()

    restored = ThermalNetworkModel.from_json(model.to_json())

    assert set(restored.nodes) == set(model.nodes)
    assert restored.to_dict() == model.to_dict()
