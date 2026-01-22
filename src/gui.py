"""Professional HVAC Robot Controller GUI using PyQt6."""
# pylint: disable=no-name-in-module,too-many-lines
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QFileDialog,
    QMessageBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QTextEdit,
    QProgressBar,
    QComboBox,
)

from .bravida_client import BravidaClient
from .bulk_reader import BulkPointReader
from .hvac_ai_analyzer import HVACAIAnalyzer
from .logging_utils import setup_logger


class WorkerThread(QThread):
    """Worker thread for running Bravida operations without blocking GUI."""

    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, operation, client_args, point, value=None, dry_run=False):
        super().__init__()
        self.operation = operation
        self.client_args = client_args
        self.point = point
        self.value = value
        self.dry_run = dry_run

    def run(self) -> None:
        """Execute the Bravida operation in the worker thread."""
        try:
            with BravidaClient(**self.client_args) as client:
                if self.operation == "force":
                    result = client.force_point(
                        self.point, self.value, dry_run=self.dry_run
                    )
                elif self.operation == "unforce":
                    result = client.unforce_point(self.point)
                elif self.operation == "read":
                    result = client.read_point(self.point)
                else:
                    raise ValueError(f"Unknown operation: {self.operation}")

                self.result.emit(
                    {
                        "operation": self.operation,
                        "point": result.point,
                        "value": result.value,
                        "success": result.success,
                        "message": result.message,
                        "updated_value": result.updated_value,
                        "screenshot": result.screenshot_path,
                    }
                )
        except (RuntimeError, ValueError) as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class PointControlWidget(QWidget):
    """Widget for controlling a single HVAC point."""

    def __init__(self, client_args):
        super().__init__()
        self.client_args = client_args
        self.worker_thread: Optional[WorkerThread] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()

        # Point name
        point_layout = QHBoxLayout()
        point_layout.addWidget(QLabel("Point Name:"))
        self.point_input = QLineEdit()
        self.point_input.setPlaceholderText("e.g., 360.005-JV40_Pos")
        point_layout.addWidget(self.point_input)
        layout.addLayout(point_layout)

        # Force value
        force_layout = QHBoxLayout()
        force_layout.addWidget(QLabel("Force Value:"))
        self.force_value_input = QLineEdit()
        self.force_value_input.setPlaceholderText("Enter numeric value")
        force_layout.addWidget(self.force_value_input)
        layout.addLayout(force_layout)

        # Dry run checkbox
        self.dry_run_checkbox = QCheckBox(
            "Dry Run (preview without clicking OK)"
        )
        layout.addWidget(self.dry_run_checkbox)

        # Buttons
        button_layout = QHBoxLayout()
        self.force_button = QPushButton("Force Point")
        self.force_button.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 8px;"
        )
        self.force_button.clicked.connect(self._on_force_clicked)
        button_layout.addWidget(self.force_button)

        self.unforce_button = QPushButton("Unforce Point")
        self.unforce_button.setStyleSheet(
            "background-color: #FF9800; color: white; padding: 8px;"
        )
        self.unforce_button.clicked.connect(self._on_unforce_clicked)
        button_layout.addWidget(self.unforce_button)

        self.read_button = QPushButton("Read Value")
        self.read_button.setStyleSheet(
            "background-color: #2196F3; color: white; padding: 8px;"
        )
        self.read_button.clicked.connect(self._on_read_clicked)
        button_layout.addWidget(self.read_button)

        layout.addLayout(button_layout)

        # Status display
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def _on_force_clicked(self) -> None:
        point = self.point_input.text().strip()
        value = self.force_value_input.text().strip()
        if not point or not value:
            msg = "Please enter both point name and value."
            QMessageBox.warning(self, "Input Error", msg)
            return
        self._run_operation("force", point, value)

    def _on_unforce_clicked(self) -> None:
        point = self.point_input.text().strip()
        if not point:
            QMessageBox.warning(self, "Input Error",
                              "Please enter a point name.")
            return
        self._run_operation("unforce", point)

    def _on_read_clicked(self) -> None:
        point = self.point_input.text().strip()
        if not point:
            QMessageBox.warning(self, "Input Error",
                              "Please enter a point name.")
            return
        self._run_operation("read", point)

    def _run_operation(self, operation, point, value=None) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Running {operation}...")
        self._disable_controls(True)

        self.worker_thread = WorkerThread(
            operation,
            self.client_args,
            point,
            value,
            self.dry_run_checkbox.isChecked(),
        )
        self.worker_thread.result.connect(self._on_operation_result)
        self.worker_thread.error.connect(self._on_operation_error)
        self.worker_thread.finished.connect(self._on_operation_finished)
        self.worker_thread.start()

    def _on_operation_result(self, result: dict) -> None:
        """Handle successful operation result."""
        if result["success"]:
            msg = f"\u2713 {result['operation'].upper()} Successful\n"
            msg += f"Point: {result['point']}\n"
            if (result["operation"] == "read" and
                    result["updated_value"]):
                msg += f"Current Value: {result['updated_value']}"
            elif result["operation"] == "force":
                msg += f"Set Value: {result['value']}"
            self.status_label.setText(msg)
            success_style = "color: #4CAF50; font-weight: bold;"
            self.status_label.setStyleSheet(success_style)
            QMessageBox.information(self, "Success", msg)
        else:
            msg = f"\u2717 {result['operation'].upper()} Failed\n"
            msg += f"Error: {result['message']}"
            self.status_label.setText(msg)
            error_style = "color: #F44336; font-weight: bold;"
            self.status_label.setStyleSheet(error_style)
            QMessageBox.critical(self, "Error", msg)

    def _on_operation_error(self, error: str) -> None:
        """Handle operation error."""
        self.status_label.setText(f"Error: {error}")
        error_style = "color: #F44336; font-weight: bold;"
        self.status_label.setStyleSheet(error_style)
        QMessageBox.critical(self, "Error",
                           f"Operation failed:\n{error}")

    def _on_operation_finished(self) -> None:
        """Handle operation completion."""
        self.progress_bar.setVisible(False)
        self._disable_controls(False)

    def _disable_controls(self, disabled: bool) -> None:
        self.force_button.setEnabled(not disabled)
        self.unforce_button.setEnabled(not disabled)
        self.read_button.setEnabled(not disabled)
        self.point_input.setEnabled(not disabled)
        self.force_value_input.setEnabled(not disabled)


class BatchOperationsWidget(QWidget):
    """Widget for managing batch operations."""

    def __init__(self, client_args):
        super().__init__()
        self.client_args = client_args
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()

        # Config file selection
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Config File:"))
        self.config_path_label = QLineEdit()
        self.config_path_label.setReadOnly(True)
        self.config_path_label.setPlaceholderText(
            "Select a JSON config file..."
        )
        file_layout.addWidget(self.config_path_label)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse_clicked)
        file_layout.addWidget(browse_button)
        layout.addLayout(file_layout)

        # Batch settings
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("Max Retries:"))
        self.retries_spinbox = QSpinBox()
        self.retries_spinbox.setValue(3)
        self.retries_spinbox.setMinimum(1)
        self.retries_spinbox.setMaximum(10)
        settings_layout.addWidget(self.retries_spinbox)

        settings_layout.addWidget(QLabel("Backoff Seconds:"))
        self.backoff_spinbox = QDoubleSpinBox()
        self.backoff_spinbox.setValue(2.0)
        self.backoff_spinbox.setMinimum(0.1)
        self.backoff_spinbox.setMaximum(10.0)
        self.backoff_spinbox.setSingleStep(0.5)
        settings_layout.addWidget(self.backoff_spinbox)

        self.dry_run_checkbox = QCheckBox("Dry Run")
        settings_layout.addWidget(self.dry_run_checkbox)
        layout.addLayout(settings_layout)

        # Operations table
        layout.addWidget(QLabel("Operations:"))
        self.operations_table = QTableWidget()
        self.operations_table.setColumnCount(4)
        self.operations_table.setHorizontalHeaderLabels(
            ["Action", "Point", "Value", "Status"]
        )
        self.operations_table.setColumnWidth(0, 80)
        self.operations_table.setColumnWidth(1, 200)
        self.operations_table.setColumnWidth(2, 100)
        self.operations_table.setColumnWidth(3, 150)
        layout.addWidget(self.operations_table)

        # Buttons
        button_layout = QHBoxLayout()
        preview_button = QPushButton("Preview Config")
        preview_button.clicked.connect(self._on_preview_clicked)
        button_layout.addWidget(preview_button)

        run_button = QPushButton("Run Batch")
        run_button.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 8px;"
        )
        run_button.clicked.connect(self._on_run_clicked)
        button_layout.addWidget(run_button)

        layout.addLayout(button_layout)

        # Status
        self.batch_status_label = QLabel("Ready")
        status_style = "color: #666; font-style: italic;"
        self.batch_status_label.setStyleSheet(status_style)
        layout.addWidget(self.batch_status_label)

        self.setLayout(layout)

    def _on_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Config File", "", "JSON Files (*.json)"
        )
        if path:
            self.config_path_label.setText(path)
            self._load_config(path)

    def _load_config(self, config_path: str) -> None:
        """Load batch configuration from JSON file."""
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            if isinstance(config, dict):
                operations = config.get("operations", config)
            else:
                operations = config
            self.operations_table.setRowCount(0)
            for i, op in enumerate(operations):
                self.operations_table.insertRow(i)
                action = op.get("action", "force")
                point = op.get("point", "")
                value = op.get("value", "")
                self.operations_table.setItem(
                    i, 0, QTableWidgetItem(action)
                )
                self.operations_table.setItem(
                    i, 1, QTableWidgetItem(point)
                )
                self.operations_table.setItem(
                    i, 2,
                    QTableWidgetItem(str(value) if value else "")
                )
                self.operations_table.setItem(
                    i, 3, QTableWidgetItem("Pending")
                )
            msg = f"Loaded {len(operations)} operations"
            self.batch_status_label.setText(msg)
        except (IOError, json.JSONDecodeError, KeyError) as exc:
            msg = f"Failed to load config:\n{str(exc)}"
            QMessageBox.critical(self, "Error", msg)

    def _on_preview_clicked(self) -> None:
        """Preview the batch configuration file."""
        if not self.config_path_label.text():
            msg = "Please select a config file first."
            QMessageBox.warning(self, "No Config", msg)
            return
        try:
            with open(self.config_path_label.text(),
                      encoding="utf-8") as f:
                config_text = f.read()
            QMessageBox.information(
                self, "Config Preview", config_text
            )
        except IOError as exc:
            msg = f"Failed to preview config:\n{str(exc)}"
            QMessageBox.critical(self, "Error", msg)

    def _on_run_clicked(self) -> None:
        """Execute batch operations."""
        if not self.config_path_label.text():
            msg = "Please select a config file first."
            QMessageBox.warning(self, "No Config", msg)
            return
        msg = (
            "Batch operations are running in the background.\n"
            "Check the log viewer for results."
        )
        QMessageBox.information(self, "Batch Execution", msg)
        self.batch_status_label.setText(
            "Running batch operations..."
        )
        batch_style = "color: #2196F3; font-weight: bold;"
        self.batch_status_label.setStyleSheet(batch_style)


class LogViewerWidget(QWidget):
    """Widget for viewing operation logs."""

    def __init__(self):
        super().__init__()
        self._setup_ui()
        self._load_logs()
        self.timer = QTimer()
        self.timer.timeout.connect(self._load_logs)
        self.timer.start(2000)  # Refresh every 2 seconds

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Recent Operations:"))
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._load_logs)
        header_layout.addWidget(refresh_button)
        clear_button = QPushButton("Clear Logs")
        clear_button.clicked.connect(self._clear_logs)
        header_layout.addWidget(clear_button)
        layout.addLayout(header_layout)

        # Log table
        self.log_table = QTableWidget()
        self.log_table.setColumnCount(6)
        self.log_table.setHorizontalHeaderLabels(
            ["Timestamp", "Action", "Point", "Status",
             "Message", "Value"]
        )
        self.log_table.setColumnWidth(0, 150)
        self.log_table.setColumnWidth(1, 80)
        self.log_table.setColumnWidth(2, 150)
        self.log_table.setColumnWidth(3, 80)
        self.log_table.setColumnWidth(4, 250)
        self.log_table.setColumnWidth(5, 100)
        layout.addWidget(self.log_table)

        self.setLayout(layout)

    def _load_logs(self) -> None:
        """Load and display operation logs."""
        log_path = Path("logs") / "bravida_actions.jsonl"
        if not log_path.exists():
            return

        try:
            logs = []
            with open(log_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        logs.append(json.loads(line))

            # Show last 20 logs
            logs = logs[-20:]
            self.log_table.setRowCount(0)

            for i, log in enumerate(logs):
                self.log_table.insertRow(i)
                # Format: YYYY-MM-DD HH:MM:SS
                timestamp = log.get("timestamp", "")[:19]
                action = log.get("action", "")
                point = log.get("point", "")
                is_success = log.get("success")
                status = "\u2713 Success" if is_success else "\u2717 Failed"
                message = log.get("message", "")[:50]
                value = log.get(
                    "value", log.get("updated_value", "")
                )

                self.log_table.setItem(
                    i, 0, QTableWidgetItem(timestamp)
                )
                self.log_table.setItem(
                    i, 1, QTableWidgetItem(action)
                )
                self.log_table.setItem(
                    i, 2, QTableWidgetItem(point)
                )
                status_item = QTableWidgetItem(status)
                if is_success:
                    status_item.setForeground(
                        QColor("#4CAF50")
                    )
                else:
                    status_item.setForeground(
                        QColor("#F44336")
                    )
                self.log_table.setItem(i, 3, status_item)
                self.log_table.setItem(
                    i, 4, QTableWidgetItem(message)
                )
                self.log_table.setItem(
                    i, 5, QTableWidgetItem(str(value))
                )
        except (IOError, json.JSONDecodeError) as exc:
            print(f"Error loading logs: {exc}")

    def _clear_logs(self) -> None:
        """Clear all operation logs."""
        reply = QMessageBox.question(
            self,
            "Clear Logs",
            "Are you sure you want to clear all logs?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            log_path = Path("logs") / "bravida_actions.jsonl"
            if log_path.exists():
                log_path.unlink()
            self._load_logs()


class AIAnalysisWidget(QWidget):
    """Widget for AI-powered HVAC analysis."""

    def __init__(self, client_args):
        super().__init__()
        self.client_args = client_args
        self.analyzer = HVACAIAnalyzer()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()

        # Control buttons
        button_layout = QHBoxLayout()
        self.scan_button = QPushButton("📊 Scan All Points")
        self.scan_button.setStyleSheet(
            "background-color: #2196F3; color: white; padding: 8px;"
        )
        self.scan_button.clicked.connect(self._on_scan_clicked)
        button_layout.addWidget(self.scan_button)

        self.analyze_button = QPushButton("🤖 Analyze & Recommend")
        self.analyze_button.setStyleSheet(
            "background-color: #FF9800; color: white; padding: 8px;"
        )
        self.analyze_button.clicked.connect(self._on_analyze_clicked)
        self.analyze_button.setEnabled(False)
        button_layout.addWidget(self.analyze_button)

        self.auto_adjust_button = QPushButton("⚡ Auto-Adjust")
        self.auto_adjust_button.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 8px;"
        )
        self.auto_adjust_button.clicked.connect(self._on_auto_adjust_clicked)
        self.auto_adjust_button.setEnabled(False)
        button_layout.addWidget(self.auto_adjust_button)

        layout.addLayout(button_layout)

        # System state display
        layout.addWidget(QLabel("System State:"))
        self.state_display = QTextEdit()
        self.state_display.setReadOnly(True)
        self.state_display.setStyleSheet(
            "background-color: #f5f5f5; font-family: monospace;"
        )
        layout.addWidget(self.state_display)

        # AI Analysis display
        layout.addWidget(QLabel("AI Analysis:"))
        self.analysis_display = QTextEdit()
        self.analysis_display.setReadOnly(True)
        self.analysis_display.setStyleSheet(
            "background-color: #f5f5f5; font-family: monospace;"
        )
        layout.addWidget(self.analysis_display)

        # Recommendations table
        layout.addWidget(QLabel("Recommendations:"))
        self.recommendations_table = QTableWidget()
        self.recommendations_table.setColumnCount(6)
        self.recommendations_table.setHorizontalHeaderLabels(
            ["Action", "Point", "Value", "Reason",
             "Confidence", "Priority"]
        )
        self.recommendations_table.setColumnWidth(0, 70)
        self.recommendations_table.setColumnWidth(1, 150)
        self.recommendations_table.setColumnWidth(2, 80)
        self.recommendations_table.setColumnWidth(3, 200)
        self.recommendations_table.setColumnWidth(4, 90)
        self.recommendations_table.setColumnWidth(5, 70)
        layout.addWidget(self.recommendations_table)

        # Status
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            "color: #666; font-style: italic;"
        )
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def _on_scan_clicked(self) -> None:
        """Scan all HVAC points."""
        self.status_label.setText("🔄 Scanning all points...")
        self.scan_button.setEnabled(False)
        if not hasattr(self, 'progress_bar'):
            self.progress_bar = QProgressBar()
            layout = self.state_display.parent().layout()
            layout.insertWidget(1, self.progress_bar)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress

        try:
            reader = BulkPointReader(self.client_args)
            state = reader.read_all_points()
            self.current_state = state

            summary = reader.get_readable_summary(state)
            self.state_display.setText(summary)

            self.analyze_button.setEnabled(True)
            self.auto_adjust_button.setEnabled(True)
            success_count = sum(
                1 for p in state.points.values() if p.success
            )
            self.status_label.setText(
                f"✓ Scan complete: {success_count}/{len(state.points)} "
                "points read"
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            msg = f"Error scanning points: {str(exc)}"
            self.status_label.setText(f"✗ {msg}")
            self.state_display.setText(msg)
            QMessageBox.critical(self, "Scan Error", msg)
        finally:
            self.scan_button.setEnabled(True)
            self.progress_bar.setVisible(False)

    def _on_analyze_clicked(self) -> None:
        """Run AI analysis on current state."""
        if not hasattr(self, "current_state"):
            QMessageBox.warning(
                self, "No Data",
                "Please scan points first."
            )
            return

        self.status_label.setText("🤖 Running AI analysis...")
        self.analyze_button.setEnabled(False)

        try:
            analysis, recommendations = (
                self.analyzer.analyze_system_state(
                    self.current_state
                )
            )
            self.analysis_display.setText(analysis)
            self._display_recommendations(recommendations)
            self.analyzer.save_analysis_history(
                self.current_state, analysis, recommendations
            )

            msg = (
                f"✓ Analysis complete: "
                f"{len(recommendations)} recommendations"
            )
            self.status_label.setText(msg)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            msg = f"✗ Analysis error: {str(exc)}"
            self.status_label.setText(msg)
            QMessageBox.critical(self, "Analysis Error", msg)
        finally:
            self.analyze_button.setEnabled(True)

    def _on_auto_adjust_clicked(self) -> None:
        """Auto-apply recommendations."""
        if self.recommendations_table.rowCount() == 0:
            QMessageBox.warning(
                self, "No Recommendations",
                "Run analysis first to get recommendations."
            )
            return

        reply = QMessageBox.question(
            self,
            "Auto-Adjust HVAC System",
            (
                f"Apply {self.recommendations_table.rowCount()} "
                "AI recommendations?"
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.status_label.setText(
            "⚡ Applying recommendations..."
        )
        self.auto_adjust_button.setEnabled(False)

        try:
            applied = 0
            failed = 0
            for row in range(self.recommendations_table.rowCount()):
                action = (
                    self.recommendations_table.item(
                        row, 0
                    ).text()
                )
                point = (
                    self.recommendations_table.item(
                        row, 1
                    ).text()
                )
                value = (
                    self.recommendations_table.item(
                        row, 2
                    ).text()
                )

                try:
                    with BravidaClient(**self.client_args) as client:
                        if action == "force":
                            result = client.force_point(point, value)
                        else:
                            result = client.unforce_point(point)

                        if result.success:
                            applied += 1
                        else:
                            failed += 1
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    failed += 1
                    print(f"Error applying {point}: {exc}")

            total = self.recommendations_table.rowCount()
            msg = f"✓ Applied {applied} of {total} recommendations"
            if failed > 0:
                msg += f"\n⚠ {failed} failed"
            self.status_label.setText(msg)
            QMessageBox.information(self, "Complete", msg)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            msg = f"✗ Error applying recommendations: {str(exc)}"
            self.status_label.setText(msg)
            QMessageBox.critical(self, "Error", msg)
        finally:
            self.auto_adjust_button.setEnabled(True)

    def _display_recommendations(self, recommendations):
        """Display recommendations in table."""
        self.recommendations_table.setRowCount(0)
        for i, rec in enumerate(recommendations):
            self.recommendations_table.insertRow(i)
            self.recommendations_table.setItem(
                i, 0, QTableWidgetItem(rec.action)
            )
            self.recommendations_table.setItem(
                i, 1, QTableWidgetItem(rec.point)
            )
            self.recommendations_table.setItem(
                i, 2,
                QTableWidgetItem(rec.value or "-")
            )
            self.recommendations_table.setItem(
                i, 3, QTableWidgetItem(rec.reason)
            )
            self.recommendations_table.setItem(
                i, 4,
                QTableWidgetItem(f"{rec.confidence:.1%}")
            )
            self.recommendations_table.setItem(
                i, 5, QTableWidgetItem(str(rec.priority))
            )


class SettingsWidget(QWidget):
    """Widget for application settings."""

    def __init__(self, settings: dict) -> None:
        super().__init__()
        self.settings = settings
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()

        # URL setting
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Bravida Cloud URL:"))
        self.url_input = QLineEdit()
        self.url_input.setText(self.settings.get("url", ""))
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)

        # Storage state path
        state_layout = QHBoxLayout()
        state_layout.addWidget(QLabel("Storage State Path:"))
        self.state_input = QLineEdit()
        default_state = "state/bravida_storage_state.json"
        self.state_input.setText(
            self.settings.get("storage_state", default_state)
        )
        state_layout.addWidget(self.state_input)
        layout.addLayout(state_layout)

        # Timeout setting
        timeout_layout = QHBoxLayout()
        timeout_layout.addWidget(QLabel("Timeout (ms):"))
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setValue(
            self.settings.get("timeout_ms", 30000)
        )
        self.timeout_spinbox.setMinimum(5000)
        self.timeout_spinbox.setMaximum(120000)
        self.timeout_spinbox.setSingleStep(5000)
        timeout_layout.addWidget(self.timeout_spinbox)
        layout.addLayout(timeout_layout)

        # Headless mode
        self.headless_checkbox = QCheckBox(
            "Headless Mode (no browser window)"
        )
        self.headless_checkbox.setChecked(
            self.settings.get("headless", False)
        )
        layout.addWidget(self.headless_checkbox)

        # AI Configuration Section
        ai_box = QGroupBox("🤖 AI Configuration")
        ai_layout = QVBoxLayout()

        # AI Backend selection
        backend_layout = QHBoxLayout()
        backend_layout.addWidget(QLabel("AI Backend:"))
        self.ai_backend_combo = QComboBox()
        self.ai_backend_combo.addItems(
            ["None (Rule-based)", "OpenAI (ChatGPT)",
             "Anthropic (Claude)"]
        )
        current_backend = self.settings.get("ai_backend", "none")
        if current_backend == "openai":
            self.ai_backend_combo.setCurrentIndex(1)
        elif current_backend == "anthropic":
            self.ai_backend_combo.setCurrentIndex(2)
        else:
            self.ai_backend_combo.setCurrentIndex(0)
        backend_layout.addWidget(self.ai_backend_combo)
        ai_layout.addLayout(backend_layout)

        # OpenAI API Key
        openai_layout = QHBoxLayout()
        openai_layout.addWidget(QLabel("OpenAI API Key:"))
        self.openai_key_input = QLineEdit()
        self.openai_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key_input.setText(
            self.settings.get("openai_api_key", "")
        )
        openai_layout.addWidget(self.openai_key_input)
        ai_layout.addLayout(openai_layout)

        # Anthropic API Key
        anthropic_layout = QHBoxLayout()
        anthropic_layout.addWidget(QLabel("Anthropic API Key:"))
        self.anthropic_key_input = QLineEdit()
        self.anthropic_key_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.anthropic_key_input.setText(
            self.settings.get("anthropic_api_key", "")
        )
        anthropic_layout.addWidget(self.anthropic_key_input)
        ai_layout.addLayout(anthropic_layout)

        # Parallel workers for bulk reading
        workers_layout = QHBoxLayout()
        workers_layout.addWidget(QLabel("Parallel Workers:"))
        self.workers_spinbox = QSpinBox()
        self.workers_spinbox.setValue(
            self.settings.get("ai_workers", 5)
        )
        self.workers_spinbox.setMinimum(1)
        self.workers_spinbox.setMaximum(20)
        workers_layout.addWidget(self.workers_spinbox)
        ai_layout.addLayout(workers_layout)

        ai_box.setLayout(ai_layout)
        layout.addWidget(ai_box)

        # Info box
        info_box = QGroupBox("Information")
        info_layout = QVBoxLayout()
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setText(
            "HVAC Robot Controller GUI\n\n"
            "This tool automates Bravida Cloud point "
            "control via browser automation with AI "
            "optimization.\n\n"
            "Features:\n"
            "• Force/Unforce individual points\n"
            "• Read current point values\n"
            "• Batch operations from JSON config\n"
            "• Real-time logging and monitoring\n\n"
            "Before first use, ensure your login "
            "credentials are saved via CLI:\n"
            "python -m src.main login"
        )
        info_layout.addWidget(info_text)
        info_box.setLayout(info_layout)
        layout.addWidget(info_box)

        layout.addStretch()
        self.setLayout(layout)

    def get_settings(self) -> dict:
        """Return current settings as a dictionary."""
        backend_map = {
            0: "none",
            1: "openai",
            2: "anthropic",
        }
        return {
            "url": self.url_input.text(),
            "storage_state": self.state_input.text(),
            "timeout_ms": self.timeout_spinbox.value(),
            "headless": self.headless_checkbox.isChecked(),
            "ai_backend": backend_map.get(
                self.ai_backend_combo.currentIndex(), "none"
            ),
            "openai_api_key": self.openai_key_input.text(),
            "anthropic_api_key": self.anthropic_key_input.text(),
            "ai_workers": self.workers_spinbox.value(),
        }


class HVACRobotGUI(QMainWindow):
    """Main window for HVAC Robot Controller."""

    def __init__(self) -> None:
        super().__init__()
        default_url = (
            "https://bracloud.bravida.no/"
            "#/NO%20R%C3%B8a%20Bad%20360.005/360.005/360.005"
        )
        self.settings = {
            "url": default_url,
            "storage_state": "state/bravida_storage_state.json",
            "timeout_ms": 30000,
            "headless": False,
            "ai_backend": "none",
            "openai_api_key": "",
            "anthropic_api_key": "",
            "ai_workers": 5,
        }
        self._setup_ui()
        setup_logger()

    def _setup_ui(self) -> None:
        """Set up the main user interface."""
        self.setWindowTitle(
            "HVAC Robot Controller - Bravida Cloud Automation"
        )
        self.setGeometry(100, 100, 1200, 800)

        # Style
        stylesheet = (
            "QMainWindow { background-color: #f5f5f5; }"
            "QGroupBox { border: 1px solid #ddd; "
            "border-radius: 4px; margin-top: 10px; "
            "padding-top: 10px; }"
            "QGroupBox::title { subcontrol-origin: margin; "
            "left: 10px; padding: 0 5px; }"
            "QPushButton { border-radius: 4px; "
            "font-weight: bold; }"
            "QLineEdit, QSpinBox, QDoubleSpinBox { "
            "padding: 5px; border: 1px solid #ddd; "
            "border-radius: 4px; }"
            "QTabWidget::pane { border: 1px solid #ddd; }"
            "QTabBar::tab { background-color: #e0e0e0; "
            "padding: 8px 20px; margin-right: 2px; }"
            "QTabBar::tab:selected { background-color: white; }"
        )
        self.setStyleSheet(stylesheet)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()

        # Title
        title = QLabel("\ud83e\udd16 HVAC Robot Controller")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Tabs
        tabs = QTabWidget()

        # Tab 1: Single Point Control
        self.point_control_widget = PointControlWidget(
            self._get_client_args()
        )
        tabs.addTab(self.point_control_widget, "\ud83d\udcc4 Point Control")

        # Tab 2: Batch Operations
        self.batch_widget = BatchOperationsWidget(
            self._get_client_args()
        )
        tabs.addTab(self.batch_widget, "\ud83d\udcd1 Batch Operations")

        # Tab 3: AI Analysis
        self.ai_widget = AIAnalysisWidget(
            self._get_client_args()
        )
        tabs.addTab(self.ai_widget, "\ud83e\udd16 AI Analysis")

        # Tab 4: Log Viewer
        self.log_viewer_widget = LogViewerWidget()
        tabs.addTab(self.log_viewer_widget, "\ud83d\udcc8 Logs & Status")

        # Tab 5: Settings
        self.settings_widget = SettingsWidget(self.settings)
        tabs.addTab(self.settings_widget, "\u2699\ufe0f Settings")

        layout.addWidget(tabs)

        central_widget.setLayout(layout)

    def _get_client_args(self) -> dict:
        """Return client configuration arguments."""
        return {
            "base_url": self.settings["url"],
            "storage_state_path": Path(
                self.settings["storage_state"]
            ),
            "artifacts_dir": Path("artifacts"),
            "headless": self.settings["headless"],
            "timeout_ms": self.settings["timeout_ms"],
        }

    def closeEvent(self, event) -> None:  # type: ignore[name-defined] # pylint: disable=invalid-name
        """Save settings on close."""
        self.settings = self.settings_widget.get_settings()
        event.accept()


def main() -> int:
    """Launch the GUI application."""
    app = QApplication([])
    window = HVACRobotGUI()
    window.show()
    return app.exec()


if __name__ == "__main__":
    main()
