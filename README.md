# ROSATOM AI Assistant for STE Slicer

Прототип связывает web UI/STE Slicer plugin, OpenAI-compatible LLM planner, FastAPI/Celery orchestrator и неизменённый MCP server. Он демонстрирует анализ геометрии, планирование, рекомендации материала, генерацию G-code, телеметрию парка и экспорт набора результатов.

## Состав и статус реализации

- `orchestrator/`: API, очередь задач, MCP-клиент, RAG-рекомендации, OpenAI-compatible planning adapter и exporter.
- `frontend/`: web dashboard и 3D preview загруженной модели.
- `mcp_server/`: исходный MCP server; инструменты сохранены без изменений.
- `ste_slicer_plugin/`: прототип bridge/UI, который умеет отправлять запросы, загружать выбранный файл и передавать план в задачу.
- При успешной задаче `results/<job_id>/` содержит `project.3mf`, `result.gcode`, `chat.png` и `manifest.json`; рядом создаётся ZIP-комплект.

## Быстрый запуск

Требуются Docker Desktop с Compose и доступ к сети для сборки образов.

```sh
cp .env.example .env
# При необходимости отредактируйте .env, затем:
docker compose up -d --build
```

Web UI: http://localhost:5173. API health: http://localhost:8000/health. Чтобы остановить:

```sh
docker compose down
```

Для LLM установите в `.env`:

```dotenv
LLM_API_URL=https://api.example.com/v1
LLM_API_KEY=replace-with-your-key
LLM_MODEL=your-model-name
LLM_TIMEOUT_SECONDS=60
```

`LLM_API_URL` — base URL OpenAI-compatible API; адаптер дописывает `/chat/completions`, если путь не задан. Не добавляйте реальные секреты в git. Без URL/key приложение работает на локальном демонстрационном planner.

## Установка plugin в STE Slicer / Cura 3.6

1. Найдите каталог ресурсов Cura/STE Slicer для пользовательских plugin. Обычно он находится в пользовательском каталоге приложения, в подкаталоге `plugins`; точный путь зависит от сборки и ОС.
2. Скопируйте содержимое `ste_slicer_plugin/` в отдельный каталог `RosatomAssistant` внутри `plugins`.
3. Перезапустите Slicer. Если хост не обнаруживает plugin, проверьте его журнал plugin loader и соответствие API конкретной сборки.
4. В диалоге plugin задайте URL доступного orchestrator (например `http://127.0.0.1:8000`). LLM URL/key/model задаются на backend через environment, не в Slicer.
5. Для desktop-плагина `localhost` должен быть доступен из компьютера пользователя; URL Docker service name `orchestrator` подходит только контейнер-контейнерному трафику.

Для ручной упаковки используйте `python3 scripts/package_plugin.py`; ZIP появится в `dist/`.

## Что реально гарантирует prototype

- MCP tools вызываются по объявленным именам и фактическим сигнатурам: `analyze_stl_geometry(file_path)`, `generate_gcode(file_path, material, layer_height)`, `get_fleet_telemetry()` и `control_printer(printer_id, action, gcode_path)`.
- STL/OBJ 3MF export использует исходную сетку; неверный mesh приводит к ошибке экспорта вместо подстановки вымышленного треугольника. Декларируемые ориентация и копии отображаются в экспортируемой mesh-геометрии для STL/OBJ.
- Для входного 3MF сохраняется оригинальный файл, а plan отражается в manifest; произвольный vendor-specific 3MF не переписывается.
- PNG — рендер компактной демонстрационной карточки диалога, не скриншот окна реального STE Slicer. Для презентации замените `chat.png` на настоящий screenshot из целевого окружения.

## Известные ограничения относительно ТЗ

Этот репозиторий пока не доказывает production-совместимость и не является полностью валидированным установленным plugin для конкретного дистрибутива STE Slicer. Реальный API меню/сцены и установка должны быть проверены на целевой сборке. Plugin пока передаёт выбранный файл, а не управляет объектами уже открытой сцены; кнопка выбора файла — bridge workflow, несмотря на подпись текущей сцены. Режим 5D передаётся как metadata, но существующий MCP `generate_gcode` принимает только путь, материал и высоту слоя; это не доказывает 5D траекторию. MCP SlicerEngine может использовать fallback G-code; такой результат не следует выдавать за production slicing. Проектный 3MF для STL/OBJ — совместимый базовый mesh-пакет, не native Cura project с проверенным printer profile. Нужны целевые тесты по эталонным геометрии и G-code и подтверждение жюри/владельцев профилей.

Не включайте в сдаваемый пакет сторонний проприетарный Slicer. Проверяйте лицензионные notice для Cura 3.6/LGPLv3 и сторонних зависимостей согласно правилам организатора.

## Проверки

```sh
python3 -m compileall -q orchestrator ste_slicer_plugin
python3 -m json.tool frontend/package.json >/dev/null
docker compose config
```

Проверки контейнерного runtime, загрузки plugin в STE Slicer и сравнения с эталонным G-code следует выполнить в целевой среде.
