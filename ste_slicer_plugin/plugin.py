"""STE Slicer / Cura 3.6-compatible integration bridge.

The plugin keeps host-specific imports optional so it can be unit-tested outside
STE Slicer. In the host it exposes a menu action and a dockable chat widget.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:  # Cura/STE runtime
    from UM.Extension import Extension  # type: ignore
except ImportError:  # pragma: no cover - used outside the host
    class Extension:  # type: ignore[no-redef]
        def __init__(self) -> None:
            pass

try:
    from UM.Application import Application  # type: ignore
except ImportError:  # pragma: no cover
    Application = None  # type: ignore[assignment,misc]


@dataclass
class PluginSettings:
    """Public plugin settings; LLM secrets stay in the orchestrator environment."""

    orchestrator_url: str = field(
        default_factory=lambda: os.getenv(
            "ROSATOM_ORCHESTRATOR_URL",
            "http://127.0.0.1:8000",
        )
    )


class OrchestratorClient:
    def __init__(self, settings: PluginSettings, timeout: float = 60.0) -> None:
        self.settings = settings
        self.timeout = timeout

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.orchestrator_url.rstrip('/')}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("Orchestrator returned an invalid response")
        return value

    def chat(self, message: str, job_id: str | None = None) -> dict[str, Any]:
        return self._request("/api/v1/chat", {"message": message, "job_id": job_id})

    def upload_model(
        self,
        path: str,
        material: str | None = None,
        quality: str = "standard",
        plan: dict[str, Any] | None = None,
        request: str | None = None,
    ) -> dict[str, Any]:
        boundary = "----RosatomSTEPluginBoundary"
        file_path = Path(path)
        content = file_path.read_bytes()
        selected_plan = plan if isinstance(plan, dict) else {}
        selected_material = material or selected_plan.get("material") or ""
        selected_quality = quality
        if not material and selected_plan.get("profile"):
            selected_quality = str(selected_plan["profile"])
        metadata = {
            "source": "ste_slicer_plugin",
            "request": request or "Подготовь текущую модель к печати.",
            "plan": selected_plan,
        }
        fields = {
            "material": selected_material,
            "quality": selected_quality,
            "start_print": "false",
            "parameters": json.dumps(selected_plan.get("parameters", {})),
            "metadata": json.dumps(metadata, ensure_ascii=False),
        }
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.extend([f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(), str(value).encode(), b"\r\n"])
        chunks.extend([f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode(), b"Content-Type: application/octet-stream\r\n\r\n", content, b"\r\n", f"--{boundary}--\r\n".encode()])
        request = urllib.request.Request(
            f"{self.settings.orchestrator_url.rstrip('/')}/api/v1/jobs",
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise RuntimeError("Orchestrator returned an invalid job")
        return result


class RosatomAssistantExtension(Extension):
    """Host adapter exposing the assistant in the STE Slicer extension menu."""

    def __init__(self, settings: PluginSettings | None = None) -> None:
        super().__init__()
        self.settings = settings or PluginSettings()
        self.client = OrchestratorClient(self.settings)
        self._chat_callback: Callable[[dict[str, Any]], None] | None = None
        self._register_host_action()

    def _register_host_action(self) -> None:
        if Application is None:
            return
        app = Application.getInstance()
        if hasattr(app, "addMenuItem"):
            app.addMenuItem("ROSATOM AI Assistant", self.show_chat)

    def show_chat(self) -> None:
        """Open the UI panel; the Qt implementation is injected by the host adapter."""
        try:
            from .ui import AssistantDialog
        except ImportError:
            return
        dialog = AssistantDialog(self.client)
        dialog.show()

    def send_chat(self, message: str, job_id: str | None = None, callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._chat_callback = callback

        def worker() -> None:
            try:
                result = self.client.chat(message, job_id)
            except (OSError, urllib.error.URLError, RuntimeError) as exc:
                result = {"message": f"Ошибка подключения к orchestrator: {exc}", "actions": []}
            if self._chat_callback:
                self._chat_callback(result)

        threading.Thread(target=worker, daemon=True).start()


def getMetaData() -> dict[str, Any]:  # noqa: N802 - Cura plugin API name
    return {
        "tool": "RosatomAssistant",
        "name": "ROSATOM AI Assistant",
        "description": "LLM/MCP assistant for 3D/5D print planning in STE Slicer",
        "version": "1.0.0",
        "author": "ROSATOM AI Team",
        "api": "Cura 3.6 / STE Slicer compatible",
    }


def createExtension() -> RosatomAssistantExtension:  # noqa: N802 - Cura plugin API name
    return RosatomAssistantExtension()
