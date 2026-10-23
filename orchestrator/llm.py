"""OpenAI-compatible planning adapter for the STE Slicer assistant.

The adapter intentionally returns a constrained JSON plan. The plan is advisory;
all file operations and slicing remain controlled by the orchestrator and MCP tools.
"""

from __future__ import annotations

import json
import os
from typing import Any

LLM_API_URL = os.getenv("LLM_API_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

SYSTEM_PROMPT = """You are an additive manufacturing planning assistant for STE Slicer.
Return only valid JSON with these keys:
mode: one of 3D or 5D;
material: string;
profile: string;
orientation: {x: number, y: number, z: number};
arrangement: {copies: integer, spacing_mm: number, strategy: string};
parameters: object;
reasoning: string;
assumptions: array of strings.
Never invent tool results. Prefer safe conservative settings.
"""


def _fallback_plan(message: str, context: dict[str, Any]) -> dict[str, Any]:
    text = message.lower()
    material = "PEEK" if "peek" in text or "пик" in text else "PLA"
    mode = "5D" if "5d" in text or "пять" in text else "3D"
    copies = 2 if "две" in text or "2 " in text or "два" in text else 1
    return {
        "mode": mode,
        "material": material,
        "profile": "high-temperature" if material == "PEEK" else "standard",
        "orientation": {"x": 0, "y": 0, "z": 0},
        "arrangement": {
            "copies": copies,
            "spacing_mm": 5,
            "strategy": "centered_grid",
        },
        "parameters": {
            "layer_height": 0.2,
            "supports": "auto",
            "infill": 30,
        },
        "reasoning": (
            "Выбран консервативный профиль на основе материала и текста задачи. "
            "Ориентация оставлена безопасной до проверки геометрии MCP."
        ),
        "assumptions": [
            "Файл совместим с выбранным профилем.",
            "Размеры и коллизии будут проверены перед слайсингом.",
        ],
        "source": "local-demo-planner",
    }


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("LLM response does not contain choices")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    return str(content).strip()


def _parse_plan(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    plan = json.loads(content)
    if not isinstance(plan, dict):
        raise ValueError("LLM plan must be a JSON object")

    if plan.get("mode") not in {"3D", "5D"}:
        plan["mode"] = "3D"
    orientation = plan.get("orientation", {})
    if not isinstance(orientation, dict):
        orientation = {}
    def bounded_angle(value: Any) -> float:
        try:
            return max(-360.0, min(360.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
    plan["orientation"] = {
        axis: bounded_angle(orientation.get(axis, 0)) for axis in ("x", "y", "z")
    }

    arrangement = plan.get("arrangement", {})
    if not isinstance(arrangement, dict):
        arrangement = {}
    try:
        copies = int(arrangement.get("copies", 1))
    except (TypeError, ValueError):
        copies = 1
    try:
        spacing = float(arrangement.get("spacing_mm", 5))
    except (TypeError, ValueError):
        spacing = 5.0
    plan["arrangement"] = {
        "copies": max(1, min(100, copies)),
        "spacing_mm": max(0.0, min(1000.0, spacing)),
        "strategy": str(arrangement.get("strategy", "centered_grid"))[:80],
    }
    plan["parameters"] = plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {}
    plan.setdefault("material", "PLA")
    plan.setdefault("profile", "standard")
    plan.setdefault("reasoning", "План сформирован LLM.")
    plan.setdefault("assumptions", [])
    if not isinstance(plan["assumptions"], list):
        plan["assumptions"] = []
    plan["source"] = "openai-compatible-llm"
    return plan


async def create_print_plan(message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    if not LLM_API_URL or not LLM_API_KEY:
        return _fallback_plan(message, context)

    url = LLM_API_URL
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"request": message, "context": context}, ensure_ascii=False)},
        ],
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            "The httpx dependency is required when LLM_API_URL and LLM_API_KEY are configured."
        ) from exc

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return _parse_plan(_extract_content(response.json()))
