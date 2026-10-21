import os
import subprocess
import trimesh
import numpy as np
import pyvista as pv


class MeshAnalyzer:
    """Модуль анализа 3D-модели (STL/OBJ/STEP) с использованием trimesh."""

    # Плотности материалов в г/см³
    MATERIAL_DENSITIES = {
        "PLA": 1.24,
        "ABS": 1.04,
        "PA12-CF": 1.15,
        "PEEK": 1.30
    }

    def __init__(self, file_path: str):
        self.mesh = trimesh.load(file_path)
        if isinstance(self.mesh, trimesh.Scene):
            # Конвертируем Scene в единый Mesh, если модель состоит из нескольких тел
            self.mesh = trimesh.util.concatenate(
                [g for g in self.mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
            )
        if not isinstance(self.mesh, trimesh.Trimesh):
            raise ValueError("Не удалось загрузить меш как единый trimesh.Trimesh объект.")

    def get_bounding_box(self) -> dict:
        """Возвращает габариты (extents) и границы (bounds) в мм."""
        return {
            "extents_mm": self.mesh.extents.tolist(),
            "min_bounds": self.mesh.bounds[0].tolist(),
            "max_bounds": self.mesh.bounds[1].tolist()
        }

    def get_volume_and_mass(self, material: str = "PLA") -> dict:
        """Рассчитывает объем (мм³) и массу (граммы) для заданного материала."""
        volume_mm3 = self.mesh.volume
        volume_cm3 = volume_mm3 / 1000.0
        density = self.MATERIAL_DENSITIES.get(material.upper(), 1.24)
        mass_g = volume_cm3 * density

        return {
            "volume_mm3": float(volume_mm3),
            "volume_cm3": float(volume_cm3),
            "mass_g": float(mass_g),
            "material": material.upper()
        }

    def get_first_layer_area(self, z_tolerance: float = 0.2) -> float:
        """Вычисляет площадь первого слоя (сечение на минимальной высоте + допуск)."""
        z_min = self.mesh.bounds[0][2]
        slice_plane = self.mesh.section(
            plane_origin=[0, 0, z_min + z_tolerance],
            plane_normal=[0, 0, 1]
        )
        if slice_plane is None:
            return 0.0

        # Исправлено: в trimesh метод называется to_2D() с большой буквой D
        path_2d, _ = slice_plane.to_2D()
        return float(path_2d.area)

    def get_overhang_analysis(self, threshold_angle: float = 45.0) -> dict:
        """
        Анализирует углы нависания относительно вертикали (Z).
        threshold_angle: критический угол без поддержки (обычно 45°).
        """
        normals = self.mesh.face_normals
        # Скалярное произведение нормали грани на вектор вертикали вниз [0, 0, -1]
        dot_products = -normals[:, 2]

        # Угол между нормалью и вертикалью вниз
        angles_rad = np.arccos(np.clip(dot_products, -1.0, 1.0))
        angles_deg = np.degrees(angles_rad)

        # Исправлено: добавлен минус перед threshold_angle
        critical_mask = (dot_products > 0) & (angles_deg > (90 - threshold_angle))

        critical_area = np.sum(self.mesh.area_faces[critical_mask])
        total_area = self.mesh.area

        return {
            "max_overhang_angle_deg": float(np.max(angles_deg)),
            "critical_overhang_area_mm2": float(critical_area),
            "total_area_mm2": float(total_area),
            "overhang_ratio": float(critical_area / total_area if total_area > 0 else 0.0)
        }


class MeshRenderer:
    """Генерация высококачественных PNG-превью из 3D-моделей в headless-режиме."""

    def __init__(self, file_path: str):
        # Включаем строгий headless-режим pyvista
        pv.OFFSCREEN = True
        self.mesh = pv.read(file_path)

    def render_preview(self, output_png_path: str, resolution: tuple = (1024, 1024)) -> str:
        """Рендерит модель в PNG с освещением и возвращает путь к файлу."""
        plotter = pv.Plotter(off_screen=True, window_size=resolution)
        plotter.set_background("white")

        # Добавляем модель с красивым шейдингом
        plotter.add_mesh(
            self.mesh,
            color="#2b7cd3",
            specular=0.6,
            smooth_shading=True
        )

        # Настраиваем студийное освещение для качественного VLM-анализа
        plotter.add_light(pv.Light(position=(200, 200, 300), intensity=0.8, color='white'))
        plotter.add_light(pv.Light(position=(-200, -200, -100), intensity=0.4, color='lightblue'))

        # Устанавливаем камеру в изометрию и делаем скриншот
        plotter.camera_position = 'isometric'
        plotter.reset_camera()
        plotter.screenshot(output_png_path)
        plotter.close()

        return output_png_path


class SlicerManager:
    """Управление профилями печати и вызов CLI слайсера (PrusaSlicer)."""

    PRESETS = {
        "PLA": {"nozzle": 210, "bed": 60, "speed": 100, "cooling": 100},
        "ABS": {"nozzle": 245, "bed": 100, "speed": 80, "cooling": 0},
        "PA12-CF": {"nozzle": 280, "bed": 90, "speed": 50, "cooling": 0},
        "PEEK": {"nozzle": 400, "bed": 140, "speed": 30, "cooling": 0}
    }

    def __init__(self, cli_path: str = "prusa-slicer"):
        self.cli_path = cli_path

    def generate_ini(self, material: str, output_ini_path: str) -> str:
        mat = material.upper()
        if mat not in self.PRESETS:
            raise ValueError(f"Неизвестный материал: {material}. Доступны: {list(self.PRESETS.keys())}")

        cfg = self.PRESETS[mat]

        ini_content = f"""# PrusaSlicer Config for {mat} (Auto-generated)
temperature = {cfg["nozzle"]}
first_layer_temperature = {cfg["nozzle"]}
bed_temperature = {cfg["bed"]}
first_layer_bed_temperature = {cfg["bed"]}
perimeter_speed = {cfg["speed"]}
infill_speed = {cfg["speed"]}
bridge_fan_speed = {cfg["cooling"]}
max_fan_speed = {cfg["cooling"]}
min_fan_speed = {cfg["cooling"]}
filament_cost = 30
support_material = 0
"""
        os.makedirs(os.path.dirname(os.path.abspath(output_ini_path)), exist_ok=True)
        with open(output_ini_path, "w", encoding="utf-8") as f:
            f.write(ini_content)

        return output_ini_path

    def slice(self, stl_path: str, ini_path: str, output_gcode_path: str) -> str:
        """Запускает процесс нарезки через CLI слайсера."""
        cmd = [
            self.cli_path,
            "--export-gcode",
            "--load", ini_path,
            "--output", output_gcode_path,
            stl_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Ошибка слайсинга: {result.stderr}")

        return output_gcode_path


class PostProcessor5D:
    """Эмулятор 5D-постпроцессинга для многоосевой 3D-печати (A/B поворотный стол)."""

    def __init__(self, tilt_step_deg: float = 15.0):
        self.tilt_step_deg = tilt_step_deg

    def process_gcode(self, input_gcode_path: str, output_gcode_path: str) -> str:
        """
        Парсит стандартный G-code и добавляет кинематические команды осей A и B
        для динамического наклона платформы печати.
        """
        with open(input_gcode_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        processed_lines = []
        current_a = 0.0
        current_b = 0.0

        for line in lines:
            stripped = line.strip()

            # Внедряем корректировку углов поворота стола на определенных слоях / экструзиях
            if stripped.startswith("G1") or stripped.startswith("G0"):
                if "Z" in stripped and current_a == 0.0:
                    # Пример эмуляции: наклоняем стол на заданный угол при достижении высоты
                    current_a = self.tilt_step_deg
                    line = line.strip() + f" A{current_a:.2f} B{current_b:.2f}\n"

            processed_lines.append(line)

        os_dir = os.path.dirname(os.path.abspath(output_gcode_path))
        if os_dir:
            os.makedirs(os_dir, exist_ok=True)

        with open(output_gcode_path, 'w', encoding='utf-8') as f:
            f.writelines(processed_lines)

        return output_gcode_path


if __name__ == "__main__":
    model_file = "HH25_007.stl"

    # 1. Анализ геометрии
    analyzer = MeshAnalyzer(model_file)
    print("Габариты:", analyzer.get_bounding_box())
    print("Объем и масса (PA12-CF):", analyzer.get_volume_and_mass("PA12-CF"))
    print("Площадь 1-го слоя:", analyzer.get_first_layer_area())
    print("Анализ нависаний:", analyzer.get_overhang_analysis(threshold_angle=45))

    # 2. Рендеринг для VLM
    renderer = MeshRenderer(model_file)
    preview_path = renderer.render_preview("output_preview.png")
    print(f"Превью сохранено: {preview_path}")

    # 3. Настройка слайсера и генерация G-code
    slicer = SlicerManager()
    ini_path = slicer.generate_ini("PA12-CF", "configs/pa12_cf.ini")
    gcode_path = slicer.slice(model_file, ini_path, "output_standard.gcode")
    print(f"Базовый G-code сгенерирован: {gcode_path}")

    # 4. 5D постпроцессинг (без поддержек)
    post_processor = PostProcessor5D(tilt_step_deg=20.0)
    final_5d_gcode = post_processor.process_gcode("output_standard.gcode", "output_5d.gcode")
    print(f"Многоосевой 5D G-code готов: {final_5d_gcode}")
    