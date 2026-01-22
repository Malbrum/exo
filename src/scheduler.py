"""Hourly scheduler for automatic login and HVAC point reading."""
from __future__ import annotations

import json

import time
from datetime import datetime
from pathlib import Path

from .bravida_client import BravidaClient
from .bulk_reader import BulkPointReader
from .logging_utils import setup_logger

logger = setup_logger()


def run_hourly_scheduler(
    storage_state_path: Path,
    artifacts_dir: Path,
    base_url: str,
    headless: bool = True,
    timeout_ms: int = 30_000,
    output_file: Path = Path("hvac_readings.jsonl"),
) -> int:
    """Run hourly login + read cycle indefinitely.
    
    Args:
        storage_state_path: Path to Playwright session state
        artifacts_dir: Directory for failure screenshots
        base_url: Bravida Cloud URL
        headless: Run browser headless
        timeout_ms: Playwright timeout
        output_file: File to append hourly readings (JSONL format)
    
    Returns:
        Exit code (0 on success, 1 on error)
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting hourly scheduler (Ctrl+C to stop)")
    logger.info(f"Readings will be saved to {output_file}")
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            cycle_time = datetime.now().isoformat()
            logger.info(f"=== Cycle {cycle_count} @ {cycle_time} ===")
            
            try:
                # Step 1: Refresh login (interactive the first time, then headless with stored state)
                logger.info("Refreshing session...")
                with BravidaClient(
                    base_url=base_url,
                    storage_state_path=storage_state_path,
                    artifacts_dir=artifacts_dir,
                    headless=headless,
                    timeout_ms=timeout_ms,
                ) as client:
                    if not client.page:
                        raise RuntimeError("Playwright page failed to initialize (headless browser unavailable).")
                    # Test connectivity; if session expired, navigate to trigger re-auth
                    client.page.goto(base_url, wait_until="networkidle")
                    logger.info("Session refreshed")
                    
                    # Step 2: Read all points
                    logger.info("Reading all HVAC points...")
                    reader = BulkPointReader({
                        "base_url": base_url,
                        "storage_state_path": storage_state_path,
                        "artifacts_dir": artifacts_dir,
                        "headless": headless,
                        "timeout_ms": timeout_ms,
                    })
                    
                    state = reader.read_all_points()
                    logger.info(f"Successfully read {len(state.points)} points")
                    
                    # Step 3: Save readings
                    record = {
                        "timestamp": state.timestamp,
                        "cycle": cycle_count,
                        "points": {
                            name: {
                                "value": point.value,
                                "unit": point.unit,
                                "success": point.success,
                                "error": point.error,
                            }
                            for name, point in state.points.items()
                        },
                        "temperature_avg": state.temperature_avg,
                        "humidity_avg": state.humidity_avg,
                    }
                    
                    with output_file.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    
                    logger.info(f"Readings saved to {output_file}")
                    
                    # Summary
                    success_count = sum(1 for p in state.points.values() if p.success)
                    logger.info(f"✓ Cycle {cycle_count} complete: {success_count}/{len(state.points)} points")
                    
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(f"Cycle {cycle_count} error: {str(exc)}")
                # Continue to next cycle instead of crashing
            
            # Wait 1 hour before next cycle
            logger.info("Waiting 1 hour until next cycle...")
            time.sleep(3600)
    
    except KeyboardInterrupt:
        logger.info(f"\nScheduler stopped by user after {cycle_count} cycles")
        return 0
    
    return 0
