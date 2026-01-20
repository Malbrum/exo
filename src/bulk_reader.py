"""Bulk HVAC value reader and AI-powered analyzer."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from .bravida_client import BravidaClient


@dataclass
class HVACPoint:
    """Represents a single HVAC point reading."""

    name: str
    value: Optional[str] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class HVACSystemState:
    """Complete snapshot of HVAC system state."""

    timestamp: str
    points: Dict[str, HVACPoint]
    temperature_avg: Optional[float] = None
    humidity_avg: Optional[float] = None
    pressure_avg: Optional[float] = None


class BulkPointReader:
    """Reads multiple HVAC points in parallel for efficiency."""

    def __init__(self, client_args: dict, max_workers: int = 5) -> None:
        """Initialize bulk reader with client configuration."""
        self.client_args = client_args
        self.max_workers = max_workers
        self.point_definitions: Dict[str, dict] = {}
        self._load_point_definitions()

    def _load_point_definitions(self) -> None:
        """Load HVAC point definitions from config."""
        config_path = Path("config") / "hvac_points.json"
        if config_path.exists():
            try:
                with open(config_path, encoding="utf-8") as f:
                    self.point_definitions = json.load(f)
            except (IOError, json.JSONDecodeError):
                # Fallback to default points
                self.point_definitions = self._get_default_points()
        else:
            self.point_definitions = self._get_default_points()

    def _get_default_points(self) -> Dict[str, dict]:
        """Return default HVAC point definitions."""
        return {
            "360.005-JV40_Pos": {
                "name": "Ventilation Damper Position",
                "unit": "%",
                "category": "ventilation",
                "setpoint": False,
            },
            "360.005-JV50_Pos": {
                "name": "Heating Valve Position",
                "unit": "%",
                "category": "heating",
                "setpoint": False,
            },
            "360.005-JP40_Pos": {
                "name": "Cooling Valve Position",
                "unit": "%",
                "category": "cooling",
                "setpoint": False,
            },
            "360.005-RT40": {
                "name": "Room Temperature",
                "unit": "°C",
                "category": "temperature",
                "setpoint": False,
            },
            "360.005-RH40": {
                "name": "Room Humidity",
                "unit": "%",
                "category": "humidity",
                "setpoint": False,
            },
            "360.005-SB40": {
                "name": "Supply Air Humidity",
                "unit": "%",
                "category": "humidity",
                "setpoint": False,
            },
        }

    def read_all_points(self) -> HVACSystemState:
        """Read all HVAC points in parallel."""
        from datetime import datetime

        timestamp = datetime.now().isoformat()
        points = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._read_single_point, point_name): point_name
                for point_name in self.point_definitions.keys()
            }

            for future in as_completed(futures):
                point_name = futures[future]
                try:
                    point_data = future.result()
                    points[point_name] = point_data
                except Exception as exc:
                    points[point_name] = HVACPoint(
                        name=point_name, success=False, error=str(exc)
                    )

        system_state = HVACSystemState(timestamp=timestamp, points=points)
        self._calculate_averages(system_state)
        return system_state

    def _read_single_point(self, point_name: str) -> HVACPoint:
        """Read a single point from Bravida."""
        from datetime import datetime

        try:
            with BravidaClient(**self.client_args) as client:
                result = client.read_point(point_name)

            definition = self.point_definitions.get(
                point_name, {"unit": ""}
            )
            return HVACPoint(
                name=definition.get("name", point_name),
                value=result.updated_value,
                unit=definition.get("unit"),
                category=definition.get("category"),
                success=result.success,
                error=result.message if not result.success else None,
                timestamp=datetime.now().isoformat(),
            )
        except Exception as exc:
            return HVACPoint(
                name=point_name,
                success=False,
                error=f"Exception: {str(exc)}",
            )

    def _calculate_averages(self, state: HVACSystemState) -> None:
        """Calculate average values from system state."""
        temps = []
        humidities = []
        pressures = []

        for point in state.points.values():
            if not point.success or point.value is None:
                continue

            try:
                value = float(point.value)
                if point.category == "temperature":
                    temps.append(value)
                elif point.category == "humidity":
                    humidities.append(value)
                elif point.category == "pressure":
                    pressures.append(value)
            except (ValueError, TypeError):
                continue

        if temps:
            state.temperature_avg = sum(temps) / len(temps)
        if humidities:
            state.humidity_avg = sum(humidities) / len(humidities)
        if pressures:
            state.pressure_avg = sum(pressures) / len(pressures)

    def get_readable_summary(self, state: HVACSystemState) -> str:
        """Generate human-readable summary of system state."""
        lines = [f"HVAC System State @ {state.timestamp}"]
        lines.append("=" * 50)

        if state.temperature_avg is not None:
            lines.append(f"Avg Temperature: {state.temperature_avg:.1f}°C")
        if state.humidity_avg is not None:
            lines.append(f"Avg Humidity: {state.humidity_avg:.1f}%")

        lines.append("\nIndividual Points:")
        for point_name, point in state.points.items():
            if point.success:
                lines.append(
                    f"  • {point.name}: {point.value} {point.unit}"
                )
            else:
                lines.append(f"  • {point.name}: ERROR - {point.error}")

        return "\n".join(lines)
