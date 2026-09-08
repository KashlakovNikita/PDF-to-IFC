"""Задача 10: собрать IFC из тестового датасета и открыть его в вьюере.

Зачем отдельный скрипт: до задачи 1 брифа геометрия труб не была проверена
ничем, кроме юнит-тестов на атрибуты IFC-сущностей, поэтому «открыть и
посмотреть» смысла не имело — смотреть было не на что. Теперь труба идёт по
ломаной с фитингами изгибов, и глазами это уже осмысленно проверять.

Запуск (из корня репозитория, при активированном venv):

    python scripts/export_sample_ifc.py
    python scripts/export_sample_ifc.py --output out/parnas.ifc --demo-bend

Что дальше делать с файлом — раздел «Как посмотреть результат» в README.md.

--demo-bend добавляет в модель искусственную точку изгиба на одном участке.
Это НЕ данные проекта и не попадает в data/samples — только способ увидеть
в вьюере, как выглядит разбиение нитки на под-сегменты с IfcPipeFitting BEND,
пока реальные координаты плана не оцифрованы (задача 18).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pdf_to_ifc.ifc_export import generate_ifc_from_network, save  # noqa: E402
from pdf_to_ifc.model import ThermalNetworkModel  # noqa: E402

DEFAULT_MODEL = REPO_ROOT / "data" / "samples" / "parnas_model.json"
DEFAULT_OUTPUT = REPO_ROOT / "out" / "parnas.ifc"


def add_demo_bend(model: ThermalNetworkModel) -> None:
    """Поставить точку изгиба на первом участке модели (только для демонстрации).

    Точка смещена на 20 м вбок от середины прямой между узлами — этого
    достаточно, чтобы в вьюере было видно и излом трассы, и фитинг BEND в
    точке излома. Ставится сразу на обе нитки (supply/return), иначе подача и
    обратка разъедутся, и картинка будет вводить в заблуждение.
    """
    if not model.edges:
        return

    first = model.edges[0]
    start = model.nodes[first.start_node]
    end = model.nodes[first.end_node]
    bend = (
        (start.x + end.x) / 2.0,
        (start.y + end.y) / 2.0 + 20.0,
        (start.z_pipe_bottom + end.z_pipe_bottom) / 2.0,
    )

    for edge in model.edges:
        if (edge.start_node, edge.end_node) == (first.start_node, first.end_node):
            edge.waypoints = [bend]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help=f"JSON доменной модели (по умолчанию {DEFAULT_MODEL.name})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"куда писать IFC (по умолчанию {DEFAULT_OUTPUT})")
    parser.add_argument("--demo-bend", action="store_true",
                        help="добавить искусственную точку изгиба на первый участок")
    args = parser.parse_args()

    model = ThermalNetworkModel.load_json(args.model)
    if args.demo_bend:
        add_demo_bend(model)

    file = generate_ifc_from_network(model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(file, args.output)

    pipes = file.by_type("IfcPipeSegment")
    bends = [f for f in file.by_type("IfcPipeFitting") if f.PredefinedType == "BEND"]
    print(f"Модель:  {args.model}")
    print(f"Записан: {args.output}")
    print(f"Узлов сети: {len(model.nodes)}, ниток: {len(model.edges)}")
    print(f"IfcPipeSegment: {len(pipes)}, фитингов изгиба (BEND): {len(bends)}")
    print()
    print("Как посмотреть:")
    print("  BIMvision (Windows, бесплатный): File -> Open -> указать этот .ifc;")
    print("  трубы искать в дереве Model -> Site -> Distribution elements.")
    print("  Онлайн (ничего не ставить): https://view.ifcjs.io/ или https://ifcviewer.com —")
    print("  перетащить файл в окно браузера. Файл локальный, никуда не загружается")
    print("  дальше вкладки только у ifc.js-вьюеров, работающих полностью в браузере;")
    print("  для проектных данных под NDA пользуйтесь BIMvision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
