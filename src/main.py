"""CLI entrypoint for Bravida Cloud RPA automation."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from .bravida_client import BravidaClient
from .logging_utils import DEFAULT_LOG_DIR, DEFAULT_LOG_FILE, log_action, setup_logger

DEFAULT_URL = (
    "https://bracloud.bravida.no/#/NO%20R%C3%B8a%20Bad%20360.005/360.005/360.005"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bravida Cloud UI automation")
    parser.add_argument("--url", default=DEFAULT_URL, help="Anleggs-URL i Bravida Cloud")
    parser.add_argument(
        "--storage-state",
        default="state/bravida_storage_state.json",
        help="Path til lagret storage state",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Kjør headless (default er headful)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Timeout i millisekunder",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="Manuell innlogging og lagring av session state")

    force_parser = subparsers.add_parser("force", help="Force en enkelt verdi")
    force_parser.add_argument("--point", required=True, help="Punktnavn")
    force_parser.add_argument("--value", required=True, help="Force-verdi")
    force_parser.add_argument(
        "--dry-run", action="store_true", help="Simuler uten å klikke OK"
    )

    batch_parser = subparsers.add_parser("batch", help="Kjør batch med flere punkt")
    batch_parser.add_argument("--config", required=True, help="Path til JSON config")
    batch_parser.add_argument(
        "--dry-run", action="store_true", help="Simuler uten å klikke OK"
    )
    batch_parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Antall retries per punkt",
    )
    batch_parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=2.0,
        help="Base backoff i sekunder",
    )

    return parser.parse_args()


def load_batch_config(path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        operations = raw.get("operations", [])
    else:
        operations = raw
    if not isinstance(operations, list):
        raise ValueError("Batch config må være en liste eller ha 'operations'-liste.")
    return operations


def main() -> int:
    args = parse_args()
    logger = setup_logger()
    log_path = DEFAULT_LOG_DIR / DEFAULT_LOG_FILE

    storage_state_path = Path(args.storage_state)
    artifacts_dir = Path("artifacts")

    if args.command in {"force", "batch"} and not storage_state_path.exists():
        logger.error("Mangler storage state. Kjør 'login' først.")
        return 1

    with BravidaClient(
        base_url=args.url,
        storage_state_path=storage_state_path,
        artifacts_dir=artifacts_dir,
        headless=args.headless,
        timeout_ms=args.timeout_ms,
    ) as client:
        if args.command == "login":
            client.login_and_save_state()
            logger.info("Storage state lagret til %s", storage_state_path)
            return 0

        if args.command == "force":
            result = client.force_point(args.point, args.value, dry_run=args.dry_run)
            payload = {
                "point": result.point,
                "value": result.value,
                "success": result.success,
                "message": result.message,
                "screenshot": result.screenshot_path,
                "dry_run": args.dry_run,
            }
            log_action(log_path, payload)
            if result.success:
                logger.info("Force OK: %s=%s", result.point, result.value)
                return 0
            logger.error("Force feilet: %s", result.message)
            return 1

        if args.command == "batch":
            operations = load_batch_config(Path(args.config))
            exit_code = 0
            for op in operations:
                point = op.get("point")
                value = op.get("value")
                if not point or value is None:
                    logger.error("Ugyldig operasjon i config: %s", op)
                    exit_code = 1
                    continue
                for attempt in range(1, args.retries + 1):
                    result = client.force_point(
                        str(point), str(value), dry_run=args.dry_run
                    )
                    payload = {
                        "point": result.point,
                        "value": result.value,
                        "success": result.success,
                        "message": result.message,
                        "screenshot": result.screenshot_path,
                        "dry_run": args.dry_run,
                        "attempt": attempt,
                    }
                    log_action(log_path, payload)
                    if result.success:
                        logger.info(
                            "Force OK: %s=%s (forsøk %s)",
                            result.point,
                            result.value,
                            attempt,
                        )
                        break
                    logger.error(
                        "Force feilet for %s (forsøk %s): %s",
                        result.point,
                        attempt,
                        result.message,
                    )
                    if attempt < args.retries:
                        backoff = args.backoff_seconds * attempt
                        time.sleep(backoff)
                else:
                    exit_code = 1
            return exit_code

    return 0


if __name__ == "__main__":
    sys.exit(main())
