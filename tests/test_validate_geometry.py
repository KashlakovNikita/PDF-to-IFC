"""Задача 5 брифа: тесты на сверку геометрии (scripts/validate_geometry.py).

Тесты делятся на две части:

1. Проверка самой метрики на синтетике — расстояние до отрезка, допуск как
   строжайшее из абсолютного и относительного, отчёт по направлениям.
2. Проверка того, что осевая линия, извлечённая из СГЕНЕРИРОВАННОГО файла
   через ifcopenshell.geom, ложится ровно на ломаную доменной модели. Это
   ключевой тест задачи 1 брифа с другой стороны: он смотрит не на атрибуты
   IFC-сущностей, а на то, где тело трубы реально оказалось в пространстве.
   На коде до фикса он падает — там труба уезжала мимо конечного узла.

Тесты, которым нужен эталонный файл (он лежит в data/raw и в репозитории
физически есть, но в общем случае это тяжёлый бинарник), пропускаются, если
файла нет на диске.
"""

import numpy as np
import pytest

from pdf_to_ifc.ifc_export import generate_ifc_from_network, save
from pdf_to_ifc.model import NetworkEdge, NetworkNode, ThermalNetworkModel
from validate_geometry import (
    DEFAULT_REFERENCE,
    Centerline,
    _distances_to_network,
    compare,
    load_generated_centerlines,
    load_reference_centerlines,
)


def line(start, end, name="line") -> Centerline:
    return Centerline(name=name, start=np.array(start, dtype=float),
                      end=np.array(end, dtype=float), radius=0.1)


def make_bent_model() -> ThermalNetworkModel:
    """Г-образный участок: ТК-1 (0,0,28) -> (10,20,28) -> (20,20,28) -> ТК-2 (30,0,28)."""
    model = ThermalNetworkModel(project_name="Сверка геометрии")
    model.add_node(NetworkNode(name="ТК-1", x=0.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber"))
    model.add_node(NetworkNode(name="ТК-2", x=30.0, y=0.0, z_surface=30.0, z_pipe_bottom=28.0, node_type="chamber"))
    model.add_edge(NetworkEdge(
        start_node="ТК-1", end_node="ТК-2", branch="supply",
        diameter=325, length=60.0, material="Steel", insulation="PPU+PE",
        laying_type="underground", waypoints=[(10.0, 20.0, 28.0), (20.0, 20.0, 28.0)],
    ))
    return model


# --- метрика ---------------------------------------------------------------


def test_distance_is_measured_to_the_segment_not_to_its_endpoints():
    """Точка над серединой длинного отрезка отстоит от него на перпендикуляр."""
    network = [line((0.0, 0.0, 0.0), (100.0, 0.0, 0.0))]
    points = np.array([[50.0, 3.0, 0.0]])

    assert _distances_to_network(points, network)[0] == pytest.approx(3.0)


def test_distance_beyond_the_segment_end_is_measured_to_the_end():
    network = [line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))]
    points = np.array([[13.0, 4.0, 0.0]])

    assert _distances_to_network(points, network)[0] == pytest.approx(5.0)


def test_identical_networks_give_zero_deviation_and_full_share():
    network = [line((0.0, 0.0, 0.0), (50.0, 0.0, 0.0)), line((50.0, 0.0, 0.0), (50.0, 50.0, 0.0))]

    report = compare(network, network, title="сам с собой", samples=20,
                     max_deviation=0.2, max_relative=0.05)

    assert report.share_within_tolerance == 1.0
    assert report.deviations().max() == pytest.approx(0.0, abs=1e-9)


def test_shifted_network_is_out_of_tolerance_by_the_shift_value():
    original = [line((0.0, 0.0, 0.0), (50.0, 0.0, 0.0))]
    shifted = [line((0.0, 1.0, 0.0), (50.0, 1.0, 0.0))]

    report = compare(shifted, original, title="сдвиг на 1 м", samples=20,
                     max_deviation=0.2, max_relative=0.05)

    assert report.deviations().max() == pytest.approx(1.0)
    assert report.share_within_tolerance == 0.0
    assert report.sections[0].within_tolerance is False


def test_tolerance_is_the_stricter_of_absolute_and_relative():
    """Для короткого участка строже относительный допуск, для длинного — абсолютный."""
    short = [line((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), name="короткий")]
    long = [line((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), name="длинный")]
    target = [line((0.0, 0.0, 0.0), (100.0, 0.0, 0.0))]

    short_report = compare(short, target, title="", samples=5, max_deviation=0.2, max_relative=0.05)
    long_report = compare(long, target, title="", samples=5, max_deviation=0.2, max_relative=0.05)

    assert short_report.sections[0].tolerance == pytest.approx(0.05 * 2.0)
    assert long_report.sections[0].tolerance == pytest.approx(0.2)


def test_share_within_tolerance_is_weighted_by_length_not_by_count():
    """Доля считается по ДЛИНЕ сети: один длинный плохой участок весит больше."""
    target = [line((0.0, 0.0, 0.0), (100.0, 0.0, 0.0))]
    source = [
        line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), name="хороший короткий"),
        line((0.0, 90.0, 0.0), (90.0, 90.0, 0.0), name="плохой длинный"),
    ]

    report = compare(source, target, title="", samples=5, max_deviation=0.2, max_relative=0.05)

    assert report.share_within_tolerance == pytest.approx(10.0 / 100.0)


# --- геометрия сгенерированного файла --------------------------------------


def test_generated_centerlines_land_exactly_on_the_model_polyline(tmp_path):
    """Осевые линии из тела трубы совпадают с ломаной модели.

    Извлекается не Depth/ObjectPlacement, а фактические вершины тела через
    ifcopenshell.geom — то есть проверяется то, что увидит вьюер. До фикса
    задачи 1 брифа тело уезжало мимо конечного узла, и тест падал.
    """
    model = make_bent_model()
    path = tmp_path / "bent.ifc"
    save(generate_ifc_from_network(model), path)

    centerlines, stats = load_generated_centerlines(path)
    endpoints = sorted(
        tuple(np.round(point, 3))
        for centerline in centerlines
        for point in (centerline.start, centerline.end)
    )
    expected = sorted(
        tuple(np.round(np.array(point), 3))
        for point in [(0, 0, 28), (10, 20, 28), (10, 20, 28), (20, 20, 28), (20, 20, 28), (30, 0, 28)]
    )

    assert stats["pipes_total"] == 3
    assert stats["geometry_failed"] == 0
    assert endpoints == expected


def test_generated_file_compared_with_itself_is_fully_within_tolerance(tmp_path):
    model = make_bent_model()
    path = tmp_path / "bent.ifc"
    save(generate_ifc_from_network(model), path)

    centerlines, _ = load_generated_centerlines(path)
    report = compare(centerlines, centerlines, title="", samples=20,
                     max_deviation=0.2, max_relative=0.05)

    assert report.share_within_tolerance == 1.0


def test_centerline_length_matches_polyline_link_length(tmp_path):
    """Длина извлечённой оси = длине звена ломаной, а не edge.length целиком."""
    model = make_bent_model()
    path = tmp_path / "bent.ifc"
    save(generate_ifc_from_network(model), path)

    centerlines, _ = load_generated_centerlines(path)
    lengths = sorted(round(c.length, 3) for c in centerlines)
    diagonal = round((10.0 ** 2 + 20.0 ** 2) ** 0.5, 3)

    assert lengths == [10.0, diagonal, diagonal]


def test_extracted_radius_matches_dn(tmp_path):
    """Толщина тела, измеренная от оси, — это радиус по DN (в пределах дискретизации круга)."""
    model = make_bent_model()
    path = tmp_path / "bent.ifc"
    save(generate_ifc_from_network(model), path)

    centerlines, _ = load_generated_centerlines(path)

    assert all(c.radius == pytest.approx(0.325 / 2, rel=0.05) for c in centerlines)


# --- эталон ----------------------------------------------------------------


needs_reference = pytest.mark.skipif(
    not DEFAULT_REFERENCE.exists(),
    reason=f"нет эталонного файла {DEFAULT_REFERENCE} (тяжёлый бинарник из data/raw)",
)


@needs_reference
def test_reference_loader_takes_only_heating_systems_and_drops_drainage():
    """Фильтр систем: Т1/Т2 берём, дренаж «Др» — нет (он не из этого проекта)."""
    heating, heating_stats = load_reference_centerlines(DEFAULT_REFERENCE, ("Т1", "Т2", "Т1/Т2"))
    drainage, drainage_stats = load_reference_centerlines(DEFAULT_REFERENCE, ("Др",))

    assert heating_stats["proxy_total"] == 328
    assert heating_stats["pipes_total"] == 165
    assert heating_stats["pipes_selected"] == 130
    assert drainage_stats["pipes_selected"] == 35
    assert len(heating) == 130
    assert len(drainage) == 35


@needs_reference
def test_reference_centerlines_are_straight_pipe_pieces_in_local_coordinates():
    """Эталон — прямые куски труб в МСК; это обоснование метода извлечения оси."""
    centerlines, _ = load_reference_centerlines(DEFAULT_REFERENCE, ("Т1", "Т2", "Т1/Т2"))
    starts = np.array([c.start for c in centerlines])

    assert all(c.length > 0.1 for c in centerlines)
    assert all(c.radius < c.length for c in centerlines)
    assert starts[:, 0].min() > 100_000  # X в местной системе координат, не локальный ноль
    assert starts[:, 1].min() > 100_000
