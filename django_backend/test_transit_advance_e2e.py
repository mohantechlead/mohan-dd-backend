"""End-to-end check of the transit-advance flow through the Next.js proxy.

"Advance" here means a stage advance (ECD/IM8 -> Transit Permit -> Closure
Guarantee), not money: the request carries no fields at all. The transitor
cannot move the stage -- and so cannot generate or print the guarantee
letters -- until the admin approves.

Generates its own JWTs (no hand-copied tokens) and drives:
  transitor -> send plain request -> stage still locked
  admin     -> approve -> returns advance + purchase detail
  transitor -> stage moves -> new MPN/DDFT letters are printable

NOTE: resets TEST_PURCHASE (stage, letters, advance) so the run is repeatable.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_backend.settings")

import django

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from inventory.models import Purchase, TransitAdvance, TransitDocument  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

NEXT = "http://localhost:3000"
DJANGO = "http://127.0.0.1:8000"
PURCHASE = os.environ.get("TEST_PURCHASE", "MPDDBLT01")

User = get_user_model()
tokens = {
    name: str(RefreshToken.for_user(User.objects.get(username=name)).access_token)
    for name in ("admin", "transitor")
}

# Reset so the request -> review -> advance -> letters flow runs from scratch.
purchase = Purchase.objects.get(purchase_number=PURCHASE)
TransitDocument.objects.filter(purchase=purchase).delete()
TransitAdvance.objects.filter(purchase=purchase).delete()
if purchase.stage != "ecd_im8":
    purchase.stage = "ecd_im8"
    purchase.save(update_fields=["stage"])
if purchase.assigned_transitor is None:
    purchase.assigned_transitor = User.objects.get(username="transitor")
    purchase.save(update_fields=["assigned_transitor"])


def call(base, method, path, token=None, body=None, cookie=False):
    """Return (status, parsed-json-or-text)."""
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        if cookie:
            req.add_header("Cookie", f"auth-token={token}")
        else:
            req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status, raw = resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode()
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def check(label, actual, expected, detail=""):
    ok = actual == expected
    print(
        f"  [{'PASS' if ok else 'FAIL'}] {label}: got {actual}, want {expected}"
        + (f" -- {detail}" if detail and not ok else "")
    )
    return ok


results = []
A, T = tokens["admin"], tokens["transitor"]

print("\n== 1. transitor sends a plain advance request (via Next proxy) ==")
st, data = call(NEXT, "POST", f"/api/purchases/{PURCHASE}/advance", T, {}, cookie=True)
results.append(check("request advance", st, 200, str(data)[:300]))
advance_id = data.get("id") if isinstance(data, dict) else None
results.append(check("status pending", data.get("status"), "pending"))
results.append(check("requested_by", data.get("requested_by"), "transitor"))
results.append(check("names the next stage", data.get("target_stage"), "transit_permit"))
results.append(
    check(
        "stage label",
        data.get("target_stage_label"),
        "Transit Permit",
    )
)
for money_field in ("amount", "currency", "note"):
    results.append(check(f"no {money_field} field", money_field in (data or {}), False))

print("\n== 2. transitor cannot move the stage while it is pending ==")
st, data = call(
    NEXT,
    "POST",
    f"/api/purchases/{PURCHASE}/stage",
    T,
    {"stage": "transit_permit"},
    cookie=True,
)
results.append(check("stage move blocked", st, 403, str(data)[:300]))
results.append(
    check("mentions approval", "approve" in str(data.get("detail", "")).lower(), True)
)

st, data = call(NEXT, "GET", f"/api/purchases/{PURCHASE}/transit-documents", T, cookie=True)
results.append(check("letters blocked", st, 403, str(data)[:300]))

st, data = call(NEXT, "GET", f"/api/purchases/{PURCHASE}", T, cookie=True)
results.append(
    check(
        "purchase detail hides letters",
        len(data.get("transit_documents", [])) if isinstance(data, dict) else -1,
        0,
        str(data)[:300],
    )
)

print("\n== 3. admin inbox lists it with purchase detail (via Next proxy) ==")
st, data = call(NEXT, "GET", "/api/transit-advances?status=pending", A, cookie=True)
results.append(check("admin list", st, 200, str(data)[:300]))
rows = data if isinstance(data, list) else []
mine = [r for r in rows if r.get("advance", {}).get("purchase_number") == PURCHASE]
results.append(check("our row present", len(mine) >= 1, True, str(rows)[:300]))
if mine:
    row = mine[0]
    results.append(check("row carries purchase detail", bool(row.get("purchase", {}).get("buyer")), True))
    results.append(
        check("row carries the requested stage", row.get("advance", {}).get("target_stage"), "transit_permit")
    )
    results.append(
        check("row carries no money", "amount" in row.get("advance", {}), False)
    )

print("\n== 4. non-admin cannot review (via Next proxy) ==")
st, data = call(NEXT, "POST", f"/api/transit-advances/{advance_id}/approve", T, {}, cookie=True)
results.append(check("transitor approve blocked", st, 403, str(data)[:300]))

print("\n== 5. admin approves -> advance + purchase detail (via Next proxy) ==")
st, data = call(NEXT, "POST", f"/api/transit-advances/{advance_id}/approve", A, {}, cookie=True)
results.append(check("approve", st, 200, str(data)[:300]))
results.append(check("advance approved", data.get("advance", {}).get("status"), "approved"))
results.append(check("reviewed_by", data.get("advance", {}).get("reviewed_by"), "admin"))
results.append(
    check("approved stage", data.get("advance", {}).get("target_stage"), "transit_permit")
)
results.append(check("purchase in payload", data.get("purchase", {}).get("purchase_number"), PURCHASE))
results.append(check("buyer in payload", bool(data.get("purchase", {}).get("buyer")), True))
results.append(check("stage in payload", bool(data.get("purchase", {}).get("stage")), True))
results.append(
    check("advance embedded in purchase", data.get("purchase", {}).get("advance", {}).get("status"), "approved")
)

print("\n== 6. asking again before moving is rejected ==")
st, data = call(NEXT, "POST", f"/api/purchases/{PURCHASE}/advance", T, {}, cookie=True)
results.append(check("duplicate request blocked", st, 400, str(data)[:300]))

print("\n== 7. transitor advances the stage and the letters become printable ==")
st, data = call(
    NEXT,
    "POST",
    f"/api/purchases/{PURCHASE}/stage",
    T,
    {"stage": "transit_permit"},
    cookie=True,
)
results.append(check("stage move allowed", st, 200, str(data)[:300]))
results.append(check("stage is transit_permit", data.get("stage"), "transit_permit"))
letters = data.get("transit_documents", []) if isinstance(data, dict) else []
results.append(check("two letters generated", len(letters), 2, str(letters)[:300]))
refs = [d.get("reference_number", "") for d in letters]
print(f"       references: {refs}")
for ref in refs:
    results.append(check(f"format of {ref}", bool(re.fullmatch(r"MPN/DDFT/\d{3}/26", ref)), True))

st, data = call(NEXT, "GET", f"/api/purchases/{PURCHASE}/transit-documents", T, cookie=True)
results.append(check("letters unlocked", st, 200, str(data)[:300]))
if isinstance(data, list):
    print(f"       letters: {[d.get('document_type') for d in data]}")

st, data = call(NEXT, "GET", f"/api/purchases/{PURCHASE}", T, cookie=True)
letter_count = len(data.get("transit_documents", [])) if isinstance(data, dict) else -1
results.append(check("purchase detail shows letters", letter_count > 0, True, str(data)[:200]))
print(f"       letters visible to transitor: {letter_count}")

print("\n== 8. re-approving an already-reviewed advance is rejected ==")
st, data = call(NEXT, "POST", f"/api/transit-advances/{advance_id}/approve", A, {}, cookie=True)
results.append(check("second approve blocked", st, 400, str(data)[:300]))

print("\n== 9. the next stage can be asked for straight away ==")
st, data = call(NEXT, "POST", f"/api/purchases/{PURCHASE}/advance", T, {}, cookie=True)
results.append(check("next-stage request accepted", st, 200, str(data)[:300]))
results.append(
    check("names closure guarantee", data.get("target_stage"), "closure_guarantee")
)

print("\n== 10. admin can always see the letters ==")
st, data = call(DJANGO, "GET", f"/api/inventory/purchases/{PURCHASE}", A)
results.append(check("admin purchase detail", st, 200, str(data)[:300]))

# Leave the demo purchase where a person testing by hand would want it:
# stage reached, advance approved for that stage, letters printable.
purchase.refresh_from_db()
advance = TransitAdvance.objects.get(purchase__purchase_number=PURCHASE)
advance.status = "approved"
advance.target_stage = purchase.stage
advance.save(update_fields=["status", "target_stage"])
print(f"\nDemo state: {PURCHASE} at {purchase.stage}, advance approved, "
      f"{purchase.transit_documents.count()} letter(s) printable.")

passed = sum(1 for r in results if r)
print(f"\n==== {passed}/{len(results)} checks passed ====")
sys.exit(0 if all(results) else 1)
