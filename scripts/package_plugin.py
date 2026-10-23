#!/usr/bin/env python3
"""Build a distributable ROSATOM STE Slicer/Cura plugin archive.

The package intentionally contains source and metadata only. Runtime LLM secrets
are configured in the orchestrator environment and are never copied here.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = ROOT / "ste_slicer_plugin"
DEFAULT_OUTPUT = ROOT / "dist" / "rosatom-ste-slicer-plugin.zip"

INCLUDED_FILES = ("__init__.py", "plugin.py", "ui.py", "plugin.json")


def build_archive(output: Path) -> Path:
    missing = [name for name in INCLUDED_FILES if not (PLUGIN_SOURCE / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Plugin source is incomplete; missing: {', '.join(missing)}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in INCLUDED_FILES:
            archive.write(PLUGIN_SOURCE / name, f"RosatomAssistant/{name}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination ZIP path (default: dist/rosatom-ste-slicer-plugin.zip)",
    )
    args = parser.parse_args()
    archive = build_archive(args.output)
    print(f"Created {archive.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
