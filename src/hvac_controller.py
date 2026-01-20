"""Automatic HVAC controller logic for Bravida Cloud UI automation."""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .bravida_client import BravidaClient, ForceResult
from .logging_utils import DEFAULT_LOG_DIR, DEFAULT_LOG_FILE, log_action


@dataclass(frozen=True)
class SensorReadings:
    indoor_temp_c: float
    indoor_rh_percent: float
    outdoor_temp_c: Optional[float]


def load_controller_config(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Controller config must be a JSON object.")
    return raw


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _dew_point_c(temp_c: float, rh_percent: float) -> float:
    a = 17.62
    b = 243.12
    gamma = (a * temp_c / (b + temp_c)) + math.log(max(rh_percent, 0.1) / 100.0)
    return (b * gamma) / (a - gamma)


def _read_point_value(client: BravidaClient, point: str) -> Tuple[Optional[float], ForceResult]:
    result = client.read_point(point)
    value = _parse_float(result.updated_value)
    return value, result


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _save_state(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _select_actions(
    conditions: Dict[str, Any],
    actions: Dict[str, Any],
    combine_actions: bool,
) -> Tuple[str, List[Dict[str, Any]]]:
    high_rh = bool(conditions.get("high_rh"))
    condensation_risk = bool(conditions.get("condensation_risk"))
    poor_air_quality = bool(conditions.get("poor_air_quality"))

    selected: List[Dict[str, Any]] = []
    key_parts: List[str] = []

    if poor_air_quality:
        key_parts.append("poor_air_quality")
        selected.extend(actions.get("on_air_quality", []))
        return "poor_air_quality", selected

    if condensation_risk:
        key_parts.append("condensation_risk")
        selected.extend(actions.get("on_condensation_risk", []))
        if not combine_actions:
            return "condensation_risk", selected

    if high_rh:
        key_parts.append("high_rh")
        selected.extend(actions.get("on_high_rh", []))
        if not combine_actions and key_parts:
            return "+".join(key_parts), selected

    if not key_parts:
        selected.extend(actions.get("on_normal", []))
        return "normal", selected

    return "+".join(key_parts), selected


def _execute_actions(
    client: BravidaClient,
    actions: Iterable[Dict[str, Any]],
    dry_run: bool,
    log_path: Path,
) -> bool:
    all_ok = True
    for action in actions:
        op = str(action.get("action", "force")).lower()
        point = action.get("point")
        value = action.get("value")
        if not point:
            log_action(log_path, {"action": "auto_action", "success": False, "message": "Missing point."})
            all_ok = False
            continue
        if op == "force":
            if value is None:
                log_action(
                    log_path,
                    {
                        "action": "auto_action",
                        "point": point,
                        "success": False,
                        "message": "Missing value for force.",
                    },
                )
                all_ok = False
                continue
            result = client.force_point(str(point), str(value), dry_run=dry_run)
        elif op == "unforce":
            result = client.unforce_point(str(point))
        elif op == "read":
            result = client.read_point(str(point))
        else:
            log_action(
                log_path,
                {
                    "action": "auto_action",
                    "point": point,
                    "success": False,
                    "message": f"Unsupported action: {op}.",
                },
            )
            all_ok = False
            continue

        log_action(
            log_path,
            {
                "action": f"auto_{op}",
                "point": result.point,
                "value": result.value,
                "success": result.success,
                "message": result.message,
                "updated_value": result.updated_value,
                "screenshot": result.screenshot_path,
                "dry_run": dry_run,
            },
        )
        all_ok = all_ok and result.success

    return all_ok


def run_controller(
    client: BravidaClient,
    config_path: Path,
    log_path: Path = DEFAULT_LOG_DIR / DEFAULT_LOG_FILE,
    once: bool = False,
    dry_run_override: Optional[bool] = None,
    state_path_override: Optional[Path] = None,
    cycle_seconds_override: Optional[float] = None,
    cooldown_seconds_override: Optional[float] = None,
) -> int:
    config = load_controller_config(config_path)
    sensors = config.get("sensors", {})
    thresholds = config.get("thresholds", {})
    actions = config.get("actions", {})

    cycle_seconds = float(config.get("cycle_seconds", 300.0))
    cooldown_seconds = float(config.get("cooldown_seconds", 900.0))
    combine_actions = bool(config.get("combine_actions", True))
    dry_run = bool(config.get("dry_run", False))
    state_path = Path(config.get("state_path", "state/hvac_controller_state.json"))

    if cycle_seconds_override is not None:
        cycle_seconds = float(cycle_seconds_override)
    if cooldown_seconds_override is not None:
        cooldown_seconds = float(cooldown_seconds_override)
    if dry_run_override is not None:
        dry_run = bool(dry_run_override)
    if state_path_override is not None:
        state_path = state_path_override

    indoor_temp_point = sensors.get("indoor_temp")
    indoor_rh_point = sensors.get("indoor_rh")
    outdoor_temp_point = sensors.get("outdoor_temp")
    co_point = sensors.get("co")
    co2_point = sensors.get("co2")

    if not indoor_temp_point or not indoor_rh_point:
        raise ValueError("Controller config requires sensors.indoor_temp and sensors.indoor_rh.")

    max_rh = float(thresholds.get("max_rh", 60.0))
    condensation_margin_c = float(thresholds.get("condensation_margin_c", 2.0))
    max_co_ppm = thresholds.get("max_co_ppm", thresholds.get("max_co"))
    max_co2_ppm = thresholds.get("max_co2_ppm", thresholds.get("max_co2"))

    while True:
        state = _load_state(state_path)
        last_action_key = state.get("last_action_key")
        last_action_ts = state.get("last_action_ts", 0)

        indoor_temp_c, indoor_temp_result = _read_point_value(client, indoor_temp_point)
        indoor_rh, indoor_rh_result = _read_point_value(client, indoor_rh_point)

        if indoor_temp_c is None or indoor_rh is None:
            log_action(
                log_path,
                {
                    "action": "auto_evaluate",
                    "success": False,
                    "message": "Failed to parse indoor sensor values.",
                    "indoor_temp_value": indoor_temp_result.updated_value,
                    "indoor_rh_value": indoor_rh_result.updated_value,
                },
            )
            if once:
                return 1
            time.sleep(cycle_seconds)
            continue

        outdoor_temp_c: Optional[float] = None
        outdoor_temp_result: Optional[ForceResult] = None
        if outdoor_temp_point:
            outdoor_temp_c, outdoor_temp_result = _read_point_value(client, outdoor_temp_point)

        co_ppm: Optional[float] = None
        co2_ppm: Optional[float] = None
        if co_point:
            co_ppm, _ = _read_point_value(client, co_point)
        if co2_point:
            co2_ppm, _ = _read_point_value(client, co2_point)

        dew_point_c = _dew_point_c(indoor_temp_c, indoor_rh)
        high_rh = indoor_rh >= max_rh
        condensation_risk = False
        if outdoor_temp_c is not None:
            condensation_risk = outdoor_temp_c <= (dew_point_c - condensation_margin_c)
        poor_air_quality = False
        if max_co_ppm is not None and co_ppm is not None:
            poor_air_quality = poor_air_quality or (co_ppm >= float(max_co_ppm))
        if max_co2_ppm is not None and co2_ppm is not None:
            poor_air_quality = poor_air_quality or (co2_ppm >= float(max_co2_ppm))

        conditions = {
            "indoor_temp_c": indoor_temp_c,
            "indoor_rh_percent": indoor_rh,
            "outdoor_temp_c": outdoor_temp_c,
            "co_ppm": co_ppm,
            "co2_ppm": co2_ppm,
            "dew_point_c": dew_point_c,
            "high_rh": high_rh,
            "condensation_risk": condensation_risk,
            "poor_air_quality": poor_air_quality,
        }

        action_key, selected_actions = _select_actions(conditions, actions, combine_actions)

        now_ts = time.time()
        if action_key == last_action_key and (now_ts - float(last_action_ts)) < cooldown_seconds:
            log_action(
                log_path,
                {
                    "action": "auto_evaluate",
                    "success": True,
                    "message": "Cooldown active; skipping actions.",
                    **conditions,
                    "action_key": action_key,
                },
            )
        else:
            log_action(
                log_path,
                {
                    "action": "auto_evaluate",
                    "success": True,
                    "message": "Evaluation complete.",
                    **conditions,
                    "action_key": action_key,
                    "selected_actions": selected_actions,
                },
            )

            actions_ok = _execute_actions(client, selected_actions, dry_run, log_path)
            state_payload = {
                "last_action_key": action_key,
                "last_action_ts": now_ts,
                "last_action_time_utc": datetime.now(timezone.utc).isoformat(),
                "last_actions_ok": actions_ok,
            }
            _save_state(state_path, state_payload)

        if once:
            return 0
        time.sleep(cycle_seconds)
