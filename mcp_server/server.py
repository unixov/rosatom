from mcp.server import Server, Tool
from utils.geometry import analyze_stl
from utils.fleet import get_printer_status, send_to_printer, mark_job_complete
from utils.slicer import generate_gcode

def suggest_parameters(material: str, printer_model: str, analysis: dict | None = None) -> dict:
    profiles = {
        "PLA": {"layer_height": 0.2, "infill": 20, "temp_bed": 60, "temp_nozzle": 210},
        "PETG": {"layer_height": 0.2, "infill": 25, "temp_bed": 75, "temp_nozzle": 240},
        "ABS": {"layer_height": 0.25, "infill": 30, "temp_bed": 100, "temp_nozzle": 250}
    }
    base = profiles.get(material, profiles["PLA"])
    if analysis and analysis.get("volume_mm3", 0) < 1000:
        base["layer_height"] = 0.15
    return base

tools = [
    Tool(
        name="analyze_stl",
        description="Analyze STL file geometry and return volume, surface area, bounding box, etc.",
        arguments=[{"name": "stl_path", "type": "string"}],
        implementation=analyze_stl,
    ),
    Tool(
        name="suggest_parameters",
        description="Suggest print parameters based on material and printer type.",
        arguments=[
            {"name": "material", "type": "string"},
            {"name": "printer_model", "type": "string"},
            {"name": "analysis", "type": "object", "optional": True}
        ],
        implementation=suggest_parameters,
    ),
    Tool(
        name="generate_gcode",
        description="Generate G-code using PrusaSlicer CLI based on STL and parameters.",
        arguments=[
            {"name": "stl_path", "type": "string"},
            {"name": "params", "type": "object"},
            {"name": "output_gcode", "type": "string"}
        ],
        implementation=generate_gcode,
    ),
    Tool(
        name="get_printer_status",
        description="Get status of all printers or a specific printer.",
        arguments=[{"name": "printer_id", "type": "string", "optional": True}],
        implementation=get_printer_status,
    ),
    Tool(
        name="send_to_printer",
        description="Send G-code to a specific printer for printing.",
        arguments=[
            {"name": "printer_id", "type": "string"},
            {"name": "gcode_path", "type": "string"},
            {"name": "priority", "type": "string", "optional": True}
        ],
        implementation=send_to_printer,
    ),
    Tool(
        name="mark_job_complete",
        description="Mark a printer job as complete and set printer to idle.",
        arguments=[{"name": "printer_id", "type": "string"}],
        implementation=mark_job_complete,
    ),
]

if __name__ == "__main__":
    server = Server(name="rosatom-3d-mcp", tools=tools)
    server.serve()
