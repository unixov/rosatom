"""Optional Qt UI loaded only inside STE Slicer."""

from __future__ import annotations

from typing import Any

try:
    from PyQt6.QtCore import QThread, pyqtSignal  # type: ignore
    from PyQt6.QtWidgets import (
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
    )
except ImportError:  # Cura 3.6 commonly embeds PyQt5
    from PyQt5.QtCore import QThread, pyqtSignal  # type: ignore
    from PyQt5.QtWidgets import (  # type: ignore
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
    )

from .plugin import OrchestratorClient, PluginSettings


class _ChatWorker(QThread):
    completed = pyqtSignal(object)

    def __init__(self, client: OrchestratorClient, message: str, job_id: str | None) -> None:
        super().__init__()
        self.client = client
        self.message = message
        self.job_id = job_id

    def run(self) -> None:
        try:
            self.completed.emit(self.client.chat(self.message, self.job_id))
        except Exception as exc:  # pragma: no cover - host/network path
            self.completed.emit({"message": f"Ошибка: {exc}", "actions": []})


class AssistantDialog(QDialog):
    def __init__(self, client: OrchestratorClient, scene_adapter: Any = None) -> None:
        super().__init__()
        self.client = client
        self.scene_adapter = scene_adapter
        self.settings = client.settings
        self.job_id: str | None = None
        self.current_plan: dict[str, Any] = {}
        self.last_request = ""
        self.worker: _ChatWorker | None = None
        self.setWindowTitle("ROSATOM AI Assistant · STE Slicer")
        self.resize(520, 640)

        root = QVBoxLayout(self)
        settings_form = QFormLayout()
        self.orchestrator_edit = QLineEdit(self.settings.orchestrator_url)
        settings_form.addRow("Orchestrator URL", self.orchestrator_edit)
        settings_form.addRow(
            "LLM configuration",
            QLabel("Настраивается на orchestrator через environment; ключ не хранится в плагине."),
        )
        self.scene_status_label = QLabel(self._scene_status_text())
        self.scene_status_label.setWordWrap(True)
        settings_form.addRow("Scene API", self.scene_status_label)
        root.addLayout(settings_form)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        root.addWidget(self.transcript)
        self.message_edit = QLineEdit()
        self.message_edit.setPlaceholderText("Например: напечатай две детали из PLA в режиме 3D")
        self.mode_box = QComboBox()
        self.mode_box.addItems(["3D", "5D"])
        self.material_box = QComboBox()
        self.material_box.addItems(["PLA", "ABS", "PA12-CF", "PEEK"])
        self.profile_box = QComboBox()
        self.profile_box.addItems(["standard", "high", "draft"])
        choices = QHBoxLayout()
        choices.addWidget(self.mode_box)
        choices.addWidget(self.material_box)
        choices.addWidget(self.profile_box)
        root.addLayout(choices)
        self.send_button = QPushButton("Отправить")
        self.send_button.clicked.connect(self._send)
        self.file_button = QPushButton("Выбрать модель")
        self.file_button.clicked.connect(self._upload)
        actions = QHBoxLayout()
        actions.addWidget(self.message_edit)
        actions.addWidget(self.send_button)
        actions.addWidget(self.file_button)
        root.addLayout(actions)
        self._append("assistant", "Готов. Опишите задачу печати или загрузите 3D-модель.")

    def _scene_status_text(self) -> str:
        if self.scene_adapter is None:
            return "Scene API не подключён: используется bridge workflow с выбором файла."
        try:
            status = self.scene_adapter.status()
        except Exception as exc:  # pragma: no cover - host-specific path
            return f"Scene API недоступен: {exc}"
        if status.get("available"):
            return "Scene API обнаружен; операции сцены требуют проверки на этой сборке."
        return "Scene API не обнаружен; используется bridge workflow с выбором файла."

    def _sync_settings(self) -> None:
        self.settings.orchestrator_url = self.orchestrator_edit.text().strip()

    def _append(self, role: str, text: str) -> None:
        self.transcript.append(f"<b>{role.upper()}</b>: {text}")

    def _send(self) -> None:
        message = self.message_edit.text().strip()
        if not message:
            return
        self._sync_settings()
        self.last_request = message
        self._append("user", message)
        self.message_edit.clear()
        self.send_button.setEnabled(False)
        self.worker = _ChatWorker(self.client, message, self.job_id)
        self.worker.completed.connect(self._received)
        self.worker.start()

    def _received(self, response: dict[str, Any]) -> None:
        self.send_button.setEnabled(True)
        self.job_id = response.get("job_id") or self.job_id
        self._append("assistant", str(response.get("message", "Нет ответа")))
        plan = response.get("plan")
        if plan:
            self.current_plan = plan
            self._append("plan", str(plan))

    def _upload(self) -> None:
        self._sync_settings()
        path, _ = QFileDialog.getOpenFileName(self, "Выберите модель", "", "Models (*.stl *.3mf *.obj)")
        if not path:
            return
        selected_plan = dict(self.current_plan)
        selected_plan["mode"] = self.mode_box.currentText()
        selected_plan["material"] = self.material_box.currentText()
        selected_plan["profile"] = self.profile_box.currentText()
        try:
            result = self.client.upload_model(
                path,
                material=selected_plan["material"],
                quality=selected_plan["profile"],
                plan=selected_plan,
                request=self.last_request or "Подготовь модель к печати.",
            )
            self.job_id = result.get("job_id")
            self._append("assistant", f"Модель {path} поставлена в очередь: {self.job_id}")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка загрузки", str(exc))
