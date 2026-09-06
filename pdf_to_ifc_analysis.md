# Анализ: Трансформация PDF документации → IFC-модель сети

## Текущий workflow (ручной процесс)

### Входные данные (PDF)
**Файл:** `Раздел_РД__1_ТС_Парнас_Проект.pdf` (20 МБ, многостраничный)

Содержит:
1. **Общие данные проекта**
   - Наименование объекта: "Реконструкция магистральной тепловой сети в НЗ Парнас по 8-му проезду"
   - Источник теплоснабжения: котельная "Парнас-4", УТ-1а до ТК-4
   - Год строительства: 1987
   - Температурный график: 150/70°С

2. **План сетей (чертежи с координатами)**
   - Расположение трубопроводов в пространстве
   - Координаты узлов (точек подключения, поворотов)
   - Обозначение колодцев/камер (УТ-1а, ТК-2, ТК-3, ТК-4 и т.д.)
   - Типы прокладки (подземная, надземная, в футляре, в канале)

3. **Продольные профили**
   - Отметки поверхности земли
   - Отметки лотка труб (нижняя кромка)
   - Отметки верха труб
   - Отметки колодцев
   - Уклоны участков

4. **Спецификация оборудования (таблицы)**
   - Трубопроводная арматура (краны Ду, давление)
   - Трубопроводы (диаметры: 600, 400, 300, 250 мм; материал, длины, типы изоляции)
   - Опоры (неподвижные, скользящие)
   - Компенсационные устройства (сильфоны)
   - Контрольно-измерительные приборы (манометры)

5. **Ведомости объёмов работ**
   - Объёмы земляных работ по типам прокладки
   - Количество монтажных работ
   - Материалы

6. **Таблица параметров (пример)**
   ```
   | № | Тип прокладки | Ду, мм | Подземная | Надземная | Итого |
   |----|---------------|--------|-----------|-----------|--------|
   | 1  | 600          | 0.00   | 48.00     | 48.00     |
   | 2  | 400          | 399.00 | 28.00     | 427.00    |
   | 4  | 300          | 35.62  | 0.00      | 4.00      |
   | 5  | 250          | 155.00 | 0.00      | 155.00    |
   |    | Всего:       | 589.62 | 76.00     | 665.62    |
   ```

### Выходные данные (IFC-модель)
**Файл:** `ПРНС_ЛО_ТКР-ТС_У1_Э1_I2300.ifc` (3.5 МБ)

Структура IFC2X3:
- **IFCPROJECT** - проект (ПРНС_ЛО_ТКР-ТС_У1_Э1_I2300)
- **IFCSITE** - площадка/земельный участок
- **Множество объектов** (~400+):
  - **IFCPIPING** / **IFCPIPESEGMENT** - участки трубопроводов
  - **IFCDISTRIBUTIONCHAMBER** / **IFCJUNCTIONBOX** - узлы, колодцы, камеры
  - **IFCVALVE** - краны, запорная арматура
  - **IFCFLOWSEGMENT** - элементы трубопровода
  - Геометрия: координаты XYZ, диаметры, толщины стенок
  - Атрибуты: материал, тип изоляции, давление, температура

Пример структуры IFC:
```
IFCPROJECT
├── IFCSITE
│   └── (IFCLOCALPLACEMENT с координатами)
└── IFCRELCONTAINEDINSPATIALSTRUCTURE
    └── ~400 IFCBUILDINGELEMENTPROXY / IFCPIPING
        ├── IFCPRODUCTDEFINITIONSHAPE
        ├── IFCSHAPEREPRESENTATION
        └── Геометрия (IFCPOLYLOOP, IFCFACE, IFCBREP)
```

---

## Ключевые правила трансформации PDF → IFC

### 1. Парсинг геометрии
- **Источник:** План сетей (чертежи), профили
- **Извлечение:** Координаты узлов (XYZ), линии трубопроводов
- **Результат в IFC:** 
  - Узлы → IFCCARTESIANPOINT с координатами
  - Линии → IFCPIPESEGMENT с начальной и конечной точкой
  - Расчёт длины участка из координат

### 2. Парсинг атрибутов из спецификации
- **Диаметры труб:** Таблица спецификации → DN (номинальный диаметр)
  - Пример: "Труба Ст 325х8.0–ППУ1–ПЭ-ОДК" → DN=325, толщина=8.0
- **Материал:** ГОСТ → IFCMATERIAL
  - "сталь 20 по ГОСТ 8731-87" → Steel Grade 20
- **Тип изоляции:** Спецификация → IFCINSULATION
  - "ППУ-345 в полиэтиленовой оболочке" → Polyurethane + Polyethylene
- **Давление/температура:** Спецификация → IFCFLUIDFLOWPROPERTIES
  - Ру=2.5 МПа, Т=160°С

### 3. Классификация узлов
- **УТ-1а (узел трубопровода)** → IFCJUNCTIONBOX / IFCDISTRIBUTIONNODE
- **ТК-2, ТК-3, ТК-4 (тепловые камеры)** → IFCDISTRIBUTIONCHAMBER
- **ПГ7, УП (проходные/уличные)** → IFCDISTRIBUTIONCHAMBER специального типа

### 4. Типы прокладки
- Подземная, бесканальная → IFCPIPESEGMENT.PredefinedType = BURIEDPIPE
- Подземная в канале → IFCPIPESEGMENT + контейнер IFCDUCT
- Подземная в футляре → IFCPIPESEGMENT с IFCPROTECTIONSLIP (защитный кожух)
- Надземная → IFCPIPESEGMENT.PredefinedType = FLEXIBLESEGMENT или RIGIDSEGMENT

### 5. Отметки и глубина заложения
- **Профиль → отметки лотка:**
  - Из профиля извлекаются Z-координаты (высоты)
  - Отметка лотка трубы → Z координата в IFCLOCAL PLACEMENT
  - Глубина заложения = Z_поверхности - Z_лотка

---

## Архитектура системы автоматической генерации IFC из PDF

```
┌─────────────────────────────────────────────────────────────────────┐
│                          PDF-документация                          │
│  (планы, профили, спецификации, ведомости, чертежи, таблицы)       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                      ┌────────▼────────┐
                      │  1. PDF-парсер  │
                      │   (pdfplumber/  │
                      │   PyPDF2/       │
                      │   fitz)         │
                      └────────┬────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
    ┌────▼────┐      ┌────────▼────────┐    ┌──────▼──────┐
    │ Чертежи │      │   Таблицы/      │    │  Профили    │
    │ (планы) │      │ Спецификация    │    │  (отметки)  │
    └────┬────┘      └────────┬────────┘    └──────┬──────┘
         │                     │                     │
    ┌────▼──────────────────────┴─────────────────────┴───────┐
    │                                                          │
    │  2. Интеллектуальное извлечение данных                 │
    │                                                          │
    │  2a. Парсинг координат                                  │
    │      - Распознавание обозначений узлов (УТ, ТК, ПГ)   │
    │      - Извлечение XY из плана (пиксели → реал. коорд.)│
    │      - Калибровка масштаба по штампу чертежа           │
    │                                                          │
    │  2b. Парсинг таблиц (OCR + структура)                 │
    │      - Распознавание диаметров, материалов             │
    │      - Регулярные выражения для ГОСТ-обозначений       │
    │      - LightGBM для классификации типов элементов      │
    │                                                          │
    │  2c. Парсинг профилей                                  │
    │      - Извлечение Z-координат (отметки)                │
    │      - Интерполяция рельефа                            │
    │      - Расчёт уклонов участков                         │
    │                                                          │
    └─────────────────────┬────────────────────────────────────┘
                          │
          ┌───────────────▼───────────────┐
          │  3. Доменная модель сети      │
          │                               │
          │  Node (узлы):                 │
          │  ├─ id, марка (УТ, ТК, ПГ)   │
          │  ├─ x, y, z_поверхности       │
          │  ├─ z_лотка, z_верха_трубы   │
          │  └─ тип узла                  │
          │                               │
          │  Pipe (рёбра):                │
          │  ├─ start_node, end_node      │
          │  ├─ диаметр, материал         │
          │  ├─ длина, уклон              │
          │  ├─ тип изоляции              │
          │  ├─ тип прокладки             │
          │  └─ параметры давления/тем-ры │
          │                               │
          └─────────────────┬─────────────┘
                            │
          ┌─────────────────▼──────────────┐
          │  4. IFC-генератор              │
          │                                │
          │  - Создание IFCPROJECT         │
          │  - Создание IFCSITE            │
          │  - Генерация IFCPIPING узлов   │
          │  - Генерация IFCPIPESEGMENT    │
          │  - Генерация IFCVALVE (краны)  │
          │  - Создание геометрии (BREP)   │
          │  - Проставление атрибутов      │
          │  - Создание свойств (PSET)     │
          │                                │
          └─────────────────┬──────────────┘
                            │
          ┌─────────────────▼──────────────┐
          │  5. IFC 4x3 / IFC 2x3 файл     │
          │                                │
          │  PRNS_LO_TKR-TS_...ifc         │
          │  (готов к открытию в Revit,   │
          │   ARCHICAD, BricsCAD, etc.)   │
          │                                │
          └────────────────────────────────┘
```

---

## Технологический стек для автоматизации

| Компонент | Библиотека | Обоснование |
|-----------|-----------|-----------|
| **PDF-парсинг** | pdfplumber + PyPDF2 | Изоляция текстового и графического слоя |
| **Парсинг таблиц** | pandas + regex | Автоматизация спецификации и ведомостей |
| **OCR (если нужен)** | pytesseract + Tesseract | Для рукописных заметок на чертежах |
| **Граф сети** | NetworkX | Топология узлов и рёбер |
| **Обработка координат** | Shapely + PyProj | Трансформация пикселей чертежа в реальные координаты |
| **Классификация** | scikit-learn / LightGBM | Распознавание типов узлов, материалов, прокладок |
| **Геометрия** | pythonOCC / CadQuery | Генерация твёрдотельных моделей труб для IFC BREP |
| **IFC-генерация** | ifcopenshell | Создание и валидация IFC-моделей |
| **Валидация** | ifcopenshell.validate | Проверка соответствия IFC4.3 стандарту |

---

## Ключевые сложности и решения

### 1. Извлечение координат из чертежа
**Проблема:** План — это 2D-изображение в PDF с условными обозначениями, не всегда точно расставленными.

**Решение:**
- Использовать **маркеры калибровки** на штампе чертежа (известная сетка координат)
- **Детектор узлов** (CV + ML) — поиск кружков/точек обозначений УТ, ТК
- **Интеграция с ГИС** — привязка к реальным координатам если доступна геоложение (может быть указано в техусловиях)

### 2. Парсинг неструктурированных таблиц
**Проблема:** Таблицы спецификации в PDF часто содержат объединённые ячейки, текст «вразнобой», шрифтовые выделения.

**Решение:**
- **Первая попытка:** `pdfplumber.extract_table()` + очистка пробелов/символов
- **Backup:** `pytesseract` для OCR проблемных областей
- **Структурный парсинг:** regex-паттерны для ГОСТ-обозначений типа `"Ст 325х8.0–ППУ1–ПЭ-ОДК"`

### 3. Маппинг между диаметрами и длинами
**Проблема:** В таблице может быть "Итого: 665.62 п.м." без разбивки по диаметрам, а на чертеже не все участки явно помечены.

**Решение:**
- Использовать **граф сети** — каждый участок (edge) имеет известные start/end узлы
- На основе топологии и спецификации **распределить длины** пропорционально геометрии
- **AI-классификатор** для каждого участка предсказывает диаметр по соседним узлам, типу прокладки, давлению

### 4. Три измерения (Z-координаты)
**Проблема:** План 2D, отметки размещены на профилях — нужно связать профиль с участком на плане.

**Решение:**
- **Парсинг профиля** — извлечение таблицы отметок (узел → Z_лотка, Z_верха, Z_земли)
- **Маппинг профиля на план** — по текстовым обозначениям узлов связать узлы на плане с их отметками из профиля
- **Интерполяция** — для промежуточных участков рассчитать Z линейно между узлами

---

## Фазы реализации

### Фаза 1: Минимум для MVP (1–2 мес.)
1. **PDF-парсер** — извлечение текста, таблиц, чертежей
2. **Таблица спецификации** — автоматический парсинг основной таблицы (диаметры, материалы, количества)
3. **Доменная модель** — простой граф узлов и рёбер с атрибутами из таблицы
4. **IFC-генератор** — базовая генерация IFCPROJECT, IFCSITE, IFCPIPING без сложной геометрии
5. **Координаты** — ручной ввод через интерфейс или простой файл (CSV с узлами)

**Результат:** Функциональный IFC, который можно открыть в Revit, но без точной геометрии и координат

### Фаза 2: Интеллектуальный парсинг (2–3 мес.)
6. **Распознавание координат** — детектор обозначений узлов, калибровка чертежа
7. **Парсинг профилей** — извлечение таблиц отметок, связь с узлами
8. **AI-классификатор** для типов прокладки, материалов (LightGBM)
9. **Полная геометрия** — расчёт 3D-координат, создание BREP для труб

**Результат:** Полнофункциональный IFC с реальными координатами, открываемый в любом BIM-инструменте

### Фаза 3: Интеграция и оптимизация (1–2 мес.)
10. **Валидация IFC** — проверка соответствия стандарту, исправление ошибок
11. **Экспорт доп. форматов** — DXF (для проверки против исходного чертежа), гидравлические расчёты
12. **Пользовательский интерфейс** — загрузка PDF, настройка параметров парсинга, просмотр результатов

---

## Примеры парсинга из вашего PDF

### Пример 1: Таблица спецификации (автоматический парсинг)

**Исходная таблица в PDF:**
```
Трубопроводная арматура:
Кран стальной шаровой полнопроходной приварной с редуктором
1. Ду300, Ру=2,5 МПа, Т=160°С | BBF/KSF-V-HS | БЕМЕР | шт | 4 | 458.0 | С опорой скольжения

Трубопроводы:
Труба стальная бесшовная горячедеформированная по ГОСТ 8732-78
сталь 20 по ГОСТ 8731-87 в изоляции из пенополиуретана ППУ-345
в полиэтиленовой оболочке с системой ОДК
8. Труба Ст 89х5,0–ППУ1–ПЭ-ОДК | ГОСТ 30732-2020 | м | 2.00 | 12.75
9. Труба Ст 325х8,0–ППУ1–ПЭ-ОДК | ГОСТ 30732-2020 | м | 805.08 | 75.49
```

**Парсинг (pseudo-code):**
```python
import re
import pandas as pd

# Регулярные выражения для ГОСТ-обозначений
pipe_pattern = r'Ст\s+(\d+)х(\d+(?:,\d+)?)'  # "Ст 325х8,0"
pressure_pattern = r'Ру=([0-9.,]+)\s*МПа'     # "Ру=2,5 МПа"
temp_pattern = r'Т=(\d+)°С'                    # "Т=160°С"

# Извлечение таблицы pdfplumber
tables = pdf.extract_tables()
spec_table = tables[0]  # таблица спецификации

# Парсинг каждой строки
for row in spec_table:
    name = row['Наименование']
    
    # Извлечение диаметра
    match = re.search(pipe_pattern, name)
    if match:
        outer_diameter = float(match.group(1))
        wall_thickness = float(match.group(2).replace(',', '.'))
        # outer_diameter=325, wall_thickness=8.0
    
    # Извлечение давления и температуры
    pressure = re.search(pressure_pattern, name)
    temperature = re.search(temp_pattern, name)
    
    # Результат: {диаметр, толщина, материал, Р, Т, количество, длина}
    equipment = {
        'dn': outer_diameter,
        'wall_thickness': wall_thickness,
        'material': 'Steel Grade 20',
        'pressure_mpa': float(pressure.group(1).replace(',', '.')),
        'temperature_c': int(temperature.group(1)),
        'quantity': float(row['Кол.']),
        'length_m': float(row['Масса единицы'].replace(',', '.'))
    }
```

**Результат в доменной модели:**
```python
Pipe(
    network_code='К2',  # типовая сеть из техусловий
    dn=325,
    wall_thickness=8.0,
    material='Steel',
    grade='20',
    pressure_mpa=2.5,
    temperature_c=160,
    insulation='PUR+PE',  # ППУ-345 + ПЭ
    corrosion_protection='OCP',  # система ОДК
    total_length_m=805.08,
)
```

### Пример 2: Таблица ведомости объёмов (распределение по типам прокладки)

**Исходные данные (из таблицы в PDF):**
```
                            Подземная    Надземная    Всего:
600 мм                      0.00         48.00        48.00
400 мм                      399.00       28.00        427.00
300 мм                      35.62        0.00         4.00
250 мм                      155.00       0.00         155.00
Всего:                      589.62       76.00        665.62 п.м. трассы
```

**Парсинг и распределение по участкам:**
```python
# Из таблицы извлечены суммарные длины по диаметрам и типам прокладки
total_lengths = {
    (600, 'underground'): 0.00,
    (600, 'overhead'): 48.00,
    (400, 'underground'): 399.00,
    (400, 'overhead'): 28.00,
    # ... и т.д.
}

# Граф сети содержит список всех участков (edges)
pipes = [
    Pipe(start='УТ-1а', end='ТК-2', dn=400, laying_type='underground'),
    Pipe(start='ТК-2', end='ТК-3', dn=400, laying_type='underground'),
    Pipe(start='ТК-3', end='ТК-4', dn=400, laying_type='overhead'),
    # ... и т.д.
]

# Распределение: пропорционально координатам и соседним узлам
for pipe in pipes:
    # Граф даёт нам информацию о соседях, типе узла
    # На основе этого предсказываем диаметр и длину
    pipe.length = estimate_length_from_coordinates(pipe.start, pipe.end)
    pipe.dn = classify_diameter(pipe, total_lengths)
```

### Пример 3: Парсинг профиля (Z-координаты)

**Исходные данные (таблица в профиле):**
```
Участок (узел)  Z_земли  Z_верха_трубы  Z_лотка  Уклон
УТ-1а           150.50   140.00         138.80   0.005
ТК-2            149.80   139.50         138.30   0.004
ТК-3            148.50   138.00         137.10   0.006
ТК-4            147.20   137.00         135.90   0.008
```

**Парсинг и связь с планом:**
```python
# Извлечение таблицы отметок из профиля
profile_data = extract_profile_table(pdf_page)

# Маппинг профиля на узлы графа (по имени узла)
for node in network_graph.nodes():
    if node.name in profile_data:
        node.z_surface = profile_data[node.name]['z_earth']
        node.z_pipe_top = profile_data[node.name]['z_top']
        node.z_pipe_bottom = profile_data[node.name]['z_bottom']  # лоток
        node.depth = node.z_surface - node.z_pipe_bottom

# Для участков (edges) — линейная интерполяция между узлами
for edge in network_graph.edges():
    start_node = edge.start
    end_node = edge.end
    
    # Берём длину участка из графа координат плана
    length = euclidean_distance(start_node.xy, end_node.xy)
    
    # Берём отметки из профиля
    z_start = start_node.z_pipe_bottom
    z_end = end_node.z_pipe_bottom
    
    # Рассчитываем уклон
    slope = (z_start - z_end) / length  # или из профиля, если есть
    
    edge.slope = slope
    edge.length = length
```

---

## Ожидаемый результат на выходе IFC

Когда вся автоматизация заработает, из одного PDF можно будет получить:

1. **IFCPROJECT** с корректным наименованием проекта
2. **IFCSITE** с координатами площадки (если есть в техусловиях)
3. **~400+ IFCPIPESEGMENT** с:
   - Координатами XYZ (из плана + профилей)
   - Диаметрами (из спецификации)
   - Материалами и толщинами стенок
   - Типом изоляции
   - Типом прокладки (бесканальная, в канале, в футляре, надземная)
   - Атрибутами давления и температуры

4. **~30+ IFCDISTRIBUTIONCHAMBER** (камеры) с:
   - Координатами
   - Номерами (УТ-1а, ТК-2, ТК-3, ТК-4)
   - Отметками входа/выхода

5. **Свойства** (PropertySet):
   - Дата проекта, инженер-проектировщик, номер объекта
   - Стадийность (рабочий проект)
   - Источник теплоснабжения

6. **Полная геометрия** в BREP (твёрдые тела) для каждой трубы — можно визуализировать в 3D

---

---

## Часть 2: Глубокий анализ парсинга и типичные проблемы

### Problem 1: Привязка диаметров к участкам сети

**Ситуация:** В спецификации указано:
- Ст 325х8,0–ППУ1–ПЭ-ОДК: **805.08 м** (всего)
- Но эта длина **разбита по типам прокладки**: 197.10 м (канал) + 24.00 м (беск.) + 157.44 м (беск.) + 2.00 м (футляр) + 30.90 м (футляр) = ~412 м из 805 м

**Ключевая проблема:** В одной таблице спецификации указана **общая длина по диаметру**, а в другой таблице "Ведомость объёмов работ" указаны **длины по типам прокладки для разных диаметров**, но БЕЗ привязки к конкретным участкам между узлами.

**Решение на практике:**

```python
# Шаг 1: Из спецификации извлечём все трубопроводы с их общими параметрами
specification_pipes = {
    325: {
        'dn': 325,
        'wall_thickness': 8.0,
        'material': 'Steel',
        'total_length': 805.08,
        'standard': 'ГОСТ 30732-2020',
        'insulation': 'PPU+PE',
        'corrosion_protection': 'OCP',
    },
    426: {
        'dn': 426,
        'wall_thickness': 9.0,
        'material': 'Steel',
        'total_length': 391.18 + 195.22,  # две колонки
        'standard': 'ГОСТ 30732-2020',
        'insulation': 'PPU+PE',
        'corrosion_protection': 'OCP',
    },
    # ...
}

# Шаг 2: Из ведомости объёмов работ извлечём распределение по типам прокладки
volume_distribution = {
    325: {
        'underground_ducted': 197.10,       # в непроходном канале с дренажом
        'underground_no_duct': 181.44,      # подземная без дренажа
        'in_casing_630': 32.90,             # в футляре 630х8,0
        'overhead': 0.0,
    },
    426: {
        'underground_ducted': 102.01,
        'underground_no_duct': 36.58,       # с подъёмом
        'in_casing_630': 7.00,
        'overhead': 97.61,
    },
}

# Шаг 3: Граф сети содержит рёбра (участки между узлами)
# Каждому ребру нужно присвоить диаметр и тип прокладки

# Алгоритм распределения:
# - Используем граф топологии (какие узлы соединены)
# - Используем тип узла (камера/уличный/проходной) для определения типа прокладки
# - ML-классификатор предсказывает диаметр на основе:
#   * Соседних узлов (какой давления, типа)
#   * Расстояния до начала/конца сети
#   * Типа узла
#   * Соседних диаметров (ближайшие участки часто одного диаметра)

class PipeDiameterClassifier:
    def __init__(self, volume_distribution, specification):
        self.volume_dist = volume_distribution
        self.spec = specification
        self.clf = train_lightgbm_model(training_data)  # обучено на прошлых проектах
    
    def classify_pipe(self, edge, network_graph):
        """Предсказать диаметр участка"""
        features = self.extract_features(edge, network_graph)
        # features = [length, laying_type, source_pressure, target_pressure, 
        #             num_taps, distance_from_source, ...]
        
        diameter_proba = self.clf.predict_proba(features)
        # Возвращает вероятности для каждого диаметра
        
        diameter = self.clf.predict(features)[0]
        confidence = diameter_proba.max()
        
        return diameter, confidence
    
    def assign_all_pipes(self, network_graph):
        """Распределить диаметры по всем участкам"""
        for edge in network_graph.edges():
            dn, confidence = self.classify_pipe(edge, network_graph)
            
            if confidence < 0.7:
                # Низкая уверенность → вывести на проверку
                edge.diameter = None
                edge.diameter_confidence = confidence
                edge.suggested_diameter = dn
            else:
                edge.diameter = dn
                edge.diameter_confidence = confidence
        
        # Финальная верификация: сумма длин по диаметрам должна ≈ итогам из спецификации
        self.verify_distribution(network_graph)
    
    def verify_distribution(self, network_graph):
        """Проверить, что распределённые диаметры совпадают с итогами спецификации"""
        computed_lengths = defaultdict(float)
        
        for edge in network_graph.edges():
            if edge.diameter is not None:
                computed_lengths[edge.diameter] += edge.length
        
        # Сравнить с спецификацией
        for dn, spec_length in self.spec.items():
            computed = computed_lengths.get(dn, 0)
            error = abs(computed - spec_length['total_length']) / spec_length['total_length']
            
            if error > 0.05:  # ошибка > 5%
                print(f"WARNING: Диаметр {dn} - расхождение {error*100:.1f}%")
                print(f"  Спецификация: {spec_length['total_length']:.2f} м")
                print(f"  Распределено: {computed:.2f} м")
```

**Практический результат:**
Каждому ребру графа присвоены:
- `edge.diameter` (или `None` если не уверены)
- `edge.laying_type` (underground_ducted, overhead, etc.)
- `edge.confidence` (уровень уверенности)

---

### Problem 2: Парсинг координат из PDF-чертежа

**Ситуация:** План сетей — это 2D-чертёж в PDF. Узлы обозначены как кружки/точки с подписями (УТ-1а, ТК-2 и т.д.), но координаты **явно на чертеже НЕ указаны**.

**Методы извлечения координат:**

#### Метод A: Использование масштаба и привязки (базовый)

```python
import pdfplumber
from PIL import Image
import cv2

def extract_plan_coordinates(pdf_path, plan_page_num):
    """
    Извлечение координат узлов из плана сетей
    
    Шаги:
    1. Преобразовать страницу PDF в изображение
    2. Найти штамп (масштаб)
    3. Определить соответствие: пиксели → реальные координаты
    4. Найти обозначения узлов (кружки)
    5. Привязать к реальным координатам
    """
    
    # Шаг 1-2: Преобразование и поиск масштаба
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[plan_page_num]
        
        # Извлечение масштаба из штампа (ГОСТ 21.101)
        # Штамп обычно содержит: М 1:500 или М 1:1000
        stamp_text = page.extract_text()
        scale_match = re.search(r'М\s*1\s*:\s*(\d+)', stamp_text)
        
        if scale_match:
            scale_ratio = int(scale_match.group(1))
            print(f"Масштаб найден: 1:{scale_ratio}")
        else:
            print("Масштаб не найден, используем эвристику...")
            scale_ratio = 500  # по умолчанию
    
    # Рендер страницы в изображение (300 DPI)
    from pdf2image import convert_from_path
    images = convert_from_path(pdf_path, first_page=plan_page_num+1, 
                               last_page=plan_page_num+1, dpi=300)
    img = cv2.cvtColor(cv2.imread(str(images[0])), cv2.COLOR_BGR2GRAY)
    
    # Шаг 3: Калибровка — найти угловые точки чертежа или сетку координат
    # На плане часто есть координатная сетка (тонкие линии через 100-500м)
    # или рамка с обозначением координат X, Y
    
    # Приближённо: используем рамку чертежа как калибровочные точки
    # Ищем "+" символы (обычно они отмечают углы координатной сетки)
    circles = cv2.HoughCircles(img, cv2.HOUGH_GRADIENT, dp=1, minDist=50,
                              param1=50, param2=30, minRadius=3, maxRadius=8)
    
    calibration_points = []
    if circles is not None:
        circles = np.round(circles[0, :]).astype("int")
        for (x, y, r) in circles:
            # Проверяем, находятся ли точки на краю чертежа
            if x < 50 or x > img.shape[1]-50 or y < 50 or y > img.shape[0]-50:
                # Это калибровочная точка
                calibration_points.append({'pixel': (x, y), 'real': (0, 0)})  # placeholder
    
    print(f"Найдено калибровочных точек: {len(calibration_points)}")
    
    # Шаг 4: Поиск обозначений узлов (кружки с подписью УТ-1а, ТК-2 и т.д.)
    # Для упрощения используем template matching на известные паттерны
    
    node_labels = ['УТ-1а', 'ТК-2', 'ТК-3', 'ТК-4', 'ПГ7', 'УП']  # пример
    found_nodes = {}
    
    for label in node_labels:
        # Поиск текста на изображении через OCR
        # (или через пиксельную маску, если известна позиция)
        
        # Используем pytesseract для простого случая
        results = pytesseract.image_to_data(img, output_type='dict')
        
        for i, text in enumerate(results['text']):
            if label in text or text.strip() in label:
                x = results['left'][i] + results['width'][i] // 2
                y = results['top'][i] + results['height'][i] // 2
                found_nodes[label] = {'pixel': (x, y)}
    
    print(f"Найдено узлов: {len(found_nodes)}")
    
    # Шаг 5: Трансформация пикселей → реальные координаты
    # Используем информацию из профиля (он содержит список узлов с их реальными координатами)
    # или ручную привязку первых 2-3 узлов
    
    # Для упрощения предположим, что у нас есть ручная привязка из техусловий:
    reference_points = {
        'УТ-1а': (116763.09, 110258.78),  # реальные координаты в системе СК
        'ТК-2': (116850.15, 110200.45),
    }
    
    # Рассчитываем аффинную трансформацию
    if len(reference_points) >= 2:
        src_pts = np.float32([found_nodes[k]['pixel'] for k in reference_points.keys()])
        dst_pts = np.float32([reference_points[k] for k in reference_points.keys()])
        
        # Аффинная матрица трансформации
        affine_matrix = cv2.getAffineTransform(src_pts[:3], dst_pts[:3])
        
        # Применяем трансформацию ко всем найденным узлам
        network_nodes = {}
        for label, pixel_coords in found_nodes.items():
            px = np.array([pixel_coords['pixel'][0], pixel_coords['pixel'][1], 1])
            real_coords = affine_matrix @ px
            network_nodes[label] = {
                'x': real_coords[0],
                'y': real_coords[1],
                'pixel': pixel_coords['pixel']
            }
        
        print("Координаты узлов (реальные):")
        for label, coords in network_nodes.items():
            print(f"  {label}: ({coords['x']:.2f}, {coords['y']:.2f})")
        
        return network_nodes
    else:
        print("Недостаточно контрольных точек для калибровки")
        return {}

# Использование:
nodes = extract_plan_coordinates('Раздел_РД__1_ТС_Парнас_Проект.pdf', plan_page_num=2)
```

#### Метод B: Использование таблицы из техусловий (самый надёжный)

```python
def extract_nodes_from_technical_conditions(pdf_path):
    """
    В техусловиях часто есть таблица с координатами узлов.
    Пример из вашего файла техусловий:
    
    Таблица по инвентарным номерам, типам прокладки, диаметрам и протяженности
    
    № п/п | инв. номер | Ду,мм | бесканал. | канал. | футляр | воздн | итого
    1     | 3-4-30000516 | 600  | 0.00     | 0.00  | 0.00  | 48.00 | 48.00
    2     | 3-4-30000517 | 400  | 126.00   | 20.00 | 14.00 | 28.00 | 188.00
    """
    
    # Парсинг техусловий для извлечения инвентарных номеров
    with pdfplumber.open(pdf_path) as pdf:
        # Техусловия обычно в конце документа
        for page_num, page in enumerate(pdf.pages[-5:]):
            tables = page.extract_tables()
            
            for table in tables:
                # Ищем таблицу с "инв. номер"
                if any('инв' in str(cell).lower() for row in table for cell in row):
                    # Это таблица с инвентарными номерами
                    
                    nodes_from_inventory = {}
                    
                    for row in table[1:]:  # пропускаем заголовок
                        if row[0] and row[0].strip():  # если есть номер
                            inv_number = row[1].strip()  # инвентарный номер
                            dn = int(row[2].strip())
                            
                            # Инвентарный номер содержит информацию о расположении
                            # Пример: 3-4-30000516 расшифровывается в техусловиях
                            # как конкретное расположение
                            
                            nodes_from_inventory[inv_number] = {
                                'dn': dn,
                                'components': parse_inventory_number(inv_number)
                            }
                    
                    return nodes_from_inventory
    
    return {}

def parse_inventory_number(inv_num):
    """
    Инвентарные номера сети часто кодируют информацию о расположении.
    Пример кодирования (гипотеза):
    
    3-4-30000516 → Сеть 3, Подъезд 4, Длина 300м, Узел 516
    
    Требуется консультация с архивом или нормативом вашего города.
    """
    parts = inv_num.split('-')
    
    if len(parts) >= 2:
        network_id = int(parts[0])  # номер сети
        section_id = int(parts[1])  # участок/подъезд
        
        return {
            'network': network_id,
            'section': section_id,
            'raw_code': inv_num
        }
    
    return {'raw_code': inv_num}
```

**Практический результат:**
Массив узлов с координатами, который затем используется для построения рёбер:
```python
network_nodes = {
    'УТ-1а': {'x': 116763.09, 'y': 110258.78, 'z': None},
    'ТК-2': {'x': 116850.15, 'y': 110200.45, 'z': None},
    'ТК-3': {'x': 116920.30, 'y': 110120.12, 'z': None},
    'ТК-4': {'x': 117000.50, 'y': 110050.75, 'z': None},
}

# Создание рёбер (трубопроводов) между узлами
edges = [
    {'start': 'УТ-1а', 'end': 'ТК-2', 'distance': 145.30},
    {'start': 'ТК-2', 'end': 'ТК-3', 'distance': 98.76},
    {'start': 'ТК-3', 'end': 'ТК-4', 'distance': 112.54},
]
```

---

### Problem 3: Связь между планом и профилем

**Ситуация:** План показывает расположение в XY, профили показывают отметки (Z). Нужно связать их воедино.

**Решение:**

```python
def link_profile_to_plan(network_nodes, profile_data):
    """
    Профиль содержит таблицу типа:
    
    Узел     | Z_земли | Z_верха | Z_лотка | Глубина | Уклон
    УТ-1а    | 150.50  | 140.00  | 138.80  | 11.70   | 0.005
    ТК-2     | 149.80  | 139.50  | 138.30  | 11.50   | 0.004
    
    Нужно связать эти отметки с узлами из плана.
    """
    
    # Парсинг профиля
    profile_parsed = extract_profile_table(pdf_path, profile_page_num=3)
    
    # Маппинг: имя узла (из профиля) → объект узла (из плана)
    for node_name in network_nodes.keys():
        if node_name in profile_parsed:
            profile_row = profile_parsed[node_name]
            
            network_nodes[node_name].update({
                'z_surface': float(profile_row['Z_земли']),
                'z_pipe_top': float(profile_row['Z_верха']),
                'z_pipe_bottom': float(profile_row['Z_лотка']),  # основное для IFC
                'depth': float(profile_row['Глубина']),
            })
    
    # Для рёбер: интерполяция Z между узлами
    for edge in network_edges:
        start_node = network_nodes[edge['start']]
        end_node = network_nodes[edge['end']]
        
        # Линейная интерполяция
        z_start = start_node['z_pipe_bottom']
        z_end = end_node['z_pipe_bottom']
        
        # Уклон участка
        edge['slope'] = (z_start - z_end) / edge['distance']
        
        # Проверка соответствия нормам (минимальный уклон для самотока)
        MIN_SLOPE = 0.003  # 0.3% для канализации
        if edge['slope'] < MIN_SLOPE:
            print(f"WARNING: Участок {edge['start']}-{edge['end']} "
                  f"имеет малый уклон {edge['slope']:.4f} (мин. {MIN_SLOPE})")
    
    return network_nodes, network_edges

# Использование:
network_nodes, network_edges = link_profile_to_plan(
    network_nodes,
    profile_data
)

print("\nУзлы с Z-координатами:")
for name, node in network_nodes.items():
    print(f"  {name}: ({node['x']:.2f}, {node['y']:.2f}, {node['z_pipe_bottom']:.2f})")

print("\nРёбра с уклонами:")
for edge in network_edges:
    print(f"  {edge['start']}-{edge['end']}: уклон {edge['slope']:.4f}, "
          f"длина {edge['distance']:.2f}м")
```

---

### Problem 4: Генерация IFC с полной геометрией

**Ситуация:** Нужно из доменной модели сети сгенерировать IFC-файл, который можно открыть в Revit/ARCHICAD.

```python
import ifcopenshell
from ifcopenshell.api import run

def generate_ifc_from_network(network_nodes, network_edges, project_name):
    """
    Генерация IFC4 из доменной модели сети
    """
    
    # Создание IFC-файла
    ifc_file = ifcopenshell.file(schema='IFC4X3')  # Используем IFC4x3 для инфраструктуры
    
    # Создание проекта
    project = run("root.create_project", ifc_file, name=project_name)
    
    # Создание сайта/площадки
    site = run("root.create_site", ifc_file, name="Парнас - 8-й проезд")
    
    # Добавление сайта в проект
    run("aggregate.assign_object", ifc_file, relating_object=project, 
        related_object=site)
    
    # Единицы измерения
    run("unit.assign_unit", ifc_file, 
        units=[
            {"unit_type": "LENGTHUNIT", "name": "METRE"},
            {"unit_type": "AREAUNIT", "name": "SQUARE_METRE"},
            {"unit_type": "VOLUMEUNIT", "name": "CUBIC_METRE"},
            {"unit_type": "MASSUNIT", "name": "KILOGRAM"},
        ])
    
    # Система координат
    run("unit.assign_unit_coordinate_system", ifc_file, 
        x_axis=(1.0, 0.0, 0.0),
        y_axis=(0.0, 1.0, 0.0),
        z_axis=(0.0, 0.0, 1.0),
        origin=(0.0, 0.0, 0.0))
    
    # 1. Создание узлов (камеры, колодцы)
    ifc_nodes = {}
    
    for node_name, node_data in network_nodes.items():
        # Создание местоположения узла
        node_placement = run("geometry.create_local_placement", ifc_file,
            relative_to=site.ObjectPlacement,
            x=node_data['x'],
            y=node_data['y'],
            z=node_data['z_surface'])
        
        # Создание элемента (камера/колодец)
        if node_name.startswith('ТК'):
            # Тепловая камера - как IFCDISTRIBUTIONCHAMBER
            element_type = 'THERMALISOLATEDIFC'  # условный тип
            element = ifc_file.create_entity('IfcDistributionChamberElement',
                Name=node_name,
                ObjectPlacement=node_placement)
        else:
            # Уличный узел - как IFCJUNCTIONBOX
            element = ifc_file.create_entity('IfcJunctionBox',
                Name=node_name,
                ObjectPlacement=node_placement)
        
        # Добавление атрибутов
        element.RefElevation = node_data['z_surface']
        
        # Добавление в сайт
        run("aggregate.assign_object", ifc_file, relating_object=site,
            related_object=element)
        
        ifc_nodes[node_name] = element
    
    # 2. Создание трубопроводов (рёбер)
    ifc_pipes = []
    
    for i, edge in enumerate(network_edges):
        start_node = network_nodes[edge['start']]
        end_node = network_nodes[edge['end']]
        
        # Геометрия трубы: от начального узла к конечному
        start_pt = ifc_file.create_entity('IfcCartesianPoint',
            Coordinates=(start_node['x'], start_node['y'], start_node['z_pipe_bottom']))
        end_pt = ifc_file.create_entity('IfcCartesianPoint',
            Coordinates=(end_node['x'], end_node['y'], end_node['z_pipe_bottom']))
        
        # Линия (3D полилиния)
        line = ifc_file.create_entity('IfcLineSegment2D',
            StartPoint=start_pt,
            EndPoint=end_pt)
        
        # Профиль трубы (окружность для трубы)
        dn = edge.get('diameter', 325)  # диаметр в мм
        radius = dn / 2000.0  # переводим в метры
        
        circle = ifc_file.create_entity('IfcCircleProfileDef',
            ProfileType='AREA',
            Radius=radius)
        
        # Экструзия профиля по линии
        swept_solid = ifc_file.create_entity('IfcExtrudedAreaSolid',
            SweptArea=circle,
            Position=None,  # будет использовано местоположение
            ExtrudedDirection=ifc_file.create_entity('IfcDirection',
                DirectionRatios=(end_node['x']-start_node['x'], 
                                 end_node['y']-start_node['y'], 
                                 end_node['z_pipe_bottom']-start_node['z_pipe_bottom'])),
            Length=edge['distance'])
        
        # Форма представления
        shape = ifc_file.create_entity('IfcShapeRepresentation',
            RepresentationIdentifier='Body',
            RepresentationType='SweptSolid',
            Items=[swept_solid])
        
        # Определение формы
        product_shape = ifc_file.create_entity('IfcProductDefinitionShape',
            Representations=[shape])
        
        # Местоположение трубы
        pipe_placement = run("geometry.create_local_placement", ifc_file,
            relative_to=site.ObjectPlacement,
            x=start_node['x'],
            y=start_node['y'],
            z=start_node['z_pipe_bottom'])
        
        # Создание элемента IFCPIPING (трубопровод)
        pipe = ifc_file.create_entity('IfcPipeSegment',
            GlobalId=ifcopenshell.guid.new(),
            Name=f"Участок_{i+1}_{edge['start']}_to_{edge['end']}",
            ObjectPlacement=pipe_placement,
            Representation=product_shape)
        
        # Атрибуты трубы
        pipe.Description = f"DN={dn}mm, L={edge['distance']:.2f}m, Slope={edge['slope']:.4f}"
        
        # Создание свойств (PropertySet)
        property_set = ifc_file.create_entity('IfcPropertySet',
            Name='Pipe_Properties',
            HasProperties=[
                ifc_file.create_entity('IfcPropertySingleValue',
                    Name='Diameter',
                    NominalValue=ifc_file.create_entity('IfcLengthMeasure', 
                                                         wrappedValue=dn/1000.0)),  # в метрах
                ifc_file.create_entity('IfcPropertySingleValue',
                    Name='Length',
                    NominalValue=ifc_file.create_entity('IfcLengthMeasure',
                                                         wrappedValue=edge['distance'])),
                ifc_file.create_entity('IfcPropertySingleValue',
                    Name='Slope',
                    NominalValue=ifc_file.create_entity('IfcRatioMeasure',
                                                         wrappedValue=edge['slope'])),
                ifc_file.create_entity('IfcPropertySingleValue',
                    Name='Material',
                    NominalValue=ifc_file.create_entity('IfcLabel',
                                                         wrappedValue=edge.get('material', 'Steel'))),
                ifc_file.create_entity('IfcPropertySingleValue',
                    Name='Insulation',
                    NominalValue=ifc_file.create_entity('IfcLabel',
                                                         wrappedValue=edge.get('insulation', 'PPU+PE'))),
            ])
        
        # Связь свойств с элементом
        run("pset.assign_pset", ifc_file, element=pipe, pset=property_set)
        
        # Добавление в сайт
        run("aggregate.assign_object", ifc_file, relating_object=site,
            related_object=pipe)
        
        ifc_pipes.append(pipe)
    
    # Сохранение файла
    output_filename = f"{project_name.replace(' ', '_')}_generated.ifc"
    ifc_file.write(output_filename)
    print(f"IFC-файл сохранён: {output_filename}")
    
    return ifc_file, output_filename

# Использование:
ifc_file, output_path = generate_ifc_from_network(
    network_nodes=network_nodes,
    network_edges=network_edges,
    project_name="ПРНС_ЛО_ТКР-ТС_Парнас"
)

print(f"Создано объектов в IFC:")
print(f"  Узлов (камер/колодцев): {len(network_nodes)}")
print(f"  Трубопроводов: {len(network_edges)}")
```

---

## Часть 3: Полная очерёдность разработки (детальный roadmap)

### Этап 1: Базовая инфраструктура (неделя 1)

**Цель:** Создать MVP, работающий на ручных данных

```python
# main.py - точка входа

from dataclasses import dataclass
from typing import Dict, List
import json

@dataclass
class NetworkNode:
    """Узел сети (камера, колодец)"""
    name: str
    x: float  # координата
    y: float  # координата
    z_surface: float  # отметка земли
    z_pipe_bottom: float  # отметка лотка трубы
    node_type: str  # 'chamber', 'junction', 'street_unit'
    
    def to_dict(self):
        return {
            'name': self.name,
            'x': self.x,
            'y': self.y,
            'z_surface': self.z_surface,
            'z_pipe_bottom': self.z_pipe_bottom,
            'node_type': self.node_type,
        }

@dataclass
class NetworkEdge:
    """Участок трубопровода (ребро графа)"""
    start_node: str  # имя начального узла
    end_node: str  # имя конечного узла
    diameter: int  # диаметр в мм
    length: float  # длина в метрах
    material: str  # материал ('Steel', 'CI', etc.)
    insulation: str  # тип изоляции
    laying_type: str  # тип прокладки ('underground', 'overhead', 'in_duct', 'in_casing')
    slope: float = None  # уклон (рассчитывается автоматически)
    
    def calculate_slope(self, nodes: Dict[str, NetworkNode]):
        """Расчёт уклона по Z-координатам узлов"""
        start = nodes[self.start_node]
        end = nodes[self.end_node]
        self.slope = (start.z_pipe_bottom - end.z_pipe_bottom) / self.length
        return self.slope
    
    def to_dict(self):
        return {
            'start_node': self.start_node,
            'end_node': self.end_node,
            'diameter': self.diameter,
            'length': self.length,
            'material': self.material,
            'insulation': self.insulation,
            'laying_type': self.laying_type,
            'slope': self.slope,
        }

class ThermalNetworkModel:
    """Доменная модель тепловой сети"""
    
    def __init__(self, project_name: str, source: str = "Парнас-4"):
        self.project_name = project_name
        self.source = source
        self.nodes: Dict[str, NetworkNode] = {}
        self.edges: List[NetworkEdge] = []
    
    def add_node(self, node: NetworkNode):
        """Добавить узел сети"""
        self.nodes[node.name] = node
    
    def add_edge(self, edge: NetworkEdge):
        """Добавить участок"""
        # Валидация: оба узла должны существовать
        if edge.start_node not in self.nodes or edge.end_node not in self.nodes:
            raise ValueError(f"Узлы {edge.start_node} или {edge.end_node} не найдены")
        
        # Автоматический расчёт уклона
        edge.calculate_slope(self.nodes)
        
        self.edges.append(edge)
    
    def validate(self):
        """Проверка целостности модели"""
        errors = []
        
        for edge in self.edges:
            # Проверка минимального уклона для самотока
            MIN_SLOPE = 0.003
            if 0 < edge.slope < MIN_SLOPE:
                errors.append(f"Участок {edge.start_node}-{edge.end_node}: "
                            f"малый уклон {edge.slope:.4f} (мин. {MIN_SLOPE})")
            
            # Проверка отметок
            start = self.nodes[edge.start_node]
            end = self.nodes[edge.end_node]
            
            if start.z_pipe_bottom < start.z_surface - 20:
                errors.append(f"Узел {edge.start_node}: глубина {start.z_surface - start.z_pipe_bottom:.2f}м > 20м")
        
        return errors
    
    def to_json(self):
        """Сериализация в JSON"""
        return {
            'project_name': self.project_name,
            'source': self.source,
            'nodes': {name: node.to_dict() for name, node in self.nodes.items()},
            'edges': [edge.to_dict() for edge in self.edges],
        }

# Пример использования:
if __name__ == "__main__":
    
    # Создание модели
    model = ThermalNetworkModel(
        project_name="ПРНС_ЛО_ТКР-ТС_Парнас",
        source="Котельная Парнас-4"
    )
    
    # Добавление узлов (ручной ввод)
    model.add_node(NetworkNode(
        name="УТ-1а",
        x=116763.09, y=110258.78,
        z_surface=150.50, z_pipe_bottom=138.80,
        node_type='street_unit'
    ))
    
    model.add_node(NetworkNode(
        name="ТК-2",
        x=116850.15, y=110200.45,
        z_surface=149.80, z_pipe_bottom=138.30,
        node_type='chamber'
    ))
    
    # ... добавление остальных узлов ...
    
    # Добавление участков
    model.add_edge(NetworkEdge(
        start_node="УТ-1а", end_node="ТК-2",
        diameter=400, length=145.30,
        material="Steel", insulation="PPU+PE",
        laying_type="underground"
    ))
    
    # Валидация
    errors = model.validate()
    if errors:
        print("Ошибки валидации:")
        for err in errors:
            print(f"  - {err}")
    else:
        print("Модель валидна ✓")
    
    # Сохранение
    with open('network_model.json', 'w', encoding='utf-8') as f:
        json.dump(model.to_json(), f, indent=2, ensure_ascii=False)
    
    # Генерация IFC
    ifc_file, path = generate_ifc_from_network(
        network_nodes=model.nodes,
        network_edges=model.edges,
        project_name=model.project_name
    )
    
    print(f"\n✓ Сгенерирован IFC: {path}")
```

---

### Этап 2: PDF-парсинг (неделя 2-3)

Реализовать функции парсинга спецификации, профилей, координат из PDF.

### Этап 3: ML-классификация (неделя 4-5)

Обучить классификатор диаметров на исторических данных.

### Этап 4: UI и интеграция (неделя 6-8)

Создать интерфейс для загрузки PDF, настройки параметров, визуализации результатов.

---

## Следующие шаги

1. **Начать с MVP:**
   - Ручной ввод координат узлов (10 узлов) через CSV
   - Парсинг спецификации (диаметры, материалы, количества)
   - Базовая генерация IFC с этими параметрами

2. **Тестировать на вашем проекте:**
   - Открыть IFC в Revit/ARCHICAD
   - Сравнить с исходным PDF планом
   - Выявить пробелы (какие данные не парсятся автоматически)

3. **Итеративно добавлять интеллект:**
   - Распознавание координат из чертежа
   - Парсинг профилей
   - AI-классификация

4. **Валидация:**
   - Проверка соответствия IFC стандарту
   - Сравнение с исходным проектом (графическая или числовая проверка)
