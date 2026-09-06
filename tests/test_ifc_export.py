"""Задача 6: минимальный IFC-каркас (IFCPROJECT + IFCSITE).

ifcopenshell нельзя установить в песочнице, где писался этот код — он
проверялся вручную только по документированному API ifcopenshell.api.
Это тот тест, который реально должен прогнать pytest на машине с
установленным ifcopenshell (см. requirements.txt).
"""

import ifcopenshell
import pytest

from pdf_to_ifc.ifc_export import create_minimal_project, generate_ifc_from_network, save
from pdf_to_ifc.model import NetworkEdge, NetworkNode, ThermalNetworkModel


def test_create_minimal_project_has_project_and_site():
    file = create_minimal_project(project_name="Тест-проект", site_name="Тест-площадка")

    projects = file.by_type("IfcProject")
    sites = file.by_type("IfcSite")

    assert len(projects) == 1
    assert projects[0].Name == "Тест-проект"
    assert len(sites) == 1
    assert sites[0].Name == "Тест-площадка"


def test_site_is_aggregated_under_project():
    file = create_minimal_project()
    project = file.by_type("IfcProject")[0]
    site = file.by_type("IfcSite")[0]

    aggregates = file.by_type("IfcRelAggregates")
    assert any(
        rel.RelatingObject == project and site in rel.RelatedObjects
        for rel in aggregates
    )


def test_project_has_length_unit_in_meters():
    file = create_minimal_project()
    units = file.by_type("IfcUnitAssignment")[0].Units
    length_units = [u for u in units if getattr(u, "UnitType", None) == "LENGTHUNIT"]

    assert len(length_units) == 1
    assert length_units[0].Name == "METRE"


def test_project_has_body_geometric_context():
    file = create_minimal_project()
    contexts = file.by_type("IfcGeometricRepresentationSubContext")

    assert any(c.ContextIdentifier == "Body" for c in contexts)


def test_save_writes_a_file_that_reopens_with_ifcopenshell(tmp_path):
    file = create_minimal_project(project_name="Сохранённый проект")
    path = tmp_path / "minimal.ifc"

    save(file, path)
    reopened = ifcopenshell.open(str(path))

    assert path.exists()
    assert reopened.by_type("IfcProject")[0].Name == "Сохранённый проект"
    assert len(reopened.by_type("IfcSite")) == 1


# ---------------------------------------------------------------------------
# Задача 7: generate_ifc_from_network() — камеры/опоры/компенсаторы и трубы
# ---------------------------------------------------------------------------


def make_four_node_model() -> ThermalNetworkModel:
    """chamber, street_unit, support, compensator — все 4 типа узлов сразу,
    плюс одна двухниточная (supply/return) труба между двумя из них.
    """
    model = ThermalNetworkModel(project_name="Тест IFC")
    model.add_node(NetworkNode(name="УТ-1", x=0, y=0, z_surface=28.0, z_pipe_bottom=27.0, node_type="street_unit"))
    model.add_node(NetworkNode(name="Н1", x=50, y=0, z_surface=28.0, z_pipe_bottom=26.9, node_type="support"))
    model.add_node(NetworkNode(name="УК1", x=100, y=0, z_surface=28.0, z_pipe_bottom=26.8, node_type="compensator"))
    model.add_node(NetworkNode(name="ТК-2", x=150, y=0, z_surface=28.0, z_pipe_bottom=26.7, node_type="chamber"))

    model.add_edge(NetworkEdge(
        start_node="УТ-1", end_node="Н1", branch="supply",
        diameter=426, length=50.0, material="Steel", insulation="PUR-OC", laying_type="overhead",
    ))
    model.add_edge(NetworkEdge(
        start_node="УТ-1", end_node="Н1", branch="return",
        diameter=426, length=50.0, material="Steel", insulation="PUR-OC", laying_type="overhead",
    ))
    return model


def test_generate_ifc_creates_chamber_and_fitting_per_node_type():
    file = generate_ifc_from_network(make_four_node_model())

    chambers = {e.Name: e for e in file.by_type("IfcDistributionChamberElement")}
    fittings = {e.Name: e for e in file.by_type("IfcFlowFitting")}

    assert set(chambers) == {"УТ-1", "ТК-2"}
    assert set(fittings) == {"Н1", "УК1"}
    assert chambers["УТ-1"].ObjectType == "Уличный узел"
    assert chambers["ТК-2"].ObjectType == "Камера"
    assert fittings["Н1"].ObjectType == "Опора"
    assert fittings["УК1"].ObjectType == "Компенсатор"


def test_generate_ifc_creates_one_pipe_segment_per_branch():
    file = generate_ifc_from_network(make_four_node_model())

    pipes = file.by_type("IfcPipeSegment")
    names = {p.Name for p in pipes}

    assert len(pipes) == 2
    assert names == {"УТ-1->Н1 (supply)", "УТ-1->Н1 (return)"}


def test_generate_ifc_places_node_entities_at_node_coordinates():
    file = generate_ifc_from_network(make_four_node_model())

    chamber = next(e for e in file.by_type("IfcDistributionChamberElement") if e.Name == "ТК-2")
    coords = chamber.ObjectPlacement.RelativePlacement.Location.Coordinates

    assert coords == pytest.approx((150.0, 0.0, 26.7))


def test_generate_ifc_places_pipe_at_midpoint_of_its_nodes():
    file = generate_ifc_from_network(make_four_node_model())

    pipe = next(p for p in file.by_type("IfcPipeSegment") if p.Name == "УТ-1->Н1 (supply)")
    coords = pipe.ObjectPlacement.RelativePlacement.Location.Coordinates

    # УТ-1 (0, 0, 27.0) и Н1 (50, 0, 26.9) -> середина
    assert coords == pytest.approx((25.0, 0.0, 26.95))


def test_generate_ifc_containment_includes_nodes_and_pipes():
    file = generate_ifc_from_network(make_four_node_model())

    site = file.by_type("IfcSite")[0]
    rels = [r for r in file.by_type("IfcRelContainedInSpatialStructure") if r.RelatingStructure == site]
    contained = {product.Name for rel in rels for product in rel.RelatedElements}

    assert contained == {"УТ-1", "Н1", "УК1", "ТК-2", "УТ-1->Н1 (supply)", "УТ-1->Н1 (return)"}


def test_generate_ifc_rejects_unknown_node_type():
    model = ThermalNetworkModel(project_name="Тест")
    model.add_node(NetworkNode(name="X", x=0, y=0, z_surface=0, z_pipe_bottom=0, node_type="unknown_type"))

    with pytest.raises(ValueError):
        generate_ifc_from_network(model)


def test_generate_ifc_reuses_a_provided_file():
    base_file = create_minimal_project(project_name="Общий каркас")

    result = generate_ifc_from_network(make_four_node_model(), file=base_file)

    assert result is base_file
    assert result.by_type("IfcProject")[0].Name == "Общий каркас"
    assert len(result.by_type("IfcPipeSegment")) == 2

