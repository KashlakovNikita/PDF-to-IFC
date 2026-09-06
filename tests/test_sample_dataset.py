"""Задача 4: тестовый датасет из реального PDF (Парнас) грузится в модель из задачи 2.

Данные — data/samples/parnas_nodes.csv и parnas_edges.csv, собраны вручную из
профиля (лист 5) и спецификации (лист 1) реального проекта. Отметки, диаметры,
материалы и изоляция — реальные (считаны с чертежа). Координаты x/y —
СИНТЕТИЧЕСКИЕ placeholder'ы (шаг 50 м вдоль оси): в PDF нет читаемой координатной
сетки с числами, реальные XY появятся в задаче 18 (извлечение координат с плана).
"""
import csv
from pathlib import Path

import pytest

from pdf_to_ifc.model import NetworkNode, NetworkEdge, ThermalNetworkModel

DATA_DIR = Path(__file__).parent.parent / "data" / "samples"


def load_sample_model() -> ThermalNetworkModel:
    model = ThermalNetworkModel(project_name="Парнас (тестовый датасет)", source="Котельная Парнас-4")

    with open(DATA_DIR / "parnas_nodes.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            model.add_node(NetworkNode(
                name=row["name"],
                x=float(row["x"]),
                y=float(row["y"]),
                z_surface=float(row["z_surface"]),
                z_pipe_bottom=float(row["z_pipe_bottom"]),
                node_type=row["node_type"],
            ))

    with open(DATA_DIR / "parnas_edges.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            model.add_edge(NetworkEdge(
                start_node=row["start_node"],
                end_node=row["end_node"],
                branch=row["branch"],
                diameter=int(row["diameter"]),
                length=float(row["length"]),
                material=row["material"],
                insulation=row["insulation"],
                laying_type=row["laying_type"],
            ))

    return model


def test_sample_dataset_has_10_to_15_nodes():
    model = load_sample_model()
    assert 10 <= len(model.nodes) <= 15


def test_sample_dataset_has_supply_and_return_for_every_section():
    model = load_sample_model()
    # 12 участков трассы x 2 нитки (Т1/Т2) = 24 ребра
    assert len(model.edges) == 24
    branches = {(e.start_node, e.end_node): set() for e in model.edges}
    for e in model.edges:
        branches[(e.start_node, e.end_node)].add(e.branch)
    assert all(b == {"supply", "return"} for b in branches.values())


def test_sample_dataset_diameter_transition_is_present():
    """Реальный переход Ф426 -> Ф325 где-то по трассе (не выдумка, а факт из спецификации)."""
    model = load_sample_model()
    diameters = {e.diameter for e in model.edges}
    assert diameters == {426, 325}


def test_sample_dataset_slopes_computed_without_errors():
    model = load_sample_model()
    assert all(e.slope is not None for e in model.edges)
