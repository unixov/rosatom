from typing import List, Dict, Any

PRINTERS = {
    "pr-001": {"model": "Prusa i3 MK3S", "status": "idle", "available": True},
    "pr-002": {"model": "Ultimaker S5", "status": "printing", "available": False},
    "pr-003": {"model": "Bambu Lab X1", "status": "idle", "available": True},
}

def get_printer_status(printer_id: str | None = None) -> List[Dict[str, Any]]:
    if printer_id:
        return [PRINTERS.get(printer_id, {})]
    return [{"id": k, **v} for k, v in PRINTERS.items()]

def send_to_printer(printer_id: str, gcode_path: str, priority: str = "normal") -> Dict[str, Any]:
    if printer_id not in PRINTERS or not PRINTERS[printer_id]["available"]:
        return {"success": False, "error": "Printer unavailable"}
    PRINTERS[printer_id]["status"] = "printing"
    PRINTERS[printer_id]["available"] = False
    return {
        "success": True,
        "printer_id": printer_id,
        "gcode_path": gcode_path,
        "priority": priority,
        "eta_minutes": 120
    }

def mark_job_complete(printer_id: str) -> Dict[str, Any]:
    if printer_id in PRINTERS:
        PRINTERS[printer_id]["status"] = "idle"
        PRINTERS[printer_id]["available"] = True
    return {"success": True, "printer_id": printer_id}
