"""Задача 29: ручной ввод сети текстом — запасной путь, когда парсинг не сработал.

Зачем это часть продукта, а не костыль
---------------------------------------
Инструмент строится вокруг парсинга PDF и DWG, но по разведке исходников (Ш0)
уже видно, что автоизвлечение сработает не всегда: на листах планов и профилей
этого проекта текст переведён в кривые, отметки лежат в невычисленных полях
AutoCAD, а координатной сетки в PDF нет вовсе. Инженеру нужен путь, которым он
доведёт проект до IFC даже там, где экстрактор молчит, — и этот путь должен быть
частью продукта, а не «ну откройте JSON в блокноте».

Отсюда требования к формату: он пишется руками без документации под рукой,
читается глазами при сверке с чертежом, переживает копирование в письмо и
диффится в гите построчно. JSON модели (ThermalNetworkModel.to_json) этим
требованиям не отвечает: он вложенный, с кавычками и запятыми, и одна опечатка
рушит весь файл.

Формат
-------
Построчный, с русскими ключами. Пустые строки и строки, начинающиеся с "#",
игнорируются. Регистр ключей не важен, порядок полей — тоже.

    # Парнас, участок от УТ-1 до ТК-2
    проект: Парнас (ручной ввод)
    источник: обмер 12.09.2026, чертёж 2/115-23-ТС л.2

    узел УТ-1: x=116320.8 y=110434.3 земля=27.91 лоток=28.62 тип=street_unit
    узел Н1:   x=116355.8 y=110420.5 земля=27.63 лоток=28.74 тип=support

    участок УТ-1 -> Н1: нитка=supply ду=426 длина=38.1 материал=Сталь
        изгиб: 116340.0 110428.0 28.70
        изгиб: 116350.0 110424.0 28.72

Строка «изгиб» относится к последнему объявленному участку и задаёт точку
поворота трассы (waypoints задачи 1 брифа): три числа — x, y, z.

Ключи узла: x, y, земля (z_surface), лоток (z_pipe_bottom), тип (node_type),
нитка (branch — для раздельных графов задачи 26).
Ключи участка: нитка, ду (диаметр, мм), длина (м), материал, изоляция,
прокладка (тип прокладки), давление (МПа), температура (°C), гост
(обозначение трубы по ГОСТ; пишется в кавычках, потому что содержит пробелы:
гост="Ст 426х9,0/560 ППУ-ОЦ в изоляции по ГОСТ 30732-2020").

Английские написания ключей тоже принимаются (x, y, z_surface, z_pipe_bottom,
node_type, branch, dn, length, material, insulation, laying_type, pressure,
temperature, gost) — чтобы файл можно было писать в раскладке, которая под рукой.

Ошибки
-------
Разбор не «пропускает молча»: на непонятной строке, неизвестном ключе или
нечисловом значении поднимается ManualInputError с номером строки и её текстом.
Файл, который инженер правит руками, обязан говорить, что именно не так, а не
терять данные наполовину.

Обратно в текст
----------------
format_manual_text() выгружает модель в тот же формат. Это делает путь
двусторонним: распарсили что смогли -> выгрузили -> инженер дописал руками ->
загрузили обратно.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Union

from pdf_to_ifc.model import NetworkEdge, NetworkNode, ThermalNetworkModel


class ManualInputError(ValueError):
    """Ошибка разбора с номером строки и её текстом."""

    def __init__(self, line_number: int, line: str, message: str) -> None:
        super().__init__(f"строка {line_number}: {message}\n    {line.strip()}")
        self.line_number = line_number
        self.line = line


# Синонимы ключей: русские (основные) и английские (для удобства раскладки).
NODE_KEYS = {
    "x": "x", "х": "x",
    "y": "y", "у": "y",
    "земля": "z_surface", "z_surface": "z_surface", "отметка_земли": "z_surface",
    "лоток": "z_pipe_bottom", "z_pipe_bottom": "z_pipe_bottom", "отметка_лотка": "z_pipe_bottom",
    "тип": "node_type", "node_type": "node_type",
    "нитка": "branch", "branch": "branch",
}
EDGE_KEYS = {
    "нитка": "branch", "branch": "branch",
    "ду": "diameter", "диаметр": "diameter", "dn": "diameter", "diameter": "diameter",
    "длина": "length", "length": "length",
    "материал": "material", "material": "material",
    "изоляция": "insulation", "insulation": "insulation",
    "прокладка": "laying_type", "laying_type": "laying_type", "тип_прокладки": "laying_type",
    "давление": "pressure_mpa", "pressure": "pressure_mpa", "pressure_mpa": "pressure_mpa",
    "температура": "temperature_c", "temperature": "temperature_c", "temperature_c": "temperature_c",
    "гост": "gost_designation", "обозначение": "gost_designation",
    "gost": "gost_designation", "gost_designation": "gost_designation",
}
FLOAT_FIELDS = {"x", "y", "z_surface", "z_pipe_bottom", "length", "pressure_mpa", "temperature_c"}
INT_FIELDS = {"diameter"}

_PAIR_RE = re.compile(r"([^\s=]+)\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)")


def _split_pairs(text: str, line_number: int, line: str, allowed: Dict[str, str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    consumed = 0
    for match in _PAIR_RE.finditer(text):
        key = match.group(1).strip().lower().replace(" ", "_")
        raw = match.group(2).strip().strip("\"'")
        if key not in allowed:
            raise ManualInputError(
                line_number, line,
                f"неизвестный ключ {match.group(1)!r}; допустимы: {', '.join(sorted(set(allowed)))}",
            )
        values[allowed[key]] = raw
        consumed += len(match.group(0))
    leftovers = _PAIR_RE.sub("", text).strip(" \t,;")
    if leftovers:
        raise ManualInputError(line_number, line, f"непонятный фрагмент {leftovers!r}")
    return values


def _convert(values: Dict[str, str], line_number: int, line: str) -> Dict[str, object]:
    converted: Dict[str, object] = {}
    for field, raw in values.items():
        if field in FLOAT_FIELDS:
            try:
                converted[field] = float(raw.replace(",", "."))
            except ValueError:
                raise ManualInputError(line_number, line, f"{field}={raw!r} — не число") from None
        elif field in INT_FIELDS:
            try:
                converted[field] = int(float(raw.replace(",", ".")))
            except ValueError:
                raise ManualInputError(line_number, line, f"{field}={raw!r} — не число") from None
        else:
            converted[field] = raw
    return converted


def parse_manual_text(text: str) -> ThermalNetworkModel:
    """Разобрать текст ручного ввода в доменную модель."""
    project_name = "Ручной ввод"
    source = "не указан"
    nodes: List[NetworkNode] = []
    edges: List[NetworkEdge] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        lowered = stripped.lower()
        if lowered.startswith("проект:") or lowered.startswith("project:"):
            project_name = stripped.split(":", 1)[1].strip()
            continue
        if lowered.startswith("источник:") or lowered.startswith("source:"):
            source = stripped.split(":", 1)[1].strip()
            continue

        if lowered.startswith("узел") or lowered.startswith("node"):
            head, _, tail = stripped.partition(":")
            if not tail:
                raise ManualInputError(line_number, line, "после имени узла нужен двоеточие")
            name = head.split(None, 1)[1].strip() if len(head.split(None, 1)) > 1 else ""
            if not name:
                raise ManualInputError(line_number, line, "у узла нет имени")
            values = _convert(_split_pairs(tail, line_number, line, NODE_KEYS), line_number, line)
            missing = [f for f in ("x", "y", "z_surface", "z_pipe_bottom", "node_type")
                       if f not in values]
            if missing:
                raise ManualInputError(
                    line_number, line, f"у узла не хватает полей: {', '.join(missing)}")
            nodes.append(NetworkNode(name=name, **values))  # type: ignore[arg-type]
            continue

        if lowered.startswith("участок") or lowered.startswith("edge"):
            head, _, tail = stripped.partition(":")
            if not tail:
                raise ManualInputError(line_number, line, "после узлов участка нужно двоеточие")
            body = head.split(None, 1)[1] if len(head.split(None, 1)) > 1 else ""
            if "->" not in body:
                raise ManualInputError(line_number, line, "участок задаётся как «узел -> узел»")
            start_node, end_node = (part.strip() for part in body.split("->", 1))
            if not start_node or not end_node:
                raise ManualInputError(line_number, line, "у участка пустое имя узла")
            values = _convert(_split_pairs(tail, line_number, line, EDGE_KEYS), line_number, line)
            missing = [f for f in ("diameter", "length") if f not in values]
            if missing:
                raise ManualInputError(
                    line_number, line, f"у участка не хватает полей: {', '.join(missing)}")
            values.setdefault("material", "не указан")
            values.setdefault("insulation", "не указана")
            values.setdefault("laying_type", "не указан")
            edges.append(NetworkEdge(
                start_node=start_node, end_node=end_node, **values))  # type: ignore[arg-type]
            continue

        if lowered.startswith("изгиб") or lowered.startswith("bend"):
            if not edges:
                raise ManualInputError(line_number, line, "изгиб указан раньше участка")
            _, _, tail = stripped.partition(":")
            numbers = re.split(r"[\s,;]+", (tail or stripped.split(None, 1)[1]).strip())
            numbers = [value for value in numbers if value]
            if len(numbers) != 3:
                raise ManualInputError(line_number, line, "изгиб задаётся тремя числами: x y z")
            try:
                point = tuple(float(value.replace(",", ".")) for value in numbers)
            except ValueError:
                raise ManualInputError(line_number, line, "координаты изгиба — не числа") from None
            edges[-1].waypoints.append(point)  # type: ignore[arg-type]
            continue

        raise ManualInputError(
            line_number, line,
            "строка не опознана; ожидались «проект:», «источник:», «узел ...», «участок ...», «изгиб ...»",
        )

    model = ThermalNetworkModel(project_name=project_name, source=source)
    for node in nodes:
        model.add_node(node)
    for edge in edges:
        model.add_edge(edge)
    return model


def format_manual_text(model: ThermalNetworkModel) -> str:
    """Выгрузить модель в тот же формат — чтобы путь был двусторонним."""
    lines = [
        f"проект: {model.project_name}",
        f"источник: {model.source}",
        "",
    ]
    for node in model.nodes.values():
        branch = f" нитка={node.branch}" if node.branch != "single" else ""
        lines.append(
            f"узел {node.name}: x={node.x:.3f} y={node.y:.3f} "
            f"земля={node.z_surface:.2f} лоток={node.z_pipe_bottom:.2f} "
            f"тип={node.node_type}{branch}"
        )
    lines.append("")
    for edge in model.edges:
        parts = [
            f"нитка={edge.branch}",
            f"ду={edge.diameter}",
            f"длина={edge.length:.2f}",
            f"материал={edge.material}",
            f"изоляция={edge.insulation}",
            f"прокладка={edge.laying_type}",
        ]
        if edge.pressure_mpa is not None:
            parts.append(f"давление={edge.pressure_mpa}")
        if edge.temperature_c is not None:
            parts.append(f"температура={edge.temperature_c}")
        if edge.gost_designation:
            parts.append(f'гост="{edge.gost_designation}"')
        lines.append(f"участок {edge.start_node} -> {edge.end_node}: " + " ".join(parts))
        for x, y, z in edge.waypoints:
            lines.append(f"    изгиб: {x:.3f} {y:.3f} {z:.3f}")
    return "\n".join(lines) + "\n"


def load_manual_file(path: Union[str, Path]) -> ThermalNetworkModel:
    return parse_manual_text(Path(path).read_text(encoding="utf-8"))


def save_manual_file(model: ThermalNetworkModel, path: Union[str, Path]) -> None:
    Path(path).write_text(format_manual_text(model), encoding="utf-8")
