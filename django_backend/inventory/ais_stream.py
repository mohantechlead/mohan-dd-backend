"""On-demand AIS position lookup via aisstream.io WebSocket.

Short-lived client: connect, subscribe for one vessel (by MMSI or by name)
within corridor bboxes, wait for a PositionReport (or timeout), disconnect.
No worker/Redis required.

Requires AISSTREAM_API_KEY (free key from https://aisstream.io GitHub signup).
Without a key, an MMSI, or a vessel name, this module is a no-op and callers
keep prior status.

Name-only lookups subscribe to the corridor plus a wide Indian Ocean / East
Africa box (and the Mediterranean) and match ``MetaData.ShipName`` /
``ShipStaticData.Name`` case-insensitively, so operators never have to know
the MMSI.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class AisPosition:
    mmsi: str
    lat: float
    lng: float
    sog: Optional[float] = None  # knots
    cog: Optional[float] = None  # course over ground
    nav_status: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    name: Optional[str] = None


# Default corridor covering Bab el-Mandeb / Red Sea approaches used by
# Djibouti-bound purchases. Override with AISSTREAM_BBOXES env (JSON array
# of [[minLat,minLng],[maxLat,maxLng]] boxes).
_DEFAULT_BBOXES = [
    # Gulf of Aden + Bab el-Mandeb
    [[10.0, 41.0], [16.0, 52.0]],
    # Southern Red Sea
    [[10.0, 41.0], [30.0, 45.0]],
    # Gulf of Tadjoura / Djibouti approaches
    [[10.5, 41.5], [13.5, 44.0]],
    # Suez approaches (north transit)
    [[27.0, 32.0], [32.0, 36.0]],
]

# Extra coverage used for name-only lookups: a ship bound for Djibouti is
# usually somewhere in the Indian Ocean / Arabian Sea / East African coast,
# and northbound traffic may already be in the Mediterranean. MMSI lookups
# stay on the tight corridor above to keep them fast.
_WIDE_SEARCH_BBOXES = [
    # Indian Ocean, Arabian Sea, Gulf of Aden, Red Sea, East Africa
    [[-40.0, 20.0], [32.0, 100.0]],
    # Mediterranean / Suez approaches
    [[30.0, -6.0], [46.0, 37.0]],
    # East Asia: South China Sea, Taiwan, East China Sea, Yellow Sea
    [[15.0, 105.0], [42.0, 135.0]],
    # South-East Asia straits / Malacca approaches
    [[-10.0, 95.0], [20.0, 120.0]],
]

_MMSI_RE = re.compile(r"^\d{6,10}$")
_DEBUG = os.environ.get("AISSTREAM_DEBUG", "") == "1"


def _load_bboxes(wide: bool = False) -> list[list[list[float]]]:
    raw = os.environ.get("AISSTREAM_BBOXES", "").strip()
    boxes = None
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                boxes = parsed
        except (json.JSONDecodeError, ValueError):
            pass
    if boxes is None:
        boxes = list(_DEFAULT_BBOXES)
    if wide and not raw:
        boxes = boxes + list(_WIDE_SEARCH_BBOXES)
    return boxes


def lookup_budget_sec() -> float:
    """Total time allowed for one logical lookup (including MMSI->name retry)."""
    if os.environ.get("DYNO"):
        return 22.0
    return 50.0


def _timeout_sec(wide: bool = False) -> float:
    env_name = "AISSTREAM_NAME_TIMEOUT_SEC" if wide else "AISSTREAM_TIMEOUT_SEC"
    # Heroku's router cuts a request off after ~30 s. Keep the name lookup
    # short there so the whole check-status request stays under that limit;
    # a local developer machine can afford the longer window.
    if os.environ.get("DYNO"):
        default = 20.0
    else:
        default = 45.0 if wide else 20.0
    raw = os.environ.get(env_name, str(int(default))).strip()
    try:
        value = float(raw)
        if 5 <= value <= 90:
            # Never let a copied local value (e.g. 45 s) push a Heroku request
            # past the router's 30 s window.
            return min(value, 25.0) if os.environ.get("DYNO") else value
    except ValueError:
        pass
    return default


def _normalize_name(value) -> str:
    """Upper-case and collapse separators so AIS names compare reliably."""
    if value is None:
        return ""
    text = re.sub(r"[^A-Za-z0-9]+", " ", str(value)).strip().upper()
    return " ".join(text.split())


def _matches_vessel_name(candidate: str, wanted: str) -> bool:
    """Compare AIS ship names, tolerating suffixes and 20-char truncation."""
    if not candidate or not wanted:
        return False
    if candidate == wanted:
        return True
    if candidate.startswith(wanted + " "):
        return True
    # AIS names are clipped to 20 chars, so the wanted (longer) name may start
    # with the candidate.
    if len(candidate) >= 6 and wanted.startswith(candidate + " "):
        return True
    # Tolerate operator/type prefixes such as "MV " / "MT ".
    if len(wanted) >= 6 and candidate.endswith(" " + wanted):
        return True
    return False


async def _stream_position(
    api_key: str,
    boxes: list[list[list[float]]],
    timeout: float,
    mmsi: str,
    wanted_name: str,
) -> Optional[AisPosition]:
    """One WebSocket session. Raises on connection trouble so callers retry."""
    import websockets

    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": boxes,
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }
    if mmsi:
        # aisstream requires nine-character MMSI strings (not integers).
        subscription["FiltersShipMMSI"] = [mmsi]

    # MMSI -> name mapping learned from static reports; position reports from
    # some ships arrive with an empty MetaData.ShipName.
    matched_mmsis: set[str] = set()
    _debug_count = 0

    async with websockets.connect(
        "wss://stream.aisstream.io/v0/stream",
        compression="deflate",
        open_timeout=min(10.0, timeout),
        close_timeout=2,
        ping_interval=15,
        ping_timeout=15,
        max_size=2**20,
    ) as ws:
        await ws.send(json.dumps(subscription))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            try:
                message = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue

            meta = message.get("MetaData") or {}
            data = message.get("Message") or {}
            ship_name = _normalize_name(meta.get("ShipName"))
            if _DEBUG:
                _debug_count += 1
                if _debug_count % 50 == 0:
                    print("AIS sample:", _debug_count, repr(ship_name), flush=True)
            if _DEBUG and ship_name and _matches_vessel_name(ship_name, wanted_name):
                print(
                    "AIS candidate:",
                    ship_name,
                    "| types:",
                    list(data.keys()),
                    flush=True,
                )
            static = data.get("ShipStaticData") or {}
            if static:
                static_name = _normalize_name(static.get("Name"))
                if static_name:
                    ship_name = ship_name or static_name

            meta_mmsi = str(meta.get("MMSI") or static.get("UserID") or "").strip()
            if (
                not mmsi
                and meta_mmsi
                and ship_name
                and _matches_vessel_name(ship_name, wanted_name)
            ):
                matched_mmsis.add(meta_mmsi)

            report = data.get("PositionReport") or data.get("StandardClassBPositionReport")
            if not report:
                continue
            lat = report.get("Latitude")
            lng = report.get("Longitude")
            if lat is None or lng is None:
                continue

            msg_mmsi = str(meta.get("MMSI") or report.get("UserID") or "").strip()
            if not mmsi:
                if not (
                    _matches_vessel_name(ship_name, wanted_name)
                    or (msg_mmsi and msg_mmsi in matched_mmsis)
                ):
                    continue

            sog = report.get("Sog")
            cog = report.get("Cog")
            nav = report.get("NavigationalStatus")
            return AisPosition(
                mmsi=msg_mmsi or mmsi,
                lat=float(lat),
                lng=float(lng),
                sog=float(sog) if sog is not None else None,
                cog=float(cog) if cog is not None else None,
                nav_status=str(nav) if nav is not None else None,
                last_seen_at=datetime.now(timezone.utc),
                name=ship_name or None,
            )


async def _fetch_position_async(
    mmsi: str | None = None,
    vessel_name: str | None = None,
    timeout_override: float | None = None,
) -> Optional[AisPosition]:
    try:
        import websockets  # noqa: F401
    except ImportError:
        return None

    api_key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not api_key:
        return None

    mmsi = (mmsi or "").strip()
    if mmsi and not _MMSI_RE.match(mmsi):
        mmsi = ""
    wanted_name = _normalize_name(vessel_name)
    if not mmsi and not wanted_name:
        return None

    boxes = _load_bboxes(wide=not mmsi)
    timeout = timeout_override or _timeout_sec(wide=not mmsi)
    if timeout_override is not None:
        timeout = max(5.0, min(float(timeout_override), 90.0))

    # Hard overall deadline. Retries share the same budget so a slow handshake
    # can never multiply the wait (important on Heroku's 30 s router limit).
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    # aisstream sometimes drops the opening handshake; a couple of quick
    # retries make lookups far more reliable without lengthening good runs.
    for attempt in range(3):
        remaining = deadline - loop.time()
        if remaining <= 1.0:
            break
        try:
            return await _stream_position(
                api_key, boxes, remaining, mmsi, wanted_name
            )
        except Exception as exc:  # connection trouble — retry, then soft-fail
            if _DEBUG:
                print(f"AIS attempt {attempt + 1} failed: {type(exc).__name__}: {exc}")
            remaining = deadline - loop.time()
            if attempt < 2 and remaining > 2.0:
                await asyncio.sleep(min(1.5, remaining - 1.0))
    return None


def fetch_position(
    mmsi: str = "",
    vessel_name: str | None = None,
    timeout_override: float | None = None,
) -> Optional[AisPosition]:
    """Sync wrapper around the short-lived aisstream WS client.

    Looks up by MMSI when one is supplied (fast, corridor-only). Otherwise
    falls back to a name match over the wider coverage area.
    """
    mmsi = (mmsi or "").strip()
    vessel_name = (vessel_name or "").strip()
    if not mmsi and not vessel_name:
        return None

    def _lookup():
        return asyncio.run(
            _fetch_position_async(
                mmsi=mmsi,
                vessel_name=vessel_name,
                timeout_override=timeout_override,
            )
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Normal case: plain sync caller (Django request thread).
        try:
            return _lookup()
        except Exception:
            return None
    # Already inside an event loop — run the client on a worker thread with its
    # own loop so we do not block or nest loops.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        try:
            return pool.submit(_lookup).result()
        except Exception:
            return None
