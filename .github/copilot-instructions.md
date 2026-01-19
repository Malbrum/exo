# Bravida Cloud RPA - AI Copilot Instructions

## Architecture Overview

**Purpose**: UI automation tool for forcing/reading point values in Bravida Cloud via browser automation (Playwright).

**Key Components**:
- [src/main.py](../src/main.py): CLI entry point with five command modes (login, force, unforce, read, batch)
- [src/bravida_client.py](../src/bravida_client.py): Core Playwright wrapper managing browser context, dialogs, and UI interactions
- [src/selectors.py](../src/selectors.py): Centralized DOM selectors and button text constants for Bravida Cloud UI
- [src/logging_utils.py](../src/logging_utils.py): Dual logging to file (JSONL actions + text logs) and console

**Data Flow**: CLI args → `main.parse_args()` → `BravidaClient` context manager → Operation method (force/unforce/read) → `ForceResult` dataclass → Logging (JSONL + text)

## Critical Patterns & Conventions

### Command Structure
All operations use named arguments, not positional:
```bash
python -m src.main force --point 360.005-JV40_Pos --value 30
python -m src.main batch --config config.json --retries 3 --backoff-seconds 2.0
```
Batch config is always JSON with `{"operations": [{...}]}` or plain array of objects with `action`, `point`, `value` (if force).

### Browser Context Management
`BravidaClient` uses context manager (`__enter__`/`__exit__`) to manage Playwright lifecycle:
- Storage state persisted in `state/bravida_storage_state.json` for SSO sessions
- Viewport fixed at 1400×900 (critical for UI stability)
- Default headful mode (headless only on `--headless` flag)
- Timeout configurable per-instance (default 30s)

### Error Handling & Resilience
- Operations wrap UI interactions in try-except catching `PlaywrightTimeoutError`, `PlaywrightError`, `RuntimeError`
- Batch mode automatically retries per-operation with exponential backoff: `backoff = base * attempt`
- Failures capture full-page screenshots to `artifacts/` for debugging
- All results return `ForceResult` dataclass (always succeeds structurally, check `.success` bool)

### Selector Strategy (src/selectors.py)
UI locators are fragile and versioned:
- `FORCE_TOGGLE_SELECTOR = "button.toggleButton[aria-pressed='false']"` (prefer CSS attributes)
- `INPUT_SELECTORS` list tried in order (dual-text → number → text) for flexibility across point types
- Text-based locators use `get_by_text()` with `exact=True/False` for robustness
- Dialog role detection: `get_by_role(DIALOG_ROLE)` to wait for modal

### Logging & Observability
Two log streams:
1. **JSONL** (`logs/bravida_actions.jsonl`): Structured per-operation with `timestamp`, `action`, `point`, `value`, `success`, `message`, `attempt` (batch), `screenshot` (on failure), `dry_run`
2. **Text log** (`logs/bravida_rpa.log`): Human-readable messages to console + file

Failure screenshots auto-saved with pattern `failure_<point>_<timestamp>.png` for forensics.

## Developer Workflows

### Setup
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install
```

### First Login (Interactive)
```bash
python -m src.main login
# Opens headful browser, waits for manual SSO/MFA, saves session to state/bravida_storage_state.json
```

### Testing Single Operations
```bash
python -m src.main force --point 360.005-JV40_Pos --value 30 --dry-run  # Preview without clicking OK
python -m src.main read --point 360.005-JV40_Pos  # Verify current value
python -m src.main unforce --point 360.005-JV40_Pos  # Release force
```

### Batch Automation
1. Create `config.json` with operation list
2. Run `python -m src.main batch --config config.json --dry-run` to preview
3. Run without `--dry-run` to execute with auto-retry (3 attempts, 2s backoff by default)

### Debugging
- Check `logs/bravida_rpa.log` for error context
- Review `logs/bravida_actions.jsonl` for structured action history
- Inspect `artifacts/*.png` screenshots on failures (marked with point + timestamp)
- Increase `--timeout-ms` if network is slow (default 30000ms)

## Integration Points & Dependencies

### Playwright (v1.40.0+)
- Sync API (not async) – all methods block
- Chrome browser hardcoded (`playwright.chromium`)
- Storage state serialization for session persistence
- Network waits via `wait_until="networkidle"` on all navigation

### External System: Bravida Cloud
- Base URL: Default `https://bracloud.bravida.no/#/NO%20Røa%20Bad%20360.005/360.005/360.005` (overridable)
- SSO/MFA required – no credential automation, interactive login only
- Dialog modal workflow: click point → open dialog → interact (force/unforce/read) → click OK/Cancel → confirm close
- Point names: format like `360.005-JV40_Pos` with optional short-name fallback (e.g., `JV40_Pos`)

## Adding Features

### New Operation Type
1. Add subparser in `main.parse_args()` with required args
2. Implement method in `BravidaClient` returning `ForceResult`
3. Call method in `main()` within context manager, log result via `log_action()`
4. Add selectors to [src/selectors.py](../src/selectors.py) if UI interaction differs

### New Batch Feature
- Extend JSON config schema → validate in `load_batch_config()`
- Update batch loop in `main()` to handle new operation types
- Log all outcomes (success/failure/attempt) to JSONL with same schema

### Selector Update (UI Fragility)
- Prioritize CSS selectors with attributes over text matching where possible
- Test multiple fallback locators in `INPUT_SELECTORS` array
- Use `exact=True` for point name guards; `exact=False` for flexible search
- Update [src/selectors.py](../src/selectors.py) constants, not hardcoded strings
