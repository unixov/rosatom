import urllib.request
import json
from typing import Dict, Any, List

class FleetManager:
    def __init__(self):
        # Реестр принтеров Росатома
        self._fleet_db: Dict[str, Dict[str, Any]] = {
            "ROS-3D-01": {
                "ip": "192.168.1.101",
                "type": "FDM-3A",
                "status": "printing",
                "nozzle_temp": 240.5,
                "target_nozzle": 240.0,
                "bed_temp": 100.0,
                "target_bed": 100.0,
                "progress": 72.4,
                "current_file": "turbine_blade_v2.gcode"
            },
            "ROS-5D-02": {
                "ip": "192.168.1.102",
                "type": "5D-Axis-Kinematics",
                "status": "idle",
                "nozzle_temp": 22.1,
                "target_nozzle": 0.0,
                "bed_temp": 21.5,
                "target_bed": 0.0,
                "progress": 0.0,
                "current_file": None
            }
        }

    def get_printer_status(self, printer_id: str) -> Dict[str, Any]:
        """Запрашивает состояние конкретного принтера (Moonraker API / Mock)."""
        if printer_id not in self._fleet_db:
            return {"error": f"Printer '{printer_id}' is not registered in the fleet."}

        printer = self._fleet_db[printer_id]
        
        # Попытка реального запроса к Moonraker API
        try:
            url = f"http://{printer['ip']}/printer/objects/query?toolhead&extruder&heater_bed"
            req = urllib.request.Request(url, headers={'User-Agent': 'Rosatom-MCP/1.0'})
            with urllib.request.urlopen(req, timeout=1.0) as response:
                data = json.loads(response.read().decode())
                # Парсинг данных Moonraker
                status_res = data.get("result", {}).get("status", {})
                printer["nozzle_temp"] = status_res.get("extruder", {}).get("temperature", printer["nozzle_temp"])
                printer["bed_temp"] = status_res.get("heater_bed", {}).get("temperature", printer["bed_temp"])
        except Exception:
            # В случае недоступности IP используется актуальное состояние эмулятора
            pass

        return {"printer_id": printer_id, **printer}

    def list_all_printers(self) -> List[Dict[str, Any]]:
        """Возвращает список всех принтеров флота."""
        return [{"printer_id": pid, **data} for pid, data in self._fleet_db.items()]

    def send_command(self, printer_id: str, command: str, gcode_file: str = None) -> Dict[str, Any]:
        """Отправляет управляющую команду на принтер (start, pause, cancel, emergency_stop)."""
        if printer_id not in self._fleet_db:
            return {"error": f"Printer '{printer_id}' non-existent."}

        printer = self._fleet_db[printer_id]
        
        if command == "start":
            if not gcode_file:
                return {"error": "G-code file is required to start printing."}
            printer["status"] = "printing"
            printer["current_file"] = gcode_file
            printer["progress"] = 0.1
            return {"status": "success", "message": f"Started printing {gcode_file} on {printer_id}"}
            
        elif command == "pause":
            printer["status"] = "paused"
            return {"status": "success", "message": f"Print job paused on {printer_id}"}
            
        elif command == "cancel":
            printer["status"] = "idle"
            printer["progress"] = 0.0
            printer["current_file"] = None
            return {"status": "success", "message": f"Print job canceled on {printer_id}"}
            
        elif command == "emergency_stop":
            printer["status"] = "error"
            printer["target_nozzle"] = 0.0
            printer["target_bed"] = 0.0
            return {"status": "success", "message": f"EMERGENCY STOP EXECUTED ON {printer_id}"}

        return {"error": f"Unknown command '{command}'."}
    