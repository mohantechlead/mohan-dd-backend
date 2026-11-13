"""Normalize carrier tracking payloads / page text into rich tracking details.

Used by hard-carrier adapters (curl_cffi) and the browser fallback, which
captures the JSON the carrier SPA itself fetches.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Activity phrase -> BillOfLading.transit_status (order matters).
_ACTIVITY_STATUS: list[tuple[str, str]] = [
    (r"deliver|released|picked up|proof of delivery", "delivered"),
    (
        r"available|ready for|cleared|customs released|arrival at destination",
        "arrived",
    ),
    (
        r"discharg|import discharge|at destination|destination terminal|"
        r"awaiting|customs hold|stripped|empty return",
        "at_destination",
    ),
    (r"tranship|trans-?ship|relay|changed vessel", "at_transhipment"),
    (
        r"depart|load|loaded|on board|sail|gate out|in transit|vessel departure|"
        r"export load|container departure",
        "in_transit",
    ),
    (
        r"gate in|empty|book|confirm|pending|received|stuffing|vgm|"
        r"container arrival|arrival at origin",
        "pending",
    ),
]


def map_activity_to_status(activity: str) -> Optional[str]:
    low = (activity or "").lower()
    if not low.strip():
        return None
    for pattern, status in _ACTIVITY_STATUS:
        if re.search(pattern, low):
            return status
    return None


def _event_sort_key(evt: dict) -> tuple[int, str]:
    # Expected events should not beat actual events for "latest".
    kind = 1 if str(evt.get("event_time_type", "ACTUAL")).upper() == "EXPECTED" else 0
    return (kind, str(evt.get("time") or ""))


def normalize_maersk(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize api.maersk.com/synergy/tracking response into our detail shape."""
    origin = raw.get("origin") or {}
    destination = raw.get("destination") or {}
    containers_raw = raw.get("containers") or []

    containers: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []

    for c in containers_raw:
        events: list[dict[str, Any]] = []
        for loc in c.get("locations") or []:
            for evt in loc.get("events") or []:
                events.append(
                    {
                        "activity": evt.get("activity") or "",
                        "location": loc.get("city") or "",
                        "terminal": loc.get("terminal") or "",
                        "country": loc.get("country") or "",
                        "country_code": loc.get("country_code") or "",
                        "vessel": evt.get("vessel_name") or None,
                        "voyage": evt.get("voyage_num") or None,
                        "time": evt.get("event_time") or None,
                        "kind": str(evt.get("event_time_type") or "ACTUAL").upper(),
                    }
                )
        events.sort(key=_event_sort_key)
        all_events.extend(events)

        expected = [
            e
            for e in events
            if e["kind"] == "EXPECTED"
            and re.search(
                r"container arrival|discharg|arrival|delivery",
                e["activity"],
                re.IGNORECASE,
            )
        ]
        eta = expected[-1] if expected else None
        latest_actual = next(
            (e for e in reversed(events) if e["kind"] == "ACTUAL"), None
        )
        # Prefer the vessel that physically moved the container (actual events),
        # not a planned feeder from an EXPECTED event.
        vessel_event = next(
            (
                e
                for e in reversed(events)
                if e.get("vessel") and e["kind"] == "ACTUAL"
            ),
            None,
        )
        if vessel_event is None:
            vessel_event = next((e for e in reversed(events) if e.get("vessel")), None)
        containers.append(
            {
                "container_number": c.get("container_num") or "",
                "size": c.get("container_size") or "",
                "type": c.get("container_type") or "",
                "eta": eta.get("time") if eta else None,
                "latest_event": latest_actual,
                "vessel": vessel_event.get("vessel") if vessel_event else None,
                "voyage": vessel_event.get("voyage") if vessel_event else None,
                "events": events[-12:],
            }
        )

    # Overall status from the newest ACTUAL event across containers.
    actuals = [e for e in all_events if e["kind"] == "ACTUAL"]
    actuals.sort(key=lambda e: str(e.get("time") or ""))
    latest_event = actuals[-1] if actuals else None
    status = map_activity_to_status(latest_event["activity"]) if latest_event else None

    vessel_name = None
    voyage = None
    for e in reversed(actuals or all_events):
        if e.get("vessel"):
            vessel_name = e["vessel"]
            voyage = e.get("voyage")
            break

    eta = None
    for c in containers:
        if c.get("eta"):
            eta = c["eta"]
            break

    return {
        "transit_status": status,
        "origin": _place(origin),
        "destination": _place(destination),
        "vessel_name": vessel_name,
        "vessel_voyage": voyage,
        "eta": eta,
        "last_event": _format_event(latest_event) if latest_event else None,
        "last_updated": raw.get("last_update_time"),
        "containers": containers,
        "events": (actuals[-15:] if actuals else all_events[-15:]),
        "source": "maersk-api",
    }


def _place(obj: dict[str, Any]) -> Optional[str]:
    parts = [obj.get("city"), obj.get("terminal"), obj.get("country")]
    text = ", ".join(p for p in parts if p)
    return text or None


# --- ESL (Ethiopian Shipping & Logistics) / DCSA tracking API ----------------

_ESL_GATE_OUT_RE = re.compile(r"gat(?:e|ed)\s*out", re.IGNORECASE)
_ESL_GATE_IN_RE = re.compile(r"gat(?:e|ed)\s*in", re.IGNORECASE)


def looks_like_esl(raw: dict[str, Any]) -> bool:
    """esl.et unified-tracking payload (DCSA-shaped, includes the shipment)."""
    return (
        isinstance(raw.get("events"), list)
        and isinstance(raw.get("shipment"), dict)
        and isinstance(raw.get("reference"), dict)
        and "contractVersion" in raw
    )


def _esl_date(value: Optional[str]) -> str:
    """ESL dates carry DAY precision; drop the meaningless 00:00."""
    return _human_time(value).replace(" 00:00", "")


def _esl_port(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text.upper() if text else None


def _map_esl_event(activity: str, location: str, pol: str, pod: str) -> Optional[str]:
    """ESL milestone -> transit status, using the location to disambiguate."""
    low = (activity or "").lower()
    if not low.strip():
        return None
    loc = (location or "").upper()
    at_origin = bool(pol) and pol.upper() in loc
    at_discharge = bool(pod) and pod.upper() in loc
    if re.search(r"deliver|picked up|released|empty return", low):
        return "delivered"
    if _ESL_GATE_OUT_RE.search(low):
        # Leaving the origin terminal starts the ocean leg; leaving the
        # destination terminal means the consignee has taken the box.
        return "in_transit" if at_origin and not at_discharge else "at_destination"
    if _ESL_GATE_IN_RE.search(low):
        return "at_destination" if at_discharge else "pending"
    if re.search(r"discharg", low):
        return "at_destination"
    if re.search(r"loaded|on board|sailed|departed", low):
        return "in_transit"
    if re.search(r"clearance|waiting|customs|train|truck|arriv", low):
        # Inland movement inside the destination country.
        return "at_destination"
    return map_activity_to_status(activity)


def _esl_event_text(evt: dict[str, Any]) -> str:
    bits = [str(evt.get("activity") or "Event")]
    if evt.get("location"):
        bits.append(f"at {evt['location']}")
    if evt.get("vessel"):
        bits.append(f"({evt['vessel']}/{evt.get('voyage') or '-'})")
    if evt.get("time"):
        bits.append(f"on {_esl_date(evt['time'])}")
    return " ".join(bits)


def normalize_esl(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize esl.et's DCSA-style unified-tracking payload."""
    shipment = raw.get("shipment") or {}
    pol = _esl_port(shipment.get("pol"))
    pod = _esl_port(shipment.get("pod"))
    containers_raw = raw.get("containers") or shipment.get("containers") or []

    def _location(evt: dict[str, Any]) -> str:
        call = evt.get("transportCall") or {}
        loc = call.get("location") or {}
        return str(loc.get("locationName") or "").strip()

    # The planned final destination (Dire Dawa) beats the UN/LOCODE in
    # shipment.destination (ETDIR) for humans.
    destination = None
    for evt in raw.get("events") or []:
        if re.search(r"final\s+destination", str(evt.get("title") or ""), re.I):
            name = _location(evt)
            if name:
                destination = name.upper()
                break
    destination = destination or pod

    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    by_id: dict[str, dict[str, Any]] = {}
    eta = None
    last_updated = None
    for evt in raw.get("events") or []:
        title = str(evt.get("title") or "").strip()
        if not title:
            continue
        when = evt.get("eventDateTime") or evt.get("eventCreatedDateTime")
        created = evt.get("eventCreatedDateTime")
        if created and (last_updated is None or str(created) > str(last_updated)):
            last_updated = created
        if str(evt.get("eventClassifierCode") or "").upper() == "PLN":
            if not eta and re.search(r"arriv", title, re.I):
                eta = when
            continue
        name = _location(evt)
        key = (title.lower(), str(when), name.lower())
        if key in seen:
            # One row per container otherwise; keep a single timeline entry.
            continue
        seen.add(key)
        call = evt.get("transportCall") or {}
        vessel = str((call.get("vessel") or {}).get("vesselName") or "").strip()
        if not re.search(r"[A-Za-z]{2,}", vessel):
            vessel = ""
        voyage = str((call.get("voyage") or {}).get("carrierVoyageNumber") or "").strip()
        normalized = {
            "activity": title,
            "location": name,
            "vessel": vessel or None,
            "voyage": voyage or None,
            "time": when,
            "kind": "ACTUAL",
            "sequence": evt.get("displaySequence") or 0,
        }
        events.append(normalized)
        event_id = str(evt.get("eventID") or "")
        if event_id:
            by_id[event_id] = normalized

    events.sort(key=lambda e: (str(e.get("time") or ""), e.get("sequence") or 0))
    for evt in events:
        evt.pop("sequence", None)

    # The carrier says which milestone is current; sequence/date order alone can
    # put a same-day admin step ("Train Assigned") after the real movement.
    current_id = str((raw.get("timeline") or {}).get("currentMilestoneId") or "")
    latest = by_id.get(current_id) or (events[-1] if events else None)
    status = (
        _map_esl_event(latest["activity"], latest["location"], pol or "", pod or "")
        if latest
        else None
    )

    vessel_name = None
    voyage = None
    for evt in reversed(events):
        if evt.get("vessel"):
            vessel_name = evt["vessel"]
            voyage = evt.get("voyage")
            break
    if not vessel_name:
        # ESL's container-level "vessel" is often an internal id ("14").
        for c in containers_raw:
            name = str(c.get("vessel") or "").strip()
            if re.search(r"[A-Za-z]{2,}", name) and _looks_like_vessel(name):
                vessel_name = name
                voyage = str(c.get("voyage") or "").strip() or None
                break

    containers: list[dict[str, Any]] = []
    for c in containers_raw:
        number = str(c.get("containerNumber") or "").strip()
        if not number:
            continue
        containers.append(
            {
                "container_number": number,
                "size": str(c.get("containerSize") or "").strip(),
                "type": str(c.get("containerType") or "").strip(),
                "status": str(c.get("status") or "").strip() or None,
                "latest_event": latest,
            }
        )

    return {
        "transit_status": status,
        "origin": pol,
        "destination": destination,
        "vessel_name": vessel_name,
        "vessel_voyage": voyage,
        "eta": eta,
        "last_event": _esl_event_text(latest) if latest else None,
        "last_updated": last_updated,
        "containers": containers,
        "events": events[-15:],
        "source": "esl-api",
    }


def _human_time(value: Optional[str]) -> str:
    """Format an ISO timestamp like 2026-10-10T03:37:00Z for display."""
    if not value:
        return ""
    text = str(value).strip().replace("Z", "+00:00")
    try:
        from datetime import datetime

        return datetime.fromisoformat(text).strftime("%d %b %Y %H:%M")
    except ValueError:
        return str(value)


def summarize_details(details: dict[str, Any]) -> Optional[str]:
    """One-line status detail: event | vessel/voyage | ETA | origin -> destination."""
    if not details:
        return None
    parts: list[str] = []
    if details.get("last_event"):
        parts.append(str(details["last_event"]))
    vessel = details.get("vessel_name")
    voyage = details.get("vessel_voyage")
    if vessel:
        parts.append(f"{vessel}/{voyage}" if voyage else str(vessel))
    if details.get("eta"):
        parts.append(f"ETA {_human_time(details['eta'])}")
    origin = details.get("origin")
    destination = details.get("destination")
    if origin or destination:
        parts.append(f"{origin or '?'} -> {destination or '?'}")
    return " | ".join(parts)[:500] or None


def _format_event(evt: dict[str, Any]) -> str:
    activity = evt.get("activity") or "Event"
    loc = ", ".join(
        p for p in (evt.get("location"), evt.get("terminal"), evt.get("country")) if p
    )
    bits = [activity]
    if loc:
        bits.append(f"at {loc}")
    if evt.get("vessel"):
        bits.append(f"({evt['vessel']}/{evt.get('voyage') or '-'})")
    if evt.get("time"):
        bits.append(f"on {_human_time(evt['time'])}")
    return " ".join(bits)


# --- Generic page-text extraction -------------------------------------------

_DATE_RE = r"\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}(?:\s+\d{2}:\d{2})?"
_VESSEL_VOYAGE_RE = re.compile(
    r"([A-Z][A-Z0-9 .'\-]{2,40})\s*/\s*([A-Z0-9]{2,10})"
)

# Words that appear next to "vessel"/"ship" in navigation copy ("Track Shipment",
# "Shipping Solutions") and must never be mistaken for a ship name.
_VESSEL_STOPWORDS = {
    "track",
    "trace",
    "tracking",
    "shipment",
    "shipments",
    "shipping",
    "ship",
    "schedule",
    "schedules",
    "status",
    "container",
    "containers",
    "cargo",
    "eta",
    "etd",
    "bl",
    "bill",
    "lading",
    "import",
    "export",
    "service",
    "services",
    "route",
    "routing",
    "destination",
    "origin",
    "port",
    "ports",
    "vessel",
    "voyage",
    "terminal",
    "booking",
    "reference",
    "number",
    "details",
    "search",
    "menu",
    "home",
    "login",
    "register",
}

# Copy that belongs to site chrome / CTAs, never to a shipment.
_PLACE_NOISE = (
    "track shipment",
    "tracking",
    "self-service",
    "self service",
    "solutions",
    "sign up",
    "log in",
    "login",
    "contact us",
    "cookie",
    "privacy",
    "newsletter",
    "subscribe",
    "learn more",
    "read more",
    "departure date",
    "arrival time",
    "port of discharging",
    "schedule",
)


def _looks_like_vessel(name: Any) -> bool:
    """Reject nav words and sentence fragments passed off as a ship name."""
    if not isinstance(name, str):
        return False
    cleaned = re.sub(r"[^A-Za-z0-9 .'\-]", " ", name).strip(" .'-")
    if not (2 <= len(cleaned) <= 40):
        return False
    words = [w for w in re.split(r"\s+", cleaned) if w]
    if not words or len(words) > 5:
        return False
    if any(w.lower() in _VESSEL_STOPWORDS for w in words):
        return False
    return True


def _looks_like_place(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = value.strip(" ,")
    if not (2 <= len(cleaned) <= 80):
        return False
    lowered = cleaned.lower()
    return not any(noise in lowered for noise in _PLACE_NOISE)


def looks_like_vessel(name: Any) -> bool:
    """Public wrapper used to validate names already stored on a BL."""
    return _looks_like_vessel(name)


def sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    """Drop route/vessel values that were scraped from site chrome."""
    if not isinstance(details, dict) or not details:
        return details or {}
    cleaned = dict(details)
    if cleaned.get("vessel_name") and not _looks_like_vessel(cleaned["vessel_name"]):
        cleaned.pop("vessel_name", None)
        cleaned.pop("vessel_voyage", None)
    for key in ("origin", "destination"):
        if cleaned.get(key) and not _looks_like_place(cleaned[key]):
            cleaned.pop(key, None)
    return cleaned


def extract_generic_details(text: str) -> dict[str, Any]:
    """Best-effort route / vessel / ETA / latest-event extraction from text."""
    flat = re.sub(r"\s+", " ", text or "")
    details: dict[str, Any] = {}

    # Carrier cards such as Maersk render
    # "Discharge (AL ZUBARA / 636E) Latest event | 10 Oct 2026 03:37".
    m = re.search(
        r"([A-Za-z][A-Za-z /'\-]{2,30})\s*\(\s*"
        r"([A-Z0-9][A-Z0-9 .'\-]{1,40}?)\s*/\s*([A-Z0-9]{2,10})\s*\)",
        flat,
    )
    if m:
        activity = m.group(1).strip()
        vessel = m.group(2).strip()
        voyage = m.group(3).strip()
        details.setdefault("vessel_name", vessel)
        details["vessel_voyage"] = voyage
        details.setdefault(
            "last_event",
            f"{activity[:1].upper()}{activity[1:]} ({vessel} / {voyage})",
        )
        m_date = re.search(
            r"Latest event\s*[|\-:]?\s*(" + _DATE_RE + r")", flat, re.IGNORECASE
        )
        if m_date:
            details["last_event"] = f"{details['last_event']} on {m_date.group(1)}"

    m = re.search(r"\bETA\b[:\s]*(" + _DATE_RE + r")", flat, re.IGNORECASE)
    if m:
        details["eta"] = m.group(1)

    # "Feeder arrival (HUI DA 9 / 643N) 29 Oct 2026 22:00"
    m = re.search(
        r"(?:feeder\s+arrival|arrival|arrives)\b[^|]{0,80}?\s*\|?\s*("
        + _DATE_RE
        + r")",
        flat,
        re.IGNORECASE,
    )
    if m:
        details.setdefault("eta", m.group(1))

    # Route cards: "Departs ANTWERP CONTAINER TERMINAL 730 18 Aug 2026".
    place_end = (
        r"(?=\s+\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}"
        r"|\s+(?:Arrives|Departs|Last updated|Note)\b|$)"
    )
    m = re.search(
        r"\bDeparts\s+([A-Z][A-Z0-9 .,'\-]{2,80}?)" + place_end,
        flat,
        re.IGNORECASE,
    )
    if m:
        details.setdefault("origin", m.group(1).strip(" ,"))

    m = re.search(
        r"\bArrives\s+([A-Z][A-Z0-9 .,'\-]{2,80}?)" + place_end,
        flat,
        re.IGNORECASE,
    )
    if m:
        details.setdefault("destination", m.group(1).strip(" ,"))

    m = re.search(
        r"\bvessel(?:\s+name)?\s*[:\-]\s*([A-Za-z0-9 .'\-]{3,40})", flat, re.IGNORECASE
    )
    if m and _looks_like_vessel(m.group(1)):
        details.setdefault("vessel_name", m.group(1).strip())

    m = _VESSEL_VOYAGE_RE.search(flat)
    if m and _looks_like_vessel(m.group(1)):
        details.setdefault("vessel_name", m.group(1).strip())
        details["vessel_voyage"] = m.group(2)

    m = re.search(
        r"(?:origin|port of loading|shipped from)\s*[:\-]?\s*([A-Za-z .,'\-]{3,60})",
        flat,
        re.IGNORECASE,
    )
    if m:
        details["origin"] = m.group(1).strip(" ,")

    m = re.search(
        r"(?:destination|port of discharge|shipped to)\s*[:\-]?\s*([A-Za-z .,'\-]{3,60})",
        flat,
        re.IGNORECASE,
    )
    if m:
        details["destination"] = m.group(1).strip(" ,")

    m = re.search(
        r"latest event\s*[:\-]?\s*(.{3,160}?)(?:\s+(?:last updated|view|show|note)\b|$)",
        flat,
        re.IGNORECASE,
    )
    if m:
        details["last_event"] = m.group(1).strip()

    m = re.search(
        r"last updated\s*[:\-]?\s*([A-Za-z0-9 ,:/\-]{3,40})", flat, re.IGNORECASE
    )
    if m:
        details["last_updated"] = m.group(1).strip()

    # Final sanity pass: drop values that came from chrome rather than cargo.
    if details.get("vessel_name") and not _looks_like_vessel(details["vessel_name"]):
        details.pop("vessel_name", None)
        details.pop("vessel_voyage", None)
    for key in ("origin", "destination"):
        if details.get(key) and not _looks_like_place(details[key]):
            details.pop(key, None)
    if details.get("last_event"):
        event = str(details["last_event"])
        if not (
            re.search(_DATE_RE, event)
            or re.search(
                r"discharg|load|arriv|depart|gate|transit|deliver|customs|"
                r"vessel|sailed|berthed|released|cleared",
                event,
                re.IGNORECASE,
            )
        ):
            details.pop("last_event", None)
    if details.get("eta") and not re.search(_DATE_RE, str(details["eta"])):
        details.pop("eta", None)

    return details


def merge_details(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (extra or {}).items():
        if value in (None, "", [], {}):
            continue
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
    return merged


def looks_like_maersk(raw: dict[str, Any]) -> bool:
    containers = raw.get("containers")
    if not isinstance(containers, list) or not containers:
        return False
    return any(
        isinstance(c, dict) and isinstance(c.get("locations"), list)
        for c in containers
    )


def normalize_tracking_payload(url: str, raw: Any) -> Optional[dict[str, Any]]:
    """Normalize a captured carrier JSON payload when we recognize its shape."""
    if not isinstance(raw, dict):
        return None
    candidates: list[dict[str, Any]] = []
    if isinstance(raw.get("trackingResponse"), dict):
        candidates.append(raw["trackingResponse"])
    candidates.append(raw)
    for candidate in candidates:
        if looks_like_maersk(candidate):
            return normalize_maersk(candidate)
        if looks_like_esl(candidate):
            return normalize_esl(candidate)
    return None
