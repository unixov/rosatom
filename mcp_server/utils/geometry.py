import os
import trimesh
import numpy as np
from typing import Dict, Any

class GeometryAnalyzer:
    """
    Инженерный модуль геометрического анализа 3D-моделей (STL)
    для выбора режима печати (3D vs 5D) и расчета физических характеристик.
    """
    def __init__(self, file_path: str):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"STL file not found: {file_path}")

        self.file_path = file_path
        self._mesh = self._load_and_validate_mesh()

    def _load_mesh(self) -> trimesh.Trimesh:
        """Загружает модель и корректно обрабатывает сцены со множеством тел."""
        loaded = trimesh.load(self.file_path)
        if isinstance(loaded, trimesh.Scene):
            # Объединяем сцену из нескольких тел в единый меш
            return loaded.dump(concatenate=True)
        return loaded

    def _load_and_validate_mesh(self) -> trimesh.Trimesh:
        try:
            return self._load_mesh()
        except Exception as e:
            raise ValueError(f"Failed to parse STL file: {str(e)}")

    def get_dimensions(self)  -> Dict[str, float]:
        """Рассчитывает габаритные размеры детали в миллиметрах (X, Y, Z)."""
        bounds = self._mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]
        dimensions = bounds[1] - bounds[0]
        return {
            "length_x_mm": round(float(dimensions[0]), 2),
            "width_y_mm": round(float(dimensions[1]), 2),
            "height_z_mm": round(float(dimensions[2]), 2)
        }

    def get_volume_and_area(self) -> Dict[str, float]:
        """Рассчитывает объем (см³) и площадь поверхности (см²)."""
        volume_mm3 = float(self._mesh.volume)
        area_mm2 = float(self._mesh.area)
        return {
            "volume_cm3": round(volume_mm3 / 1000.0, 2),
            "surface_area_cm2": round(area_mm2 / 100.0, 2)
        }

    def analyze_overhangs(self) -> Dict[str, Any]:
        """
        Анализирует углы нависания (overhangs) для выбора оптимального режима печати.
        Если нависания критические (> 15% площади), система рекомендует 5D-осевую печать.
        """
        normals = self._mesh.face_normals
        face_areas = self._mesh.area_faces
        total_area = float(np.sum(face_areas))

        if total_area == 0.0:
            return {"overhang_ratio_percent": 0.0, "recommended_mode": "Standard-3D"}

        # Проекция нормалей на ось Z: грани, смотрящие вниз (Z < -0.1)
        z_normals = normals[:, 2]
        overhang_mask = z_normals < -0.1
        overhang_area = float(np.sum(face_areas[overhang_mask]))

        overhang_ratio = overhang_area / total_area
        overhang_percent = round(overhang_ratio * 100.0, 1)

        # Инженерный критерий Росатома для 5D-печати
        recommended_mode = "5D-axis" if overhang_percent > 15.0 else "Standard-3D"

        return {
            "overhang_ratio_percent": overhang_percent,
            "recommended_mode": recommended_mode
        }

    def check_integrity(self) -> Dict[str, Any]:
        """Проверяет качество сетки и герметичность (watertight) детали."""
        return {
            "is_watertight": bool(self._mesh.is_watertight),
            "is_empty": bool(self._mesh.is_empty),
            "euler_number": int(self._mesh.euler_number)
        }

    def get_full_report(self) -> Dict[str, Any]:
        """Формирует сводный комплексный отчет для MCP-сервера и агента."""
        dims = self.get_dimensions()
        vol_area = self.get_volume_and_area()
        overhangs = self.analyze_overhangs()
        integrity = self.check_integrity()

        return {
            "file_name": os.path.basename(self.file_path),
            **dims,
            **vol_area,
            **overhangs,
            **integrity
        }
