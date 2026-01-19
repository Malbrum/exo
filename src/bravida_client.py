"""Playwright wrapper for automating Bravida Cloud UI."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import (  # type: ignore
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    expect,
    sync_playwright,
)

from .selectors import (
    CANCEL_BUTTON_TEXT,
    DIALOG_ROLE,
    FORCE_BUTTON_TEXT,
    INPUT_SELECTORS,
    OK_BUTTON_TEXT,
)


@dataclass
class ForceResult:
    point: str
    value: str
    success: bool
    message: str
    screenshot_path: Optional[str] = None


class BravidaClient:
    def __init__(
        self,
        base_url: str,
        storage_state_path: Path,
        artifacts_dir: Path,
        headless: bool = False,
        timeout_ms: int = 30_000,
    ) -> None:
        self.base_url = base_url
        self.storage_state_path = storage_state_path
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.artifacts_dir = artifacts_dir
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self) -> "BravidaClient":
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        context_args = {"viewport": {"width": 1400, "height": 900}}
        if self.storage_state_path.exists():
            context_args["storage_state"] = str(self.storage_state_path)
        self.context = self.browser.new_context(**context_args)
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def login_and_save_state(self) -> None:
        if not self.page:
            raise RuntimeError("Playwright page not initialized.")
        self.page.goto(self.base_url, wait_until="networkidle")
        input(
            "Fullfør innlogging i nettleseren, og trykk Enter her når du er ferdig..."
        )
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.context:
            raise RuntimeError("Playwright context not initialized.")
        self.context.storage_state(path=str(self.storage_state_path))

    def force_point(self, point_name: str, value: str, dry_run: bool = False) -> ForceResult:
        if not self.page:
            raise RuntimeError("Playwright page not initialized.")
        try:
            self.page.goto(self.base_url, wait_until="networkidle")
            dialog = self.open_point_dialog(point_name)
            self._guard_dialog_point(dialog, point_name)

            force_button = dialog.get_by_role("button", name=FORCE_BUTTON_TEXT)
            force_button.click()

            value_input = self._wait_for_force_input(dialog)
            value_input.fill(str(value))

            ok_button = dialog.get_by_role("button", name=OK_BUTTON_TEXT)
            if not ok_button.is_enabled():
                raise RuntimeError("OK-knappen er deaktivert, avbryter.")

            if dry_run:
                return ForceResult(
                    point=point_name,
                    value=str(value),
                    success=True,
                    message="Dry-run: ville ha klikket OK.",
                )

            ok_button.click()
            dialog.wait_for(state="detached", timeout=self.timeout_ms)
            return ForceResult(
                point=point_name,
                value=str(value),
                success=True,
                message="Force gjennomført.",
            )
        except (PlaywrightTimeoutError, PlaywrightError, RuntimeError) as exc:
            screenshot = self._capture_failure(point_name)
            return ForceResult(
                point=point_name,
                value=str(value),
                success=False,
                message=str(exc),
                screenshot_path=screenshot,
            )

    def open_point_dialog(self, point_name: str) -> "object":
        if not self.page:
            raise RuntimeError("Playwright page not initialized.")
        short_name = point_name.split("-")[-1]
        candidates = [point_name]
        if short_name != point_name:
            candidates.append(short_name)

        last_error: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                for candidate in candidates:
                    row = self.page.locator("tr", has_text=candidate).first
                    if row.count() > 0:
                        row.click()
                        break
                    cell = self.page.get_by_text(candidate, exact=False).first
                    if cell.count() > 0:
                        cell.click()
                        break
                dialog = self.page.get_by_role(DIALOG_ROLE).first
                dialog.wait_for(state="visible", timeout=self.timeout_ms)
                return dialog
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                last_error = exc
                time.sleep(attempt)
        raise RuntimeError(f"Klarte ikke å åpne dialog for {point_name}: {last_error}")

    def _guard_dialog_point(self, dialog, point_name: str) -> None:
        point_locator = dialog.get_by_text(point_name, exact=True)
        expect(point_locator).to_be_visible(timeout=self.timeout_ms)

    def _wait_for_force_input(self, dialog):
        for selector in INPUT_SELECTORS:
            locator = dialog.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=self.timeout_ms)
                return locator
            except PlaywrightTimeoutError:
                continue
        raise RuntimeError("Fant ikke inputfelt for force-verdi.")

    def _capture_failure(self, point_name: str) -> Optional[str]:
        if not self.page:
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.artifacts_dir / f"failure_{point_name}_{timestamp}.png"
        self.page.screenshot(path=str(file_path), full_page=True)
        return str(file_path)
