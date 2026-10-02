"""Natural-language -> validated query plan.

Rule-based parser first (deterministic, no network). Gemini is used only as
an assist layer and never touches the database:
1. If rules produce a confident plan, use it.
2. Otherwise, if GEMINI_API_KEY is configured, ask Gemini for a STRICT JSON
   intent object, then validate it against validators.validate_query_plan.
3. Final user-facing wording may be polished by Gemini, but numbers always
   come from executed ORM queries.
"""

import logging
import re
import uuid
from datetime import date

from django.conf import settings

from .context import (
    ADVISABLE_ENTITIES,
    ENTITIES,
    FORECASTABLE_ENTITIES,
    RELATIONSHIPS,
    STATUS_MEANINGS,
)
from .validators import validate_query_plan

logger = logging.getLogger(__name__)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

PRONOUNS = {"those", "them", "these", "it", "that"}


def new_conversation_id() -> str:
    return uuid.uuid4().hex[:12]


def resolve_context(message: str, history: list) -> dict:
    """Carry forward entity/filters when the user says 'those/them/show breakdown'."""
    if not history:
        return {}
    last = history[-1]
    text = message.lower()
    if any(p in text for p in PRONOUNS) or "breakdown" in text or "those" in text:
        return {
            "entity": last.get("entity"),
            "filters": dict(last.get("filters") or {}),
            "date_range": dict(last.get("date_range") or {}),
        }
    return {}


def _direct_plan(entity: str, operation: str, chart: str = "none",
                 group_by: str | None = None) -> tuple[dict | None, float, str]:
    """Build and validate a fixed plan for intents that need no parsing."""
    plan = {"entity": entity, "operation": operation, "field": None,
            "group_by": group_by, "filters": {}, "date_range": {},
            "sort": None, "limit": None, "chart": chart}
    ok, error = validate_query_plan(plan)
    if ok:
        return plan, 0.8, "rule-based"
    return None, 0.0, error


REFUSAL_PATTERNS = [
    (r"\bphone\b|\btelephone\b|\bmobile\b|\bcontact number\b|\bphone number\b", "phone numbers"),
    (r"\bemail\b|\bmail address\b", "email addresses"),
    (r"\bbank\b.{0,25}\bdetail|\baccount number\b|\bbank account\b", "bank details"),
    (r"\btin\b|\btax id\b", "TIN numbers"),
    (r"\bpassword\b", "passwords"),
    (r"\bstreet address\b|\bhome address\b", "private addresses"),
]


def _refusal_check(low: str) -> str | None:
    """Specific refusal for private fields. Checked before anything else."""
    for pattern, thing in REFUSAL_PATTERNS:
        if re.search(pattern, low):
            return (
                f"I can't share {thing} — that information is private and I never show it. "
                "I can show names, totals, and statuses instead. What would you like to know?"
            )
    return None


def _domain_spec() -> str:
    lines = []
    for entity, meta in ENTITIES.items():
        if entity == "overview":
            continue
        fields = ", ".join(meta["safe_fields"]) or "-"
        lines.append(f"- {entity}: {meta['description']} Fields: {fields}.")
    lines.append("Links: " + " | ".join(RELATIONSHIPS))
    lines.append("Statuses: " + "; ".join(f"{k}={v}" for k, v in STATUS_MEANINGS.items()))
    lines.append("Operations: count, sum, avg, min, max, list, group_count, "
                 "group_sum, top_n, brief, forecast, advise, capabilities, fulfilment.")
    return "\n".join(lines)


def _resolved_refs(history: list) -> dict:
    """Newest-first known references (order/purchase/invoice numbers, names)."""
    refs: dict = {}
    for turn in reversed(history or []):
        plan = (turn or {}).get("plan") or {}
        for key in ("order_number", "order_number_contains", "purchase_number",
                    "invoice_number", "buyer", "shipper", "customer_name",
                    "supplier_name", "status"):
            value = (plan.get("filters") or {}).get(key)
            if value and key not in refs:
                refs[key] = value
        if refs.get("order_number") or refs.get("order_number_contains"):
            refs.setdefault("entity", plan.get("entity"))
            break
    return refs


def llm_parse_message(message: str, history: list | None = None):
    """LLM-first intent detection. Returns (plan, confidence, note) or None.

    The model only produces a validated JSON plan — it never sees raw rows
    and never touches the database. Anything invalid falls back to rules.
    """
    from .validators import ALLOWED_FILTER_KEYS, validate_query_plan

    model = _gemini_model()
    if model is None:
        return None
    history = history or []
    convo_lines = []
    for turn in history[-3:]:
        user_text = ((turn or {}).get("message") or "")[:250]
        assistant_plan = (turn or {}).get("plan") or {}
        if user_text:
            convo_lines.append(
                f"- user said: {user_text} | understood as: "
                f"{assistant_plan.get('operation')}/{assistant_plan.get('entity')} "
                f"{assistant_plan.get('filters', {})}")
    convo = "\n".join(convo_lines) if convo_lines else "(start of conversation)"
    refs = _resolved_refs(history)
    prompt = (
        "You parse warehouse questions into a strict JSON query plan. "
        "Output ONLY a JSON object, no other text.\n"
        f"Today is {date.today().isoformat()}.\n"
        "Domain:\n" + _domain_spec() + "\n"
        "Allowed filter keys: " + ", ".join(sorted(ALLOWED_FILTER_KEYS)) + ". "
        "Allowed charts: bar, line, pie, scatter, none.\n"
        "Conversation so far:\n" + convo + "\n"
        f"Known references: {refs if refs else 'none'}.\n"
        "Rules:\n"
        "- entity must be one of the listed entities, 'payments' (all kinds "
        "together), or 'overview' (whole business). Bare 'payment' with no type "
        "words means 'payments'. 'sales' means order. 'over/under delivered' "
        "means git.\n"
        "- operation must be one of the listed operations.\n"
        "- Resolve 'it', 'those', 'that order/supplier', 'same X', and bare "
        "numbers like 22722 using the conversation and known references "
        "(bare digits with order context mean order_number_contains).\n"
        "- Dates become YYYY-MM-DD in date_range {start, end}.\n"
        "- Decision words (decide, advice, recommend, in detail, tell me about) "
        "mean advise; predict/forecast means forecast with group_by month; "
        "critical/urgent means entity overview + advise; 'what can you' means "
        "capabilities.\n"
        "- Delivery progress ('how much of order X has been delivered', "
        "'what was delivered') means entity order (or dn for 'what was'), "
        "operation fulfilment for amounts, list of dn rows for item detail.\n"
        "- If genuinely ambiguous, return {\"entity\": null, \"question\": "
        "\"<one specific question naming the candidate areas>\"}.\n"
        "- Only use filters the user explicitly stated: numbers, quoted names, "
        "or a status/date range they actually named. Never invent status, "
        "party, or number filters.\n"
        "Return keys: entity, operation, field, group_by, filters, date_range, "
        "limit, chart.\n"
        f"Question: {message[:500]}"
    )
    try:
        response = model.generate_content(prompt)
        raw = (getattr(response, "text", "") or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            return None
        import json
        plan = json.loads(raw[start:end + 1])
        if plan.get("entity") is None and plan.get("question"):
            return None
        plan["entity"] = str(plan.get("entity") or "").strip().lower()
        plan["operation"] = str(plan.get("operation") or "").strip().lower()
        plan["filters"] = plan.get("filters") or {}
        plan["date_range"] = plan.get("date_range") or {}
        plan["chart"] = plan.get("chart") or "none"
        ok, _ = validate_query_plan(plan)
        if ok and _filters_grounded(plan, message.lower()) \
                and _operation_fits(plan, message.lower()):
            return plan, 0.85, "llm"
        if ok:
            logger.warning("LLM plan rejected: ungrounded or mistyped %s", plan)
        else:
            logger.warning("LLM plan rejected by validator: %s", plan)
        return None
    except Exception as exc:
        logger.warning("LLM intent parse failed: %s", exc)
        return None


def _filters_grounded(plan: dict, low: str) -> bool:
    """Every filter must be traceable to the user's own words.

    The LLM sometimes invents plausible filters (e.g. status=completed
    unasked). Ungrounded plans are rejected so the rule parser gets a turn.
    date_range is exempt: relative dates like 'last month' compute to dates
    that never appear literally.
    """
    filters = plan.get("filters") or {}
    for key, value in filters.items():
        if value is None or value == "":
            return False
        if key in ("is_last",):
            continue
        if key == "status":
            if str(value).lower() not in low:
                return False
            continue
        if key == "variance_type":
            if "over" not in low and "under" not in low and "short" not in low:
                return False
            continue
        if key in ("partner_type", "payment_type"):
            if str(value).lower().replace("_", " ") not in low:
                return False
            continue
        text_value = str(value).strip()
        if key in ("order_number", "order_number_contains", "purchase_number",
                   "invoice_number", "dn_no", "grn_no"):
            digits = "".join(ch for ch in text_value if ch.isdigit())
            if not digits or digits not in low:
                return False
            continue
        token = text_value.lower()
        if token not in low and not any(
                len(part) >= 4 and part in low for part in token.split()):
            return False
    return True


def _operation_fits(plan: dict, low: str) -> bool:
    """The plan's operation must match the question type.

    Catches LLM plans that are valid but answer the wrong question
    (e.g. a flat list for 'which supplier received the most').
    """
    op = plan.get("operation")
    if re.search(r"\btop\b|most|highest|fastest|largest", low):
        return op == "top_n"
    if re.search(r"how many|number of", low):
        return op in ("count", "group_count")
    if re.search(r"how much|total of|sum of", low):
        return op in ("sum", "fulfilment", "list")
    if "trend" in low or "over time" in low:
        return op in ("group_count", "forecast")
    if re.search(r"\bpredict|\bforecast", low):
        return op == "forecast"
    return True


def specific_clarification(low: str) -> str:
    """Targeted follow-up naming likely areas instead of a generic menu."""
    if re.search(r"trend|month|chart|graph|compar|breakdown|percent|forecast|predict", low):
        return ("Do you want that for orders, deliveries, or payments? "
                "Name one and I'll chart it.")
    if re.search(r"\bpay\b|\bmoney\b|\bcost\b|\bexpense\b", low):
        return "Is that about money coming in, money going out, or costs?"
    if re.search(r"\border\b|\bdeliver|\bstock\b|\binvoice\b|\bpurchase\b", low):
        return ("Do you want the overall total, a breakdown, or the records "
                "for one specific number?")
    return ("I can look up orders, deliveries, stock, invoices, or payments. "
            "Which one is your question about?")


def parse_message(message: str, history: list | None = None, use_llm: bool = True):
    """Entry point: refusal -> LLM planning -> rule fallback -> clarification."""
    history = history or []
    text = (message or "").strip()
    if not text:
        return None, 0.0, "Please ask a question about orders, deliveries, stock, or payments."
    refused = _refusal_check(text.lower())
    if refused:
        return None, 0.0, refused
    if use_llm:
        try:
            result = llm_parse_message(text, history)
        except Exception as exc:
            logger.warning("LLM parse wrapper failed: %s", exc)
            result = None
        if result:
            return result
    return rule_parse_message(text, history)


def rule_parse_message(message: str, history: list | None = None) -> tuple[dict | None, float, str]:
    """Deterministic rule-based parser. Used directly when no LLM key is set,
    and as the fallback when LLM planning fails or is rejected."""
    history = history or []
    text = (message or "").strip()
    low = text.lower()
    if not text:
        return None, 0.0, "Please ask a question about orders, deliveries, stock, or payments."
    ctx = resolve_context(text, history)
    last_plan = (history[-1].get("plan") or {}) if history else {}

    entity = _detect_entity(low)
    chart_request = _detect_chart_request(low)
    wants_visual = chart_request is not None or "analytic" in low
    from_memory = False
    critical_trigger = bool(re.search(
        r"\bcritical\b|\burgent|\bemergency\b|\balarming\b|\bbiggest problem\b"
        r"|\bmost important\b|\banything wrong\b|\bsomething wrong\b", low))
    cap_trigger = bool(re.search(
        r"what can you\b|what do you know|your capabilit|list your skills", low))
    has_context = bool(last_plan.get("entity") or ctx.get("entity"))
    if critical_trigger and entity is None and not has_context:
        # "tell me something critical" names nothing: scan the whole business.
        return _direct_plan("overview", "advise")
    if cap_trigger and entity is None and not has_context:
        # "what can you answer" names nothing: describe everything.
        return _direct_plan("overview", "capabilities")

    if entity is None and last_plan.get("entity"):
        # Follow-up with no new entity ("show me the line graph", "and for
        # August?"). Continue the previous analysis instead of forgetting it.
        entity = last_plan["entity"]
        from_memory = True
        if wants_visual and not _detect_filters(text, low, entity) \
                and not _detect_date_range(low):
            plan = {
                "entity": entity,
                "operation": last_plan.get("operation") or "group_count",
                "field": last_plan.get("field"),
                "group_by": last_plan.get("group_by") or "month",
                "filters": dict(last_plan.get("filters") or {}),
                "date_range": dict(last_plan.get("date_range") or {}),
                "sort": None,
                "limit": last_plan.get("limit"),
                "chart": chart_request if chart_request != "generic" else "line",
            }
            ok, error = validate_query_plan(plan)
            if ok:
                return plan, 0.7, "continued"
            return None, 0.0, error
    if not entity and ctx.get("entity"):
        entity = ctx["entity"]
        from_memory = True
    forecast_trigger = bool(re.search(
        r"\bforecast\b|\bpredict|\bprojection\b|\bprojected\b", low))
    if entity == "overview" and forecast_trigger:
        entity = _detect_entity(low, exclude=("overview",)) or "order"
    if entity == "overview":
        plan = {
            "entity": "overview", "operation": "brief", "field": None,
            "group_by": "month", "filters": {}, "date_range": {},
            "sort": None, "limit": None, "chart": "line",
        }
        ok, error = validate_query_plan(plan)
        if ok:
            return plan, 0.8, "rule-based"
        return None, 0.0, error
    if not entity:
        return None, 0.0, specific_clarification(low)

    operation, field, group_by, limit = _detect_operation(low, entity)
    filters = _detect_filters(text, low, entity)
    date_range = _detect_date_range(low)
    if forecast_trigger and entity in FORECASTABLE_ENTITIES:
        # "predict next month orders": project monthly counts, line chart.
        operation, field, group_by, limit = "forecast", None, "month", None
        date_range = {}
    decision_trigger = bool(re.search(
        r"\bdecide\b|\bdecision\b|\badvice\b|\badvise\b|\brecommend|\bsuggest"
        r"|\bwhat should\b|\bhelp me\b|\battention\b|\brisk\b|\bworried\b|\bworry\b"
        r"|\bin detail\b|\bdetailed\b|\btell me about\b|\bmore about\b",
        low))
    if decision_trigger and entity in ADVISABLE_ENTITIES and operation != "forecast":
        # "help me make a decision for sales": scoped analysis, not a bare count.
        operation, field, group_by = "advise", None, "month"
    if critical_trigger:
        # Cross-business urgency scan, even mid-conversation.
        entity, operation, field, group_by = "overview", "advise", None, None
        filters, date_range, limit = {}, {}, None
    if cap_trigger and operation != "forecast":
        operation, field, group_by = "capabilities", None, None
    if entity == "git" and operation == "sum" \
            and re.search(r"detect|issue|which|show|list", low):
        # "by how much was it over delivered, and can you detect the issue":
        # name the offending lines; the total is added to the answer.
        operation, limit = "list", 20
    if entity in ("dn", "order") and "deliver" in low \
            and re.search(r"how much|much of|fulfil|progress|percent|%|left|remain", low):
        # "How much of that order has been delivered": order fulfilment.
        ref = (filters.get("order_number")
               or filters.get("order_number_contains")
               or (ctx.get("filters") or {}).get("order_number")
               or (ctx.get("filters") or {}).get("order_number_contains"))
        if ref or "order" in low:
            entity, operation, field, group_by = "order", "fulfilment", None, None
    if not filters and ctx.get("filters"):
        filters = ctx["filters"]
    if not date_range and ctx.get("date_range"):
        date_range = ctx["date_range"]
    if group_by is None and ("per month" in low or "by month" in low or "monthly" in low):
        operation, group_by = "group_count", "month"
    if chart_request in ("line", "bar", "pie", "scatter") \
            and operation in {"count", "sum", "avg", "min", "max"} \
            and group_by is None:
        operation = "group_count"
        group_by = "month" if chart_request == "line" else _default_group(entity)
    if chart_request in ("line", "bar", "pie", "scatter"):
        chart = chart_request
    else:
        chart = _suggest_chart(operation, group_by)

    plan = {
        "entity": entity,
        "operation": operation,
        "field": field,
        "group_by": group_by,
        "filters": filters,
        "date_range": date_range,
        "sort": None,
        "limit": limit,
        "chart": chart,
    }
    ok, error = validate_query_plan(plan)
    if not ok:
        # Try Gemini assist once; otherwise ask a clarifying question.
        assisted = gemini_intent_assist(text, entity)
        if assisted:
            ok2, error2 = validate_query_plan(assisted)
            if ok2:
                return assisted, 0.6, "assisted"
            return None, 0.0, error2
        return None, 0.0, error

    confidence = 0.9 if filters or date_range or operation != "list" else 0.7
    if operation == "list" and not filters and not date_range and not (
            from_memory and re.search(r"\ball\b|\bthem\b|\beverything\b", low)):
        return None, 0.0, (
            "That could return a lot of records. "
            "Do you want a specific date range, customer/supplier, or order number?"
        )
    return plan, confidence, "rule-based"


def _detect_entity(low: str, exclude: tuple = ()) -> str | None:
    # Over/under delivery and receipt questions are variance questions,
    # even though they contain the words "deliver" or "receipt".
    if "git" not in exclude and re.search(r"over[\s-]?deliver|under[\s-]?deliver|over[\s-]?receipt|under[\s-]?receipt", low):
        return "git"
    if "payments" not in exclude and re.search(r"\bsupplier\b", low) \
            and not re.search(r"\border\b", low) \
            and re.search(r"\bpay|\bmoney\b|\bamount\b|\breceiv|\bmost\b|\btop\b", low):
        # "which supplier received the most payments" = money paid out.
        return "vendor_payment"
    if "payments" not in exclude and re.search(r"\bcustomer\b", low) \
            and not re.search(r"\border\b", low) \
            and re.search(r"\bpay\b|\bmoney\b|\bamount\b|\breceiv|\bmost\b|\btop\b", low):
        # "which customers paid the most" = money received.
        return "received_payment"
    scores = {}
    for entity, meta in ENTITIES.items():
        if entity in exclude:
            continue
        hits = sum(1 for kw in meta["keywords"] if kw in low)
        if hits:
            scores[entity] = hits
    if not scores:
        return None
    # Prefer more specific entities on ties (invoice > order, dn > order).
    priority = ["overview", "shipping_invoice", "dn", "grn", "git", "vendor_payment",
                "received_payment", "expense_payment", "payments", "purchase", "order",
                "stock", "item", "partner"]
    return sorted(scores, key=lambda e: (scores[e], -priority.index(e) if e in priority else 0), reverse=True)[0]


def _detect_operation(low: str, entity: str):
    limit = None
    m = re.search(r"top\s+(\d{1,3})", low)
    if m:
        limit = max(1, min(100, int(m.group(1))))
    if "trend" in low or "over time" in low:
        return "group_count", None, "month", limit
    if re.search(r"how many|count|number of", low):
        return "count", None, None, limit
    if re.search(r"how much", low):
        return "sum", _default_metric(entity), None, limit
    if "top" in low or "highest" in low or "most" in low or "fastest" in low:
        group_by = _detect_group_by(low, entity) or _default_group(entity)
        field = _default_metric(entity)
        return "top_n", field, group_by, limit or 10
    if "percent" in low or "percentage" in low or "breakdown" in low or "by status" in low or "by customer" in low or "by month" in low or "by supplier" in low or "by vendor" in low:
        group_by = _detect_group_by(low, entity) or _default_group(entity)
        return "group_count", None, group_by, limit
    if "compar" in low:
        return "group_count", None, "month", limit
    if re.search(r"\btotal\b|\bsum\b", low):
        return "sum", _default_metric(entity), None, limit
    if "average" in low or "avg" in low:
        return "avg", _default_metric(entity), None, limit
    if "suspicious" in low or "greater than" in low or "over-deliver" in low or "overdeliver" in low:
        return "list", None, None, 20
    if entity in ("dn", "grn") and re.search(r"what was|what has been", low):
        return "list", None, None, 20
    if re.search(r"\bshow\b|\blist\b|\bfind\b|\bget\b|\bwhat happened\b|\bdetails?\b", low):
        return "list", None, None, 20
    return "count", None, None, limit


def _detect_group_by(low: str, entity: str) -> str | None:
    if "month" in low:
        return "month"
    if "status" in low:
        return "status" if "status" in ENTITIES[entity]["safe_fields"] else None
    if any(w in low for w in ("supplier", "vendor")):
        for candidate in ("supplier_name", "shipper", "name"):
            if candidate in ENTITIES[entity]["safe_fields"]:
                return candidate
        if entity == "payments":
            return "supplier_name"
    if any(w in low for w in ("customer", "buyer", "client")):
        for candidate in ("buyer", "customer_name", "name"):
            if candidate in ENTITIES[entity]["safe_fields"]:
                return candidate
    if any(w in low for w in ("supplier", "shipper", "vendor")):
        for candidate in ("shipper", "supplier_name", "name"):
            if candidate in ENTITIES[entity]["safe_fields"]:
                return candidate
    if any(w in low for w in ("product", "item")):
        for candidate in ("item_name",):
            if candidate in ENTITIES[entity]["safe_fields"]:
                return candidate
    return None


def _default_group(entity: str) -> str:
    meta = ENTITIES[entity]
    for candidate in ("buyer", "customer_name", "supplier_name", "shipper",
                      "name", "item_name", "status", "month"):
        if candidate == "month" or candidate in meta["safe_fields"]:
            return candidate
    return "month"


def _default_metric(entity: str) -> str | None:
    meta = ENTITIES[entity]
    for candidate in ("total_quantity", "PR_before_VAT", "before_vat",
                      "final_price", "amount", "quantity", "variance_quantity"):
        if candidate in meta["numeric_fields"]:
            return candidate
    return None


def _detect_filters(text: str, low: str, entity: str) -> dict:
    filters: dict = {}
    m = re.search(r"\bM(\d{2,6})\b", text.upper())
    if m and entity in {"order", "dn", "shipping_invoice", "received_payment"}:
        filters["order_number"] = f"M{m.group(1)}"
    m = re.search(r"MPDDFZE(\d{1,6})", text.upper())
    if m and entity in {"purchase", "grn", "git", "vendor_payment"}:
        filters["purchase_number"] = f"MPDDFZE{m.group(1).zfill(3)}"
    m = re.search(r"\bA(\d{2,6})\b", text.upper())
    if m and entity == "shipping_invoice":
        filters["invoice_number"] = f"A{m.group(1)}"
    if not any(k in filters for k in ("order_number", "order_number_contains")):
        digits = re.search(r"\b(\d{4,6})\b", text)
        if digits and (entity in {"order", "dn", "shipping_invoice", "received_payment"}
                       or "order" in low or (ctx.get("filters") or {}).get("order_number")):
            # Bare "22722" with order context means that order number.
            filters["order_number_contains"] = digits.group(1)
    for status in ("pending", "approved", "completed", "cancelled"):
        if re.search(rf"\b{status}\b", low):
            filters["status"] = status
    if "over" in low and ("deliver" in low or "variance" in low or "suspicious" in low):
        filters["variance_type"] = "increased"
    m = re.search(r'["\']([^"\']{2,80})["\']', text)
    if m:
        name = m.group(1).strip()
        key = {"order": "buyer", "dn": "customer_name", "grn": "supplier_name",
               "purchase": "shipper", "partner": "name"}.get(entity)
        if key:
            filters[key] = name
    return filters


def _detect_date_range(low: str) -> dict:
    today = date.today()
    if "last month" in low:
        first_this = today.replace(day=1)
        end = first_this.toordinal() - 1
        end_date = date.fromordinal(end)
        return {"start": end_date.replace(day=1).isoformat(), "end": end_date.isoformat()}
    if "this month" in low or "current month" in low:
        return {"start": today.replace(day=1).isoformat(), "end": today.isoformat()}
    if "this year" in low or "current year" in low:
        return {"start": today.replace(month=1, day=1).isoformat(), "end": today.isoformat()}
    if "last year" in low:
        return {"start": f"{today.year - 1}-01-01", "end": f"{today.year - 1}-12-31"}
    for name, num in MONTHS.items():
        if name in low:
            year = today.year
            m = re.search(r"(20\d{2})", low)
            if m:
                year = int(m.group(1))
            start = date(year, num, 1)
            end = date(year + (num == 12), num % 12 + 1, 1).fromordinal(
                date(year + (num == 12), num % 12 + 1, 1).toordinal() - 1)
            return {"start": start.isoformat(), "end": end.isoformat()}
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", low)
    if m:
        return {"start": m.group(1), "end": m.group(1)}
    return {}


def _detect_chart_request(low: str) -> str | None:
    """Return 'line'/'bar'/'pie'/'scatter'/'generic' when the user asks for a visual."""
    if re.search(r"\bline\b", low):
        return "line"
    if re.search(r"\bpie\b|\bdonut\b", low):
        return "pie"
    if re.search(r"\bbar\b", low):
        return "bar"
    if re.search(r"\bscatter\b", low):
        return "scatter"
    if re.search(r"\bgraph\b|\bchart\b|\bvisual\b", low):
        return "generic"
    return None


def _suggest_chart(operation: str, group_by: str | None) -> str:
    if group_by == "month":
        return "line"
    if operation in {"top_n", "group_sum", "group_count"}:
        return "bar"
    if operation == "group_count" and group_by in {"status", "partner_type", "payment_type"}:
        return "pie"
    return "none"


# ---------------- Gemini assist (optional, never touches the DB) ----------------

def _gemini_model():
    key = getattr(settings, "GEMINI_API_KEY", "") or ""
    if not key:
        return None
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        logger.warning("google-generativeai not installed; skipping Gemini assist")
        return None
    genai.configure(api_key=key)
    model_name = getattr(settings, "GEMINI_MODEL", "gemini-3.1-flash-lite")
    return genai.GenerativeModel(model_name)


def gemini_intent_assist(message: str, entity: str) -> dict | None:
    """Ask Gemini for a strict-JSON intent; always validated before use."""
    model = _gemini_model()
    if model is None:
        return None
    allowed_entities = sorted(ENTITIES)
    prompt = (
        "You map a warehouse question to a strict JSON query plan. "
        f"Allowed entities: {allowed_entities}. "
        "Allowed operations: count,sum,avg,min,max,list,group_count,group_sum,top_n. "
        "Allowed charts: bar,line,pie,scatter,none. "
        "Reply with ONLY a JSON object with keys entity,operation,field,"
        "group_by,filters,date_range,limit,chart. "
        f"Entity hint: {entity}. Question: {message[:500]}"
    )
    try:
        response = model.generate_content(prompt)
        raw = (getattr(response, "text", "") or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            return None
        import json
        plan = json.loads(raw[start:end + 1])
        plan.setdefault("filters", {})
        plan.setdefault("date_range", {})
        plan.setdefault("chart", "none")
        return plan
    except Exception as exc:  # network/model errors must not break chat
        logger.warning("Gemini intent assist failed: %s", exc)
        return None


def gemini_explain(summary: str, sample_rows: list, noun: str = "records",
                   measure: str = "") -> str | None:
    """Polish wording only. Numbers come from the caller; never invent data."""
    model = _gemini_model()
    if model is None:
        return None
    import json
    measure_line = (f"The headline number is {measure}. " if measure else "")
    prompt = (
        "You are a friendly warehouse assistant talking to a non-technical user. "
        "Rewrite the finding below in 1-3 short plain sentences a shopkeeper would "
        "understand. Use everyday words only: no jargon, no field names, no mention "
        "of filters, record counts, date ranges, or databases. "
        f"Call each record a '{noun}' (plural '{noun}s') and nothing else. "
        + measure_line +
        "Do not use status words like waiting, pending, or approved unless the "
        "finding itself was already filtered by that status. "
        "Use ONLY these numbers; do not add facts, names, or totals not present. "
        "If data is missing, say so simply.\n"
        f"Finding: {summary[:1000]}\nSample: {json.dumps(sample_rows[:5])[:1500]}"
    )
    try:
        response = model.generate_content(prompt)
        return (getattr(response, "text", "") or "").strip() or None
    except Exception as exc:
        logger.warning("Gemini explain failed: %s", exc)
        return None
