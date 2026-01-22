"""Playwright wrapper for automating Bravida Cloud UI."""
from __future__ import annotations

import json
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
    FORCE_TOGGLE_SELECTOR,
    INPUT_SELECTORS,
    OK_BUTTON_TEXT,
    UNFORCE_BUTTON_TEXT,
)


@dataclass
class ForceResult:
    point: str
    value: str
    success: bool
    message: str
    screenshot_path: Optional[str] = None
    updated_value: Optional[str] = None


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
        context_args = {
            "viewport": {"width": 1400, "height": 900},
            "ignore_https_errors": True,  # Accept self-signed certs
        }
        if self.storage_state_path.exists():
            context_args["storage_state"] = str(self.storage_state_path)
            print(f"DEBUG: Loading storage_state from {self.storage_state_path}")
        self.context = self.browser.new_context(**context_args)
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        cookies = self.context.cookies()
        cookie_names = [c['name'] for c in cookies[:5]]
        print(f"DEBUG: Context has {len(cookies)} cookies after __enter__: {cookie_names}")
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
        self.page.goto(self.base_url, wait_until="load")
        input(
            "Fullfør innlogging i nettleseren, og trykk Enter her når du er ferdig..."
        )
        # Wait additional time for cookies to be set by JavaScript
        time.sleep(3)
    
    def login_with_credentials(self, username: str, password: str, domain: str) -> None:
        """Programmatic login using credentials with CSRF token and challenge-response flow."""
        if not self.page:
            raise RuntimeError("Playwright page not initialized.")
        # Navigate to login page
        self.page.goto("https://bracloud.bravida.no/login.html", wait_until="load")
        time.sleep(3)  # Wait for login.js to fully execute and attach event handlers
        
        # Wait for page to be fully interactive (body has loginPageLoaded class)
        try:
            self.page.locator("body.loginPageLoaded").wait_for(state="visible", timeout=10000)
            print("DEBUG: Login page fully loaded")
        except PlaywrightTimeoutError:
            print("WARNING: Login page may not be fully loaded, proceeding anyway")
        
        # Fill in credentials using correct ID selectors
        self.page.fill("#txtUserID", username)
        self.page.fill("#txtPassWord", password)
        self.page.fill("#txtDomainName", domain)
        print(f"DEBUG: Filled credentials (user: {username})")
        
        # Submit form - call the JavaScript login handler directly
        # This is more reliable than clicking the button
        # The JavaScript flow is: self.send(user, pass, domain) → Q() → nt() → P.login()
        print("DEBUG: Submitting login form via JavaScript...")
        
        # Get the input values
        user_value = self.page.locator("#txtUserID").input_value()
        pass_value = self.page.locator("#txtPassWord").input_value()
        domain_value = self.page.locator("#txtDomainName").input_value()
        
        # Wait for the /webstation/vp/Login API call
        # We hook this before calling send() to catch the API request
        try:
            with self.page.expect_response(
                lambda resp: "webstation/vp/Login" in resp.url and resp.status == 200,
                timeout=self.timeout_ms
            ) as response_info:
                # Call the JavaScript send() function which was exposed by login.js
                # self.send = (t, e, n) => nt(t, e, n)
                self.page.evaluate(f"self.send('{user_value}', '{pass_value}', '{domain_value}')")
                print("DEBUG: JavaScript send() function called")
            
            print(f"DEBUG: /vp/Login API call received (status {response_info.value.status})")
        except PlaywrightTimeoutError as e:
            print("DEBUG: Timeout waiting for /vp/Login. Checking page state...")
            print(f"DEBUG: Current URL: {self.page.url}")
            print(f"DEBUG: Page title: {self.page.title()}")
            raise RuntimeError(
                f"Login did not trigger API call: {e}"
            ) from e
        
        # Wait for the redirect to happen after login succeeds
        # The U() function calls location.assign() which may redirect differently
        print("DEBUG: Waiting for page redirect after successful API call...")
        
        # Wait for either a navigation event or network activity
        try:
            self.page.wait_for_url("**/*", timeout=10000)  # Wait for URL change
        except PlaywrightTimeoutError:
            print("WARNING: URL did not change within 10s, checking current state...")
        
        # Also wait for network to settle
        try:
            self.page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeoutError:
            print("WARNING: networkidle timeout after API call")
        
        time.sleep(2)  # Extra grace period for session to be fully established
        
        # Check current state
        current_url = self.page.url
        current_title = self.page.title()
        print(f"DEBUG: After login, current URL: {current_url}")
        print(f"DEBUG: After login, page title: {current_title}")
        
        # CRITICAL: Do NOT navigate away!
        # The HttpOnly cookies from /vp/Login are set on bracloud.bravida.no/
        # but the page is still on login.html. When we navigate elsewhere, we might
        # lose the session context.
        # Instead, navigate to the app URL but stay on same domain so cookies persist
        
        # The page title is already "Building Operation WorkStation" which suggests
        # the session IS valid. The API should work now.
        print("DEBUG: Authenticated session established (page title changed)")
        
        # Navigate to the app URL WITH the base_url hash to load the actual app
        # This ensures the app JavaScript loads and initializes properly
        print(f"DEBUG: Navigating to app URL with hash: {self.base_url}")
        self.page.goto(self.base_url, wait_until="networkidle", timeout=self.timeout_ms)
        time.sleep(2)  # Extra wait for app to initialize
    
    def save_session_state(self) -> None:
        """Save session state to storage_state.json."""
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.context:
            raise RuntimeError("Playwright context not initialized.")
        self.context.storage_state(path=str(self.storage_state_path))
    
    def get_cookies(self) -> list:
        """Return active cookies from the current context."""
        if not self.context:
            raise RuntimeError("Playwright context not initialized.")
        return self.context.cookies()
    
    def api_call(self, payload: dict) -> dict:
        """Make an authenticated API call using the browser's session."""
        if not self.page:
            raise RuntimeError("Playwright page not initialized.")
        
        # Try using Playwright's native request context first (better session handling)
        try:
            print("DEBUG: Attempting API call with page.request...")
            response = self.page.request.post(
                "https://bracloud.bravida.no/json/POST",
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"}
            )
            result = response.json()
            print(f"DEBUG: page.request returned: {list(result.keys())}")
            return result
        except Exception as e:
            print(f"DEBUG: page.request failed: {e}, falling back to page.evaluate()")
        
        # Fallback to page.evaluate() with fetch
        csrf_token = None
        try:
            csrf_elem = self.page.locator("#csrf").first
            if csrf_elem.count() > 0:
                csrf_token = csrf_elem.input_value()
                print(f"DEBUG: CSRF token found: {csrf_token[:20]}...")
        except Exception as e:
            print(f"DEBUG: Could not extract CSRF token: {e}")
        
        script = f"""
        async () => {{
            const headers = {{'Content-Type': 'application/json'}};
            const csrfToken = document.getElementById('csrf')?.value;
            if (csrfToken) {{
                headers['X-CSRF-Token'] = csrfToken;
            }}
            const response = await fetch('https://bracloud.bravida.no/json/POST', {{
                method: 'POST',
                headers: headers,
                body: JSON.stringify({json.dumps(payload)}),
                credentials: 'include'
            }});
            const text = await response.text();
            try {{
                return JSON.parse(text);
            }} catch (e) {{
                return {{error: 'Response is not JSON', status: response.status, body: text.substring(0, 200)}};
            }}
        }}
        """
        result = self.page.evaluate(script)
        return result

    def force_point(self, point_name: str, value: str, dry_run: bool = False) -> ForceResult:
        if not self.page:
            raise RuntimeError("Playwright page not initialized.")
        try:
            self.page.goto(self.base_url, wait_until="networkidle")
            dialog = self.open_point_dialog(point_name)
            self._guard_dialog_point(dialog, point_name)

            force_button = self._get_force_button(dialog)
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
            updated_value = self._read_value(dialog)
            dialog.wait_for(state="detached", timeout=self.timeout_ms)
            return ForceResult(
                point=point_name,
                value=str(value),
                success=True,
                message="Force gjennomført.",
                updated_value=updated_value,
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

    def unforce_point(self, point_name: str) -> ForceResult:
        if not self.page:
            raise RuntimeError("Playwright page not initialized.")
        try:
            self.page.goto(self.base_url, wait_until="networkidle")
            dialog = self.open_point_dialog(point_name)
            self._guard_dialog_point(dialog, point_name)

            unforce_button = dialog.get_by_text(UNFORCE_BUTTON_TEXT).first
            unforce_button.click()

            ok_button = dialog.get_by_role("button", name=OK_BUTTON_TEXT)
            if not ok_button.is_enabled():
                raise RuntimeError("OK-knappen er deaktivert, avbryter.")

            ok_button.click()
            updated_value = self._read_value(dialog)
            dialog.wait_for(state="detached", timeout=self.timeout_ms)
            return ForceResult(
                point=point_name,
                value="",
                success=True,
                message="Force sluppet.",
                updated_value=updated_value,
            )
        except (PlaywrightTimeoutError, PlaywrightError, RuntimeError) as exc:
            screenshot = self._capture_failure(point_name)
            return ForceResult(
                point=point_name,
                value="",
                success=False,
                message=str(exc),
                screenshot_path=screenshot,
            )

    def read_point(self, point_name: str) -> ForceResult:
        if not self.page:
            raise RuntimeError("Playwright page not initialized.")
        try:
            self.page.goto(self.base_url, wait_until="networkidle")
            dialog = self.open_point_dialog(point_name)
            self._guard_dialog_point(dialog, point_name)

            updated_value = self._read_value(dialog)
            cancel_button = dialog.get_by_role("button", name=CANCEL_BUTTON_TEXT)
            cancel_button.click()
            dialog.wait_for(state="detached", timeout=self.timeout_ms)
            return ForceResult(
                point=point_name,
                value="",
                success=True,
                message="Verdi lest.",
                updated_value=updated_value,
            )
        except (PlaywrightTimeoutError, PlaywrightError, RuntimeError) as exc:
            screenshot = self._capture_failure(point_name)
            return ForceResult(
                point=point_name,
                value="",
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
                clicked = False
                for candidate in candidates:
                    row = self.page.locator("tr", has_text=candidate).first
                    if row.count() > 0:
                        row.scroll_into_view_if_needed()
                        row.click()
                        time.sleep(0.5)  # Wait for dialog to appear
                        clicked = True
                        break
                    cell = self.page.get_by_text(candidate, exact=False).first
                    if cell.count() > 0:
                        cell.scroll_into_view_if_needed()
                        cell.click()
                        time.sleep(0.5)  # Wait for dialog to appear
                        clicked = True
                        break
                
                if not clicked:
                    # Take screenshot if we couldn't even click
                    self._capture_failure(f"{point_name}_click_failed")
                    raise RuntimeError(f"Could not find clickable element for {point_name}")
                
                # Try multiple ways to find dialog
                dialog = self.page.get_by_role(DIALOG_ROLE).first
                try:
                    dialog.wait_for(state="visible", timeout=5000)
                except PlaywrightTimeoutError:
                    # If role-based lookup fails, try other selectors
                    dialog = self.page.locator("div.modal, div[role='dialog'], .dialog").first
                    dialog.wait_for(state="visible", timeout=5000)
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

    def _read_value(self, dialog) -> str:
        value_input = self._wait_for_force_input(dialog)
        return value_input.input_value()

    def _get_force_button(self, dialog):
        selector_button = dialog.locator(FORCE_TOGGLE_SELECTOR).first
        if selector_button.count() > 0:
            return selector_button
        return dialog.get_by_role("button", name=FORCE_BUTTON_TEXT)

    def _capture_failure(self, point_name: str) -> Optional[str]:
        if not self.page:
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.artifacts_dir / f"failure_{point_name}_{timestamp}.png"
        self.page.screenshot(path=str(file_path), full_page=True)
        return str(file_path)
