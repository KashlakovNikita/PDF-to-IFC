"""Smoke-тест задачи 1: окружение поднято, зависимости ставятся, импорты работают."""
import importlib


def test_package_importable():
    import pdf_to_ifc
    assert pdf_to_ifc.__version__


def test_core_dependencies_importable():
    for name in ("pandas", "numpy", "pdfplumber", "fitz", "ifcopenshell"):
        importlib.import_module(name)
