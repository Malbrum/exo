"""CLI entrypoint for Bravida Cloud RPA automation."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from .bravida_api import BravidaAPIClient, DEFAULT_PROPERTY_PATHS, hex_to_float
from .bravida_client import BravidaClient
from .hvac_controller import run_controller
from .logging_utils import DEFAULT_LOG_DIR, DEFAULT_LOG_FILE, log_action, setup_logger


def _load_credentials_from_env_or_file() -> Dict[str, str]:
    """Load credentials from environment variables or secrets.json.

    Order: environment vars -> secrets.json (ignored by git).
    Returns empty dict if nothing found.
    """
    user = os.getenv("BRAVIDA_USERNAME")
    pwd = os.getenv("BRAVIDA_PASSWORD")
    dom = os.getenv("BRAVIDA_DOMAIN")

    if user and pwd and dom:
        return {"username": user, "password": pwd, "domain": dom}

    secrets_path = Path("secrets.json")
    if secrets_path.exists():
        try:
            data = json.loads(secrets_path.read_text(encoding="utf-8"))
            user = data.get("BRAVIDA_USERNAME")
            pwd = data.get("BRAVIDA_PASSWORD")
            dom = data.get("BRAVIDA_DOMAIN")
            if user and pwd and dom:
                return {"username": user, "password": pwd, "domain": dom}
        except Exception:
            pass
    return {}

DEFAULT_URL = (
    "https://bracloud.bravida.no/#%2FNO%20R%C3%B8a%20Bad%20360.005%2F360.005%2F360.005"
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
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

    login_parser = subparsers.add_parser(
        "login", help="Manuell innlogging og lagring av session state"
    )
    login_parser.add_argument("--username", help="Brukernavn (for programmatisk innlogging)")
    login_parser.add_argument("--password", help="Passord (for programmatisk innlogging)")
    login_parser.add_argument("--domain", help="Domene/tenant (for programmatisk innlogging)")

    force_parser = subparsers.add_parser("force", help="Force en enkelt verdi")
    force_parser.add_argument("--point", required=True, help="Punktnavn")
    force_parser.add_argument("--value", required=True, help="Force-verdi")
    force_parser.add_argument(
        "--dry-run", action="store_true", help="Simuler uten å klikke OK"
    )

    unforce_parser = subparsers.add_parser("unforce", help="Slipp force pa et punkt")
    unforce_parser.add_argument("--point", required=True, help="Punktnavn")

    read_parser = subparsers.add_parser("read", help="Les gjeldende verdi")
    read_parser.add_argument("--point", required=True, help="Punktnavn")


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

    auto_parser = subparsers.add_parser(
        "auto", help="Automatisk HVAC-kontroll basert p† sensorverdier"
    )
    auto_parser.add_argument("--config", required=True, help="Path til JSON config")
    auto_parser.add_argument(
        "--once",
        action="store_true",
        help="Kj›r en enkelt evaluering og avslutt",
    )
    auto_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Kj›r uten † klikke OK (overstyrer config)",
    )
    auto_parser.add_argument(
        "--cycle-seconds",
        type=float,
        help="Overstyr intervall mellom evalueringer",
    )
    auto_parser.add_argument(
        "--cooldown-seconds",
        type=float,
        help="Overstyr cooldown mellom modusendringer",
    )
    auto_parser.add_argument(
        "--state-path",
        help="Overstyr lagringsfil for siste controller-tilstand",
    )

    subparsers.add_parser("gui", help="Kjør grafisk brukergrensesnitt")

    scheduler_parser = subparsers.add_parser(
        "scheduler", help="Hourly automatic login + read all HVAC points"
    )
    scheduler_parser.add_argument(
        "--output-file",
        default="hvac_readings.jsonl",
        help="Output file for readings (JSONL format)",
    )

    api_parser = subparsers.add_parser(
        "api-read", help="Les punktverdier via HTTP API (uten Playwright)"
    )
    api_parser.add_argument(
        "--csrf-token",
        help="CSRF token header (standard er CSP-cookie fra storage_state)",
    )
    api_parser.add_argument(
        "--paths-file",
        help="Path til JSON-fil med propertyPaths (default er innebygd listen)",
    )
    api_parser.add_argument("--username", help="Username for authentication")
    api_parser.add_argument("--password", help="Password for authentication")
    api_parser.add_argument("--domain", help="Domain/token for authentication")

    return parser.parse_args()


def load_batch_config(path: Path) -> List[Dict[str, Any]]:
    """Load and parse batch configuration from JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        operations = raw.get("operations", [])
    else:
        operations = raw
    if not isinstance(operations, list):
        raise ValueError("Batch config må være en liste eller ha 'operations'-liste.")
    return operations


def main() -> int:
    """CLI main function - handle all commands and operations."""
    args = parse_args()
    logger = setup_logger()
    log_path = DEFAULT_LOG_DIR / DEFAULT_LOG_FILE

    storage_state_path = Path(args.storage_state)
    artifacts_dir = Path("artifacts")

    if args.command == "scheduler":
        if not storage_state_path.exists():
            logger.error("Mangler storage state. Kjør 'login' først.")
            return 1
        from .scheduler import run_hourly_scheduler  # pylint: disable=import-outside-toplevel
        return run_hourly_scheduler(
            storage_state_path=storage_state_path,
            artifacts_dir=artifacts_dir,
            base_url=args.url,
            headless=args.headless,
            timeout_ms=args.timeout_ms,
            output_file=Path(args.output_file),
        )

    if args.command == "api-read":
        # Use browser context to make authenticated API calls
        property_paths = DEFAULT_PROPERTY_PATHS
        if args.paths_file:
            property_paths = json.loads(Path(args.paths_file).read_text(encoding="utf-8"))

        if not storage_state_path.exists() and not (args.username and args.password and args.domain):
            logger.error("Ingen storage_state funnet og ingen credentials oppgitt. Kj›r 'login' eller oppgi --username/--password/--domain.")
            return 1
        
        with BravidaClient(
            base_url=args.url,
            storage_state_path=storage_state_path,
            artifacts_dir=artifacts_dir,
            headless=True,
            timeout_ms=args.timeout_ms,
        ) as browser_client:
            if not browser_client.page:
                logger.error("Failed to initialize browser")
                return 1
            
            # Log in to establish session
            logger.info("Logging in to establish session...")
            if args.username and args.password and args.domain:
                browser_client.login_with_credentials(args.username, args.password, args.domain)
            else:
                # Try to use storage_state, but if it's empty, need credentials
                try:
                    browser_client.page.goto(args.url, wait_until="load", timeout=args.timeout_ms)
                except Exception as e:
                    logger.warning("Page load timeout: %s (continuing with API)", e)
                time.sleep(1)  # Wait for session to settle
            
            # Use browser's fetch API for authenticated calls
            results = []
            try:
                # Create subscription
                create_res = browser_client.api_call(
                    {"command": "CreateSubscription"},
                    csrf_token=args.csrf_token,
                )
                logger.info("CreateSubscription response: %s", create_res)
                handle = create_res.get("CreateSubscriptionRes", {}).get("handle")
                if not handle:
                    if "ERROR_LOGGED_OUT" in str(create_res):
                        logger.error("Session ser ut til † v‘re utg†tt. Kj›r 'login' p† nytt eller oppgi credentials.")
                    else:
                        logger.error("Failed to create subscription: %s", create_res)
                    return 1
                
                # Add property paths
                add_res = browser_client.api_call({
                    "command": "AddToSubscription",
                    "handle": int(handle),
                    "propertyPaths": property_paths
                }, csrf_token=args.csrf_token)
                logger.info("AddToSubscription returned %d items", len(add_res.get("AddToSubscriptionRes", {}).get("items", [])))
                
                # Read values
                read_res = browser_client.api_call({
                    "command": "ReadSubscription",
                    "handle": int(handle)
                }, csrf_token=args.csrf_token)
                items = read_res.get("ReadSubscriptionRes", {}).get("items", [])
                logger.info("ReadSubscription returned %d items", len(items))
                
                # Process and log results
                for item in items:
                    index = item.get("index")
                    prop = item.get("property", {})
                    value = prop.get("value")
                    unit = prop.get("unitDisplayName", "")
                    forced = prop.get("forced", False)
                    status = prop.get("status", "")
                    
                    # Decode hex value if present
                    decoded_value = None
                    if isinstance(value, str) and value.startswith("0x"):
                        decoded_value = hex_to_float(value)
                    
                    # Find property path from index
                    idx_offset = index - 253
                    if 253 <= index < 253 + len(property_paths):
                        path = property_paths[idx_offset]
                    else:
                        path = f"Index {index}"
                    payload = {
                        "index": index,
                        "path": path,
                        "value": decoded_value if decoded_value is not None else value,
                        "raw_value": value,
                        "unit": unit,
                        "forced": forced,
                        "status": status,
                        "action": "api-read",
                        "success": True,
                        "message": "API read",
                    }
                    log_action(log_path, payload)
                    logger.info("%s = %s %s", path, decoded_value if decoded_value is not None else value, unit)
                    results.append(payload)
                
                return 0 if results else 1
                
            except Exception as e:
                logger.error("API call failed: %s", e)
                logger.exception("Full traceback:")
                return 1

    if args.command == "gui":
        from .gui import HVACRobotGUI  # pylint: disable=import-outside-toplevel
        from PyQt6.QtWidgets import (  # pylint: disable=import-outside-toplevel,no-name-in-module
            QApplication as QtApp,
        )
        app = QtApp([])
        window = HVACRobotGUI()
        window.show()
        return app.exec()

    if args.command in {"force", "unforce", "read", "batch", "auto"} \
            and not storage_state_path.exists():
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
            # Prefer CLI args, otherwise fall back to environment variables or secrets.json
            creds = _load_credentials_from_env_or_file()
            username = args.username or creds.get("username")
            password = args.password or creds.get("password")
            domain = args.domain or creds.get("domain")

            if username and password and domain:
                logger.info("Logging in with provided credentials (CLI/env/secrets.json)")
                client.login_with_credentials(username, password, domain)
                logger.info("Programmatic login successful")
            else:
                logger.info("No credentials provided; falling back to interactive login")
                client.login_and_save_state()
            # Save session state
            client.save_session_state()
            logger.info("Storage state lagret til %s", storage_state_path)
            cookies = client.get_cookies()
            logger.info("Captured %d cookies", len(cookies))
            return 0

        if args.command == "unforce":
            result = client.unforce_point(args.point)
            payload = {
                "point": result.point,
                "value": result.value,
                "success": result.success,
                "message": result.message,
                "screenshot": result.screenshot_path,
                "updated_value": result.updated_value,
                "action": "unforce",
            }
            log_action(log_path, payload)
            if result.success:
                logger.info("Unforce OK: %s", result.point)
                return 0
            logger.error("Unforce feilet: %s", result.message)
            return 1

        if args.command == "read":
            result = client.read_point(args.point)
            payload = {
                "point": result.point,
                "value": result.value,
                "success": result.success,
                "message": result.message,
                "screenshot": result.screenshot_path,
                "updated_value": result.updated_value,
                "action": "read",
            }
            log_action(log_path, payload)
            if result.success:
                logger.info("Read OK: %s=%s", result.point, result.updated_value)
                return 0
            logger.error("Read feilet: %s", result.message)
            return 1

        if args.command == "batch":
            operations = load_batch_config(Path(args.config))
            exit_code = 0
            for op in operations:
                action = str(op.get("action", "force")).lower()
                point = op.get("point")
                value = op.get("value")
                if not point:
                    logger.error("Ugyldig operasjon i config: %s", op)
                    exit_code = 1
                    continue
                if action not in {"force", "unforce", "read"}:
                    logger.error("Ugyldig action i config: %s", op)
                    exit_code = 1
                    continue
                if action == "force" and value is None:
                    logger.error("Ugyldig operasjon i config: %s", op)
                    exit_code = 1
                    continue
                for attempt in range(1, args.retries + 1):
                    if action == "force":
                        result = client.force_point(
                            str(point), str(value), dry_run=args.dry_run
                        )
                    elif action == "unforce":
                        result = client.unforce_point(str(point))
                    else:
                        result = client.read_point(str(point))
                    payload = {
                        "point": result.point,
                        "value": result.value,
                        "success": result.success,
                        "message": result.message,
                        "screenshot": result.screenshot_path,
                        "dry_run": args.dry_run,
                        "attempt": attempt,
                        "updated_value": result.updated_value,
                        "action": action,
                    }
                    log_action(log_path, payload)
                    if result.success:
                        logger.info(
                            "%s OK: %s=%s (fors?k %s)",
                            action.capitalize(),
                            result.point,
                            result.updated_value if action == "read" else result.value,
                            attempt,
                        )
                        break
                    logger.error(
                        "%s feilet for %s (fors?k %s): %s",
                        action.capitalize(),
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

        if args.command == "auto":
            state_override = Path(args.state_path) if args.state_path else None
            return run_controller(
                client,
                config_path=Path(args.config),
                log_path=log_path,
                once=args.once,
                dry_run_override=args.dry_run if args.dry_run else None,
                state_path_override=state_override,
                cycle_seconds_override=args.cycle_seconds,
                cooldown_seconds_override=args.cooldown_seconds,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
