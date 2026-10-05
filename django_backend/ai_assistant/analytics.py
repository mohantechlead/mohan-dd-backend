"""Analytics over real executed rows: plain answers, charts, no jargon."""

from datetime import date

from .context import ENTITY_NOUNS


def _nouns(entity: str) -> tuple[str, str]:
    return ENTITY_NOUNS.get(entity, (entity.replace("_", " "), entity.replace("_", " ")))


FIELD_LABELS = {
    "total_quantity": "quantity",
    "PR_before_VAT": "order value",
    "before_vat": "order value",
    "final_price": "invoice value",
    "freight_amount": "freight",
    "amount": "amount",
    "quantity": "quantity",
    "variance_quantity": "variance",
    "purchase_quantity": "ordered quantity",
    "received_quantity": "received quantity",
}


def build_response(plan: dict, rows: list, provenance: dict, admin: bool):
    op = plan["operation"]
    entity = plan["entity"]
    if op == "brief":
        return _brief_response(rows, provenance)
    if op == "forecast":
        return _forecast_response(entity, rows)
    if op == "advise":
        if entity == "overview":
            return _critical_response(rows, provenance)
        return _advise_response(entity, rows, provenance)
    if op == "capabilities":
        return _capabilities_response(entity, rows, provenance)
    if op == "fulfilment":
        return _fulfilment_response(rows, provenance)
    if op == "audit":
        return _audit_response(plan, rows, provenance)
    singular, plural = _nouns(entity)
    date_range = plan.get("date_range") or {}
    period = _period_label(date_range)

    if op == "count":
        total = int((rows[0].get("value") if rows else 0) or 0)
        if total == 1:
            message = f"There is 1 {singular}."
        else:
            message = f"There are {total} {plural}."
        if period:
            message += f" This covers {period}."
        viz = {"type": "none", "title": None, "x_key": None, "y_key": None, "series": []}
        return message, [], viz

    if op in {"sum", "avg", "min", "max"}:
        total = float((rows[0].get("value") if rows else 0) or 0)
        verb = {"sum": "total", "avg": "average", "min": "lowest", "max": "highest"}[op]
        field = FIELD_LABELS.get(plan.get("field") or "", (plan.get("field") or "").replace("_", " "))
        message = f"The {verb} {field} is {round(total, 2)}."
        if period:
            message += f" This covers {period}."
        viz = {"type": "none", "title": None, "x_key": None, "y_key": None, "series": []}
        return message, rows, viz

    if op in {"group_count", "group_sum", "top_n"}:
        series = [{"x": r.get("group"), "y": r.get("value")} for r in rows[:20]]
        chart = plan.get("chart") or "bar"
        by = (plan.get("group_by") or "").replace("_", " ")
        lines = [f"Here is the breakdown by {by}:"]
        if period:
            lines.append(f"This covers {period}.")
        for r in rows[:10]:
            lines.append(f"- {r.get('group')}: {r.get('value')}")
        growth = _growth_note(rows)
        if growth:
            lines.append(f"\n{growth}")
        viz = {"type": chart, "title": f"{entity} by {by}",
               "x_key": "x", "y_key": "y", "series": series}
        return "\n".join(lines), rows, viz

    # list
    if not rows:
        message = "I couldn't find anything matching that in the records."
    elif len(rows) == 1:
        message = f"I found 1 {singular}."
    else:
        message = f"I found {len(rows)} {plural}."
    variance_note = _variance_total_note(rows)
    if variance_note:
        message += f" {variance_note}"
    viz = {"type": "none", "title": None, "x_key": None, "y_key": None, "series": []}
    return message, rows[:20], viz


def _period_label(date_range: dict) -> str:
    start, end = date_range.get("start"), date_range.get("end")
    if start and end:
        return f"{start} to {end}"
    if start:
        return f"from {start}"
    if end:
        return f"up to {end}"
    return ""


def _variance_total_note(rows: list) -> str:
    """Total over/under amount across variance rows, computed from real rows."""
    if not rows or not all(isinstance(r, dict) and "variance_quantity" in r for r in rows):
        return ""
    try:
        total = round(sum(float(r.get("variance_quantity") or 0) for r in rows), 3)
    except (TypeError, ValueError):
        return ""
    if total > 0:
        return f"Altogether, that is {total} more than was ordered."
    if total < 0:
        return f"Altogether, that is {abs(total)} less than was ordered."
    return "The differences balance out to zero overall."


def _growth_note(rows: list) -> str:
    """Month-over-month note computed from real grouped values only."""
    months = [(r.get("group"), r.get("value")) for r in rows
              if isinstance(r.get("group"), str) and r.get("group")[:4].isdigit()]
    if len(months) < 2 or all(float(v or 0) == 0 for _, v in months):
        return ""
    try:
        ordered = sorted(months, key=lambda kv: kv[0])
        (_, prev), (_, curr) = ordered[-2], ordered[-1]
        prev, curr = float(prev or 0), float(curr or 0)
        if prev == 0:
            return f"Latest month: {curr} (no prior-month baseline)."
        pct = (curr - prev) / abs(prev) * 100
        direction = "increased" if pct >= 0 else "decreased"
        return f"Changed by {abs(round(pct, 1))}% {direction} vs the previous month ({prev} to {curr})."
    except (TypeError, ValueError):
        return ""


def _month_buckets(n: int = 6) -> list[str]:
    """First-of-month ISO labels for the last n months including the current one."""
    today = date.today()
    base = today.year * 12 + (today.month - 1)
    out = []
    for i in range(n - 1, -1, -1):
        idx = base - i
        year, month = divmod(idx, 12)
        out.append(date(year, month + 1, 1).isoformat())
    return out


def _fill_monthly(rows: list, n: int = 6) -> list[dict]:
    """Fill missing months with zeros so trends and projections are honest."""
    buckets = _month_buckets(n)
    known = {}
    for r in rows or []:
        key = str(r.get("group") or "")[:10]
        try:
            known[key] = float(r.get("value") or 0)
        except (TypeError, ValueError):
            continue
    filled = []
    for b in buckets:
        value = known.get(b, 0.0)
        if b not in known:
            for key, val in known.items():
                if key.startswith(b[:7]):
                    value = val
                    break
        filled.append({"group": b, "value": value})
    return filled


def _linear_projection(values: list[float]) -> float | None:
    """Least-squares next-point projection. None when there is no trend to read."""
    n = len(values)
    if n < 2 or all(v == 0 for v in values):
        return None
    mean_x = sum(range(n)) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in range(n))
    if denom == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values)) / denom
    intercept = mean_y - slope * mean_x
    return max(0.0, round(slope * n + intercept, 1))


def _next_month_label() -> str:
    buckets = _month_buckets(1)
    year, month = int(buckets[0][:4]), int(buckets[0][5:7])
    nxt = year * 12 + month
    year, month = divmod(nxt, 12)
    return date(year, month + 1, 1).isoformat()


def _brief_response(rows: list, provenance: dict):
    by_status = provenance.get("by_status") or {}
    money = provenance.get("money") or {}
    watchouts = provenance.get("watchouts") or []
    monthly = _fill_monthly(provenance.get("monthly") or [])

    lines = ["Here is the full picture of the business as of today.", ""]
    for row in rows:
        lines.append(f"- {row.get('area')}: {row.get('detail')}")
    if by_status:
        parts = ", ".join(f"{v} {k}" for k, v in sorted(by_status.items()))
        lines += ["", f"Order statuses right now: {parts}."]
    if watchouts:
        lines += ["", "Things worth a decision:"]
        lines += [f"- {w}" for w in watchouts]
    else:
        lines += ["", "Nothing is waiting on a decision right now."]
    lines += ["",
              "These numbers come straight from today's records. "
              "Tell me any area and I can break it down further."]

    series = [{"x": r["group"], "y": r["value"]} for r in monthly]
    viz = {"type": "line", "title": "Orders by month", "x_key": "x",
           "y_key": "y", "series": series}
    return "\n".join(lines), rows, viz


def _forecast_response(entity: str, rows: list):
    from .context import ENTITY_NOUNS
    singular, plural = ENTITY_NOUNS.get(entity, ("record", "records"))
    filled = _fill_monthly(rows)
    nonzero = sum(1 for r in filled if r["value"] > 0)
    if nonzero < 2:
        message = (
            f"There isn't enough history to project {plural} yet. "
            f"Only {nonzero} of the last {len(filled)} months have any records, "
            f"so any guess would be misleading."
        )
        viz = {"type": "line", "title": f"{plural} by month", "x_key": "x",
               "y_key": "y",
               "series": [{"x": r["group"], "y": r["value"]} for r in filled]}
        return message, filled, viz
    values = [r["value"] for r in filled]
    prediction = _linear_projection(values)
    history = ", ".join(f"{int(v)} in {g[:7]}" for g, v in
                        ((r["group"], r["value"]) for r in filled))
    message = (
        f"Looking at the past months ({history}), next month looks like "
        f"about {prediction} {plural if prediction != 1 else singular}. "
        f"This is only a rough guess from past numbers, not a promise."
    )
    series = [{"x": r["group"], "y": r["value"]} for r in filled]
    series.append({"x": _next_month_label() + " (projection)", "y": prediction})
    viz = {"type": "line", "title": f"{plural} forecast", "x_key": "x",
           "y_key": "y", "series": series}
    return message, filled + [{"group": series[-1]["x"], "value": prediction}], viz


def _pretty_date(iso: str) -> str:
    """2026-09-05 -> 5 September 2026. Falls back to the raw value."""
    try:
        year, month, day = (int(part) for part in str(iso)[:10].split("-"))
        names = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November",
                 "December"]
        return f"{day} {names[month - 1]} {year}"
    except (TypeError, ValueError, IndexError):
        return str(iso) if iso else "an unknown date"


def _advise_response(entity: str, rows: list, provenance: dict):
    from .context import ENTITY_NOUNS
    singular, plural = ENTITY_NOUNS.get(entity, ("record", "records"))
    monthly = _fill_monthly(provenance.get("monthly") or [])
    spotlight = provenance.get("spotlight") or []

    lines = [f"Looking at {plural}, here is what I see:", ""]
    for row in rows:
        lines.append(f"- {row.get('area')}: {row.get('detail')}")
    if spotlight:
        first = spotlight[0]
        ref = first.get("ref") or ""
        party = first.get("party") or ""
        when = _pretty_date(first.get("date")) if first.get("date") else ""
        who = f" for {party}" if party else ""
        ancient = f" from {when}" if when else ""
        lines += ["", f"The one waiting longest is {ref}{who}{ancient}."]
    growth = _growth_note([r for r in monthly if r["value"] > 0] or monthly)
    if growth:
        lines.append(growth)
    suggestions = _advise_suggestions(entity, provenance, spotlight)
    if suggestions:
        lines += ["", "What I would do next:"]
        lines += [f"- {s}" for s in suggestions[:3]]
    lines += ["", "Want me to dig into any of these?"]

    series = [{"x": r["group"], "y": r["value"]} for r in monthly]
    viz = {"type": "line", "title": f"{plural} by month", "x_key": "x",
           "y_key": "y", "series": series}
    return "\n".join(lines), spotlight, viz


def _advise_suggestions(entity: str, provenance: dict, spotlight: list) -> list:
    pending = int(provenance.get("pending_count") or 0)
    first = spotlight[0] if spotlight else {}
    ref = first.get("ref") or ""
    party = first.get("party") or ""
    when = _pretty_date(first.get("date")) if first.get("date") else ""
    if entity in {"order", "purchase"} and pending and ref:
        return [f"Start with {ref} for {party} from {when} — it has been waiting longest.",
                "Then work through the rest in date order, oldest first."]
    if entity == "shipping_invoice" and pending and ref:
        return [f"Authorize {ref} for order {party} from {when} first.",
                "Then clear the remaining ones the same way."]
    if entity in {"dn", "grn"} and spotlight:
        return [f"Confirm {ref} for {party} is fully handled, then mark it final.",
                "Anything still open after that is worth a phone call."]
    if entity == "git" and spotlight:
        variance = first.get("variance", 0)
        try:
            amount = abs(float(variance))
        except (TypeError, ValueError):
            amount = variance
        return [f"Look at {party} on {ref} first — {amount} off the ordered quantity.",
                "Agree the correction with the other side before the next load."]
    if entity == "stock" and spotlight:
        return [f"Fix {party} ({ref}) first — its balance is below zero, "
                "so check its receipts and deliveries.",
                "Then re-check the remaining lines the same way."]
    if entity in {"vendor_payment", "received_payment", "expense_payment"} and pending and ref:
        return [f"Chase {ref} from {when} first — it has been waiting longest.",
                "Then follow up the rest in date order."]
    if pending:
        return [f"Clear {ref} first — it has been waiting longest."]
    return []


def _fulfilment_response(rows: list, provenance: dict):
    missing = provenance.get("missing_order")
    if missing:
        return (f"I couldn't find order {missing} in the records. "
                f"Check the number and ask again."), [], _none_viz()
    order_number = provenance.get("order_number", "")
    ordered = float(provenance.get("ordered") or 0)
    delivered = float(provenance.get("delivered") or 0)
    if ordered > 0:
        pct = round(delivered / ordered * 100, 1)
        message = (f"Order {order_number}: {delivered} of {ordered} delivered "
                   f"({pct}%).")
    elif delivered > 0:
        message = (f"Order {order_number}: {delivered} delivered "
                   f"(the order has no recorded total).")
    else:
        message = (f"Nothing has been delivered yet for order {order_number}.")
    if rows:
        message += " " + ", ".join(
            f"{r.get('dn_no')} brought {r.get('delivered')}" for r in rows[:5]) + "."
    if delivered > ordered > 0:
        message += (f" That is {round(delivered - ordered, 3)} more than ordered — "
                    f"worth a look.")
    viz = {"type": "none", "title": None, "x_key": None, "y_key": None,
           "series": []}
    return message, rows, viz


def _audit_response(plan: dict, rows: list, provenance: dict):
    missing = provenance.get("missing_order") or provenance.get("missing_purchase")
    scope = provenance.get("scope", "")
    if missing:
        return (f"I couldn't find proforma {missing} in the records. "
                f"Check the number and ask again."), [], _none_viz()
    scope_label = f"Order {scope}" if scope and scope != "all" else "The proformas"
    if not rows:
        checked = provenance.get("checked") or {}
        bits = []
        if checked.get("orders"):
            bits.append(f"{checked['orders']} sales orders")
        if checked.get("purchases"):
            bits.append(f"{checked['purchases']} purchases")
        coverage = f" (checked {', '.join(bits)})" if bits else ""
        return (f"{scope_label} all check out — every line matches its documents{coverage}."), \
            [], _none_viz()
    label = {"high": "needs attention", "medium": "worth checking",
             "info": "for info"}.get
    lines = [f"{scope_label} do not fully add up. "
             f"{len(rows)} {'thing needs' if len(rows) == 1 else 'things need'} a look:"]
    for row in rows[:10]:
        lines.append(f"- {row.get('detail')} ({label(row.get('severity'), 'note')})")
    first_ref = (rows[0].get("ref") or "").strip()
    if first_ref:
        lines += ["", f"Start with {first_ref}."]
    lines += ["", "Want me to dig into any of these?"]
    viz = {"type": "none", "title": None, "x_key": None, "y_key": None,
           "series": []}
    return "\n".join(lines), rows[:15], viz


def _critical_response(rows: list, provenance: dict):
    issues = provenance.get("issues") or []
    if not issues:
        message = (
            "Nothing looks critical right now. Stock levels are fine, "
            "deliveries match their orders, and nothing big is waiting "
            "for approval."
        )
        viz = {"type": "none", "title": None, "x_key": None,
               "y_key": None, "series": []}
        return message, [], viz
    headline, suggestion = issues[0]
    lines = [f"The most urgent thing I see is this: {headline}"]
    for other_headline, _ in issues[1:]:
        lines.append(f"- Also: {other_headline}")
    lines += ["", f"What I would do first: {suggestion}"]
    lines += ["", "Want the full picture? Ask me for the whole business brief."]
    viz = {"type": "none", "title": None, "x_key": None,
           "y_key": None, "series": []}
    return "\n".join(lines), rows, viz


def _capabilities_response(entity: str, rows: list, provenance: dict):
    examples = provenance.get("examples") or []
    scope = provenance.get("scope") or entity
    if scope == "all":
        lines = ["Here is what I can help with:"]
        for row in rows:
            lines.append(f"- {row.get('area')}: {row.get('total')} on record")
        lines += ["", "Try asking, for example:"]
        lines += [f"- {q}" for q in examples[:6]]
        return "\n".join(lines), rows, _none_viz()
    if scope == "payments":
        lines = ["Here is what I can tell you about payments — money in, "
                 "money out, and costs:"]
        for row in rows:
            lines.append(f"- {row.get('kind')}: {row.get('total')} in total, "
                         f"{row.get('waiting')} waiting")
        if examples:
            lines += ["", "Try asking, for example:"]
            lines += [f"- {q}" for q in examples[:4]]
        return "\n".join(lines), rows, _none_viz()
    total = rows[0].get("total", 0) if rows else 0
    from .context import ENTITY_NOUNS
    singular, plural = ENTITY_NOUNS.get(entity, ("record", "records"))
    noun = singular if total == 1 else plural
    lines = [f"For {plural}, I can count, total, break down, rank, track by month, "
             f"and project what comes next. Right now there "
             f"{'is' if total == 1 else 'are'} {total} {noun} on record."]
    if examples:
        lines += ["", "Try asking, for example:"]
        lines += [f"- {q}" for q in examples[:4]]
    return "\n".join(lines), rows, _none_viz()


def _none_viz() -> dict:
    return {"type": "none", "title": None, "x_key": None, "y_key": None,
            "series": []}


def today_iso() -> str:
    return date.today().isoformat()
