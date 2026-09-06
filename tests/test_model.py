import pytest

from pdf_to_ifc.model import NetworkNode, NetworkEdge, ThermalNetworkModel


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
