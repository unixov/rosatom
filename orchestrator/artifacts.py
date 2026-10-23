"""Submission artifact generation for STE Slicer demonstrations."""

from __future__ import annotations

import binascii
import html
import json
import shutil
import struct
import zlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


Mesh = tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]


def _parse_binary_stl(data: bytes) -> Mesh:
    if len(data) < 84:
        raise ValueError("STL payload is too small")
    count = struct.unpack_from("<I", data, 80)[0]
    if count <= 0 or 84 + count * 50 > len(data):
        raise ValueError("Invalid binary STL triangle count")
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for index in range(count):
        offset = 84 + index * 50 + 12
        points = [
            struct.unpack_from("<fff", data, offset + 12 * item)
            for item in range(3)
        ]
        base = len(vertices)
        vertices.extend(points)
        triangles.append((base, base + 1, base + 2))
    return vertices, triangles


def _parse_ascii_stl(data: bytes) -> Mesh:
    text = data.decode("utf-8", errors="ignore")
    import re

    points = [
        (float(x), float(y), float(z))
        for x, y, z in re.findall(
            r"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",
            text,
            flags=re.IGNORECASE,
        )
    ]
    if not points or len(points) % 3:
        raise ValueError("Invalid ASCII STL vertices")
    return points, [
        (index, index + 1, index + 2)
        for index in range(0, len(points), 3)
    ]


def _parse_obj(data: bytes) -> Mesh:
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for line in data.decode("utf-8", errors="ignore").splitlines():
        values = line.strip().split()
        if not values or values[0].startswith("#"):
            continue
        if values[0] == "v" and len(values) >= 4:
            vertices.append((float(values[1]), float(values[2]), float(values[3])))
        elif values[0] == "f" and len(values) >= 4:
            indices = [int(item.split("/")[0]) for item in values[1:]]
            indices = [
                value - 1 if value > 0 else len(vertices) + value
                for value in indices
            ]
            for index in range(1, len(indices) - 1):
                triangles.append((indices[0], indices[index], indices[index + 1]))
    if not vertices or not triangles:
        raise ValueError("OBJ does not contain a mesh")
    return vertices, triangles


def _read_mesh(source: Path) -> Mesh:
    data = source.read_bytes()
    if source.suffix.lower() == ".obj":
        return _parse_obj(data)
    try:
        return _parse_binary_stl(data)
    except (ValueError, struct.error):
        return _parse_ascii_stl(data)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _transform_mesh(
    mesh: Mesh,
    *,
    orientation: dict[str, Any],
    copies: int,
    spacing_mm: float,
) -> Mesh:
    """Apply the confirmed plan to the exported demonstration mesh."""
    vertices, triangles = mesh
    rx = _number(orientation.get("x"))
    ry = _number(orientation.get("y"))
    rz = _number(orientation.get("z"))
    import math

    def rotate(point: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = point
        for angle, axis in ((rx, "x"), (ry, "y"), (rz, "z")):
            radians = math.radians(angle)
            cosine, sine = math.cos(radians), math.sin(radians)
            if axis == "x":
                y, z = y * cosine - z * sine, y * sine + z * cosine
            elif axis == "y":
                x, z = x * cosine + z * sine, -x * sine + z * cosine
            else:
                x, y = x * cosine - y * sine, x * sine + y * cosine
        return x, y, z

    count = max(1, min(copies, 100))
    spacing = max(0.0, spacing_mm)
    transformed: list[tuple[float, float, float]] = []
    transformed_triangles: list[tuple[int, int, int]] = []
    for copy_index in range(count):
        offset = len(transformed)
        dx = copy_index * spacing
        transformed.extend(
            (x + dx, y, z)
            for x, y, z in (rotate(vertex) for vertex in vertices)
        )
        transformed_triangles.extend(
            (a + offset, b + offset, c + offset)
            for a, b, c in triangles
        )
    return transformed, transformed_triangles


def _mesh_to_3mf_model(
    mesh: Mesh,
    display_name: str,
) -> str:
    vertices, triangles = mesh
    vertex_xml = "".join(
        f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}" />'
        for x, y, z in vertices
    )
    triangle_xml = "".join(
        f'<triangle v1="{a}" v2="{b}" v3="{c}" />'
        for a, b, c in triangles
    )
    safe_name = html.escape(display_name, quote=True)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">'
        f'<metadata name="Title">{safe_name}</metadata>'
        '<resources><object id="1" type="model"><mesh><vertices>'
        f'{vertex_xml}</vertices><triangles>{triangle_xml}</triangles>'
        '</mesh></object></resources><build><item objectid="1" />'
        '</build></model>'
    )


def _stl_to_3mf_model(
    source: Path,
    display_name: str,
    *,
    plan: dict[str, Any],
) -> str:
    # Do not silently replace invalid input with synthetic geometry. A generated
    # project must always represent the uploaded model.
    mesh = _read_mesh(source)
    orientation = plan.get("orientation", {})
    arrangement = plan.get("arrangement", {})
    transformed = _transform_mesh(
        mesh,
        orientation=orientation if isinstance(orientation, dict) else {},
        copies=max(1, _int(arrangement.get("copies", 1))),
        spacing_mm=max(0.0, _number(arrangement.get("spacing_mm", 5), 5)),
    )
    return _mesh_to_3mf_model(transformed, display_name)


def _write_3mf_archive(
    destination: Path,
    model_xml: str,
    metadata: dict[str, Any],
) -> None:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="json" ContentType="application/json"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model_xml)
        archive.writestr(
            "Metadata/rosatom-plan.json",
            json.dumps(metadata, ensure_ascii=False, indent=2),
        )


def create_project_3mf(
    model_path: Path,
    destination: Path,
    *,
    job_id: str,
    plan: dict[str, Any],
    recommendation: dict[str, Any],
) -> Path:
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file does not exist: {model_path}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    metadata = {
        "job_id": job_id,
        "source_file": model_path.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": plan.get("mode", "3D"),
        "material": recommendation.get("material", plan.get("material", "PLA")),
        "profile": plan.get("profile", recommendation.get("quality", "standard")),
        "orientation": plan.get("orientation", {"x": 0, "y": 0, "z": 0}),
        "arrangement": plan.get("arrangement", {"copies": 1, "spacing_mm": 5}),
        "reasoning": plan.get("reasoning", "План сформирован оркестратором."),
    }

    if model_path.suffix.lower() == ".3mf":
        # Preserve the slicer's native project. The selected plan is recorded in
        # manifest.json and cannot be claimed to have been injected into an
        # arbitrary vendor-specific 3MF package.
        try:
            with zipfile.ZipFile(model_path) as archive:
                if "[Content_Types].xml" not in archive.namelist():
                    raise ValueError("3MF package has no [Content_Types].xml")
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValueError("Uploaded 3MF is not a valid ZIP package") from exc
        shutil.copy2(model_path, destination)
        return destination

    model_xml = _stl_to_3mf_model(model_path, model_path.name, plan=plan)
    _write_3mf_archive(destination, model_xml, metadata)
    return destination


def write_submission_manifest(
    directory: Path,
    *,
    job: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "project": "ROSATOM AI Assistant for STE Slicer",
        "job_id": job.get("job_id"),
        "filename": job.get("filename"),
        "status": job.get("status"),
        "artifacts": {
            "project_3mf": "project.3mf",
            "result_gcode": "result.gcode",
            "chat_screenshot": "chat.png",
        },
        "plan": plan or {},
        "result": job.get("result", {}),
    }
    path = directory / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# Minimal 5x7 glyphs keep the screenshot dependency-free and valid in Docker.
_FONT = {
    "A": "01110 10001 10001 11111 10001 10001 10001",
    "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01111 10000 10000 10000 10000 10000 01111",
    "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01111 10000 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "11111 00100 00100 00100 00100 00100 11111",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 11011 10001",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11110 00001 00001 01110 00001 00001 11110",
    "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 10000 11110 00001 00001 11110",
    "6": "01110 10000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00001 01110",
    ":": "00000 00100 00100 00000 00100 00100 00000",
    ".": "00000 00000 00000 00000 00000 00110 00110",
    "-": "00000 00000 00000 11111 00000 00000 00000",
    "/": "00001 00010 00100 01000 10000 00000 00000",
    "?": "01110 10001 00001 00010 00100 00000 00100",
}


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def _write_chat_png(path: Path, message: str, response: str) -> None:
    width, height = 1200, 700
    pixels = bytearray([8, 13, 24] * width * height)

    def rect(x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        for row in range(max(0, y), min(height, y + h)):
            start = (row * width + max(0, x)) * 3
            end = (row * width + min(width, x + w)) * 3
            pixels[start:end] = bytes(color) * ((end - start) // 3)

    def text(value: str, x: int, y: int, color: tuple[int, int, int], scale: int = 3) -> None:
        cursor = x
        for char in value.upper():
            glyph = _FONT.get(char, _FONT["?"]).split()
            for gy, line in enumerate(glyph):
                for gx, bit in enumerate(line):
                    if bit == "1":
                        rect(cursor + gx * scale, y + gy * scale, scale, scale, color)
            cursor += 6 * scale

    def wrapped(value: str, max_chars: int = 68) -> list[str]:
        safe = "".join(char if ord(char) < 128 else "?" for char in value)
        words, lines, current = safe.split(), [], ""
        for word in words:
            if len(current) + len(word) + 1 > max_chars and current:
                lines.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        if current:
            lines.append(current)
        return lines or [""]

    rect(40, 35, 1120, 90, (18, 35, 57))
    text("ROSATOM AI ASSISTANT / STE SLICER", 70, 65, (72, 217, 236), 3)
    rect(40, 160, 1120, 190, (23, 31, 48))
    text("USER", 70, 185, (116, 170, 255), 3)
    for index, line in enumerate(wrapped(message)):
        text(line, 70, 225 + index * 28, (232, 237, 246), 2)
    rect(40, 380, 1120, 255, (19, 48, 43))
    text("ASSISTANT", 70, 405, (85, 215, 160), 3)
    for index, line in enumerate(wrapped(response)):
        text(line, 70, 445 + index * 28, (232, 237, 246), 2)

    raw = b"".join(b"\x00" + bytes(pixels[row * width * 3:(row + 1) * width * 3]) for row in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(raw, 9))
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def write_chat_demo(directory: Path, *, message: str, response: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "chat.png"
    _write_chat_png(path, message, response)
    return path


def create_submission_bundle(
    *,
    model_path: Path,
    gcode_path: Path,
    destination: Path,
    job: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Create the directory required by the challenge and a distributable ZIP."""
    destination.mkdir(parents=True, exist_ok=True)
    if not gcode_path.is_file():
        raise FileNotFoundError(f"Generated G-code does not exist: {gcode_path}")
    project_path = destination / "project.3mf"
    create_project_3mf(
        model_path,
        project_path,
        job_id=str(job.get("job_id", "")),
        plan=plan or {},
        recommendation=job.get("result", {}).get("recommendation", {}),
    )
    result_path = destination / "result.gcode"
    shutil.copy2(gcode_path, result_path)
    recommendation = job.get("result", {}).get("recommendation", {})
    response = (
        "План подтверждён: режим "
        f"{(plan or {}).get('mode', '3D')}, материал "
        f"{(plan or {}).get('material', recommendation.get('material', 'PLA'))}. "
        f"{(plan or {}).get('reasoning', 'Геометрия проанализирована MCP, G-code сформирован.')}"
    )
    write_chat_demo(
        destination,
        message="Подготовь модель к печати и объясни выбранные настройки.",
        response=response,
    )
    write_submission_manifest(destination, job=job, plan=plan)
    bundle_path = destination.with_suffix(".zip")
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(destination))
    return {
        "directory": str(destination),
        "project_3mf": str(project_path),
        "result_gcode": str(result_path),
        "bundle": str(bundle_path),
    }
