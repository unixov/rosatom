from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_KNOWLEDGE_BASE: list[dict[str, Any]] = [
    {
        "material": "PLA",
        "aliases": ["PLA", "ПЛА"],
        "description": (
            "PLA подходит для прототипов, демонстрационных моделей "
            "и большинства стандартных деталей."
        ),
        "parameters": {
            "nozzle_temperature": 205,
            "bed_temperature": 60,
            "print_speed": 60,
            "layer_height": 0.20,
            "cooling": 100,
            "supports": "auto",
            "infill": 20,
        },
    },
    {
        "material": "PETG",
        "aliases": ["PETG", "ПЭТГ", "ПЕТГ"],
        "description": (
            "PETG подходит для функциональных деталей, которым нужны "
            "повышенная прочность и химическая стойкость."
        ),
        "parameters": {
            "nozzle_temperature": 240,
            "bed_temperature": 80,
            "print_speed": 45,
            "layer_height": 0.20,
            "cooling": 60,
            "supports": "auto",
            "infill": 25,
        },
    },
    {
        "material": "ABS",
        "aliases": ["ABS", "АБС"],
        "description": (
            "ABS подходит для термостойких деталей. Желательно использовать "
            "закрытую камеру и контролировать температуру окружающей среды."
        ),
        "parameters": {
            "nozzle_temperature": 250,
            "bed_temperature": 100,
            "print_speed": 40,
            "layer_height": 0.20,
            "cooling": 20,
            "supports": "auto",
            "infill": 30,
            "enclosure_required": True,
        },
    },
    {
        "material": "TPU",
        "aliases": ["TPU", "ТПУ"],
        "description": (
            "TPU подходит для гибких и эластичных деталей. "
            "Печатать рекомендуется на небольшой скорости."
        ),
        "parameters": {
            "nozzle_temperature": 225,
            "bed_temperature": 50,
            "print_speed": 25,
            "layer_height": 0.20,
            "cooling": 70,
            "supports": "auto",
            "infill": 20,
        },
    },
]


def _load_knowledge_base() -> list[dict[str, Any]]:
    configured_path = os.getenv("RAG_KNOWLEDGE_BASE_PATH")

    if not configured_path:
        return DEFAULT_KNOWLEDGE_BASE

    path = Path(configured_path)

    if not path.exists():
        return DEFAULT_KNOWLEDGE_BASE

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_KNOWLEDGE_BASE

    if not isinstance(content, list):
        return DEFAULT_KNOWLEDGE_BASE

    return content


def normalize_material(material: str | None) -> str:
    if not material:
        return "PLA"

    normalized = material.strip().upper()

    aliases = {
        "ПЛА": "PLA",
        "ПЭТГ": "PETG",
        "ПЕТГ": "PETG",
        "АБС": "ABS",
        "ТПУ": "TPU",
    }

    return aliases.get(normalized, normalized)


def _to_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _geometry_value(
    geometry: dict[str, Any],
    *keys: str,
    default: float = 0.0,
) -> float:
    for key in keys:
        if key in geometry:
            return _to_float(geometry[key], default)

    return default


def _find_material_entry(material: str) -> dict[str, Any]:
    knowledge_base = _load_knowledge_base()

    for entry in knowledge_base:
        entry_material = normalize_material(entry.get("material"))

        if entry_material == material:
            return entry

        aliases = entry.get("aliases", [])

        if any(normalize_material(alias) == material for alias in aliases):
            return entry

    for entry in knowledge_base:
        if normalize_material(entry.get("material")) == "PLA":
            return entry

    return DEFAULT_KNOWLEDGE_BASE[0]


def recommend_parameters(
    geometry: dict[str, Any] | None = None,
    material: str | None = None,
    quality: str = "standard",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    geometry = geometry or {}
    overrides = overrides or {}

    normalized_material = normalize_material(material)
    entry = _find_material_entry(normalized_material)

    parameters = dict(entry.get("parameters", {}))
    reasons = [
        entry.get(
            "description",
            "Параметры выбраны на основе локальной базы рекомендаций.",
        )
    ]

    overhang_ratio = _geometry_value(
        geometry,
        "overhang_ratio",
        "overhang_percent",
        "overhang",
    )

    height = _geometry_value(
        geometry,
        "height",
        "max_height",
        "z",
    )

    volume = _geometry_value(
        geometry,
        "volume",
        "volume_mm3",
    )

    if overhang_ratio > 1:
        overhang_ratio /= 100

    if overhang_ratio >= 0.25:
        parameters["supports"] = "everywhere"
        reasons.append(
            "Обнаружена большая площадь нависающих элементов. "
            "Поддержки включены для всей модели."
        )
    elif overhang_ratio >= 0.10:
        parameters["supports"] = "build_plate"
        reasons.append(
            "Обнаружены нависающие элементы средней сложности. "
            "Поддержки включены от платформы."
        )

    quality = quality.lower().strip()

    if quality == "draft":
        parameters["layer_height"] = 0.28
        parameters["print_speed"] = min(
            int(parameters.get("print_speed", 60) * 1.25),
            100,
        )
        reasons.append(
            "Выбран черновой режим: увеличена высота слоя "
            "и скорость печати."
        )

    elif quality == "high":
        parameters["layer_height"] = 0.12
        parameters["print_speed"] = max(
            int(parameters.get("print_speed", 60) * 0.70),
            15,
        )
        reasons.append(
            "Выбран режим высокого качества: уменьшена высота слоя "
            "и скорость печати."
        )

    else:
        quality = "standard"
        reasons.append("Выбран стандартный режим печати.")

    if height > 180:
        parameters["print_speed"] = max(
            int(parameters.get("print_speed", 40) * 0.85),
            15,
        )
        reasons.append(
            "Модель высокая, поэтому скорость уменьшена "
            "для повышения устойчивости печати."
        )

    if volume > 500_000:
        reasons.append(
            "Модель имеет большой объем. Увеличатся расход материала "
            "и длительность печати."
        )

    parameters.update(overrides)

    return {
        "material": normalized_material,
        "quality": quality,
        "parameters": parameters,
        "reasons": reasons,
        "source": "local-rag-knowledge-base",
    }
