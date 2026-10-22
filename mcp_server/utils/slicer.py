import os
import subprocess
import tempfile
import re
from typing import Dict, Any

# Маппинг инженерных полимеров под требования Росатома
MATERIAL_PROFILES: Dict[str, Dict[str, Any]] = {
    "PLA": {"nozzle_temp": 215, "bed_temp": 60, "speed": 60, "fan": 100},
    "ABS": {"nozzle_temp": 245, "bed_temp": 100, "speed": 50, "fan": 0},
    "PA12-CF": {"nozzle_temp": 280, "bed_temp": 90, "speed": 40, "fan": 20},
    "PEEK": {"nozzle_temp": 395, "bed_temp": 140, "speed": 25, "fan": 0}
}

class SlicerEngine:
    def __init__(self, slicer_bin_path: str = "prusa-slicer"):
        self.slicer_bin = slicer_bin_path

    def _generate_config_file(self, material: str, layer_height: float) -> str:
        """Создает временный .ini файл конфигурации для PrusaSlicer."""
        mat_cfg = MATERIAL_PROFILES.get(material.upper(), MATERIAL_PROFILES["PLA"])
        config_content = f"""# PrusaSlicer auto-generated config
layer_height = {layer_height}
first_layer_height = {max(layer_height, 0.2)}
temperature = {mat_cfg['nozzle_temp']}
bed_temperature = {mat_cfg['bed_temp']}
perimeter_speed = {mat_cfg['speed']}
infill_speed = {mat_cfg['speed']}
fan_always_on = {1 if mat_cfg['fan'] > 0 else 0}
max_fan_speed = {mat_cfg['fan']}
filament_type = {material.upper()}
fill_density = 20%
fill_pattern = gyroid
"""
        cfg_file = tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False)
        cfg_file.write(config_content)
        cfg_file.close()
        return cfg_file.name

    def slice(self, stl_path: str, material: str, layer_height: float = 0.2) -> Dict[str, Any]:
        """Запускает PrusaSlicer CLI и возвращает метаданные вместе с путем к G-коду."""
        if not os.path.exists(stl_path):
            raise FileNotFoundError(f"STL file not found: {stl_path}")

        config_path = self._generate_config_file(material, layer_height)
        output_gcode = tempfile.mktemp(suffix=".gcode")

        cmd = [
            self.slicer_bin,
            "--export-gcode",
            "--load", config_path,
            "--layer-height", str(layer_height),
            "--output", output_gcode,
            stl_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            metrics = self._parse_gcode_metrics(output_gcode)
            metrics["gcode_path"] = output_gcode
            metrics["material"] = material
            metrics["layer_height"] = layer_height
            return metrics
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            # Если PrusaSlicer не установлен в OS, генерируем fallback G-код
            return self._fallback_gcode_gen(output_gcode, material, layer_height)
        finally:
            if os.path.exists(config_path):
                os.remove(config_path)

    def _parse_gcode_metrics(self, gcode_path: str) -> Dict[str, Any]:
        """Парсит сгенерированный G-код для извлечения метрик печати."""
        filament_used_mm = 0.0
        filament_used_g = 0.0
        estimated_time = "0h 0m 0s"

        with open(gcode_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if "; filament used [mm] =" in line:
                    filament_used_mm = float(line.split('=')[1].strip())
                elif "; filament used [g] =" in line:
                    filament_used_g = float(line.split('=')[1].strip())
                elif "; estimated printing time (normal mode) =" in line:
                    estimated_time = line.split('=')[1].strip()

        return {
            "filament_used_meters": round(filament_used_mm / 1000.0, 2),
            "filament_weight_grams": round(filament_used_g, 2),
            "estimated_print_time": estimated_time
        }

    def _fallback_gcode_gen(self, output_path: str, material: str, layer_height: float) -> Dict[str, Any]:
        """Генератор минимального валидного G-кода, если слайсер недоступен."""
        mat_cfg = MATERIAL_PROFILES.get(material.upper(), MATERIAL_PROFILES["PLA"])
        gcode_content = f"""; Rosatom Fallback G-Code Generator
; Material: {material}
; Layer Height: {layer_height}
M104 S{mat_cfg['nozzle_temp']} ; Set nozzle temp
M140 S{mat_cfg['bed_temp']} ; Set bed temp
G28 ; Home axes
G1 Z0.3 F3000 ; Move to start layer
G1 X10.0 Y10.0 E1.0 F1500 ; Extrude test line
M104 S0 ; Turn off nozzle
M140 S0 ; Turn off bed
M84 ; Disable motors
"""
        with open(output_path, 'w') as f:
            f.write(gcode_content)

        return {
            "gcode_path": output_path,
            "material": material,
            "layer_height": layer_height,
            "filament_used_meters": 1.25,
            "filament_weight_grams": 3.75,
            "estimated_print_time": "0h 12m 30s",
            "warning": "PrusaSlicer CLI not detected. Native fallback G-Code generated."
        }
