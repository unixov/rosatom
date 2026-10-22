import os
import sys
from typing import Dict, Any, List
from fastmcp import FastMCP

# Подключение локальных утилит
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.geometry import GeometryAnalyzer # Из предыдущего модуля/файла
from utils.slicer import SlicerEngine
from utils.fleet import FleetManager

mcp = FastMCP(
    name="Rosatom-3D-5D-MCP-Engine",
    instructions="Сервер инженерных инструментов MCP для анализа STL моделей, слайсинга и управления 3D/5D принтерами."
)

# Инициализация сервисных движков
slicer_engine = SlicerEngine()
fleet_manager = FleetManager()

@mcp.tool()
def analyze_stl_geometry(file_path: str) -> Dict[str, Any]:
    """
    Выполняет полный геометрический анализ STL-файла.
    Рассчитывает габариты, объем, площадь, дефекты сетки и определяет необходимость 5D-печати.
    """
    if not os.path.exists(file_path):
        return {"error": f"File does not exist: {file_path}"}

    analyzer = GeometryAnalyzer(file_path)
    return analyzer.get_full_report()

@mcp.tool()
def generate_gcode(file_path: str, material: str = "PLA", layer_height: float = 0.2) -> Dict[str, Any]:
    """
    Генерирует G-код из STL-файла под выбранный инженерный материал (PLA, ABS, PA12-CF, PEEK).
    Возвращает путь к сгенерированному файлу и метрики расхода пластика и времени.
    """
    try:
        result = slicer_engine.slice(file_path, material, layer_height)
        return {"status": "success", **result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def get_fleet_telemetry() -> List[Dict[str, Any]]:
    """Возвращает текущий статус и телеметрию всех 3D/5D принтеров парка."""
    return fleet_manager.list_all_printers()

@mcp.tool()
def control_printer(printer_id: str, action: str, gcode_path: str = None) -> Dict[str, Any]:
    """
    Управляет принтером.
    Допустимые действия (action): 'start', 'pause', 'cancel', 'emergency_stop', 'status'.
    """
    if action == "status":
        return fleet_manager.get_printer_status(printer_id)
    return fleet_manager.send_command(printer_id, action, gcode_path)

if __name__ == "__main__":
    mcp.run(
        transport=os.getenv("MCP_TRANSPORT", "streamable-http"),
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8001")),
    )
