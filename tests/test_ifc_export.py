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


def test_generate_ifc_places_pipe_at_start_node_oriented_towards_end_node():
    file = generate_ifc_from_network(make_four_node_model())

    pipe = next(p for p in file.by_type("IfcPipeSegment") if p.Name == "УТ-1->Н1 (supply)")
    placement = pipe.ObjectPlacement.RelativePlacement

    # УТ-1 (0, 0, 27.0) -> Н1 (50, 0, 26.9)
    assert placement.Location.Coordinates == pytest.approx((0.0, 0.0, 27.0))
    dx, dy, dz = (50.0, 0.0, -0.1)
    length = (dx ** 2 + dy ** 2 + dz ** 2) ** 0.5
    assert placement.Axis.DirectionRatios == pytest.approx((dx / length, dy / length, dz / length))


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


# ---------------------------------------------------------------------------
# Задача 8: базовая геометрия труб (цилиндр по DN, без BREP)
# ---------------------------------------------------------------------------


def test_pipe_has_swept_solid_representation_with_no_breps():
    file = generate_ifc_from_network(make_four_node_model())
    pipe = file.by_type("IfcPipeSegment")[0]

    assert pipe.Representation is not None
    shape_reps = pipe.Representation.Representations
    assert len(shape_reps) == 1
    assert shape_reps[0].RepresentationType == "SweptSolid"
    assert file.by_type("IfcFacetedBrep") == []
    assert file.by_type("IfcTriangulatedFaceSet") == []


def test_pipe_solid_is_extruded_circle_with_radius_from_dn_and_depth_from_length():
    file = generate_ifc_from_network(make_four_node_model())
    pipe = next(p for p in file.by_type("IfcPipeSegment") if p.Name == "УТ-1->Н1 (supply)")

    solid = pipe.Representation.Representations[0].Items[0]
    assert solid.is_a("IfcExtrudedAreaSolid")
    assert solid.SweptArea.is_a("IfcCircleProfileDef")
    # DN=426 мм -> радиус 0.213 м; length=50.0 м из parnas-подобного ребра
    assert solid.SweptArea.Radius == pytest.approx(426 / 1000 / 2)
    assert solid.Depth == pytest.approx(50.0)
    assert solid.ExtrudedDirection.DirectionRatios == pytest.approx((0.0, 0.0, 1.0))


def test_pipe_geometry_rejects_zero_length_direction():
    model = ThermalNetworkModel(project_name="Тест")
    model.add_node(NetworkNode(name="A", x=0, y=0, z_surface=0, z_pipe_bottom=0, node_type="chamber"))
    model.add_node(NetworkNode(name="B", x=0, y=0, z_surface=0, z_pipe_bottom=0, node_type="chamber"))
    # length > 0 нужен для add_edge (иначе деление на 0 в calculate_slope),
    # а вот координаты узлов совпадают — направление трубы не определено.
    model.add_edge(NetworkEdge(
        start_node="A", end_node="B",
        diameter=100, length=10.0, material="Steel", insulation="none", laying_type="underground",
    ))

    with pytest.raises(ValueError):
        generate_ifc_from_network(model)


def test_chambers_and_fittings_have_no_geometry_representation():
    file = generate_ifc_from_network(make_four_node_model())

    for chamber in file.by_type("IfcDistributionChamberElement"):
        assert chamber.Representation is None
    for fitting in file.by_type("IfcPipeFitting"):
        assert fitting.Representation is None


# ---------------------------------------------------------------------------
# Задача 1 брифа: waypoints — труба идёт по ломаной, а не мимо конечного узла
#
# Ключевой кейс, которого раньше не было в покрытии: length (спецификация)
# заведомо больше прямого расстояния между узлами. Старый код на таком ребре
# создавал ОДИН цилиндр длиной edge.length вдоль прямого направления и
# промахивался мимо конечного узла ровно на величину изгиба — тесты ниже
# на нём падают.
# ---------------------------------------------------------------------------


def pipe_axis_endpoints(pipe):
    """Начало и конец оси трубы в глобальных координатах.

    Считается из ObjectPlacement (Location + Axis) и Depth экструзии — то есть
    ровно так, как эту трубу увидит вьюер, а не так, как её задумывал код.
    """
    placement = pipe.ObjectPlacement.RelativePlacement
    start = tuple(placement.Location.Coordinates)
    axis = tuple(placement.Axis.DirectionRatios)
    depth = pipe.Representation.Representations[0].Items[0].Depth
    end = tuple(s + a * depth for s, a in zip(start, axis))
    return start, end


def make_bent_model() -> ThermalNetworkModel:
    """Г-образный участок с двумя точками изгиба между двумя узлами.

    ТК-1 (0, 0, 28) -> (10, 20, 28) -> (20, 20, 28) -> ТК-2 (30, 0, 28).
    Прямое расстояние между узлами 30 м, длина ломаной ~54.7 м, а в
    спецификации стоит 60.0 м — все три величины разные намеренно.
    """
    model = ThermalNetworkModel(project_name="Изгибы")
    model.add_node(NetworkNode(name="ТК-1", x=0.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber"))
    model.add_node(NetworkNode(name="ТК-2", x=30.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber"))
    model.add_edge(NetworkEdge(
        start_node="ТК-1", end_node="ТК-2", branch="supply",
        diameter=325, length=60.0, material="Steel", insulation="PPU+PE",
        laying_type="underground", waypoints=[(10.0, 20.0, 28.0), (20.0, 20.0, 28.0)],
    ))
    return model


def test_edge_with_waypoints_is_split_into_one_pipe_per_polyline_link():
    file = generate_ifc_from_network(make_bent_model())

    pipes = file.by_type("IfcPipeSegment")
    names = {p.Name for p in pipes}

    assert len(pipes) == 3
    assert names == {
        "ТК-1->ТК-2 (supply) [1/3]",
        "ТК-1->ТК-2 (supply) [2/3]",
        "ТК-1->ТК-2 (supply) [3/3]",
    }


def test_pipe_chain_starts_at_start_node_and_ends_exactly_at_end_node():
    """Тот самый промах мимо конечного узла: старый код давал конец (60, 0, 28)."""
    file = generate_ifc_from_network(make_bent_model())

    pipes = sorted(file.by_type("IfcPipeSegment"), key=lambda p: p.Name)
    first_start, _ = pipe_axis_endpoints(pipes[0])
    _, last_end = pipe_axis_endpoints(pipes[-1])

    assert first_start == pytest.approx((0.0, 0.0, 28.0))
    assert last_end == pytest.approx((30.0, 0.0, 28.0))


def test_each_sub_segment_is_as_long_as_its_own_polyline_link():
    """Depth под-сегмента — расстояние между его концами, а не edge.length целиком."""
    file = generate_ifc_from_network(make_bent_model())

    pipes = sorted(file.by_type("IfcPipeSegment"), key=lambda p: p.Name)
    depths = [p.Representation.Representations[0].Items[0].Depth for p in pipes]

    diagonal = (10.0 ** 2 + 20.0 ** 2) ** 0.5
    assert depths == pytest.approx([diagonal, 10.0, diagonal])
    assert sum(depths) != pytest.approx(60.0)  # спецификация и геометрия расходятся


def test_sub_segments_are_joined_end_to_end_without_gaps():
    file = generate_ifc_from_network(make_bent_model())

    pipes = sorted(file.by_type("IfcPipeSegment"), key=lambda p: p.Name)
    for previous, following in zip(pipes, pipes[1:]):
        _, previous_end = pipe_axis_endpoints(previous)
        following_start, _ = pipe_axis_endpoints(following)
        assert previous_end == pytest.approx(following_start)


def test_bend_fitting_is_created_in_every_waypoint():
    file = generate_ifc_from_network(make_bent_model())

    bends = [f for f in file.by_type("IfcPipeFitting") if f.PredefinedType == "BEND"]
    locations = {tuple(b.ObjectPlacement.RelativePlacement.Location.Coordinates) for b in bends}

    assert len(bends) == 2
    assert locations == {(10.0, 20.0, 28.0), (20.0, 20.0, 28.0)}
    assert {b.Name for b in bends} == {"ТК-1->ТК-2 (supply) изгиб 1", "ТК-1->ТК-2 (supply) изгиб 2"}


def test_bend_fittings_are_contained_in_the_site():
    file = generate_ifc_from_network(make_bent_model())

    site = file.by_type("IfcSite")[0]
    rels = [r for r in file.by_type("IfcRelContainedInSpatialStructure") if r.RelatingStructure == site]
    contained = {product.Name for rel in rels for product in rel.RelatedElements}

    assert "ТК-1->ТК-2 (supply) изгиб 1" in contained
    assert "ТК-1->ТК-2 (supply) [1/3]" in contained


def test_edge_without_waypoints_keeps_previous_single_pipe_behaviour():
    """Обратная совместимость: пустой waypoints = ровно то, что было до задачи 1."""
    file = generate_ifc_from_network(make_four_node_model())

    pipes = file.by_type("IfcPipeSegment")
    bends = [f for f in file.by_type("IfcPipeFitting") if f.PredefinedType == "BEND"]

    assert len(pipes) == 2
    assert {p.Name for p in pipes} == {"УТ-1->Н1 (supply)", "УТ-1->Н1 (return)"}
    assert bends == []


def test_horizontal_pipe_along_x_axis_does_not_break_placement():
    """Регресс: труба строго вдоль оси X роняла экспорт нулевым RefDirection.

    _perpendicular_direction() выбирал опорный вектор (1, 0, 0) именно тогда,
    когда ось трубы почти совпадает с X, — проекция вырождалась в ноль.
    Датасет с шагом 50 м и перепадом 0.1 м промахивался мимо этого случая
    на 2e-6, поэтому в тесты баг не попадал.
    """
    model = ThermalNetworkModel(project_name="Горизонталь")
    model.add_node(NetworkNode(name="A", x=0.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber"))
    model.add_node(NetworkNode(name="B", x=50.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber"))
    model.add_edge(NetworkEdge(
        start_node="A", end_node="B", diameter=100, length=50.0, material="Steel",
        insulation="none", laying_type="underground",
    ))

    file = generate_ifc_from_network(model)

    placement = file.by_type("IfcPipeSegment")[0].ObjectPlacement.RelativePlacement
    axis = placement.Axis.DirectionRatios
    ref = placement.RefDirection.DirectionRatios

    assert axis == pytest.approx((1.0, 0.0, 0.0))
    assert sum(a * r for a, r in zip(axis, ref)) == pytest.approx(0.0, abs=1e-9)
    assert sum(r * r for r in ref) == pytest.approx(1.0)
