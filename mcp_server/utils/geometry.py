import trimesh
from typing import Dict, Any

def analyze_stl(stl_path: str) -> Dict[str, Any]:
    if not stl_path or not isinstance(stl_path, str):
        raise ValueError("Invalid STL path")
    mesh = trimesh.load(stl_path)
    return {
        "volume_mm3": float(mesh.volume),
        "surface_area_mm2": float(mesh.area),
        "bbox": mesh.bounds.tolist(),
        "faces": int(len(mesh.faces)),
        "is_watertight": bool(mesh.is_watertight),
        "center_of_mass": mesh.center_mass.tolist()
    }
