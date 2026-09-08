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

## Как посмотреть результат (задача 10)

```powershell
# собрать IFC из тестового датасета
python scripts/export_sample_ifc.py

# то же, но с искусственной точкой изгиба на первом участке —
# чтобы увидеть разбиение нитки на под-сегменты и фитинги BEND
python scripts/export_sample_ifc.py --demo-bend
```

Файл пишется в `out/parnas.ifc` (папка `out/` в `.gitignore`).

**BIMvision** (Windows, бесплатный, https://bimvision.eu): `File -> Open`,
указать `out/parnas.ifc`. Трубы лежат в дереве `Model -> Site` среди
distribution elements; свойства участка (DN, материал, изоляция, тип
прокладки, нитка) — на вкладке свойств, набор `Pset_PdfToIfc_PipeSegment`.

**Онлайн-вьюеры на ifc.js** (ничего не ставить): https://view.ifcjs.io/ —
перетащить файл в окно браузера. Такие вьюеры работают целиком в браузере,
но для проектных данных под NDA надёжнее локальный BIMvision.

На что смотреть на изогнутом участке: нитка должна идти по ломаной и
заканчиваться ровно в конечном узле, а не проезжать мимо него (это и был
баг, который чинила задача 1 брифа); в каждой точке излома стоит
`IfcPipeFitting` с `PredefinedType = BEND`.

## Демонстрация точек изгиба

```powershell
python scripts/make_bend_demo.py
```

Собирает `out/parnas_waypoints_demo.ifc`: узлы и точки изгиба снимаются с
эталонной трассы (система Т1), дальше всё штатно — обычная модель и обычный
`generate_ifc_from_network()`. Нужен потому, что на тестовом датасете точек
изгиба нет вовсе, и на нём не видно ни разбиения нитки на под-сегменты, ни
фитингов `BEND`.

Это проверка **генератора** на заведомо правильных входных данных, а не
оцифровка плана (это задача 18): координаты взяты из эталона, а не из PDF.
На текущем эталоне получается 114 `IfcPipeSegment`, 37 точек изгиба и 100 %
длины сети в допуске при максимуме отклонения 0.001 м.

## Сверка геометрии с эталоном

```powershell
python scripts/validate_geometry.py --generated out/parnas.ifc
```

Скрипт сравнивает осевые линии труб сгенерированного файла с эталонным
`data/raw/ПРНС_ЛО_ТКР-ТС_У1_Э1_I2300.ifc` (только системы Т1/Т2, дренаж `Др`
отфильтровывается) и печатает численный отчёт: доля длины сети в допуске и
список участков вне допуска. Подробности и оговорки — в докстринге скрипта
и в `REPORT_geometry_fix.md`.

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
