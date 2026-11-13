# BL / transit tracking

How `POST /purchases/{purchase_number}/bl/check-status` resolves a shipment and
what it returns.

## Resolution order

1. **Carrier adapter (curl_cffi)** — TLS impersonation, cheap and Heroku-safe.
   - `msc` → MSC public tracking JSON API (works).
   - `esl` → `esl.et/api/esl/api/unified-tracking/events` (works). This is the
     same DCSA-style JSON the ESL tracking page loads, so it returns the full
     timeline, containers, route (Nhava Sheva → Dire Dawa) and milestones
     without a browser. Needs `Accept-Language: en` (the API rejects requests
     without it).
   - `maersk` → `api.maersk.com/synergy/tracking/...`. Maersk protects this
     endpoint with Akamai bot manager, so without a valid
     `Akamai-BM-Telemetry` header it returns **403**. The adapter is attempted
     anyway (Akamai changes rules over time) and then we fall through.
2. **Plain HTTP scrape** of `shipping_company_url` (or the carrier registry
   template `https://www.maersk.com/tracking/{bl}` when the BL has no URL).
3. **Real browser fallback** — needed for Maersk, CMA CGM and Hapag-Lloyd.
   The browser opens the carrier page, accepts the cookie banner (Maersk does
   not fetch tracking data until consent is given), and *intercepts the
   tracking JSON the carrier's own SPA fetches*, which is the richest source
   of data.
4. **AIS enrichment** (optional) — needs `AISSTREAM_API_KEY`.

## Carrier coverage (free sources only)

| Carrier | Source | Status |
| --- | --- | --- |
| MSC | `msc.com/api/.../TrackingInfo` (JSON) | adapter works once a real BL/container is set |
| Maersk | tracking SPA JSON, intercepted | works locally with Chrome; needs `BL_BROWSER_CDP_URL` on Heroku |
| ESL | `esl.et/api/esl/api/unified-tracking/events` (JSON) | works everywhere, including Heroku |
| CMA CGM | tracking SPA JSON, intercepted | 403/DataDome to plain requests; browser only |
| Hapag-Lloyd | tracking SPA | Cloudflare "checking your browser" wall; needs a residential browser |
| PIL | search form | carrier gateway timed out from this network |
| CU Lines | search form | connection times out from this network |

## Rich output

Every successful check stores a `tracking_details` JSON blob on the BL and the
check-status response exposes:

| Field | Meaning |
| --- | --- |
| `origin`, `destination` | Route (city / terminal / country) |
| `vessel_name`, `vessel_voyage` | Latest known vessel and voyage |
| `eta` | Best expected arrival time |
| `last_event` | Human-readable latest actual event |
| `last_updated` | Carrier's own "last updated" timestamp |
| `events[]` | Timeline: `activity`, `location`, `terminal`, `country`, `vessel`, `voyage`, `time`, `kind` (`ACTUAL`/`EXPECTED`) |
| `containers[]` | Per container: number, size, type, ETA, latest event, events |
| `tracking_details` | Raw merged payload (same data, used by the UI) |

MSC, Maersk and ESL populate these. Other carriers get best-effort extraction
from the rendered page text.

## Safety rules

- A status is **only** taken from a page that mentions the BL/container number,
  so carrier marketing or schedule pages ("containers are available at
  destination terminals…") can never flip a BL to `at_destination`.
- Vessel names are validated against navigation copy, so phrases such as
  "Track Shipment" or "Shipping Solutions" are never stored as a ship.
- When the reference is genuinely absent the check returns
  "Reference … was not found on the tracking page" and leaves the stored status
  alone.
- "Gate Out" is read with its location: leaving the **origin** terminal means
  the ocean leg started (`in_transit`); leaving the **destination** terminal
  means the consignee has the box (`at_destination`). "Gated Out" (past tense,
  as ESL reports it) is matched too.
- A bot-verification page ("checking your browser"), a carrier gateway error
  ("upstream connect error"), or a navigation timeout is reported as such —
  never as "reference not found".


## Database

Development runs against the PostgreSQL instance on this PC (`mohanPLC`).
`LOCAL_DATABASE_URL` in `django_backend/django_backend/.env` (gitignored) is
checked **first**, so a `DATABASE_URL` exported globally for another project
cannot silently move the app onto a remote database. Heroku never receives the
`.env` file, so it keeps using its own `DATABASE_URL`.

Resolution order: `LOCAL_DATABASE_URL` → `DATABASE_URL` → local default
(`postgres://postgres:tsedi@localhost:5432/mohanPLC`).

## Environment variables

| Variable | Purpose |
| --- | --- |
| `CURL_CFFI_ENABLED` | `0` disables all `curl_cffi` adapters |
| `MAERSK_CONSUMER_KEY` | Override the public Maersk SPA consumer key |
| `MAERSK_BM_TELEMETRY` | Akamai telemetry header, if you ever have a valid one |
| `BL_BROWSER_SCRAPER` | `0` disables the browser fallback entirely |
| `BL_BROWSER_HEADLESS` | `1` runs the local browser headless |
| `BL_BROWSER_CDP_URL` | Remote Chrome DevTools endpoint (see below) |
| `AISSTREAM_API_KEY` | Enables the AIS position lookup |
| `AISSTREAM_NAME_TIMEOUT_SEC` | Name-only lookup window, default `45` locally / `20` on Heroku (5–90 s) |
| `AISSTREAM_TIMEOUT_SEC` | MMSI lookup window, default `20` (5–90 s) |
| `AISSTREAM_BBOXES` | Override the search boxes (JSON array) |
| `BL_CARRIER_TIMEOUT_SEC` | Per-request carrier timeout, default `25` / `12` on Heroku |
| `BL_HTTP_TIMEOUT_SEC` | Plain HTML fetch timeout, default `15` / `8` on Heroku |
| `BL_BROWSER_GOTO_TIMEOUT_MS` | Browser navigation timeout, default `60000` / `20000` on Heroku |
| `BL_BROWSER_POLL_SEC` | Browser result polling window, default `30` / `10` on Heroku |

### AIS coverage

aisstream.io is a **terrestrial** receiver network. A vessel name alone is
enough: the client matches `MetaData.ShipName` / `ShipStaticData.Name`
case-insensitively over the Red Sea / Gulf of Aden corridor plus wider Indian
Ocean, Mediterranean, East Asia and South-East Asia boxes. MMSI and IMO remain
optional metadata (MMSI lookups use the tight corridor for speed).

AIS is best-effort enrichment: the free stream samples/sparsifies messages, so
a name lookup may need up to 45 s locally (`AISSTREAM_NAME_TIMEOUT_SEC`) and
can still miss a ship that is transmitting. Satellite-only positions (e.g. a
vessel far offshore near China) are not available from this feed. Transit
status never depends on AIS.

### Heroku request budget

Heroku's router returns `H12` if the app has not produced a response within
**~30 s**. `check-status` therefore:

- runs the AIS lookup and the carrier scrape **concurrently** (total is the
  slower of the two, not their sum);
- shortens the AIS window to **20 s** when `DYNO` is present;
- shortens carrier/HTTP/browser timeouts on Heroku (see the table above);
- uses `gunicorn --timeout 60`, so the worker is not killed at 30 s if the
  router has already answered/queued the request.

Normal runs finish in ~10–22 s. A pathological carrier network stall, or a
browser-backed carrier without `BL_BROWSER_CDP_URL`, can still hit the router
limit; the UI shows the proxy error and the user can retry. The durable fix
for heavy usage is a background job + polling, which this app does not need at
its current request volume.

Set at least:

```bash
heroku config:set AISSTREAM_API_KEY="your-aisstream-key" -a mohan-diredawa
```

Without that key the map simply stays empty (AIS is a no-op), and no request
slows down.


## Running the browser fallback on Heroku

Heroku dynos have no Chrome desktop and no display, so the local
`patchright` + installed-Chrome path will not work. Two options:

1. **Remote browser via CDP (recommended)** — point `BL_BROWSER_CDP_URL` at a
   hosted Chrome, e.g. Browserless:

   ```bash
   heroku config:set BL_BROWSER_CDP_URL="wss://chrome.browserless.io?token=YOUR_TOKEN"
   ```

   The backend connects with `chromium.connect_over_cdp(...)`, opens a page,
   and uses the same JSON interception as local runs.

2. **Buildpack Chrome** — add a Chrome/Chromium buildpack and run headless
   (`BL_BROWSER_HEADLESS=1`). Heavier (~300 MB slug) and slower to start;
   only worth it if you don't want an external browser service.

If you configure neither, set `BL_BROWSER_SCRAPER=0`. MSC and ESL still work
through `curl_cffi`; Maersk/CMA CGM/Hapag will return a clear "browser
required" error instead of a false status.
