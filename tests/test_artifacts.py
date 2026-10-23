from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from orchestrator.artifacts import (
    _read_mesh,
    create_project_3mf,
    write_chat_demo,
)


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "triangle.stl"


class ArtifactTests(unittest.TestCase):
    def test_ascii_stl_is_read(self) -> None:
        vertices, triangles = _read_mesh(FIXTURE)
        self.assertEqual(len(vertices), 3)
        self.assertEqual(triangles, [(0, 1, 2)])

    def test_invalid_mesh_fails_instead_of_using_fake_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.stl"
            invalid.write_text("not a mesh", encoding="utf-8")
            with self.assertRaises(ValueError):
                _read_mesh(invalid)

    def test_project_and_chat_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project.3mf"
            create_project_3mf(
                FIXTURE,
                project,
                job_id="demo",
                plan={
                    "mode": "3D",
                    "material": "PLA",
                    "orientation": {"x": 0, "y": 0, "z": 90},
                    "arrangement": {"copies": 2, "spacing_mm": 5},
                },
                recommendation={"material": "PLA", "quality": "standard"},
            )
            with zipfile.ZipFile(project) as archive:
                names = set(archive.namelist())
                self.assertIn("[Content_Types].xml", names)
                self.assertIn("3D/3dmodel.model", names)
                metadata = json.loads(archive.read("Metadata/rosatom-plan.json"))
                self.assertEqual(metadata["job_id"], "demo")

            chat = write_chat_demo(root, message="hello", response="world")
            self.assertEqual(chat.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
