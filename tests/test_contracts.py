from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.llm import _parse_plan
from ste_slicer_plugin.plugin import OrchestratorClient, PluginSettings


class ContractTests(unittest.TestCase):
    def test_llm_plan_is_bounded(self) -> None:
        plan = _parse_plan(
            json.dumps(
                {
                    "mode": "invalid",
                    "orientation": {"x": 9999},
                    "arrangement": {"copies": 9999, "spacing_mm": -5},
                    "parameters": "unsafe",
                    "assumptions": "unsafe",
                }
            )
        )
        self.assertEqual(plan["mode"], "3D")
        self.assertEqual(plan["orientation"]["x"], 360.0)
        self.assertEqual(plan["arrangement"]["copies"], 100)
        self.assertEqual(plan["arrangement"]["spacing_mm"], 0.0)
        self.assertEqual(plan["parameters"], {})
        self.assertEqual(plan["assumptions"], [])

    @patch("ste_slicer_plugin.plugin.urllib.request.urlopen")
    def test_upload_contains_plan_metadata(self, urlopen) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"job_id":"demo"}'

        urlopen.return_value = Response()
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.stl"
            model.write_text("solid model\nendsolid model\n", encoding="utf-8")
            OrchestratorClient(PluginSettings("http://localhost:8000")).upload_model(
                str(model),
                material="PLA",
                quality="high",
                plan={"mode": "5D", "material": "PLA"},
                request="make two copies",
            )

        request = urlopen.call_args.args[0]
        body = request.data.decode("utf-8")
        self.assertIn('name="metadata"', body)
        self.assertIn('"mode": "5D"', body)
        self.assertIn("make two copies", body)


if __name__ == "__main__":
    unittest.main()
