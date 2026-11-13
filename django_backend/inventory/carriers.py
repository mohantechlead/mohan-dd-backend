"""Carrier registry: map shipping company names/URLs to tracking strategies.

Each profile tells the check-status pipeline which adapter to try first.
Adapters return a common ScrapedTransit shape so callers stay carrier-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ScrapedTransit:
    """Normalized result from a carrier adapter."""

    transit_status: Optional[str]  # one of BillOfLading.TRANSIT_STATUS_CHOICES, or None
    status_detail: Optional[str] = None
    source: Optional[str] = None  # "msc-api" | "html" | "embedded-json" | ...
    error: Optional[str] = None
    vessel_name: Optional[str] = None
    vessel_imo: Optional[str] = None
    eta_text: Optional[str] = None
    last_event: Optional[str] = None
    containers: list[str] = field(default_factory=list)
    # Rich details for the UI (route, ETA, vessel/voyage, timeline, containers).
    details: dict = field(default_factory=dict)

    def detail_payload(self) -> dict:
        """Merge the flat convenience fields into one JSON-friendly dict."""
        payload = {
            "vessel_name": self.vessel_name,
            "vessel_imo": self.vessel_imo,
            "eta": self.eta_text,
            "last_event": self.last_event,
            "containers": self.containers,
        }
        # Rich adapter details win over the flat convenience fields.
        for key, value in (self.details or {}).items():
            if value not in (None, "", [], {}):
                payload[key] = value
        return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


@dataclass
class CarrierProfile:
    key: str
    match_names: tuple[str, ...]
    match_hosts: tuple[str, ...] = ()
    # Optional hard-carrier adapter name used by hard_carriers.try_hard_carrier.
    hard_adapter: Optional[str] = None
    # Optional default tracking URL template with {bl} placeholder.
    url_template: Optional[str] = None


# Known carriers. Names/hosts are matched case-insensitively as substrings.
CARRIERS: tuple[CarrierProfile, ...] = (
    CarrierProfile(
        key="msc",
        match_names=("mediterranean shipping", "msc"),
        match_hosts=("msc.com", "mscmed.com"),
        hard_adapter="msc",
        url_template="https://www.msc.com/en/track-a-shipment?query={bl}",
    ),
    CarrierProfile(
        key="maersk",
        match_names=("maersk", "ap moller"),
        match_hosts=("maersk.com", "maerskline.com"),
        hard_adapter="maersk",
        url_template="https://www.maersk.com/tracking/{bl}",
    ),
    CarrierProfile(
        key="cma-cgm",
        match_names=("cma cgm", "cma-cgm", "cma cg", "anl", "apl", "cnc"),
        match_hosts=("cma-cgm.com", "monitor.cma-cgm.com"),
        hard_adapter=None,  # DataDome; browser fallback / manual only
        url_template="https://www.cma-cgm.com/ebusiness/tracking?reference={bl}",
    ),
    CarrierProfile(
        key="hapag-lloyd",
        match_names=("hapag", "hapag-lloyd", "hlag"),
        match_hosts=("hapag-lloyd.com", "hlag.com"),
        hard_adapter=None,  # Cloudflare; browser fallback / manual only
        url_template=(
            "https://www.hapag-lloyd.com/en/online-business/track/"
            "track-by-booking-solution.html"
        ),
    ),
    CarrierProfile(
        key="pil",
        match_names=("pacific international lines", "pil", "pilship"),
        match_hosts=("pilship.com", "pilship.com.sg"),
        url_template=(
            "https://www.pilship.com/digital-solutions/?tab=customer"
            "&id=track-trace&label=containerTandT&module=TrackTraceBL"
            "&refNo={bl}"
        ),
    ),
    CarrierProfile(
        key="esl",
        match_names=("ethiopian shipping", "esl"),
        match_hosts=("esl.et", "eslse-et.com"),
        hard_adapter="esl",
        url_template="https://esl.et/en/tracking-unified?mode=import&reference={bl}",
    ),
    CarrierProfile(
        key="evergreen",
        match_names=("evergreen", "evergreen marine"),
        match_hosts=("evergreen-line.com", "evergreen-marine.com"),
        url_template="https://www.evergreen-line.com/eService/ContainerTracking?refNo={bl}",
    ),
    CarrierProfile(
        key="one",
        match_names=("ocean network express", " one"),
        match_hosts=("one-line.com",),
        url_template="https://www.one-line.com/en/tracking?trackingId={bl}",
    ),
    CarrierProfile(
        key="yang-ming",
        match_names=("yang ming", "yangming"),
        match_hosts=("yangming.com",),
        url_template="https://www.yangming.com/eService/Tracking?refNo={bl}",
    ),
    CarrierProfile(
        key="cosco",
        match_names=("cosco", "cosco shipping"),
        match_hosts=("coscoshipping.com", "cosco.com"),
        url_template="https://elines.coscoshipping.com/ebusiness/tracking?refNo={bl}",
    ),
    CarrierProfile(
        key="zim",
        match_names=("zim", "zim integrated"),
        match_hosts=("zim.com",),
        url_template="https://www.zim.com/tools/track-a-shipment?trackingId={bl}",
    ),
)


def normalize(text: str) -> str:
    return (text or "").strip().lower()


def resolve_carrier(
    shipping_company_name: Optional[str] = None,
    shipping_company_url: Optional[str] = None,
) -> Optional[CarrierProfile]:
    """Best-effort match of a BL's shipping company to a CarrierProfile."""
    name = normalize(shipping_company_name or "")
    host = normalize(shipping_company_url or "")
    # Prefer host match (more precise) then name match.
    for profile in CARRIERS:
        for h in profile.match_hosts:
            if h in host:
                return profile
    for profile in CARRIERS:
        for n in profile.match_names:
            if n and n in name:
                return profile
    return None
