from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field

from tasks import (
    MODEL_STORAGE_DIR,
    OUTPUT_STORAGE_DIR,
    JobNotFoundError,
    MCPClient,
    create_job,
    store,
)
from llm import create_print_plan


APP_NAME = os.getenv(
    "APP_NAME",
    "Rosatom MCP Orchestrator",
)
APP_VERSION = os.getenv(
    "APP_VERSION",
    "1.0.0",
)

MAX_UPLOAD_SIZE_MB = int(
    os.getenv("MAX_UPLOAD_SIZE_MB", "100")
)
MAX_UPLOAD_SIZE_BYTES = (
    MAX_UPLOAD_SIZE_MB * 1024 * 1024
)

EVENT_POLL_INTERVAL = float(
    os.getenv("EVENT_POLL_INTERVAL", "0.75")
)

ALLOWED_EXTENSIONS = {
    ".stl",
    ".3mf",
    ".obj",
}


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
)


cors_origins = os.getenv(
    "CORS_ORIGINS",
    "*",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        ["*"]
        if cors_origins == "*"
        else [
            origin.strip()
            for origin in cors_origins.split(",")
            if origin.strip()
        ]
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    job_id: str | None = None


class ChatResponse(BaseModel):
    message: str
    job_id: str | None = None
    actions: list[str] = Field(default_factory=list)
    plan: dict[str, Any] | None = None


def serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id", ""),
        "task_id": job.get("task_id", ""),
        "filename": job.get("filename", ""),
        "status": job.get("status", ""),
        "current_step": job.get("current_step", ""),
        "progress": int(job.get("progress", 0)),
        "options": job.get("options", {}),
        "result": job.get("result", {}),
        "error": job.get("error", ""),
        "created_at": job.get("created_at", ""),
        "updated_at": job.get("updated_at", ""),
    }


def get_existing_job(job_id: str) -> dict[str, Any]:
    try:
        return store.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found.",
        ) from exc


def parse_json_object(
    value: str,
    field_name: str,
) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must contain valid JSON.",
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a JSON object.",
        )

    return parsed


def is_inside_directory(
    candidate: Path,
    directory: Path,
) -> bool:
    try:
        candidate.resolve().relative_to(
            directory.resolve()
        )
        return True
    except ValueError:
        return False


@app.get("/health")
async def health() -> dict[str, str]:
    try:
        store.client.ping()
        redis_status = "ok"
    except Exception:
        redis_status = "unavailable"

    return {
        "status": "ok",
        "redis": redis_status,
    }


@app.post(
    "/api/v1/jobs",
    status_code=202,
)
async def upload_model(
    file: UploadFile = File(...),
    material: str | None = Form(default=None),
    printer_id: str | None = Form(default=None),
    quality: str = Form(default="standard"),
    start_print: bool = Form(default=False),
    parameters: str = Form(default="{}"),
    metadata: str = Form(default="{}"),
) -> dict[str, Any]:
    filename = file.filename or "model"
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))

        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported model format. "
                f"Allowed formats: {allowed}"
            ),
        )

    parsed_parameters = parse_json_object(
        parameters,
        "parameters",
    )
    parsed_metadata = parse_json_object(
        metadata,
        "metadata",
    )

    MODEL_STORAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        MODEL_STORAGE_DIR
        / f"upload-{os.urandom(8).hex()}{extension}"
    )

    total_size = 0

    try:
        with temporary_path.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Uploaded file is too large. "
                            f"Maximum size is "
                            f"{MAX_UPLOAD_SIZE_MB} MB."
                        ),
                    )

                output.write(chunk)

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    finally:
        await file.close()

    submitted_plan = parsed_metadata.get("plan")
    if not isinstance(submitted_plan, dict):
        submitted_plan = {}

    options = {
        "material": material,
        "printer_id": printer_id,
        "quality": quality,
        "start_print": start_print,
        "parameters": parsed_parameters,
        "metadata": parsed_metadata,
        "plan": submitted_plan,
    }

    try:
        job = create_job(
            filename=filename,
            model_path=str(temporary_path),
            options=options,
        )
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return serialize_job(job)


@app.get("/api/v1/jobs")
async def list_jobs(
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))

    return [
        serialize_job(job)
        for job in store.list_jobs(limit)
    ]


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    return serialize_job(
        get_existing_job(job_id)
    )


@app.get("/api/v1/jobs/{job_id}/events/history")
async def get_event_history(
    job_id: str,
    after_id: int = 0,
) -> list[dict[str, Any]]:
    get_existing_job(job_id)

    return store.get_events(
        job_id,
        after_id=max(after_id, 0),
    )


@app.get("/api/v1/jobs/{job_id}/events")
async def stream_job_events(
    job_id: str,
) -> StreamingResponse:
    get_existing_job(job_id)

    async def event_stream() -> AsyncIterator[str]:
        last_event_id = 0

        yield "retry: 1500\n\n"

        while True:
            try:
                events = store.get_events(
                    job_id,
                    after_id=last_event_id,
                )
            except JobNotFoundError:
                break

            for event in events:
                event_id = int(event["event_id"])
                last_event_id = event_id

                yield (
                    f"id: {event_id}\n"
                    f"event: {event['event_type']}\n"
                    "data: "
                    f"{json.dumps(event, ensure_ascii=True)}\n\n"
                )

            current_job = store.get_job(job_id)

            if current_job.get("status") in {
                "succeeded",
                "failed",
                "cancelled",
            }:
                break

            yield ": heartbeat\n\n"

            await asyncio.sleep(EVENT_POLL_INTERVAL)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
) -> dict[str, Any]:
    job = get_existing_job(job_id)

    if job["status"] in {
        "succeeded",
        "failed",
        "cancelled",
    }:
        return serialize_job(job)

    store.request_cancel(job_id)

    updated_job = store.update_job(
        job_id,
        status="cancelling",
        current_step="cancelling",
    )

    store.add_event(
        job_id,
        "job_cancelling",
        status="cancelling",
        step="cancelling",
        progress=int(updated_job.get("progress", 0)),
        message="Запрошена отмена задачи.",
    )

    return serialize_job(
        store.get_job(job_id)
    )


@app.get("/api/v1/printers")
async def get_printers() -> Any:
    try:
        return await MCPClient().get_printers()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


@app.get("/api/v1/jobs/{job_id}/model")
async def download_model(
    job_id: str,
) -> FileResponse:
    job = get_existing_job(job_id)
    model_path = Path(job["model_path"])

    if not model_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Model file not found.",
        )

    if not is_inside_directory(
        model_path,
        MODEL_STORAGE_DIR,
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid model path.",
        )

    return FileResponse(
        path=model_path,
        filename=job["filename"],
        media_type="application/octet-stream",
    )


@app.get("/api/v1/jobs/{job_id}/gcode")
async def download_gcode(
    job_id: str,
) -> FileResponse:
    job = get_existing_job(job_id)
    result = job.get("result", {})

    gcode_path_value = result.get("gcode_path")

    if not gcode_path_value:
        raise HTTPException(
            status_code=404,
            detail="G-code has not been generated yet.",
        )

    gcode_path = Path(gcode_path_value)

    if not gcode_path.exists():
        raise HTTPException(
            status_code=404,
            detail="G-code file not found.",
        )

    if not is_inside_directory(
        gcode_path,
        OUTPUT_STORAGE_DIR,
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid G-code path.",
        )

    return FileResponse(
        path=gcode_path,
        filename=f"{job_id}.gcode",
        media_type="text/plain",
    )


@app.get("/api/v1/jobs/{job_id}/project")
async def download_project(job_id: str) -> FileResponse:
    job = get_existing_job(job_id)
    project_path = Path(job.get("result", {}).get("project_3mf_path", ""))
    results_root = OUTPUT_STORAGE_DIR.parent / "results"
    if not project_path.is_file() or not is_inside_directory(project_path, results_root):
        raise HTTPException(status_code=404, detail="3MF project has not been generated yet.")
    return FileResponse(path=project_path, filename="project.3mf", media_type="application/vnd.ms-package.3dmanufacturing-3dmodel+xml")


@app.get("/api/v1/jobs/{job_id}/artifacts")
async def download_artifacts(job_id: str) -> FileResponse:
    job = get_existing_job(job_id)
    bundle_path = Path(job.get("result", {}).get("artifact_bundle_path", ""))
    results_root = OUTPUT_STORAGE_DIR.parent / "results"
    if not bundle_path.is_file() or not is_inside_directory(bundle_path, results_root):
        raise HTTPException(status_code=404, detail="Submission artifacts have not been generated yet.")
    return FileResponse(path=bundle_path, filename=f"rosatom-{job_id}.zip", media_type="application/zip")


@app.post(
    "/api/v1/chat",
    response_model=ChatResponse,
)
async def chat(
    request: ChatRequest,
) -> ChatResponse:
    message = request.message.strip().lower()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    if request.job_id:
        job = get_existing_job(request.job_id)

        try:
            plan = await create_print_plan(
                request.message,
                {
                    "job_id": request.job_id,
                    "filename": job.get("filename"),
                    "geometry": job.get("result", {}).get("geometry", {}),
                    "current_options": job.get("options", {}),
                },
            )
        except Exception as exc:
            plan = None
            plan_error = f" Планировщик LLM недоступен: {exc}."
        else:
            plan_error = ""

        if any(
            word in message
            for word in ("статус", "status", "прогресс")
        ):
            return ChatResponse(
                message=(
                    f"Задача {request.job_id}: "
                    f"{job['status']}, прогресс "
                    f"{job['progress']}%."
                    f"{plan_error}"
                ),
                job_id=request.job_id,
                actions=["refresh_job"],
                plan=plan,
            )

    try:
        plan = await create_print_plan(request.message, {"job_id": request.job_id})
    except Exception as exc:
        plan = None
        plan_error = f" Планировщик LLM недоступен: {exc}."
    else:
        plan_error = ""

    if plan and any(word in message for word in ("режим", "материал", "профил", "ориент", "размест", "5d", "3d")):
        return ChatResponse(
            message=(
                f"План печати: режим {plan['mode']}, материал {plan.get('material', 'auto')}, "
                f"профиль {plan.get('profile', 'auto')}. {plan.get('reasoning', '')}"
                f"{plan_error}"
            ),
            job_id=request.job_id,
            actions=["refresh_job"],
            plan=plan,
        )

    if any(
        word in message
        for word in ("принтер", "printer", "флот")
    ):
        return ChatResponse(
            message=(
                "Для получения актуального состояния принтеров "
                "используйте FleetDashboard."
            ),
            job_id=request.job_id,
            actions=["load_printers"],
        )

    return ChatResponse(
        message=(
            "Загрузите STL, 3MF или OBJ-файл. "
            "После загрузки система проанализирует геометрию, "
            "подберет параметры, выберет принтер и сгенерирует G-code."
            f"{plan_error}"
        ),
        job_id=request.job_id,
        actions=["upload_model"],
        plan=plan,
    )


@app.on_event("shutdown")
def shutdown_event() -> None:
    try:
        store.client.close()
    except Exception:
        pass
