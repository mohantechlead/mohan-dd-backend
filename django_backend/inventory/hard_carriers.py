"""Hard-carrier adapters that use curl_cffi TLS impersonation (no browser).

Heroku-safe: pure outbound HTTP with prebuilt wheels. No Chrome required.

Spike results (2026-10):
- MSC: WORKS. POST /api/feature/tools/TrackingInfo after warm-up GET.
- ESL (Ethiopian Shipping & Logistics): WORKS. GET
  esl.et/api/esl/api/unified-tracking/events returns the same DCSA-style JSON
  their tracking page uses (timeline, containers, route, milestones).
- Maersk: blocked by Akamai bot JS challenge (browser fallback / manual only).
- CMA CGM: blocked by DataDome (browser fallback / manual only).
- Hapag-Lloyd: blocked by Cloudflare Security Check (browser / manual only).

Enable/disable with CURL_CFFI_ENABLED=0.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from .carriers import ScrapedTransit

_MSC_HOME = "https://www.msc.com/en/track-a-shipment"
_MSC_API = "https://www.msc.com/api/feature/tools/TrackingInfo"
_MAERSK_HOME = "https://www.maersk.com/tracking"
_MAERSK_API = "https://api.maersk.com/synergy/tracking/{ref}?operator=MAEU"
# ESL publishes the same JSON its tracking page uses (no auth, no bot wall).
_ESL_API = (
    "https://esl.et/api/esl/api/unified-tracking/events"
    "?reference={ref}&limit=100&eventType=EQUIPMENT%2CTRANSPORT"
)
_ESL_HOME = "https://esl.et/en/tracking-unified"
# Public consumer key used by the Maersk tracking SPA (safe to override).
_MAERSK_CONSUMER_KEY = "UtMm6JCDcGTnMGErNGvS2B98kt1Wl25H"
# Heroku's router gives up after ~30 s, so use tighter per-request timeouts
# there (most adapters make two requests: warm-up + API).
_DEFAULT_TIMEOUT = 12 if os.environ.get("DYNO") else 25
_TIMEOUT = int(os.environ.get("BL_CARRIER_TIMEOUT_SEC", str(_DEFAULT_TIMEOUT)))


def _curl_cffi_enabled() -> bool:
    return os.environ.get("CURL_CFFI_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _map_msc_description(text: str) -> Optional[str]:
    """Map MSC free-text event description onto TRANSIT_STATUS_CHOICES."""
    low = (text or "").lower()
    if any(
        k in low
        for k in (
            "delivered",
            "cargo release",
            "picked up",
            "delivery complete",
            "empty returned",
        )
    ):
        return "delivered"
    if any(
        k in low
        for k in (
            "available for",
            "arrived at destination",
            "customs cleared",
            "ready for collection",
            "ready for pickup",
        )
    ):
        return "arrived"
    if any(
        k in low
        for k in (
            "discharged",
            "at destination",
            "destination port",
            "awaiting pickup",
            "awaiting delivery",
            "restow",
            "stripped",
        )
    ):
        return "at_destination"
    if any(k in low for k in ("tranship", "trans-ship", "via port", "on carriage")):
        return "at_transhipment"
    if any(
        k in low
        for k in (
            "loaded on",
            "on board",
            "vessel departed",
            "departed",
            "gate out",
            "loaded to vessel",
            "loaded",
            "in transit",
            "shipped",
        )
    ):
        return "in_transit"
    if any(
        k in low
        for k in (
            "gate in",
            "empty to shipper",
            "empty",
            "booked",
            "confirmed",
            "pending",
            "received",
            "stuffing",
            "empty returned to shipper",
        )
    ):
        return "pending"
    return None


def _parse_msc_date(value: str) -> Optional[str]:
    """MSC dates look like DD/MM/YYYY."""
    if not value or not isinstance(value, str):
        return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", value.strip())
    if not m:
        return None
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


def track_msc(reference: str) -> ScrapedTransit:
    """Track an MSC container/BL via their public tracking JSON API."""
    if not _curl_cffi_enabled():
        return ScrapedTransit(None, None, None, "curl_cffi disabled (CURL_CFFI_ENABLED=0).")
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return ScrapedTransit(
            None,
            None,
            None,
            "curl_cffi is not installed on this environment.",
        )

    ref = (reference or "").strip()
    if not ref:
        return ScrapedTransit(None, None, None, "No tracking reference provided.")

    session = cffi_requests.Session(impersonate="chrome124")
    try:
        session.get(
            _MSC_HOME,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            },
            timeout=_TIMEOUT,
        )
        resp = session.post(
            _MSC_API,
            json={"trackingNumber": ref, "trackingMode": "0"},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
                "Referer": _MSC_HOME,
                "Origin": "https://www.msc.com",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return ScrapedTransit(None, None, "msc-api", f"MSC tracking request failed: {exc}")

    if resp.status_code >= 400:
        return ScrapedTransit(
            None, None, "msc-api", f"MSC tracking returned HTTP {resp.status_code}."
        )

    try:
        payload = resp.json()
    except Exception:
        return ScrapedTransit(
            None, None, "msc-api", "MSC tracking returned a non-JSON response."
        )

    if not payload.get("IsSuccess"):
        return ScrapedTransit(
            None,
            None,
            "msc-api",
            "MSC could not find that reference (check the BL/container number).",
        )

    data = payload.get("Data") or {}
    bls = data.get("BillOfLadings") or []
    if not bls:
        return ScrapedTransit(
            None, None, "msc-api", "MSC returned no bill of lading data for that reference."
        )

    bl0 = bls[0]
    info = bl0.get("GeneralTrackingInfo") or {}
    origin = info.get("ShippedFrom") or ""
    destination = info.get("ShippedTo") or ""
    containers_info = bl0.get("ContainersInfo") or []

    # Prefer the first container that has events; fall back to first.
    container = next((c for c in containers_info if c.get("Events")), None)
    if container is None and containers_info:
        container = containers_info[0]
    container = container or {}

    events = sorted(container.get("Events") or [], key=lambda e: e.get("Order") or 0)
    last_event = events[-1] if events else None

    # Prefer an "actual" movement over empty-return admin events for status.
    status = None
    status_source = None
    for evt in reversed(events):
        desc = evt.get("Description") or ""
        mapped = _map_msc_description(desc)
        if mapped:
            status = mapped
            status_source = f"{desc} @ {evt.get('Location') or ''}".strip(" @")
            break

    # Vessel from last event that has Detail with a real vessel name.
    vessel_name = None
    for evt in reversed(events):
        detail = evt.get("Detail") or []
        if not detail:
            continue
        name = detail[0]
        if name and name.upper() not in {"LADEN", "EMPTY"}:
            vessel_name = name
            break

    eta_raw = container.get("PodEtaDate")
    eta_text = _parse_msc_date(eta_raw) if eta_raw else None

    detail_parts = []
    if status_source:
        detail_parts.append(status_source)
    if origin or destination:
        detail_parts.append(f"{origin or '?'} -> {destination or '?'}")
    if eta_text:
        detail_parts.append(f"ETA {eta_text}")
    if vessel_name:
        detail_parts.append(f"Vessel {vessel_name}")

    container_numbers = [c.get("ContainerNumber") for c in containers_info if c.get("ContainerNumber")]

    return ScrapedTransit(
        transit_status=status,
        status_detail="; ".join(detail_parts)[:500] if detail_parts else None,
        source="msc-api",
        error=None if status else "MSC data loaded but no known status phrase matched.",
        vessel_name=vessel_name,
        eta_text=eta_text,
        last_event=(
            f"{last_event.get('Description')} @ {last_event.get('Location')}"
            if last_event
            else None
        ),
        containers=container_numbers,
        details={
            "origin": origin or None,
            "destination": destination or None,
            "vessel_name": vessel_name,
            "eta": eta_text,
            "last_event": (
                f"{last_event.get('Description')} @ {last_event.get('Location')}"
                if last_event
                else None
            ),
            "containers": [
                {
                    "container_number": c.get("ContainerNumber"),
                    "size": c.get("ContainerSize") or "",
                    "type": c.get("ContainerType") or "",
                }
                for c in containers_info
                if c.get("ContainerNumber")
            ],
        },
    )


def track_maersk(reference: str) -> ScrapedTransit:
    """Try Maersk's SPA tracking API with TLS impersonation.

    Maersk protects api.maersk.com with Akamai bot manager. A browser sends
    ``Akamai-BM-Telemetry`` derived from their JS sensor. When that is not
    available (the normal case), the API returns 403 and callers fall back to
    the browser/remote-browser path.
    """
    if not _curl_cffi_enabled():
        return ScrapedTransit(None, None, "maersk-api", "curl_cffi disabled (CURL_CFFI_ENABLED=0).")
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return ScrapedTransit(
            None, None, "maersk-api", "curl_cffi is not installed on this environment."
        )

    ref = (reference or "").strip()
    if not ref:
        return ScrapedTransit(None, None, "maersk-api", "No tracking reference provided.")

    consumer_key = os.environ.get("MAERSK_CONSUMER_KEY", _MAERSK_CONSUMER_KEY).strip()
    telemetry = os.environ.get("MAERSK_BM_TELEMETRY", "").strip()
    session = cffi_requests.Session(impersonate="chrome131")
    try:
        # Warm-up: collect Akamai cookies set by the public page.
        session.get(
            f"{_MAERSK_HOME}/{ref}",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=_TIMEOUT,
        )
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Consumer-Key": consumer_key,
            "API-Version": "v2",
            "Origin": "https://www.maersk.com",
            "Referer": f"{_MAERSK_HOME}/{ref}",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if telemetry:
            headers["Akamai-BM-Telemetry"] = telemetry
        resp = session.get(
            _MAERSK_API.format(ref=ref),
            headers=headers,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return ScrapedTransit(
            None, None, "maersk-api", f"Maersk tracking request failed: {exc}"
        )

    if resp.status_code == 403:
        return ScrapedTransit(
            None,
            None,
            "maersk-api",
            "Maersk API blocked the request (Akamai bot protection). "
            "A browser/remote browser is required for Maersk.",
        )
    if resp.status_code >= 400:
        return ScrapedTransit(
            None, None, "maersk-api", f"Maersk tracking returned HTTP {resp.status_code}."
        )

    try:
        raw = resp.json()
    except Exception:
        return ScrapedTransit(
            None, None, "maersk-api", "Maersk tracking returned a non-JSON response."
        )

    from .tracking_details import normalize_maersk, summarize_details

    details = normalize_maersk(raw)
    status = details.get("transit_status")
    return ScrapedTransit(
        transit_status=status,
        status_detail=summarize_details(details),
        source="maersk-api",
        error=None if status else "Maersk data loaded but no known status activity matched.",
        vessel_name=details.get("vessel_name"),
        eta_text=details.get("eta"),
        last_event=details.get("last_event"),
        containers=[
            c.get("container_number")
            for c in details.get("containers") or []
            if c.get("container_number")
        ],
        details=details,
    )


def track_esl(reference: str) -> ScrapedTransit:
    """Track an ESL B/L (or container) via their public unified-tracking API.

    The esl.et tracking page calls this JSON endpoint itself; it needs no
    account and no browser, so it works on Heroku.
    """
    if not _curl_cffi_enabled():
        return ScrapedTransit(
            None, None, "esl-api", "curl_cffi disabled (CURL_CFFI_ENABLED=0)."
        )
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return ScrapedTransit(
            None, None, "esl-api", "curl_cffi is not installed on this environment."
        )

    ref = (reference or "").strip()
    if not ref:
        return ScrapedTransit(None, None, "esl-api", "No tracking reference provided.")

    session = cffi_requests.Session(impersonate="chrome124")
    try:
        resp = session.get(
            _ESL_API.format(ref=ref),
            headers={
                "Accept": "application/json",
                "Accept-Language": "en",
                "Referer": _ESL_HOME,
            },
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return ScrapedTransit(
            None, None, "esl-api", f"ESL tracking request failed: {exc}"
        )

    if resp.status_code >= 400:
        return ScrapedTransit(
            None, None, "esl-api", f"ESL tracking returned HTTP {resp.status_code}."
        )

    try:
        payload = resp.json()
    except Exception:
        return ScrapedTransit(
            None, None, "esl-api", "ESL tracking returned a non-JSON response."
        )

    outcome = str(payload.get("outcome") or "").upper()
    if outcome and outcome != "FOUND":
        return ScrapedTransit(
            None,
            None,
            "esl-api",
            "ESL could not find that reference (check the BL/container number).",
        )
    if not payload.get("events"):
        return ScrapedTransit(
            None, None, "esl-api", "ESL returned no tracking events for that reference."
        )

    from .tracking_details import normalize_esl, summarize_details

    details = normalize_esl(payload)
    status = details.get("transit_status")
    return ScrapedTransit(
        transit_status=status,
        status_detail=summarize_details(details),
        source="esl-api",
        error=None if status else "ESL data loaded but no known status event matched.",
        vessel_name=details.get("vessel_name"),
        eta_text=details.get("eta"),
        last_event=details.get("last_event"),
        containers=[
            c.get("container_number")
            for c in details.get("containers") or []
            if c.get("container_number")
        ],
        details=details,
    )


# adapter name -> callable
ADAPTERS = {
    "msc": track_msc,
    "maersk": track_maersk,
    "esl": track_esl,
}


def try_hard_carrier(adapter_name: str, reference: str) -> Optional[ScrapedTransit]:
    """Dispatch to a hard-carrier adapter. Returns None if unknown/disabled."""
    fn = ADAPTERS.get(adapter_name)
    if fn is None:
        return None
    return fn(reference)
