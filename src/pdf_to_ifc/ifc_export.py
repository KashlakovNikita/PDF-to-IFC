"""Генерация IFC из доменной модели (src/pdf_to_ifc/model.py).

Контракт с Треком A: generate_ifc_from_network() (задача 7) будет принимать
ThermalNetworkModel (или его to_dict()/JSON — см. model.py) на входе.
На синхронизации 1 (задача 11) собираем JSON из задачи 5 (Трек A) и
скармливаем его сюда — если по дороге что-то не сойдётся по именам полей,
это и есть тот самый шов.

Задача 6 (эта): минимальный каркас — IFCPROJECT + IFCSITE, единицы измерения
и геометрический контекст, без камер/труб (это уже задача 7). Цель — убедиться,
что ifcopenshell на машине работает и что мы умеем сохранить файл, который
открывается во вьюере.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import ifcopenshell
import ifcopenshell.api


def create_minimal_project(
    project_name: str = "PDF to IFC",
    site_name: str = "Площадка",
    *,
    schema: str = "IFC4X3",
) -> ifcopenshell.file:
    """Создать пустой IFC-файл с IFCPROJECT -> IFCSITE, метрическими единицами
    и геометрическим контекстом Model/Body.

    Дальше (задача 7) в этот файл будут добавляться камеры (IfcDistributionChamberElement
    или аналог) и трубы (IfcPipeSegment) как дочерние элементы IFCSITE.
    """
    file = ifcopenshell.api.run("project.create_file", version=schema)

    project = ifcopenshell.api.run(
        "root.create_entity", file, ifc_class="IfcProject", name=project_name
    )

    # Метрические единицы: без этого длины/диаметры труб будут не в метрах,
    # а IFC-вьюеры (и задача 10 — тест открытия) не смогут это проверить.
    ifcopenshell.api.run(
        "unit.assign_unit",
        file,
        length={"is_metric": True, "raw": "METERS"},
    )

    model_context = ifcopenshell.api.run(
        "context.add_context", file, context_type="Model"
    )
    ifcopenshell.api.run(
        "context.add_context",
        file,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_context,
    )

    site = ifcopenshell.api.run(
        "root.create_entity", file, ifc_class="IfcSite", name=site_name
    )
    ifcopenshell.api.run(
        "aggregate.assign_object",
        file,
        relating_object=project,
        products=[site],
    )

    return file


def save(file: ifcopenshell.file, path: Union[str, Path]) -> None:
    file.write(str(path))
