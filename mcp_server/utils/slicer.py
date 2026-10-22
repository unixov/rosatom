import subprocess
import os
from typing import Dict, Any

def generate_gcode(stl_path: str, params: Dict[str, Any], output_gcode: str) -> Dict[str, Any]:
    if not os.path.exists(stl_path):
        return {"success": False, "error": "STL file not found"}
    
    try:
        subprocess.run(["prusa-slicer-console", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"success": False, "error": "PrusaSlicer CLI not found. Install PrusaSlicer and ensure it is in PATH."}

    cmd = [
        "prusa-slicer-console",
        "--input", stl_path,
        "--output", output_gcode,
        "--load", "default.ini",
        "--set", f"layer_height={params.get('layer_height', 0.2)}",
        "--set", f"infill_density={params.get('infill', 20)}",
        "--set", f"temperature_first_layer={params.get('temp_nozzle', 210)}",
        "--set", f"bed_temperature={params.get('temp_bed', 60)}"
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return {"success": True, "gcode_path": output_gcode, "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": e.stderr}
