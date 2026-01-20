# Bravida Cloud RPA (UI-automatisering)

Produksjonsklart UI-automatiseringsverktøy for å force punktverdier i Bravida Cloud via nettleser (Playwright).

## Krav
- Windows (lokal drift-PC)
- Python 3.11+
- Playwright (sync API)

## Installasjon

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install
```

## Førstegangs login (manuell)

Åpner nettleseren headful, lar deg logge inn via SSO/MFA, og lagrer session state.

```bash
python -m src.main login
```

Storage state lagres i `state/bravida_storage_state.json`.

## Force enkel verdi

```bash
python -m src.main force --point 360.005-JV40_Pos --value 30
python -m src.main force --point 360.005-JV50_Pos --value 35
```

## Unforce og read

```bash
python -m src.main unforce --point 360.005-JV50_Pos
python -m src.main read --point 360.005-JV50_Pos
```

## Batch-modus

Eksempel `config.json`:

```json
{
  "operations": [
    {"point": "360.005-JV40_Pos", "value": 30, "action": "force"},
    {"point": "360.005-JV50_Pos", "action": "unforce"},
    {"point": "360.005-JV60_Pos", "action": "read"}
  ]
}
```

Kjør batch:

```bash
python -m src.main batch --config config.json
```

## Automatisk HVAC-kontroll

Eksempelkonfigurasjon: `config/hvac_controller.json`

Kj›r kontinuerlig kontroll:

```bash
python -m src.main auto --config config/hvac_controller.json
```

Kontrolleren st›tter RH, kondensrisiko og luftkvalitet (CO/CO2) basert p† config.

Kj›r en enkelt evaluering (ingen loop):

```bash
python -m src.main auto --config config/hvac_controller.json --once
```

Overstyr intervall, cooldown eller dry-run:

```bash
python -m src.main auto --config config/hvac_controller.json --cycle-seconds 300 --cooldown-seconds 600 --dry-run
```

## Dry-run (sikkerhetsmodus)

Kjører hele flyten frem til rett før OK (ingen endring blir bekreftet).

```bash
python -m src.main force --point 360.005-JV40_Pos --value 30 --dry-run
python -m src.main batch --config config.json --dry-run
```

## Logger og screenshots

- Logg (JSONL): `logs/bravida_actions.jsonl`
- Generell logg: `logs/bravida_rpa.log`
- Feil-screenshots: `artifacts/`
- JSONL inkluderer `action` og `updated_value` per operasjon.

## Tips
- Standard URL kan overstyres med `--url`.
- Storage state kan overstyres med `--storage-state`.
- Default er headful. Bruk `--headless` ved behov.
