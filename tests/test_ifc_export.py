"""Задача 6: минимальный IFC-каркас (IFCPROJECT + IFCSITE).

ifcopenshell нельзя установить в песочнице, где писался этот код — он
проверялся вручную только по документированному API ifcopenshell.api.
Это тот тест, который реально должен прогнать pytest на машине с
установленным ifcopenshell (см. requirements.txt).
"""

import ifcopenshell

from pdf_to_ifc.ifc_export import create_minimal_project, save


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
