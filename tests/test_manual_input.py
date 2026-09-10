"""Задача 29: тесты ручного ввода сети текстом (pdf_to_ifc/manual_input.py).

Это запасной путь продукта: им инженер доводит проект до IFC там, где экстрактор
не справился. Поэтому проверяется не только «разбирается», но и то, что формат
прощает мелочи (регистр, запятая в числе, комментарии) и НЕ прощает потерю
данных (непонятная строка, неизвестный ключ, нечисловое значение).
"""

import pytest

from pdf_to_ifc.manual_input import (
    ManualInputError,
    format_manual_text,
    load_manual_file,
    parse_manual_text,
    save_manual_file,
)

SAMPLE = """# участок от УТ-1 до Н1, снят с чертежа 2/115-23-ТС л.2
проект: Парнас (ручной ввод)
источник: обмер 12.09.2026

узел УТ-1: x=116320.8 y=110434.3 земля=27.91 лоток=28.62 тип=street_unit
узел Н1:   x=116355.8 y=110420.5 земля=27.63 лоток=28.74 тип=support

участок УТ-1 -> Н1: нитка=supply ду=426 длина=38.1 материал=Сталь изоляция=ППУ-ОЦ прокладка=overhead давление=1.6 температура=130
    изгиб: 116340.0 110428.0 28.70
"""


def test_parses_project_nodes_and_edges():
    model = parse_manual_text(SAMPLE)

    assert model.project_name == "Парнас (ручной ввод)"
    assert model.source == "обмер 12.09.2026"
    assert set(model.nodes) == {"УТ-1", "Н1"}
    assert len(model.edges) == 1


def test_parses_pressure_and_temperature():
    """Задача 29: рабочие параметры теплоносителя вводятся руками."""
    edge = parse_manual_text(SAMPLE).edges[0]

    assert edge.pressure_mpa == pytest.approx(1.6)
    assert edge.temperature_c == pytest.approx(130.0)


def test_bend_line_attaches_to_the_previous_edge():
    edge = parse_manual_text(SAMPLE).edges[0]

    assert edge.waypoints == [(116340.0, 110428.0, 28.70)]


def test_pressure_and_temperature_default_to_unknown_not_zero():
    """Отсутствие значения — это «неизвестно», а не ноль."""
    text = """узел А: x=0 y=0 земля=30 лоток=28 тип=chamber
узел Б: x=50 y=0 земля=30 лоток=27 тип=chamber
участок А -> Б: ду=325 длина=50"""

    edge = parse_manual_text(text).edges[0]

    assert edge.pressure_mpa is None
    assert edge.temperature_c is None


def test_accepts_comma_as_decimal_separator():
    """Инженер пишет 1,6 — так принято в русской документации."""
    text = """узел А: x=0 y=0 земля=30 лоток=28 тип=chamber
узел Б: x=50 y=0 земля=30 лоток=27 тип=chamber
участок А -> Б: ду=325 длина=50,5 давление=1,6"""

    edge = parse_manual_text(text).edges[0]

    assert edge.length == pytest.approx(50.5)
    assert edge.pressure_mpa == pytest.approx(1.6)


def test_accepts_english_keys_and_any_case():
    text = """PROJECT: Test
УЗЕЛ A: X=0 Y=0 z_surface=30 z_pipe_bottom=28 node_type=chamber
узел B: x=50 y=0 земля=30 лоток=27 тип=chamber
EDGE A -> B: dn=325 length=50 branch=return"""

    model = parse_manual_text(text)

    assert model.project_name == "Test"
    assert model.edges[0].branch == "return"


def test_branch_specific_nodes_are_supported():
    """Раздельные графы задачи 26 задаются и руками."""
    text = """узел ТК-2: x=0 y=0 земля=30 лоток=28 тип=chamber нитка=supply
узел ТК-2: x=0 y=0.7 земля=30 лоток=28 тип=chamber нитка=return
узел ТК-3: x=50 y=0 земля=30 лоток=27 тип=chamber нитка=supply
участок ТК-2 -> ТК-3: ду=325 длина=50 нитка=supply"""

    model = parse_manual_text(text)

    assert set(model.nodes) == {"ТК-2@supply", "ТК-2@return", "ТК-3@supply"}


# --- формат не должен терять данные молча ----------------------------------


def test_unrecognised_line_is_reported_with_its_number():
    text = """узел А: x=0 y=0 земля=30 лоток=28 тип=chamber
абракадабра"""

    with pytest.raises(ManualInputError) as error:
        parse_manual_text(text)

    assert error.value.line_number == 2
    assert "не опознана" in str(error.value)


def test_unknown_key_is_rejected_not_ignored():
    """Опечатка в ключе не должна тихо съедать значение."""
    text = "узел А: x=0 y=0 земля=30 лоток=28 тип=chamber цвет=синий"

    with pytest.raises(ManualInputError) as error:
        parse_manual_text(text)

    assert "цвет" in str(error.value)


def test_non_numeric_value_is_reported():
    text = "узел А: x=налево y=0 земля=30 лоток=28 тип=chamber"

    with pytest.raises(ManualInputError) as error:
        parse_manual_text(text)

    assert "не число" in str(error.value)


def test_missing_node_field_is_reported():
    text = "узел А: x=0 y=0 тип=chamber"

    with pytest.raises(ManualInputError) as error:
        parse_manual_text(text)

    assert "не хватает полей" in str(error.value)


def test_edge_without_arrow_is_reported():
    text = """узел А: x=0 y=0 земля=30 лоток=28 тип=chamber
участок А Б: ду=325 длина=50"""

    with pytest.raises(ManualInputError) as error:
        parse_manual_text(text)

    assert "узел -> узел" in str(error.value)


def test_bend_before_any_edge_is_reported():
    with pytest.raises(ManualInputError) as error:
        parse_manual_text("изгиб: 1 2 3")

    assert "раньше участка" in str(error.value)


def test_bend_with_wrong_number_of_coordinates_is_reported():
    text = """узел А: x=0 y=0 земля=30 лоток=28 тип=chamber
узел Б: x=50 y=0 земля=30 лоток=27 тип=chamber
участок А -> Б: ду=325 длина=50
    изгиб: 1 2"""

    with pytest.raises(ManualInputError) as error:
        parse_manual_text(text)

    assert "тремя числами" in str(error.value)


# --- двусторонний путь ------------------------------------------------------


def test_format_and_parse_roundtrip_keeps_the_model():
    model = parse_manual_text(SAMPLE)

    restored = parse_manual_text(format_manual_text(model))

    assert restored.to_dict() == model.to_dict()


def test_save_and_load_file_roundtrip(tmp_path):
    model = parse_manual_text(SAMPLE)
    path = tmp_path / "network.txt"

    save_manual_file(model, path)
    restored = load_manual_file(path)

    assert restored.to_dict() == model.to_dict()
    assert "узел УТ-1" in path.read_text(encoding="utf-8")


def test_formatted_text_omits_unknown_pressure_and_temperature():
    """В выгрузке не должно появляться то, чего в модели нет."""
    text = """узел А: x=0 y=0 земля=30 лоток=28 тип=chamber
узел Б: x=50 y=0 земля=30 лоток=27 тип=chamber
участок А -> Б: ду=325 длина=50"""

    dumped = format_manual_text(parse_manual_text(text))

    assert "давление" not in dumped
    assert "температура" not in dumped


def test_gost_designation_is_parsed_and_dumped_back():
    """Задача 30: обозначение по ГОСТ содержит пробелы, поэтому в кавычках."""
    text = """узел А: x=0 y=0 земля=30 лоток=28 тип=chamber
узел Б: x=50 y=0 земля=30 лоток=27 тип=chamber
участок А -> Б: ду=426 длина=50 материал=Сталь гост="Ст 426х9,0/560 ППУ-ОЦ в изоляции по ГОСТ 30732-2020"
"""

    model = parse_manual_text(text)
    edge = model.edges[0]

    assert edge.gost_designation == "Ст 426х9,0/560 ППУ-ОЦ в изоляции по ГОСТ 30732-2020"
    assert edge.material == "Сталь"  # обозначение живёт рядом с материалом, не вместо
    assert 'гост="Ст 426х9,0/560' in format_manual_text(model)


def test_gost_designation_defaults_to_unknown():
    text = """узел А: x=0 y=0 земля=30 лоток=28 тип=chamber
узел Б: x=50 y=0 земля=30 лоток=27 тип=chamber
участок А -> Б: ду=325 длина=50"""

    assert parse_manual_text(text).edges[0].gost_designation is None
    assert "гост" not in format_manual_text(parse_manual_text(text))
