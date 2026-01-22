"""Direct HTTP API client for Bravida/Schneider EcoStruxure Building Operation."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Property paths captured from the AddToSubscription payload (indices returned by the
# server will be mapped back to these paths).
DEFAULT_PROPERTY_PATHS: List[str] = [
    "/NO Røa Bad 360.005/360.005/DESCR",
    "/NO Røa Bad 360.005/360.005/NOTE1",
    "/NO Røa Bad 360.005/360.005/Alarmer/CO250_Halm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/CO250_Halm/HighLimit",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-CO250/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/CO50_Halm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/CO50_Halm/HighLimit",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-CO50/Value",
    "/NO Røa Bad 360.005/360.005/Tidsskjema/TcSmrMd/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/ViTemp/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/Avfrost/Value",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-JP40_Cmd/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/JP40_StopLmt/Value",
    "/NO Røa Bad 360.005/360.005/Variabler eksterne/360.005-JV40_Cmd/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/JV40_FboAlm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Variabler/JV40_FltDly/Value",
    "/NO Røa Bad 360.005/360.005/Variabler eksterne/360.005-JV40_Pos/Value",
    "/NO Røa Bad 360.005/360.005/Variabler eksterne/360.005-JV40_Ri/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/JV40_RiAlm/AlarmState",
    "/NO Røa Bad 360.005/BACnet Interface/Application/Variabler/JV_SptMaks/Value",
    "/NO Røa Bad 360.005/BACnet Interface/Application/Variabler/JV_SptMin/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/JV40_SumAlm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Variabler eksterne/360.005-JV50_Cmd/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/JV50_FboAlm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Variabler/JV50_FltDly/Value",
    "/NO Røa Bad 360.005/360.005/Variabler eksterne/360.005-JV50_Pos/Value",
    "/NO Røa Bad 360.005/360.005/Variabler eksterne/360.005-JV50_Ri/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/JV50_RiAlm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/JV50_SumAlm/AlarmState",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-KA40_Pos/Value",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-KA41AB_Pos/Value",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-KA42_Pos/Value",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-KA50_Pos/Value",
    "/NO Røa Bad 360.005/BACnet Interface/Application/Variabler/ManCmd/Value",
    "/NO Røa Bad 360.005/360.005/Program/Applikasjon/ÅtStart",
    "/NO Røa Bad 360.005/360.005/Alarmer/QD40_Alm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/QD50_Alm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Variabler/AfrMxFbg/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/AfrMxt/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/AfrRaHa/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/FörlAfr_Dly/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/QD51_Alm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/RF50_Halm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/RF50_Halm/HighLimit",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-RF50/Value",
    "/NO Røa Bad 360.005/BACnet Interface/Application/Variabler/MaTiTe/Value",
    "/NO Røa Bad 360.005/BACnet Interface/Application/Variabler/MiTiTe/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT40_Falm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT40_Halm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT40_Halm/HighDiffLimit",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT40_Lalm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT40_Lalm/LowDiffLimit",
    "/NO Røa Bad 360.005/360.005/Variabler/RT40_SptCalc/Value",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-RT40/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT50_Alm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT50_Falm/AlarmState",
    "/NO Røa Bad 360.005/BACnet Interface/Application/Variabler/RT50_Spt/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/RT50_SptCalc/Value",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-RT50/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT55_Falm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT55_FrstDetAlm/AlarmState",
    "/NO Røa Bad 360.005/360.005/Variabler/RT55_Llmt/Value",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-RT55/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/RT55MIN_Spt/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/RT55RET_Spt/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/RT90_Falm/AlarmState",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-RT90/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/RY40_Alm/AlarmState",
    "/NO Røa Bad 360.005/IO Bus/AS-B-36 onboard IO/360.005-SB40_Pos/Value",
    "/NO Røa Bad 360.005/360.005/Variabler/SB40_Min/Value",
    "/NO Røa Bad 360.005/360.005/Alarmer/SB40MIN_Alm/AlarmState",
]


def hex_to_float(value: str) -> Optional[float]:
    """Decode an IEEE-754 hex string (e.g. 0x4043800000000000) to float."""
    if not isinstance(value, str) or not value.startswith("0x"):
        return None
    try:
        return struct.unpack(">d", int(value, 16).to_bytes(8, "big"))[0]
    except (ValueError, OverflowError, struct.error):
        return None


class BravidaAPIClient:
    """Small helper around /json/POST to read point values."""

    def __init__(
        self,
        base_url: str,
        storage_state_path: Path,
        csrf_token: Optional[str] = None,
        playwright_cookies: Optional[list] = None,
    ) -> None:
        # Strip hash fragment and path from URL - API is always at base domain
        if "#" in base_url:
            base_url = base_url.split("#")[0]
        self.base_url = base_url.rstrip("/")
        self.storage_state_path = Path(storage_state_path)
        self.csrf_token = csrf_token
        self.session = requests.Session()
        self._index_to_path: Dict[int, str] = {}
        if playwright_cookies:
            self._load_playwright_cookies(playwright_cookies)
        else:
            self._load_cookies()

    def _load_playwright_cookies(self, cookies: list) -> None:
        """Load cookies from Playwright context."""
        for cookie in cookies:
            self.session.cookies.set(
                cookie.get("name"),
                cookie.get("value"),
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )
            if cookie.get("name") in ["CSP", "JSESSIONID", "BRAVIDA"]:
                print(f"DEBUG: Loaded Playwright cookie {cookie.get('name')} = {cookie.get('value')[:20] if cookie.get('value') else 'None'}...")
            if not self.csrf_token and cookie.get("name") == "CSP":
                self.csrf_token = cookie.get("value")
        print(f"DEBUG: Loaded {len(cookies)} cookies from Playwright. CSRF token: {self.csrf_token[:20] if self.csrf_token else 'None'}...")

    def _load_cookies(self) -> None:
        data = json.loads(self.storage_state_path.read_text(encoding="utf-8"))
        cookie_count = 0
        for cookie in data.get("cookies", []):
            self.session.cookies.set(
                cookie.get("name"),
                cookie.get("value"),
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )
            cookie_count += 1
            if cookie.get("name") in ["CSP", "JSESSIONID", "BRAVIDA"]:
                print(f"DEBUG: Loaded cookie {cookie.get('name')} = {cookie.get('value')[:20] if cookie.get('value') else 'None'}...")
            if not self.csrf_token and cookie.get("name") == "CSP":
                # Heuristic: fall back to CSP cookie as CSRF token if not provided.
                self.csrf_token = cookie.get("value")
        print(f"DEBUG: Loaded {cookie_count} cookies total. CSRF token: {self.csrf_token[:20] if self.csrf_token else 'None'}...")

    def _headers(self) -> Dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "referer": self.base_url + "/",
        }
        if self.csrf_token:
            headers["x-csrf-token"] = str(self.csrf_token)
        return headers

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/json/POST",
            headers=self._headers(),
            json=payload,
            timeout=30,
            verify=False,  # Disable SSL verification (Bravida uses self-signed cert)
        )
        response.raise_for_status()
        return response.json()

    def create_subscription(self) -> int:
        data = self._post({"command": "CreateSubscription"})
        print(f"DEBUG CreateSubscription response: {data}")  # DEBUG
        res = data.get("CreateSubscriptionRes") or data
        handle = res.get("handle")
        if handle is None:
            raise RuntimeError(f"CreateSubscription did not return a handle. Response: {data}")
        return int(handle)

    def add_to_subscription(self, handle: int, property_paths: List[str]) -> Dict[int, str]:
        data = self._post(
            {
                "command": "AddToSubscription",
                "handle": handle,
                "propertyPaths": property_paths,
            }
        )
        res = data.get("AddToSubscriptionRes") or data
        items = res.get("items", [])
        mapping: Dict[int, str] = {}
        for item in items:
            idx = item.get("index")
            path = item.get("path")
            if idx is not None and path:
                mapping[int(idx)] = path
        self._index_to_path.update(mapping)
        return mapping

    def read_subscription(self, handle: int) -> List[Dict[str, Any]]:
        data = self._post({"command": "ReadSubscription", "handle": handle})
        res = data.get("ReadSubscriptionRes") or data
        return res.get("items", [])

    def read_values(self, property_paths: List[str]) -> List[Dict[str, Any]]:
        handle = self.create_subscription()
        index_map = self.add_to_subscription(handle, property_paths)
        items = self.read_subscription(handle)
        results: List[Dict[str, Any]] = []
        for item in items:
            idx = int(item.get("index")) if item.get("index") is not None else None
            prop = item.get("property", {})
            path = index_map.get(idx, self._index_to_path.get(idx, ""))
            decoded_value = hex_to_float(prop.get("value"))
            results.append(
                {
                    "index": idx,
                    "path": path,
                    "raw_value": prop.get("value"),
                    "value": decoded_value if decoded_value is not None else prop.get("value"),
                    "unit": prop.get("unitDisplayName"),
                    "forced": prop.get("forced"),
                    "status": prop.get("status"),
                }
            )
        return results
