# PDF → IFC

Инструмент для преобразования проектной документации инженерных сетей (PDF/DWG) в IFC-модель. Начинаем с тепловых сетей (Трек A — данные/модель, Трек B — IFC/парсинг), см. `pdf_to_ifc_roadmap_2weeks.md`.

## Быстрый старт (Windows, PowerShell)

```powershell
# 1. Создать и активировать виртуальное окружение
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Поставить зависимости
pip install -U pip
pip install -r requirements.txt

# 3. Проверить, что окружение рабочее
python -c "import ifcopenshell; print(ifcopenshell.version)"
pytest -q
```

Если `pip install ifcopenshell` не находит колесо под вашу версию Python — см. раздел «Проблемы с ifcopenshell» ниже. Официальные колёса собираются под конкретные минорные версии Python (обычно 3.10–3.12); проще всего завести venv именно под одну из них.

## Структура проекта

```
pdf_to_ifc/
├── src/
│   └── pdf_to_ifc/
│       ├── __init__.py
│       ├── model.py        # задача 2: NetworkNode, NetworkEdge, ThermalNetworkModel
│       ├── ifc_export.py   # задача 6-9: генерация IFC (Трек B)
│       └── parsing/        # задача 12+: парсинг PDF (Трек A)
│           └── __init__.py
├── tests/
│   └── test_smoke.py
├── data/
│   ├── raw/                # исходные PDF/DWG (в .gitignore — тяжёлые бинарники)
│   └── samples/            # тестовый CSV на 10-15 узлов (задача 4)
├── requirements.txt
├── pyproject.toml
├── .gitignore
└── README.md
```

## Проблемы с ifcopenshell

Если `pip install ifcopenshell` падает — берите готовое колесо с https://ifcopenshell.org/downloads под вашу ОС и версию Python и ставьте локально:

```powershell
pip install path\to\ifcopenshell-....whl
```

## Ветки и коммиты (два трека)

Один репозиторий, две ветки на первую неделю, чтобы не блокировать друг друга:

- `track-a-data` — доменная модель и парсинг таблиц
- `track-b-ifc` — генерация IFC и парсинг геометрии

Мержим в `main` на точках синхронизации (задачи 11 и 20 из дорожной карты).
