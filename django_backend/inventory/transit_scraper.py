"""Scrape transit status from a carrier tracking page URL.

The user stores shipping_company_url (optionally with a {bl} placeholder).
This module fetches that page and tries to extract a status string, then maps
it onto BillOfLading.TRANSIT_STATUS_CHOICES.

Two-stage strategy:
1. Plain HTTP fetch (fast) — works for simple/SSR pages.
2. Headed Chrome via patchright (slow, ~10-30s) — used when the plain fetch
   fails with an anti-bot challenge (e.g. DataDome on cma-cgm.com), an HTTP
   error, or an empty JS shell. Uses a persistent profile so the DataDome
   cookie is solved once and reused. Disable with BL_BROWSER_SCRAPER=0.

It is best-effort: carrier sites change often. Failures return status=None so
callers keep the previous value.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Map scraped status phrases -> BillOfLading.transit_status values.
# Order matters: first match wins, so more specific phrases come first.
_STATUS_PATTERNS: list[tuple[str, str]] = [
    (
        r"delivered|cargo\s+release[d]?|picked\s+up|delivery\s+complete|"
        r"delivered\s+to\s+(?:consignee|receiver|final)|proof\s+of\s+delivery|"
        r"received\s+by\s+consignee",
        "delivered",
    ),
    (
        r"available\s+for\s+(?:pickup|collection|delivery)|arrived\s+at\s+destination|"
        r"customs\s+cleared|cleared\s+customs|ready\s+for\s+pickup|"
        r"available\s+at\s+(?:depot|terminal|cfs)|empty\s+return\s+available|"
        r"on\s+dock|at\s+dock",
        "arrived",
    ),
    (
        r"discharg\w*|at\s+destination|destination\s+port|awaiting\s+(?:pickup|delivery|collection)|"
        r"restow|discharged\s+(?:at|from)\s+(?:vessel|terminal)|"
        r"waiting\s+(?:for\s+)?(?:customs|clearance|delivery|pickup)|"
        r"customs\s+(?:hold|exam|inspection)|yard\s+operation|"
        r"empty\s+container\s+(?:available|pickup)",
        "at_destination",
    ),
    (
        r"tranship|trans-?ship|via\s+port|on\s+carriage|relay|"
        r"transshipment\s+(?:port|port\s+of)|changed\s+vessel",
        "at_transhipment",
    ),
    (
        r"in\s*transit|loaded\s+on|on\s+board|vessel\s+departed|"
        r"at\s+sea|departed|rolling|loaded\s+to\s+vessel|sailing|"
        r"vessel\s+arrived|arrived\s+at\s+load|"
        r"loaded\s+into\s+vessel|on\s+water|ocean\s+voyage|"
        r"departed\s+from|left\s+(?:port|terminal|berth)|en\s+(?:route|voyage)|"
        r"import\s+loaded|loaded\s+to\s+import|underway|in\s+transhipment\s+port",
        "in_transit",
    ),
    (
        r"gate\s*in|empty|booked|confirmed|pending|not\s+yet|awaiting\s+vessel|"
        r"port\s+of\s+loading|loaded\s+at|received|booked\s+at|"
        r"container\s+gated|gate\s+in\s+(?:full|empty)|awaiting\s+loading|"
        r"to\s+be\s+loaded|scheduled|shipping\s+instruction|"
        r"empty\s+(?:repositioning|pickup|release)|received\s+at\s+(?:terminal|depot)|"
        r"vgm|si\s+received|booking\s+confirmed",
        "pending",
    ),
]

# "Gate Out" is ambiguous on its own (origin vs destination terminal), so the
# surrounding text decides which milestone it means.
_GATE_OUT_RE = re.compile(r"gat(?:e|ed)\s*out", re.IGNORECASE)
_DESTINATION_CONTEXT_RE = re.compile(
    r"djibouti|destination|discharg|import|consignee|port\s+of\s+discharge|\bpod\b",
    re.IGNORECASE,
)

# Common "Status" label lines: "Status: In Transit", "Current status: Gate Out"
_STATUS_LABEL_RE = re.compile(
    r"(?:current\s+)?(?:shipment\s+)?status\s*[:\-–]\s*([A-Za-z][A-Za-z0-9 /&'\-]{2,60})",
    re.IGNORECASE,
)

# Status-like data attributes (values must be short and map to a status).
_STATUS_ATTR_KEYS = (
    "data-status",
    "data-state",
    "data-milestone",
    "data-shipment-status",
    "data-transport-status",
)

# Words that look like a status but are page chrome/CTA text, not shipment state.
_STATUS_NOISE_RE = re.compile(
    r"pending\s+(?:tasks?|actions?|items?)|status\s+updates?|tracking\s+details|"
    r"bl\s+status|manage\s+bookings?|view\s+bookings?|"
    r"notifications?|contact\s+us|ask\s+\w+|book\s+inland|add\s+customs|"
    r"how\s+satisfied|take\s+a\s+tour|return\s+to\s+old",
    re.IGNORECASE,
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_REQUEST_TIMEOUT = 8 if os.environ.get("DYNO") else 15
_REQUEST_TIMEOUT = int(
    os.environ.get("BL_HTTP_TIMEOUT_SEC", str(_DEFAULT_REQUEST_TIMEOUT))
)
_MAX_BYTES = 2_000_000  # 2 MB cap on response body

# Browser budget: navigation + result polling must also stay inside Heroku's
# ~30 s router window. On a developer machine the original, more generous
# values still apply.
_DEFAULT_GOTO_MS = 20_000 if os.environ.get("DYNO") else 60_000
_BROWSER_GOTO_TIMEOUT_MS = int(
    os.environ.get("BL_BROWSER_GOTO_TIMEOUT_MS", str(_DEFAULT_GOTO_MS))
)
_DEFAULT_BROWSER_POLL_SEC = 10 if os.environ.get("DYNO") else 30
_BROWSER_POLL_ATTEMPTS = max(
    1,
    int(
        os.environ.get(
            "BL_BROWSER_POLL_SEC", str(_DEFAULT_BROWSER_POLL_SEC)
        )
    ),
)

_CHALLENGE_MARKERS = ("captcha-delivery.com", "please enable js", "datadome")
# Rendered pages that are security interstitials, not shipment results.
_BOT_CHECK_MARKERS = (
    "security check",
    "verify you are human",
    "are you a robot",
    "unusual traffic",
    "access denied",
    "request unsuccessful",
    "captcha",
    "incapsula",
    "just a moment",
    "checking your browser",
    "enable javascript and cookies to continue",
)


def _looks_like_bot_check(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered.strip():
        return False
    return any(marker in lowered for marker in _BOT_CHECK_MARKERS)


_UPSTREAM_ERROR_MARKERS = (
    "upstream connect error",
    "remote connection failure",
    "connection timed out",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway",
    "service temporarily unavailable",
    "temporarily unavailable",
    "server is temporarily unable",
)


def _looks_unreachable(text: str) -> bool:
    """Carrier-side gateway errors (PIL returns one for some networks)."""
    lowered = (text or "").lower()
    if len(lowered) > 1500:
        # Real shipment pages are long; only check short error pages.
        return False
    return any(marker in lowered for marker in _UPSTREAM_ERROR_MARKERS)


_NOT_FOUND_RE = re.compile(
    r"(shipment|reference|container|tracking|bill of lading)?[^.]{0,60}"
    r"(was not found|not found|no (results?|data|records?)|nothing found)",
    re.IGNORECASE,
)
# Real carrier pages are tens/hundreds of KB; challenge pages are ~1.5 KB.
_MIN_REAL_PAGE_BYTES = 12_000

_BROWSER_LOCK = threading.Lock()


@dataclass
class ScrapeResult:
    transit_status: Optional[str]  # one of TRANSIT_STATUS_CHOICES values, or None
    status_detail: Optional[str]  # human-readable snippet / vessel / ETA if found
    source: Optional[str]  # "html", "embedded-json", "browser", or None
    error: Optional[str]
    details: Optional[dict] = None  # rich route/ETA/vessel/event/container data


def build_tracking_url(base_url: str, bl_number: str) -> str:
    base = (base_url or "").strip()
    if not base:
        return ""
    if "{bl}" in base:
        return base.replace("{bl}", bl_number.strip())
    # Some carrier links embed the reference loosely — Hapag's track-by-container
    # URL ships as "?container=FDCU++0322820", which the site reads as
    # "FDCU  0322820" and rejects. Rewrite matching query values to the clean
    # reference so the page auto-searches correctly.
    ref = (bl_number or "").strip()
    if ref and "?" in base:
        try:
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

            parts = urlsplit(base)
            pairs = parse_qsl(parts.query, keep_blank_values=True)
            ref_key = _reference_key(ref)
            rewritten = [
                (key, ref if _reference_key(value) == ref_key else value)
                for key, value in pairs
            ]
            if rewritten != pairs:
                return urlunsplit(
                    (parts.scheme, parts.netloc, parts.path, urlencode(rewritten), parts.fragment)
                )
        except Exception:
            return base
    return base


def _reference_key(value: str) -> str:
    """Normalize a reference for loose comparison (drop punctuation/spaces)."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _reference_in_url(url: str, reference: str) -> bool:
    """True when the tracking URL already carries this reference."""
    ref = _reference_key(reference)
    return bool(ref) and ref in _reference_key(url)


_REFERENCE_MISSING_MSG = (
    "Reference {ref} was not found on the tracking page. "
    "Check the BL / container number and the shipping line."
)


def _reference_present(reference: str, *haystacks: str) -> bool:
    """True when the page mentions the reference (spacing/case insensitive)."""
    ref = _reference_key(reference)
    if not ref:
        return True
    return any(ref in _reference_key(text or "") for text in haystacks)


def _map_status_text(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    # "Gate Out" happens twice in a container's life: leaving the origin
    # terminal (still to be shipped) and leaving the destination terminal
    # (released to the consignee). Read the words around it instead of
    # guessing — ESL reports "Gated Out • Djibouti".
    gate_out = list(_GATE_OUT_RE.finditer(text))
    if gate_out:
        for match in gate_out:
            window = text[max(0, match.start() - 200) : match.end() + 240]
            if _DESTINATION_CONTEXT_RE.search(window):
                return "at_destination"
        return "in_transit"
    for pattern, status in _STATUS_PATTERNS:
        if re.search(pattern, lowered):
            return status
    return None


def _extract_visible_text(soup: BeautifulSoup) -> str:
    # Work on a shallow copy of tags so callers can still inspect attributes.
    text_soup = BeautifulSoup(str(soup), "html.parser")
    # Drop page chrome that often contains status-like words in nav/tooltips.
    for tag in text_soup(
        ["script", "style", "noscript", "nav", "header", "footer", "aside"]
    ):
        tag.extract()
    for tag in text_soup.find_all(attrs={"role": ["navigation", "banner", "contentinfo"]}):
        tag.extract()
    return re.sub(r"\s+", " ", text_soup.get_text(" ", strip=True))


def _sample_text_for_error(text: str, limit: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return "(empty page text)"
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _is_status_noise(text: str) -> bool:
    return bool(_STATUS_NOISE_RE.search(text or ""))


def _extract_status_labels(soup: BeautifulSoup) -> Optional[str]:
    """Pull status from labels, status-only widgets, and timeline markers."""
    text = _extract_visible_text(soup)

    # 1) "Status: In Transit" labels in visible text.
    for m in _STATUS_LABEL_RE.finditer(text):
        value = m.group(1).strip()
        if _is_status_noise(value) or _is_status_noise(m.group(0)):
            continue
        if _map_status_text(value):
            return m.group(0).strip()

    # 2) Timeline / milestone widgets: only accept short labels (nav tooltips
    #    are long sentences) and never CTA/nav copy.
    for el in soup.find_all(True):
        classes = " ".join(el.get("class") or [])
        el_id = el.get("id") or ""
        marker = f"{classes} {el_id}"
        if not marker.strip():
            continue
        is_statusish = bool(
            re.search(r"status|milestone|event|timeline|tracking|shipment", marker, re.I)
        )
        is_active = bool(
            re.search(r"current|active|latest|last|completed|selected", marker, re.I)
        )
        if not (is_statusish and is_active):
            continue
        label = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if not label or len(label) > 80 or _is_status_noise(label):
            continue
        if _map_status_text(label):
            return label

    # 3) Status-like data attributes, restricted to short values.
    for el in soup.find_all(True):
        classes = " ".join(el.get("class") or [])
        el_id = el.get("id") or ""
        if not re.search(
            r"status|milestone|event|timeline|tracking|shipment", f"{classes} {el_id}", re.I
        ):
            continue
        for key in _STATUS_ATTR_KEYS:
            raw = el.get(key)
            if not raw or not isinstance(raw, str):
                continue
            raw = re.sub(r"\s+", " ", raw).strip()
            if not raw or len(raw) > 60 or _is_status_noise(raw):
                continue
            if _map_status_text(raw):
                return f"{key}={raw}"
    return None


def _try_embedded_json(html: str) -> Optional[str]:
    """Pull status-ish strings out of common embedded JSON blobs."""
    candidates: list[str] = []
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE
    )
    if m:
        candidates.append(m.group(1))
    for m in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        candidates.append(m.group(1))

    status_words = re.compile(
        r"\b(status|state|milestone|event|deliveryStatus|shipmentStatus)\b",
        re.IGNORECASE,
    )

    def walk(obj, out: list[str]) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and status_words.search(k):
                    out.append(v)
                else:
                    walk(v, out)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, out)

    found: list[str] = []
    for blob in candidates:
        try:
            walk(json.loads(blob), found)
        except (json.JSONDecodeError, ValueError):
            continue
    for value in found:
        if _map_status_text(value):
            return value
    return found[0] if found else None


def _extract_detail_snippets(text: str) -> Optional[str]:
    """Grab short context around vessel / ETA / status keywords."""
    patterns = [
        r".{0,40}\bvessel(?:\s+name)?\s*[:\-]\s*([A-Za-z0-9 .'\-]{3,40})",
        r".{0,20}(?:eta|estimated|arrival)\s*[:\-]\s*([A-Za-z0-9 ,:/\-]{4,30})",
        r".{0,20}(?:last\s+update|updated)\s*[:\-]\s*([A-Za-z0-9 ,:/\-]{4,30})",
    ]
    snippets: list[str] = []
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            snippets.append(m.group(0).strip())
    return "; ".join(snippets[:3]) if snippets else None


def _parse_status_from_text(
    text: str, source: str, reference: str = ""
) -> ScrapeResult:
    """Shared extraction: not-found check, status map, detail snippets."""
    from .tracking_details import extract_generic_details

    # Never report a status from a page that does not mention this shipment:
    # carrier marketing/schedule pages say "at destination" too.
    if not _reference_present(reference, text):
        return ScrapeResult(
            None,
            None,
            source,
            _REFERENCE_MISSING_MSG.format(ref=reference),
        )

    details = extract_generic_details(text)
    # Strip page chrome/CTA copy so words like "pending tasks" don't win.
    clean_text = _STATUS_NOISE_RE.sub(" ", text)
    if _NOT_FOUND_RE.search(clean_text[:4000]):
        if not _map_status_text(clean_text):
            snippet = _NOT_FOUND_RE.search(clean_text)
            context = snippet.group(0).strip()[:200] if snippet else None
            return ScrapeResult(
                None,
                context,
                source,
                "Reference not found on the tracking site (check the BL number "
                "or the shipping line).",
                details=details,
            )

    mapped = _map_status_text(clean_text)
    if mapped:
        detail = details.get("last_event") or _extract_detail_snippets(clean_text)
        m = re.search(
            next(p for p, s in _STATUS_PATTERNS if s == mapped), clean_text, re.IGNORECASE
        )
        if m:
            start = max(0, m.start() - 40)
            window = clean_text[start : m.end() + 60].strip()
            detail = f"{window}" + (f" | {detail}" if detail else "")
        return ScrapeResult(
            mapped, detail[:500] if detail else None, source, None, details=details
        )

    if len(clean_text) < 120:
        return ScrapeResult(
            None,
            None,
            source,
            "Page loaded but appears to be a JavaScript shell with no readable status. "
            "Try the manual status update or a direct tracking URL.",
            details=details,
        )
    sample = _sample_text_for_error(clean_text)
    return ScrapeResult(
        None,
        details.get("last_event") or _extract_detail_snippets(clean_text),
        source,
        "Could not recognize a transit status on the page. "
        f"Page text sample: {sample}",
        details=details,
    )


def scrape_transit_status(url: str, bl_number: str = "") -> ScrapeResult:
    """Fetch *url* and best-effort extract a transit status.

    Falls back to a real (headed) Chrome session when the plain HTTP fetch is
    blocked by an anti-bot challenge (DataDome etc.) or returns a JS shell.
    Set BL_BROWSER_SCRAPER=0 to disable the browser fallback.
    """
    if not url or not url.strip().lower().startswith(("http://", "https://")):
        return ScrapeResult(None, None, None, "Invalid or missing tracking URL.")

    result = _plain_fetch_status(build_tracking_url(url, bl_number), bl_number)
    if result.transit_status or not _should_use_browser(result, url, bl_number):
        return result

    browser_result = _browser_fetch_status(url, bl_number)
    if browser_result is not None:
        return browser_result
    return result


def _should_use_browser(result: ScrapeResult, url: str = "", bl_number: str = "") -> bool:
    """Plain fetch failed in a way a real browser might overcome."""
    if os.environ.get("BL_BROWSER_SCRAPER", "").strip() in {"0", "false", "no"}:
        return False
    err = (result.error or "").lower()
    if re.search(r"http (401|403|408|429|5\d\d)", err):
        return True
    if "request failed" in err:
        return True
    if "javascript shell" in err:
        return True
    if "was not found on the tracking page" in err:
        # Search-form sites (PIL, MSC, CMA CGM, CU Lines) render results only
        # after their JS runs, so the static HTML legitimately lacks the
        # reference even when the URL already carries it. Let the browser
        # confirm before we report "not found".
        return bool(bl_number)
    if any(marker in err for marker in _CHALLENGE_MARKERS):
        return True
    return False


def _plain_fetch_status(url: str, bl_number: str = "") -> ScrapeResult:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/json"},
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return ScrapeResult(None, None, None, f"Request failed: {exc}")

    raw = resp.content[:_MAX_BYTES]
    raw_text = raw.decode(resp.encoding or "utf-8", errors="replace")
    low = raw_text[:4000].lower()
    if any(marker in low for marker in _CHALLENGE_MARKERS):
        return ScrapeResult(
            None,
            None,
            None,
            f"HTTP {resp.status_code} anti-bot challenge from tracking site.",
        )

    if resp.status_code >= 400:
        return ScrapeResult(None, None, None, f"HTTP {resp.status_code} from tracking site.")

    content_type = resp.headers.get("Content-Type", "")
    body = resp.content[:_MAX_BYTES]
    if "json" in content_type:
        try:
            data = json.loads(body.decode(resp.encoding or "utf-8", errors="replace"))
            text = json.dumps(data)
        except (json.JSONDecodeError, ValueError):
            text = body.decode(resp.encoding or "utf-8", errors="replace")
        if not _reference_present(bl_number, text):
            return ScrapeResult(
                None, None, "embedded-json", _REFERENCE_MISSING_MSG.format(ref=bl_number)
            )
        return _parse_status_from_text(text, "embedded-json", bl_number)

    html = body.decode(resp.encoding or "utf-8", errors="replace")

    # A static marketing/schedule page that never mentions this shipment must
    # not be mined for status words ("at destination" appears in blurbs). A
    # page too small to be the real (JS-rendered) result is a shell instead.
    if not _reference_present(bl_number, html):
        if len(html.strip()) < _MIN_REAL_PAGE_BYTES:
            return ScrapeResult(
                None,
                None,
                "html",
                "Page loaded but appears to be a JavaScript shell with no readable "
                "status. Try the manual status update or a direct tracking URL.",
            )
        return ScrapeResult(
            None,
            None,
            "html",
            _REFERENCE_MISSING_MSG.format(ref=bl_number),
        )

    soup = BeautifulSoup(html, "html.parser")

    # 1) Try embedded JSON first (SPA shells often still ship __NEXT_DATA__).
    json_status_text = _try_embedded_json(html)
    if json_status_text:
        mapped = _map_status_text(json_status_text)
        if mapped:
            return ScrapeResult(mapped, json_status_text[:300], "embedded-json", None)

    # 2) Status labels / data attributes / active milestone widgets.
    label_hit = _extract_status_labels(soup)
    if label_hit:
        mapped = _map_status_text(label_hit)
        if mapped:
            from .tracking_details import extract_generic_details

            return ScrapeResult(
                mapped,
                label_hit[:300],
                "html",
                None,
                details=extract_generic_details(_extract_visible_text(soup)),
            )

    # 3) Visible text heuristics.
    return _parse_status_from_text(_extract_visible_text(soup), "html", bl_number)


# --- Browser fallback (patchright + headed Chrome) ---------------------------

_SEARCH_INPUT_SELECTORS = [
    "input[name='SearchViewModel.Reference']",
    "input[name*='Reference' i]",
    "input[name*='reference' i]",
    "input[placeholder*='Container' i]",
    "input[placeholder*='Bl' i]",
    "input[placeholder*='tracking' i]",
    "input[type='search']",
]


def _browser_profile_dir() -> str:
    override = os.environ.get("BL_SCRAPER_PROFILE_DIR", "").strip()
    if override:
        return override
    return os.path.join(tempfile.gettempdir(), "mohan_bl_scraper_profile")


def _browser_fetch_status(url: str, bl_number: str) -> Optional[ScrapeResult]:
    """Use a real browser to bypass anti-bot challenges and capture data.

    Local default: installed Google Chrome via patchright (headed).
    Heroku/remote: set BL_BROWSER_CDP_URL to a CDP endpoint (Browserless etc.).
    Returns None when the browser path is unavailable so callers keep the
    plain-fetch error.
    """
    if not _BROWSER_LOCK.acquire(blocking=False):
        return ScrapeResult(
            None,
            None,
            None,
            "Another tracking check is already running; try again shortly.",
        )
    try:
        try:
            from patchright.sync_api import sync_playwright
        except ImportError:
            return None

        cdp_url = os.environ.get("BL_BROWSER_CDP_URL", "").strip()
        try:
            with sync_playwright() as p:
                if cdp_url:
                    browser = p.chromium.connect_over_cdp(cdp_url)
                    try:
                        context = (
                            browser.contexts[0]
                            if browser.contexts
                            else browser.new_context(
                                locale="en-US",
                                viewport={"width": 1366, "height": 900},
                            )
                        )
                        page = context.new_page()
                        try:
                            return _browser_run(page, url, bl_number)
                        finally:
                            try:
                                page.close()
                            except Exception:
                                pass
                    finally:
                        try:
                            browser.close()
                        except Exception:
                            pass

                headless = os.environ.get("BL_BROWSER_HEADLESS", "").strip() in {
                    "1",
                    "true",
                    "yes",
                }
                context = p.chromium.launch_persistent_context(
                    _browser_profile_dir(),
                    headless=headless,  # DataDome often blocks headless
                    channel="chrome",  # use installed Google Chrome
                    args=["--disable-blink-features=AutomationControlled"],
                    locale="en-US",
                    viewport={"width": 1366, "height": 900},
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    return _browser_run(page, url, bl_number)
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass
        except Exception as exc:  # no Chrome / display unavailable
            msg = str(exc)
            if "browser" in msg.lower() or "chrome" in msg.lower() or "display" in msg.lower():
                return None  # environment cannot run a browser — keep plain error
            return ScrapeResult(None, None, None, f"Browser scrape failed: {exc}")
    finally:
        _BROWSER_LOCK.release()


def _browser_run(page, url: str, bl_number: str) -> ScrapeResult:
    has_placeholder = "{bl}" in url
    target = build_tracking_url(url, bl_number)
    captured: list[tuple[str, object]] = []

    def _on_response(response) -> None:
        try:
            headers = {
                str(k).lower(): v for k, v in (response.headers or {}).items()
            }
            ctype = str(headers.get("content-type", "")).lower()
            resp_url = (response.url or "").lower()
            if "json" not in ctype and "/api/" not in resp_url:
                return
            if not any(
                k in resp_url
                for k in ("tracking", "shipment", "container", "synergy", "event")
            ):
                return
            data = response.json()
            if isinstance(data, (dict, list)) and len(str(data)) < 2_000_000:
                captured.append((response.url, data))
        except Exception:
            return

    try:
        page.on("response", _on_response)
    except Exception:
        pass

    # Images/fonts/media are irrelevant to tracking data and make slow carrier
    # pages (PIL, MSC) exceed the navigation timeout on a cold profile.
    def _block_heavy(route) -> None:
        try:
            if route.request.resource_type in {"image", "media", "font"}:
                route.abort()
            else:
                route.continue_()
        except Exception:
            return

    try:
        page.route("**/*", _block_heavy)
    except Exception:
        pass

    slow_navigation = False
    try:
        page.goto(
            target,
            wait_until="domcontentloaded",
            timeout=_BROWSER_GOTO_TIMEOUT_MS,
        )
    except Exception as exc:
        reason = str(exc).split("\n")[0].strip()
        if "timeout" in reason.lower():
            # The page keeps loading background requests (CU Lines, CMA CGM).
            # It is usually already usable, so continue and let the polling
            # loop below collect whatever renders.
            slow_navigation = True
        else:
            return ScrapeResult(None, None, "browser", f"Navigation failed: {reason}")

    # Cookie banners (Maersk/CMA) can hold the SPA before it fetches data.
    consent_handled = _browser_dismiss_consent(page)

    # If the URL had no {bl} and does not already carry the reference, the page
    # is a search form — fill the BL and submit (CMA CGM style flows). URLs that
    # already embed the reference (Hapag ?container=, PIL ?refNo=) usually
    # auto-search; if they do not, the poll loop retries the submit once.
    search_submitted = False
    if not has_placeholder and bl_number and not _reference_in_url(target, bl_number):
        _browser_submit_search(page, bl_number)
        search_submitted = True

    from .tracking_details import (
        extract_generic_details,
        merge_details,
        normalize_tracking_payload,
        summarize_details,
    )

    def _captured_details() -> Optional[dict]:
        for resp_url, payload in reversed(captured):
            try:
                normalized = normalize_tracking_payload(resp_url, payload)
            except Exception:
                normalized = None
            if normalized:
                return normalized
        return None

    # Wait for either captured tracking JSON or a fully rendered page.
    html = ""
    details = None
    for attempt in range(_BROWSER_POLL_ATTEMPTS):  # ~1s per attempt
        page.wait_for_timeout(1000)
        if not consent_handled:
            # Banners appear late and block the carrier's data fetch.
            consent_handled = _browser_dismiss_consent(page)
        try:
            html = page.content()
        except Exception:
            break
        details = _captured_details()
        if details:
            break
        if (
            not search_submitted
            and bl_number
            and attempt >= 8
            and not _reference_present(bl_number, html)
        ):
            # The URL embedded the reference but the SPA did not act on it
            # (PIL-style pages pre-fill the field but wait for a click).
            _browser_submit_search(page, bl_number)
            search_submitted = True
        if (
            attempt >= 4
            and len(html) >= _MIN_REAL_PAGE_BYTES
            and _reference_present(bl_number, html)
        ):
            # A full page that mentions this shipment is ready; otherwise keep
            # waiting — carrier SPAs search asynchronously after the shell.
            break

    # 1) Prefer the carrier's own JSON response (richest data).
    if details:
        details["source"] = "browser"
        status = details.get("transit_status")
        return ScrapeResult(
            status,
            summarize_details(details),
            "browser",
            None
            if status
            else "Tracking data loaded but no known status activity matched.",
            details=details,
        )

    # 2) Fall back to rendered text / DOM widgets.
    try:
        soup = BeautifulSoup(html or page.content(), "html.parser")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    # Prefer visible text with nav/header/footer stripped; raw body text is
    # dominated by menus whenever the page is a shell.
    text = _extract_visible_text(soup)
    if len(text) < 120:
        try:
            text = page.inner_text("body")
        except Exception:
            pass

    # A navigation that never finished usually means we are looking at a shell,
    # not at "this BL does not exist".
    if _looks_unreachable(text):
        return ScrapeResult(
            None,
            None,
            "browser",
            "The carrier tracking site is unreachable from this network "
            "(its gateway returned a connection error). Try again later.",
        )

    if slow_navigation and not _reference_present(bl_number, text, html):
        return ScrapeResult(
            None,
            None,
            "browser",
            "The carrier tracking page did not finish loading (network timeout). "
            "Try again in a moment.",
        )

    # Security interstitials (Hapag-Lloyd, CMA CGM) look like "no data" but are
    # really bot walls; say so instead of pretending the BL does not exist.
    if _looks_like_bot_check(text):
        return ScrapeResult(
            None,
            None,
            "browser",
            "The carrier blocked the automated check with a bot-verification page. "
            "Open the tracking URL manually, or set BL_BROWSER_CDP_URL to a "
            "residential browser service.",
        )

    try:
        label_hit = _extract_status_labels(soup)
        if (
            label_hit
            and _map_status_text(label_hit)
            and _reference_present(bl_number, text, html)
        ):
            mapped = _map_status_text(label_hit)
            return ScrapeResult(
                mapped,
                label_hit[:300],
                "browser",
                None,
                details=extract_generic_details(re.sub(r"\s+", " ", text)),
            )
    except Exception:
        pass

    result = _parse_status_from_text(
        re.sub(r"\s+", " ", text), "browser", bl_number
    )
    if result.transit_status is None and result.details is None:
        # Reference genuinely absent after interaction: report that rather than
        # inventing a status from page copy.
        return result
    result.details = merge_details(
        result.details or {}, extract_generic_details(re.sub(r"\s+", " ", text))
    )
    return result


def _browser_dismiss_consent(page) -> bool:
    """Click through a cookie/consent banner if one is visible.

    Must be retried while the page loads: banners are injected asynchronously
    and Maersk does not fetch tracking data until consent is given.
    Returns True when a banner button was clicked.
    """
    for selector in (
        "#onetrust-accept-btn-handler",
        "button:has-text('Allow all')",
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "button:has-text('I accept')",
        "button:has-text('Accept cookies')",
        "[data-test='cookie-accept-all']",
    ):
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                locator.click(timeout=2000)
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    for name in ("Allow all", "Accept all", "Accept All", "I accept"):
        try:
            locator = page.get_by_role("button", name=name, exact=False).first
            if locator.count() and locator.is_visible():
                locator.click(timeout=2000)
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    return False


def _browser_submit_search(page, bl_number: str) -> None:
    # Carrier UIs (MSC, CU Lines) hide the BL input behind a tab.
    for tab_name in ("Bill of Lading", "B/L", "BL No.", "BL number", "Reference"):
        try:
            tab = page.get_by_role("tab", name=tab_name, exact=False).first
            if tab.count() and tab.is_visible():
                tab.click(timeout=1500)
                page.wait_for_timeout(400)
                break
        except Exception:
            continue

    for selector in _SEARCH_INPUT_SELECTORS:
        try:
            loc = page.locator(selector).first
            if not loc.is_visible(timeout=800):
                continue
            loc.fill(bl_number, timeout=2000)
        except Exception:
            continue
        try:
            loc.press("Enter", timeout=2000)
            return
        except Exception:
            pass
        for button_sel in [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Search')",
            "button:has-text('Track')",
        ]:
            try:
                page.locator(button_sel).first.click(timeout=1500)
                return
            except Exception:
                continue
        return
