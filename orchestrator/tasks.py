from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import redis

from celery_app import celery_app
from rag import recommend_parameters


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "http://mcp_server:8000",
).rstrip("/")
MCP_TOOLS_PREFIX = os.getenv("MCP_TOOLS_PREFIX", "/tools").strip("/")
MCP_PRINTERS_PATH = os.getenv("MCP_PRINTERS_PATH", "/printers")
MCP_TIMEOUT_SECONDS = float(
    os.getenv("MCP_TIMEOUT_SECONDS", "180")
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
        self.timeout = MCP_TIMEOUT_SECONDS

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/"):
            path = f"/{path}"

        url = f"{self.base_url}{path}"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                response = await client.request(
                    method,
                    url,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise MCPClientError(
                f"MCP server is unavailable: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise MCPClientError(
                f"MCP request failed with HTTP "
                f"{response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise MCPClientError(
                "MCP server returned invalid JSON"
            ) from exc

        if isinstance(data, dict):
            if data.get("error"):
                raise MCPClientError(str(data["error"]))

            if "result" in data:
                return data["result"]

            if "data" in data:
                return data["data"]

        return data

    async def call_tool(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> Any:
        path = f"/{MCP_TOOLS_PREFIX}/{tool_name}"

        return await self._request(
            "POST",
            path,
            payload,
        )

    async def get_printers(self) -> Any:
        return await self._request(
            "GET",
            MCP_PRINTERS_PATH,
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
    if isinstance(result, dict):
        return (
            result.get("printer_id")
            or result.get("id")
            or requested_printer_id
        )

    return requested_printer_id


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

    _start_step(
        job_id,
        "analyze_geometry",
        10,
        "Анализ геометрии модели.",
    )

    geometry_result = await mcp.call_tool(
        "analyze_geometry",
        {
            "job_id": job_id,
            "model_path": str(model_path),
            "file_path": str(model_path),
            "filename": job["filename"],
        },
    )

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
        material=options.get("material"),
        quality=options.get("quality", "standard"),
        overrides=options.get("parameters", {}),
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
        "Выбор принтера.",
    )

    printer_result = await mcp.call_tool(
        "select_printer",
        {
            "job_id": job_id,
            "printer_id": options.get("printer_id"),
            "material": recommendation["material"],
            "parameters": recommendation["parameters"],
            "geometry": geometry,
        },
    )

    selected_printer_id = _extract_printer_id(
        printer_result,
        options.get("printer_id"),
    )

    _finish_step(
        job_id,
        "select_printer",
        55,
        printer_result,
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
        "slice_model",
        {
            "job_id": job_id,
            "model_path": str(model_path),
            "file_path": str(model_path),
            "output_path": str(expected_gcode_path),
            "printer_id": selected_printer_id,
            "material": recommendation["material"],
            "quality": recommendation["quality"],
            "parameters": recommendation["parameters"],
        },
    )

    gcode_path = _extract_gcode_path(
        slicing_result,
        expected_gcode_path,
    )

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
            "start_print",
            {
                "job_id": job_id,
                "printer_id": selected_printer_id,
                "gcode_path": str(gcode_path),
                "file_path": str(gcode_path),
            },
        )

        _finish_step(
            job_id,
            "start_print",
            95,
            print_result,
        )

    result = {
        "geometry": geometry_result,
        "recommendation": recommendation,
        "printer": printer_result,
        "gcode_path": str(gcode_path),
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
