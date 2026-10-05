"""Allowlist validation for AI query plans.

The LLM never touches the database. It may only propose a plan shaped like:
{
  "entity": "order",
  "operation": "count" | "sum" | "avg" | "min" | "max" | "list" |
               "group_count" | "group_sum" | "top_n",
  "field": "total_quantity",
  "group_by": "buyer",
  "filters": {"status": "pending", "order_number": "M1122"},
  "date_range": {"start": "2026-09-01", "end": "2026-09-30"},
  "sort": "-total_quantity",
  "limit": 10,
  "chart": "bar" | "line" | "pie" | "scatter" | "none",
}
Anything outside the allowlist is rejected and the user is asked to clarify.
"""

from .context import ENTITIES, FORECASTABLE_ENTITIES, FORBIDDEN_FIELDS

ALLOWED_OPERATIONS = {
    "count", "sum", "avg", "min", "max",
    "list", "group_count", "group_sum", "top_n",
    "brief", "forecast", "advise", "capabilities", "fulfilment", "audit",
}

ALLOWED_CHARTS = {"bar", "line", "pie", "scatter", "none"}

ALLOWED_FILTER_KEYS = {
    "order_number", "order_number_contains", "purchase_number",
    "invoice_number", "dn_no", "grn_no",
    "buyer", "shipper", "customer_name", "supplier_name", "name",
    "partner_type", "status", "item_name", "code",
    "variance_type", "payment_type", "is_last",
}

MAX_LIMIT = 100


def validate_query_plan(plan: dict) -> tuple[bool, str]:
    if not isinstance(plan, dict):
        return False, "Query plan must be an object."
    entity = plan.get("entity")
    operation = plan.get("operation")
    if entity not in ENTITIES:
        return False, f"Unknown entity '{entity}'. Ask about orders, purchases, shipping invoices, deliveries (DN), receipts (GRN), variances (GIT), stock, items, payments, or partners."
    if operation not in ALLOWED_OPERATIONS:
        return False, f"Unsupported operation '{operation}'."
    if operation == "brief":
        if entity != "overview":
            return False, "A full brief covers the whole business."
        return True, ""
    if operation == "forecast":
        if entity not in FORECASTABLE_ENTITIES:
            return False, (
                f"I can only project orders, purchases, invoices, deliveries, "
                f"receipts, and payments, not {entity}."
            )
        return True, ""
    if operation == "advise":
        if entity not in {"order", "purchase", "shipping_invoice", "dn", "grn",
                          "git", "stock", "vendor_payment", "received_payment",
                          "expense_payment", "payments", "overview"}:
            return False, (
                "I can look closely at orders, purchases, invoices, deliveries, "
                "receipts, variances, stock, and payments. Which one?"
            )
        return True, ""
    if operation == "capabilities":
        return True, ""
    if operation == "fulfilment":
        if entity != "order":
            return False, "Delivery progress is tracked per sales order."
        filters = plan.get("filters") or {}
        if not filters.get("order_number") and not filters.get("order_number_contains"):
            return False, "Which order should I check? Give me an order number."
        return True, ""
    if operation == "audit":
        if entity not in ("order", "purchase", "overview"):
            return False, (
                "I can check sales orders or purchases against their documents. "
                "Which proforma should I check?"
            )
        return True, ""
    if entity in FORBIDDEN_FIELDS:
        return False, "That entity is not available to the assistant."
    meta = ENTITIES[entity]
    skip_field_checks = entity == "payments"
    field = plan.get("field")
    if not skip_field_checks and operation in {"sum", "avg", "min", "max", "group_sum"}:
        if field not in meta["numeric_fields"]:
            return False, f"Field '{field}' cannot be aggregated for {entity}."
    if not skip_field_checks and operation in {"group_count", "group_sum", "top_n"}:
        group_by = plan.get("group_by")
        if group_by != "month" and group_by not in meta["safe_fields"]:
            return False, f"Cannot group {entity} by '{group_by}'."
    filters = plan.get("filters") or {}
    if not isinstance(filters, dict):
        return False, "Filters must be an object."
    for key, value in filters.items():
        if key in FORBIDDEN_FIELDS:
            return False, f"Filter on '{key}' is not allowed."
        if key not in ALLOWED_FILTER_KEYS and key not in meta["safe_fields"]:
            return False, f"Filter '{key}' is not supported for {entity}."
        if isinstance(value, str) and len(value) > 120:
            return False, f"Filter value for '{key}' is too long."
    chart = plan.get("chart") or "none"
    if chart not in ALLOWED_CHARTS:
        return False, f"Unsupported chart type '{chart}'."
    limit = plan.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return False, "Limit must be a number."
        if limit < 1 or limit > MAX_LIMIT:
            return False, f"Limit must be between 1 and {MAX_LIMIT}."
    date_range = plan.get("date_range") or {}
    if date_range:
        if not isinstance(date_range, dict):
            return False, "date_range must be an object."
        for bound in ("start", "end"):
            value = date_range.get(bound)
            if value is not None and not _looks_like_date(value):
                return False, f"date_range.{bound} must be YYYY-MM-DD."
    return True, ""


def _looks_like_date(value) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    parts = value.split("-")
    return (
        len(parts) == 3
        and len(parts[0]) == 4
        and len(parts[1]) == 2
        and len(parts[2]) == 2
        and value.replace("-", "").isdigit()
    )
