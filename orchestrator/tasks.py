from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import redis

from artifacts import create_submission_bundle
from celery_app import celery_app
from llm import create_print_plan
from rag import recommend_parameters


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "http://mcp_server:8001",
).rstrip("/")
MCP_PATH = os.getenv("MCP_PATH", "/mcp")
MCP_TIMEOUT_SECONDS = float(
    os.getenv("MCP_TIMEOUT_SECONDS", "180")
)
MCP_CLIENT_VERSION = os.getenv(
    "MCP_CLIENT_VERSION",
    "1.0.0",
)

MODEL_STORAGE_DIR = Path(
    os.getenv("MODEL_STORAGE_DIR", "/data/models")
)
OUTPUT_STORAGE_DIR = Path(
    os.getenv("OUTPUT_STORAGE_DIR", "/data/output")
)

JOB_TTL_SECONDS = int(
    os.getenv("JOB_TTL_SECONDS", "604800")
)


redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


class JobNotFoundError(Exception):
    pass


class JobCancelledError(Exception):
    pass


class MCPClientError(Exception):
    pass


class JobStore:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    @staticmethod
    def job_key(job_id: str) -> str:
        return f"orchestrator:job:{job_id}"

    @staticmethod
    def events_key(job_id: str) -> str:
        return f"orchestrator:job:{job_id}:events"

    @staticmethod
    def cancel_key(job_id: str) -> str:
        return f"orchestrator:job:{job_id}:cancel"

    @staticmethod
    def _serialize(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(
                value,
                ensure_ascii=True,
                default=str,
            )

        if value is None:
            return ""

        return str(value)

    def create_job(self, job: dict[str, Any]) -> None:
        key = self.job_key(job["job_id"])

        values = {
            field: self._serialize(value)
            for field, value in job.items()
        }

        self.client.hset(key, mapping=values)
        self.client.expire(key, JOB_TTL_SECONDS)

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.client.hgetall(self.job_key(job_id))

        if not job:
            raise JobNotFoundError(job_id)

        for field in ("options", "result"):
            if field in job and job[field]:
                job[field] = json.loads(job[field])
            elif field in job:
                job[field] = {}

        if "progress" in job:
            job["progress"] = int(job["progress"])

        return job

    def update_job(
        self,
        job_id: str,
        **changes: Any,
    ) -> dict[str, Any]:
        self.get_job(job_id)

        changes["updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        values = {
            field: self._serialize(value)
            for field, value in changes.items()
        }

        key = self.job_key(job_id)

        self.client.hset(key, mapping=values)
        self.client.expire(key, JOB_TTL_SECONDS)

        return self.get_job(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        keys = list(
            self.client.scan_iter(match="orchestrator:job:*")
        )

        keys = [
            key
            for key in keys
            if not key.endswith(":events")
            and not key.endswith(":cancel")
        ]

        jobs = []

        for key in keys:
            job = self.client.hgetall(key)

            if not job:
                continue

            job_id = job.get("job_id")

            if not job_id:
                continue

            try:
                jobs.append(self.get_job(job_id))
            except JobNotFoundError:
                continue

        jobs.sort(
            key=lambda item: item.get("created_at", ""),
            reverse=True,
        )

        return jobs[:limit]

    def add_event(
        self,
        job_id: str,
        event_type: str,
        *,
        status: str,
        step: str | None = None,
        progress: int = 0,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_job(job_id)

        events_key = self.events_key(job_id)
        event_id = self.client.llen(events_key) + 1

        event = {
            "event_id": event_id,
            "job_id": job_id,
            "event_type": event_type,
            "status": status,
            "step": step,
            "progress": progress,
            "message": message,
            "payload": payload or {},
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        self.client.rpush(
            events_key,
            json.dumps(
                event,
                ensure_ascii=True,
                default=str,
            ),
        )
        self.client.expire(events_key, JOB_TTL_SECONDS)

        return event

    def get_events(
        self,
        job_id: str,
        after_id: int = 0,
    ) -> list[dict[str, Any]]:
        self.get_job(job_id)

        values = self.client.lrange(
            self.events_key(job_id),
            max(after_id, 0),
            -1,
        )

        return [json.loads(value) for value in values]

    def request_cancel(self, job_id: str) -> None:
        self.get_job(job_id)

        self.client.set(
            self.cancel_key(job_id),
            "1",
            ex=JOB_TTL_SECONDS,
        )

    def is_cancel_requested(self, job_id: str) -> bool:
        return bool(
            self.client.exists(self.cancel_key(job_id))
        )


store = JobStore(redis_client)


class MCPClient:
    def __init__(self) -> None:
        self.base_url = MCP_SERVER_URL
        self.mcp_url = f"{self.base_url}{MCP_PATH}"
        self.timeout = MCP_TIMEOUT_SECONDS
        self._request_id = 0
        self._session_id: str | None = None


    async def call_tool(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> Any:
        """Call one of the tools exposed by the existing MCP server.

        The orchestrator keeps domain-level names for its pipeline stages, while
        this adapter translates them to the stable MCP-server contract.
        """
        if tool_name == "analyze_geometry":
            return await self._call_mcp_tool(
                "analyze_stl_geometry",
                {"file_path": payload["file_path"]},
            )

        if tool_name == "get_fleet_telemetry":
            return await self._call_mcp_tool(
                "get_fleet_telemetry",
                {},
            )

        if tool_name == "generate_gcode":
            parameters = payload.get("parameters") or {}
            return await self._call_mcp_tool(
                "generate_gcode",
                {
                    "file_path": payload["file_path"],
                    "material": payload.get("material", "PLA"),
                    "layer_height": float(
                        parameters.get("layer_height", 0.2)
                    ),
                },
            )

        if tool_name == "control_printer":
            return await self._call_mcp_tool(
                "control_printer",
                {
                    "printer_id": payload["printer_id"],
                    "action": payload["action"],
                    "gcode_path": payload.get("gcode_path"),
                },
            )

        raise MCPClientError(
            f"Unsupported orchestrator tool: {tool_name}"
        )

    async def _call_mcp_tool(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> Any:
        self._request_id += 1
        request_id = self._request_id

        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2024-11-05",
        }

        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=headers,
        ) as client:
            try:
                if not self._session_id:
                    initialize = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "rosatom-orchestrator",
                                "version": MCP_CLIENT_VERSION,
                            },
                        },
                    }
                    response = await client.post(
                        self.mcp_url,
                        json=initialize,
                    )
                    if response.is_error:
                        raise MCPClientError(
                            "MCP initialize failed with HTTP "
                            f"{response.status_code}: {response.text[:1000]}"
                        )
                    self._session_id = response.headers.get(
                        "mcp-session-id"
                    )
                    if self._session_id:
                        client.headers["Mcp-Session-Id"] = self._session_id
                    self._parse_mcp_response(response, request_id)

                    notification = {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    }
                    initialized_response = await client.post(
                        self.mcp_url,
                        json=notification,
                    )
                    if initialized_response.is_error:
                        raise MCPClientError(
                            "MCP initialized notification failed with HTTP "
                            f"{initialized_response.status_code}: "
                            f"{initialized_response.text[:1000]}"
                        )
                    self._request_id += 1
                    request_id = self._request_id

                request = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": payload,
                    },
                }
                response = await client.post(
                    self.mcp_url,
                    json=request,
                )
                if response.is_error:
                    raise MCPClientError(
                        f"MCP tool call failed with HTTP {response.status_code}: "
                        f"{response.text[:1000]}"
                    )
                result = self._parse_mcp_response(response, request_id)
            except httpx.HTTPError as exc:
                raise MCPClientError(
                    f"MCP server is unavailable: {exc}"
                ) from exc

        if isinstance(result, dict) and result.get("isError"):
            content = result.get("content", [])
            message = "MCP tool returned an error"
            if content and isinstance(content[0], dict):
                message = str(content[0].get("text", message))
            raise MCPClientError(message)

        if isinstance(result, dict) and "structuredContent" in result:
            return result["structuredContent"]

        content = result.get("content", []) if isinstance(result, dict) else []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (TypeError, json.JSONDecodeError):
                    return {"text": item["text"]}

        return result

    @staticmethod
    def _parse_mcp_response(
        response: httpx.Response,
        request_id: int,
    ) -> Any:
        try:
            data = response.json()
        except ValueError:
            data = None
            for line in response.text.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    candidate = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if candidate.get("id") == request_id:
                    data = candidate
                    break
            if data is None:
                raise MCPClientError(
                    "MCP server returned an invalid Streamable HTTP response"
                )

        if not isinstance(data, dict):
            raise MCPClientError("MCP server returned an invalid response")
        if data.get("error"):
            error = data["error"]
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise MCPClientError(message)

        return data.get("result", data)

    async def get_printers(self) -> Any:
        return await self._call_mcp_tool(
            "get_fleet_telemetry",
            {},
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_geometry(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}

    geometry = result.get("geometry")

    if isinstance(geometry, dict):
        return geometry

    return result


def _extract_printer_id(
    result: Any,
    requested_printer_id: str | None,
) -> str | None:
    if requested_printer_id:
        return requested_printer_id

    printers = result if isinstance(result, list) else []

    for printer in printers:
        if not isinstance(printer, dict):
            continue

        printer_id = printer.get("printer_id") or printer.get("id")
        status = str(printer.get("status", "")).lower()

        if printer_id and status in {"idle", "ready", "online"}:
            return str(printer_id)

    for printer in printers:
        if isinstance(printer, dict):
            printer_id = printer.get("printer_id") or printer.get("id")
            if printer_id:
                return str(printer_id)

    return None


def _extract_gcode_path(
    result: Any,
    fallback: Path,
) -> Path:
    if isinstance(result, dict):
        path_value = (
            result.get("gcode_path")
            or result.get("output_path")
            or result.get("file_path")
        )

        if path_value:
            return Path(path_value)

    return fallback


def _check_cancelled(job_id: str) -> None:
    if not store.is_cancel_requested(job_id):
        return

    store.update_job(
        job_id,
        status="cancelled",
        current_step="cancelled",
    )

    store.add_event(
        job_id,
        "job_cancelled",
        status="cancelled",
        step="cancelled",
        message="Задача отменена пользователем.",
    )

    raise JobCancelledError(job_id)


def _start_step(
    job_id: str,
    step: str,
    progress: int,
    message: str,
) -> None:
    _check_cancelled(job_id)

    store.update_job(
        job_id,
        status="running",
        current_step=step,
        progress=progress,
    )

    store.add_event(
        job_id,
        "step_started",
        status="running",
        step=step,
        progress=progress,
        message=message,
    )


def _finish_step(
    job_id: str,
    step: str,
    progress: int,
    payload: Any = None,
) -> None:
    store.update_job(
        job_id,
        status="running",
        current_step=step,
        progress=progress,
    )

    event_payload = payload if isinstance(payload, dict) else {}

    store.add_event(
        job_id,
        "step_finished",
        status="running",
        step=step,
        progress=progress,
        message=f"Этап {step} завершен.",
        payload=event_payload,
    )


async def _run_pipeline(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    options = job.get("options", {})

    model_path = Path(job["model_path"])

    if not model_path.exists():
        raise FileNotFoundError(
            f"Model file does not exist: {model_path}"
        )

    mcp = MCPClient()
    stored_plan = options.get("plan")
    if isinstance(stored_plan, dict) and stored_plan:
        plan = stored_plan
    else:
        plan = await create_print_plan(
            str(options.get("metadata", {}).get("request", "Подготовь модель к печати.")),
            {
                "job_id": job_id,
                "filename": job["filename"],
                "requested_material": options.get("material"),
                "quality": options.get("quality", "standard"),
            },
        )

    plan_parameters = plan.get("parameters", {})
    if not isinstance(plan_parameters, dict):
        plan_parameters = {}
    requested_parameters = options.get("parameters", {})
    if not isinstance(requested_parameters, dict):
        requested_parameters = {}
    effective_parameters = {**plan_parameters, **requested_parameters}
    effective_material = options.get("material") or plan.get("material") or "PLA"
    requested_quality = options.get("quality") or plan.get("profile") or "standard"
    quality_aliases = {"high-quality": "high", "fine": "high", "draft": "draft"}
    effective_quality = quality_aliases.get(
        str(requested_quality).lower(),
        str(requested_quality).lower(),
    )
    if effective_quality not in {"draft", "standard", "high"}:
        effective_quality = "standard"

    _start_step(
        job_id,
        "analyze_geometry",
        10,
        "Анализ геометрии модели.",
    )

    geometry_result = await mcp.call_tool(
        "analyze_stl_geometry",
        {"file_path": str(model_path)},
    )
    if isinstance(geometry_result, dict) and geometry_result.get("error"):
        raise MCPClientError(str(geometry_result["error"]))

    geometry = _extract_geometry(geometry_result)

    _finish_step(
        job_id,
        "analyze_geometry",
        25,
        geometry_result,
    )

    _start_step(
        job_id,
        "recommend_parameters",
        30,
        "Подбор параметров печати.",
    )

    recommendation = recommend_parameters(
        geometry=geometry,
        material=effective_material,
        quality=effective_quality,
        overrides=effective_parameters,
    )

    _finish_step(
        job_id,
        "recommend_parameters",
        40,
        recommendation,
    )

    _start_step(
        job_id,
        "select_printer",
        45,
        "Получение телеметрии парка и выбор принтера.",
    )

    printer_result = await mcp.call_tool(
        "get_fleet_telemetry",
        {},
    )
    selected_printer_id = _extract_printer_id(
        printer_result,
        options.get("printer_id"),
    )

    if options.get("start_print") and not selected_printer_id:
        raise MCPClientError(
            "Нет доступных принтеров для запуска печати."
        )

    if selected_printer_id and isinstance(printer_result, list):
        printer_result = next(
            (
                printer
                for printer in printer_result
                if isinstance(printer, dict)
                and str(printer.get("printer_id") or printer.get("id"))
                == selected_printer_id
            ),
            {"printer_id": selected_printer_id},
        )

    _finish_step(
        job_id,
        "select_printer",
        55,
        printer_result if isinstance(printer_result, dict) else {},
    )

    OUTPUT_STORAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    expected_gcode_path = (
        OUTPUT_STORAGE_DIR / f"{job_id}.gcode"
    )

    _start_step(
        job_id,
        "slice_model",
        60,
        "Генерация G-code.",
    )

    slicing_result = await mcp.call_tool(
        "generate_gcode",
        {
            "file_path": str(model_path),
            "material": recommendation["material"],
            "layer_height": float(recommendation["parameters"].get("layer_height", 0.2)),
        },
    )

    if isinstance(slicing_result, dict) and (
        slicing_result.get("status") == "error"
        or slicing_result.get("error")
    ):
        raise MCPClientError(
            str(slicing_result.get("message") or slicing_result.get("error"))
        )

    source_gcode_path = _extract_gcode_path(
        slicing_result,
        expected_gcode_path,
    )
    gcode_path = expected_gcode_path
    if source_gcode_path.resolve() != expected_gcode_path.resolve():
        if not source_gcode_path.is_file():
            raise FileNotFoundError(
                f"MCP generated G-code was not found: {source_gcode_path}"
            )
        shutil.copy2(source_gcode_path, expected_gcode_path)

    _finish_step(
        job_id,
        "slice_model",
        80,
        {
            "gcode_path": str(gcode_path),
            "slicing": slicing_result,
        },
    )

    print_result: Any = {
        "started": False,
        "printer_id": selected_printer_id,
    }

    if options.get("start_print") is True:
        _start_step(
            job_id,
            "start_print",
            85,
            "Отправка задания на принтер.",
        )

        print_result = await mcp.call_tool(
            "control_printer",
            {
                "job_id": job_id,
                "printer_id": selected_printer_id,
                "action": "start",
                "gcode_path": str(gcode_path),
            },
        )
        if isinstance(print_result, dict) and print_result.get("error"):
            raise MCPClientError(str(print_result["error"]))

        _finish_step(
            job_id,
            "start_print",
            95,
            print_result,
        )

    artifact_directory = OUTPUT_STORAGE_DIR.parent / "results" / job_id
    artifact_paths = create_submission_bundle(
        model_path=model_path,
        gcode_path=gcode_path,
        destination=artifact_directory,
        job={
            **job,
            "status": "succeeded",
            "result": {
                "recommendation": recommendation,
                "geometry": geometry_result,
            },
        },
        plan=plan,
    )

    result = {
        "geometry": geometry_result,
        "recommendation": recommendation,
        "plan": plan,
        "printer": printer_result,
        "gcode_path": str(gcode_path),
        "project_3mf_path": artifact_paths["project_3mf"],
        "artifacts_directory": artifact_paths["directory"],
        "artifact_bundle_path": artifact_paths["bundle"],
        "print": print_result,
    }

    store.update_job(
        job_id,
        status="succeeded",
        current_step="completed",
        progress=100,
        result=result,
    )

    store.add_event(
        job_id,
        "job_succeeded",
        status="succeeded",
        step="completed",
        progress=100,
        message="Задача успешно завершена.",
        payload=result,
    )

    return result


@celery_app.task(
    bind=True,
    name="orchestrator.process_job",
)
def process_job(
    self,
    job_id: str,
) -> dict[str, Any]:
    store.update_job(
        job_id,
        status="running",
        celery_task_id=self.request.id,
    )

    store.add_event(
        job_id,
        "job_started",
        status="running",
        progress=0,
        message="Задача запущена в Celery.",
    )

    try:
        return asyncio.run(_run_pipeline(job_id))

    except JobCancelledError:
        return {
            "job_id": job_id,
            "status": "cancelled",
        }

    except Exception as exc:
        error_message = str(exc)

        store.update_job(
            job_id,
            status="failed",
            current_step="failed",
            error=error_message,
        )

        store.add_event(
            job_id,
            "job_failed",
            status="failed",
            step="failed",
            message=error_message,
        )

        raise


def create_job(
    *,
    filename: str,
    model_path: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = _utc_now()

    job = {
        "job_id": job_id,
        "task_id": "",
        "celery_task_id": "",
        "filename": filename,
        "model_path": model_path,
        "status": "created",
        "current_step": "",
        "progress": 0,
        "options": options,
        "result": {},
        "error": "",
        "created_at": now,
        "updated_at": now,
    }

    store.create_job(job)

    async_result = process_job.delay(job_id)

    store.update_job(
        job_id,
        task_id=async_result.id,
        celery_task_id=async_result.id,
        status="queued",
    )

    store.add_event(
        job_id,
        "job_queued",
        status="queued",
        progress=0,
        message="Задача добавлена в очередь.",
    )

    return store.get_job(job_id)
