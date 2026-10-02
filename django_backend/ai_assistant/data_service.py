"""Read-only ORM execution layer. No raw SQL, no writes, ORM only.

Tool catalogue (each validated plan routes to exactly one named tool):
  search_orders / search_purchases / search_invoices / search_deliveries /
  search_receipts / search_variances / search_items / search_stock /
  search_partners / search_payments, get_order_fulfilment,
  analyze_* (aggregations run inside the same tool), advise_*, brief_all,
  forecast_*.
The tool name is recorded in provenance["tool"] for audit logging.
"""

from datetime import date

from django.db.models import Avg, Count, Max, Min, Sum
from django.db.models.functions import TruncMonth


def _tool_name(entity: str, operation: str) -> str:
    base = {
        "order": "search_orders", "purchase": "search_purchases",
        "shipping_invoice": "search_invoices", "dn": "search_deliveries",
        "grn": "search_receipts", "git": "search_variances",
        "item": "search_items", "stock": "search_stock",
        "partner": "search_partners", "expense_payment": "search_payments",
        "vendor_payment": "search_payments",
        "received_payment": "search_payments", "payments": "search_payments",
        "overview": "brief_all",
    }.get(entity, f"search_{entity}")
    if operation == "fulfilment":
        return "get_order_fulfilment"
    if operation == "forecast":
        return f"forecast_{entity}"
    if operation == "advise":
        return f"advise_{entity}"
    if operation == "capabilities":
        return f"describe_{entity}"
    if operation == "brief":
        return "brief_all"
    return f"{base}_{operation}"


def execute_plan(plan: dict, admin: bool = False, max_rows: int = 500):
    """Run a validated plan. Returns (rows, provenance)."""
    from .permissions import mask_row_for_role

    provenance_tool = _tool_name(plan["entity"], plan["operation"])
    if plan["operation"] == "forecast":
        rows, provenance = _forecast_series(plan)
    elif plan["operation"] == "capabilities":
        rows, provenance = _capabilities(plan)
    elif plan["operation"] == "advise":
        if plan["entity"] == "overview":
            rows, provenance = _critical()
        else:
            rows, provenance = _advise(plan)
    elif plan["operation"] == "fulfilment":
        rows, provenance = _fulfilment(plan)
    else:
        entity = plan["entity"]
        handler = _HANDLERS[entity]
        rows, provenance = handler(plan, max_rows=max_rows)
        rows = [mask_row_for_role(r, admin) for r in rows]
    provenance = dict(provenance)
    provenance["tool"] = provenance_tool
    return rows, provenance


def _rolling_window(months: int = 6) -> dict:
    """Start of the month N-1 months ago through today (inclusive)."""
    today = date.today()
    month_index = today.year * 12 + (today.month - 1) - (months - 1)
    year, month = divmod(month_index, 12)
    start = date(year, month + 1, 1)
    return {"start": start.isoformat(), "end": today.isoformat()}


def _fulfilment(plan):
    """Ordered vs delivered progress for one sales order. Read-only."""
    from inventory.models import DN, Order

    filters = plan.get("filters") or {}
    ref = (filters.get("order_number") or "").strip() if filters.get("order_number") else ""
    contains = str(filters.get("order_number_contains") or "").strip()
    order = None
    if ref:
        order = Order.objects.prefetch_related("items").filter(
            order_number__iexact=ref).first()
    if order is None and contains:
        order = Order.objects.prefetch_related("items").filter(
            order_number__icontains=contains).order_by("order_number").first()
    if order is None:
        return [], {"source": "inventory.Order + DN lines",
                    "missing_order": ref or contains}

    ordered = float(order.total_quantity or 0)
    deliveries = list(DN.objects.filter(sales_no__iexact=order.order_number)
                      .prefetch_related("dn_items").order_by("date"))
    per_dn = []
    for dn in deliveries:
        qty = sum(float(line.quantity or 0) for line in dn.dn_items.all())
        per_dn.append({"dn_no": dn.dn_no, "date": str(dn.date),
                       "delivered": round(qty, 3),
                       "is_last": bool(dn.is_last)})
    delivered = round(sum(r["delivered"] for r in per_dn), 3)
    return per_dn, {"source": "inventory.Order + DN lines",
                    "order_number": order.order_number,
                    "buyer": order.buyer,
                    "ordered": ordered,
                    "delivered": delivered}


def _forecast_series(plan: dict):
    """Monthly counts over the rolling window; projection happens in analytics."""
    entity = plan["entity"]
    handler = _HANDLERS[entity]
    month_plan = {
        "entity": entity, "operation": "group_count", "group_by": "month",
        "filters": dict(plan.get("filters") or {}),
        "date_range": _rolling_window(6),
        "sort": None, "limit": None, "chart": "line",
    }
    rows, provenance = handler(month_plan)
    provenance = dict(provenance)
    provenance["forecast_entity"] = entity
    return rows, provenance


def _scalar(handler, entity: str, operation: str, field: str | None = None,
            group_by: str | None = None, filters: dict | None = None,
            date_range: dict | None = None):
    plan = {"entity": entity, "operation": operation, "field": field,
            "group_by": group_by, "filters": filters or {},
            "date_range": date_range or {}, "sort": None, "limit": None,
            "chart": "none"}
    rows, _ = handler(plan)
    return rows


def _overview(plan, max_rows=500):
    """Whole-business brief from small live queries. Read-only throughout."""
    from inventory.models import ShippingInvoice

    def n(value) -> str:
        """Plain display number: 50000 instead of 50000.0."""
        try:
            return ("{:g}".format(float(value)))
        except (TypeError, ValueError):
            return str(value)

    def plural(count: int, singular: str, plural_form: str) -> str:
        return f"{count} {singular if count == 1 else plural_form}"

    summary, extra = [], {}
    orders_total = _scalar(_orders, "order", "count")
    total_orders = int((orders_total[0].get("value") if orders_total else 0) or 0)
    status_rows = _scalar(_orders, "order", "group_count", group_by="status")
    by_status = {r.get("group"): int(r.get("value") or 0) for r in status_rows}
    summary.append({"area": "Sales orders",
                    "detail": f"{total_orders} in total"})
    purchases_total = _scalar(_purchases, "purchase", "count")
    summary.append({"area": "Purchases",
                    "detail": f"{int((purchases_total[0].get('value') if purchases_total else 0) or 0)} in total"})
    dn_total = _scalar(_dns, "dn", "count")
    grn_total = _scalar(_grns, "grn", "count")
    summary.append({"area": "Deliveries",
                    "detail": f"{int((dn_total[0].get('value') if dn_total else 0) or 0)} delivery notes"})
    summary.append({"area": "Receipts",
                    "detail": f"{int((grn_total[0].get('value') if grn_total else 0) or 0)} goods received notes"})
    inv_total = ShippingInvoice.objects.count()
    unauth = ShippingInvoice.objects.filter(authorized_by__isnull=True).count()
    summary.append({"area": "Shipping invoices",
                    "detail": f"{inv_total} in total, {unauth} waiting for authorization"})
    money_in = _scalar(_received, "received_payment", "sum", field="amount")
    money_out = _scalar(_vendor, "vendor_payment", "sum", field="amount")
    costs = _scalar(_expense, "expense_payment", "sum", field="amount")
    money = {
        "received": float((money_in[0].get("value") if money_in else 0) or 0),
        "paid_suppliers": float((money_out[0].get("value") if money_out else 0) or 0),
        "expenses": float((costs[0].get("value") if costs else 0) or 0),
    }
    summary.append({"area": "Money in",
                    "detail": f"{n(money['received'])} received from customers"})
    summary.append({"area": "Money out",
                    "detail": f"{n(money['paid_suppliers'])} paid to suppliers, "
                              f"{n(money['expenses'])} in costs"})
    stock_total = _scalar(_stock, "stock", "sum", field="quantity")
    stock_count = _scalar(_stock, "stock", "count")
    stock_qty = float((stock_total[0].get("value") if stock_total else 0) or 0)
    stock_lines = int((stock_count[0].get("value") if stock_count else 0) or 0)
    summary.append({"area": "Stock",
                    "detail": f"{n(stock_qty)} across "
                              f"{plural(stock_lines, 'line', 'lines')}"})
    over_rows = _scalar(_git, "git", "count", filters={"variance_type": "increased"})
    under_rows = _scalar(_git, "git", "count", filters={"variance_type": "decreased"})
    over_n = int((over_rows[0].get("value") if over_rows else 0) or 0)
    under_n = int((under_rows[0].get("value") if under_rows else 0) or 0)
    summary.append({"area": "Variances",
                    "detail": f"{plural(over_n, 'over-delivery', 'over-deliveries')}, "
                              f"{plural(under_n, 'under-delivery', 'under-deliveries')}"})
    monthly = _scalar(_orders, "order", "group_count", group_by="month")

    watchouts = []
    pending = by_status.get("pending", 0)
    if pending:
        watchouts.append(f"{plural(pending, 'order', 'orders')} still waiting for approval.")
    if over_n:
        watchouts.append(
            f"{plural(over_n, 'line', 'lines')} delivered in higher quantity than ordered.")
    if unauth:
        watchouts.append(
            f"{plural(unauth, 'invoice', 'invoices')} still waiting for authorization.")

    extra = {"source": "multiple live tables (read-only)",
             "monthly": monthly, "status": status_rows, "money": money,
             "watchouts": watchouts, "total_orders": total_orders,
             "by_status": by_status}
    return summary, extra


def _parse_date(value):
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _apply_date_range(qs, date_field: str, date_range: dict):
    start = _parse_date((date_range or {}).get("start"))
    end = _parse_date((date_range or {}).get("end"))
    if date_field and start:
        qs = qs.filter(**{f"{date_field}__gte": start})
    if date_field and end:
        qs = qs.filter(**{f"{date_field}__lte": end})
    return qs


def _aggregate(qs, plan: dict, date_field: str):
    op = plan["operation"]
    if op == "count":
        return [{"value": qs.count()}]
    if op in {"sum", "avg", "min", "max"}:
        field = plan["field"]
        fn = {"sum": Sum, "avg": Avg, "min": Min, "max": Max}[op]
        result = qs.aggregate(value=fn(field))["value"] or 0
        return [{"value": float(result)}]
    if op in {"group_count", "group_sum", "top_n"}:
        return _grouped(qs, plan, date_field)
    # list
    limit = min(int(plan.get("limit") or 20), 100)
    return list(qs[:limit])


def _grouped(qs, plan: dict, date_field: str):
    from django.db.models import FloatField
    from django.db.models.functions import Cast

    group_by = plan.get("group_by") or "month"
    limit = min(int(plan.get("limit") or 10), 100)
    op = plan["operation"]
    if group_by == "month" and date_field:
        qs = qs.annotate(month=TruncMonth(date_field)).values("month")
        label = "month"
    else:
        qs = qs.values(group_by)
        label = group_by
    if op in {"group_sum", "top_n"}:
        field = plan.get("field")
        qs = qs.annotate(value=Sum(Cast(field, FloatField())))
    else:
        qs = qs.annotate(value=Count("pk"))
    qs = qs.order_by("-value")
    if op == "top_n":
        qs = qs[:limit]
    else:
        qs = qs[:100]
    rows = []
    for row in qs:
        key = row.get("month") or row.get(label)
        rows.append({"group": str(key), "value": float(row["value"] or 0)})
    return rows


# ---------------- entity handlers ----------------

def _orders(plan, max_rows=500):
    from inventory.models import Order
    qs = Order.objects.all()
    f = plan.get("filters", {})
    if f.get("order_number"):
        qs = qs.filter(order_number__iexact=f["order_number"].strip())
    elif f.get("order_number_contains"):
        qs = qs.filter(order_number__icontains=str(f["order_number_contains"]).strip())
    if f.get("buyer"):
        qs = qs.filter(buyer__icontains=f["buyer"])
    if f.get("shipper"):
        qs = qs.filter(shipper__icontains=f["shipper"])
    if f.get("status"):
        qs = qs.filter(status__iexact=f["status"])
    qs = _apply_date_range(qs, "order_date", plan.get("date_range"))
    op = plan["operation"]
    if op == "list":
        limit = min(int(plan.get("limit") or 20), 100)
        rows = [{
            "order_number": o.order_number, "order_date": str(o.order_date),
            "buyer": o.buyer, "shipper": o.shipper,
            "total_quantity": float(o.total_quantity or 0),
            "PR_before_VAT": float(o.PR_before_VAT or 0),
            "status": o.status,
        } for o in qs.order_by("-order_date")[:limit]]
        return rows, {"source": "inventory.Order"}
    if op in {"group_count", "group_sum", "top_n"} and plan.get("group_by") in {"buyer", "shipper", "status"}:
        return _aggregate(qs, plan, "order_date"), {"source": "inventory.Order grouped"}
    return _aggregate(qs, plan, "order_date"), {"source": "inventory.Order"}


def _purchases(plan, max_rows=500):
    from inventory.models import Purchase
    qs = Purchase.objects.all()
    f = plan.get("filters", {})
    if f.get("purchase_number"):
        qs = qs.filter(purchase_number__iexact=f["purchase_number"].strip())
    if f.get("shipper"):
        qs = qs.filter(shipper__icontains=f["shipper"])
    if f.get("status"):
        qs = qs.filter(status__iexact=f["status"])
    qs = _apply_date_range(qs, "order_date", plan.get("date_range"))
    op = plan["operation"]
    if op == "list":
        limit = min(int(plan.get("limit") or 20), 100)
        rows = [{
            "purchase_number": p.purchase_number, "order_date": str(p.order_date),
            "shipper": p.shipper, "total_quantity": float(p.total_quantity or 0),
            "before_vat": float(p.before_vat or 0), "status": p.status,
        } for p in qs.order_by("-order_date")[:limit]]
        return rows, {"source": "inventory.Purchase"}
    return _aggregate(qs, plan, "order_date"), {"source": "inventory.Purchase"}


def _invoices(plan, max_rows=500):
    from inventory.models import ShippingInvoice
    qs = ShippingInvoice.objects.select_related("order").all()
    f = plan.get("filters", {})
    if f.get("invoice_number"):
        qs = qs.filter(invoice_number__iexact=f["invoice_number"].strip())
    if f.get("order_number"):
        qs = qs.filter(order__order_number__iexact=f["order_number"].strip())
    qs = _apply_date_range(qs, "invoice_date", plan.get("date_range"))
    op = plan["operation"]
    if op == "list":
        limit = min(int(plan.get("limit") or 20), 100)
        rows = [{
            "invoice_number": i.invoice_number, "order_number": i.order.order_number,
            "invoice_date": str(i.invoice_date), "sr_no": i.sr_no,
            "final_price": float(i.final_price) if i.final_price is not None else None,
            "authorized_by": i.authorized_by,
        } for i in qs.order_by("-invoice_date")[:limit]]
        return rows, {"source": "inventory.ShippingInvoice"}
    if op in {"sum", "avg", "min", "max"} and plan.get("field") == "sr_no":
        plan = dict(plan, field="final_price") if plan.get("field") == "sr_no" else plan
    return _aggregate(qs, plan, "invoice_date"), {"source": "inventory.ShippingInvoice"}


def _dns(plan, max_rows=500):
    from inventory.models import DN
    qs = DN.objects.prefetch_related("dn_items").all()
    f = plan.get("filters", {})
    if f.get("dn_no"):
        qs = qs.filter(dn_no__iexact=f["dn_no"].strip())
    if f.get("order_number"):
        qs = qs.filter(sales_no__iexact=f["order_number"].strip())
    elif f.get("order_number_contains"):
        qs = qs.filter(sales_no__icontains=str(f["order_number_contains"]).strip())
    if f.get("customer_name"):
        qs = qs.filter(customer_name__icontains=f["customer_name"])
    if f.get("invoice_number"):
        qs = qs.filter(invoice_no__iexact=f["invoice_number"].strip())
    if f.get("is_last") is not None:
        qs = qs.filter(is_last=bool(f["is_last"]))
    qs = _apply_date_range(qs, "date", plan.get("date_range"))
    return _dn_grn_rows(qs, plan, kind="dn")


def _grns(plan, max_rows=500):
    from inventory.models import GRN
    qs = GRN.objects.prefetch_related("items").all()
    f = plan.get("filters", {})
    if f.get("purchase_number"):
        qs = qs.filter(purchase_no__iexact=f["purchase_number"].strip())
    if f.get("supplier_name"):
        qs = qs.filter(supplier_name__icontains=f["supplier_name"])
    qs = _apply_date_range(qs, "date", plan.get("date_range"))
    return _dn_grn_rows(qs, plan, kind="grn")


def _dn_grn_rows(qs, plan, kind="dn"):
    op = plan["operation"]
    if op == "count":
        return [{"value": qs.count()}], {f"source": f"inventory.{kind.upper()}"}
    built = []
    for doc in qs[:2000]:
        lines = doc.dn_items.all() if kind == "dn" else doc.items.all()
        qty = sum(float(getattr(line, "quantity", 0) or 0) for line in lines)
        if kind == "dn":
            built.append({
                "dn_no": doc.dn_no, "sales_no": doc.sales_no,
                "customer_name": doc.customer_name, "date": str(doc.date),
                "invoice_no": doc.invoice_no, "is_last": bool(doc.is_last),
                "item_count": len(lines), "total_quantity": round(qty, 3),
            })
        else:
            built.append({
                "grn_no": str(doc.grn_no), "supplier_name": doc.supplier_name,
                "purchase_no": doc.purchase_no, "date": str(doc.date),
                "is_last": bool(doc.is_last),
                "item_count": len(lines), "total_quantity": round(qty, 3),
            })
    if op == "list":
        return built[: min(int(plan.get("limit") or 20), 100)], {f"source": f"inventory.{kind.upper()}"}
    if op in {"sum", "avg", "min", "max"}:
        values = [r["total_quantity"] for r in built]
        if not values:
            return [{"value": 0}], {f"source": f"inventory.{kind.upper()} lines"}
        fn = {"sum": sum, "avg": lambda v: sum(v) / len(v),
              "min": min, "max": max}[op]
        return [{"value": round(float(fn(values)), 3)}], {f"source": f"inventory.{kind.upper()} lines"}
    # group_count / group_sum / top_n over built rows
    group_by = plan.get("group_by") or ("customer_name" if kind == "dn" else "supplier_name")
    groups: dict = {}
    for r in built:
        key = str(r.get(group_by) or "Unknown")
        groups[key] = groups.get(key, 0) + (r["total_quantity"] if op in {"group_sum", "top_n"} else 1)
    ranked = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)
    if op == "top_n":
        ranked = ranked[: min(int(plan.get("limit") or 10), 100)]
    return [{"group": k, "value": round(float(v), 3)} for k, v in ranked[:100]], \
        {f"source": f"inventory.{kind.upper()} lines grouped"}


def _git(plan, max_rows=500):
    from inventory.models import GIT
    qs = GIT.objects.select_related("grn").all()
    f = plan.get("filters", {})
    if f.get("purchase_number"):
        qs = qs.filter(purchase_no__iexact=f["purchase_number"].strip())
    if f.get("item_name"):
        qs = qs.filter(item_name__icontains=f["item_name"])
    if f.get("variance_type"):
        qs = qs.filter(variance_type__iexact=f["variance_type"])
    op = plan["operation"]
    if op == "list":
        limit = min(int(plan.get("limit") or 20), 100)
        rows = [{
            "purchase_no": g.purchase_no, "grn_no": str(g.grn.grn_no) if g.grn_id else None,
            "item_name": g.item_name,
            "purchase_quantity": float(g.purchase_quantity or 0),
            "received_quantity": float(g.received_quantity or 0),
            "variance_quantity": float(g.variance_quantity or 0),
            "variance_type": g.variance_type,
        } for g in qs.order_by("-updated_at")[:limit]]
        return rows, {"source": "inventory.GIT"}
    if op in {"group_count", "group_sum", "top_n"} and plan.get("group_by") in {"purchase_no", "item_name", "variance_type"}:
        return _aggregate(qs, plan, ""), {"source": "inventory.GIT grouped"}
    return _aggregate(qs, plan, ""), {"source": "inventory.GIT"}


def _items(plan, max_rows=500):
    from inventory.models import Items
    qs = Items.objects.all()
    f = plan.get("filters", {})
    if f.get("item_name"):
        qs = qs.filter(item_name__icontains=f["item_name"])
    if f.get("code"):
        qs = qs.filter(internal_code__icontains=f["code"])
    op = plan["operation"]
    if op == "count":
        return [{"value": qs.count()}], {"source": "inventory.Items"}
    limit = min(int(plan.get("limit") or 20), 100)
    rows = [{"item_name": i.item_name, "hscode": i.hscode,
             "internal_code": i.internal_code} for i in qs[:limit]]
    return rows, {"source": "inventory.Items"}


def _stock(plan, max_rows=500):
    from inventory.api import _build_stock_by_code
    rows = _build_stock_by_code()
    f = plan.get("filters", {})
    if f.get("code"):
        q = f["code"].strip().lower()
        rows = [r for r in rows if q in str(r.get("code", "")).lower()]
    if f.get("item_name"):
        q = f["item_name"].strip().lower()
        rows = [r for r in rows if q in str(r.get("item_name", "")).lower()]
    op = plan["operation"]
    if op == "count":
        return [{"value": len(rows)}], {"source": "derived stock (GRN-DN by code)"}
    if op in {"sum", "avg", "min", "max"}:
        values = [float(r.get("quantity") or 0) for r in rows]
        if not values:
            return [{"value": 0}], {"source": "derived stock"}
        fn = {"sum": sum, "avg": lambda v: sum(v) / len(v),
              "min": min, "max": max}[op]
        return [{"value": round(float(fn(values)), 3)}], {"source": "derived stock"}
    if op in {"group_count", "group_sum", "top_n"} or op == "list":
        ranked = sorted(rows, key=lambda r: float(r.get("quantity") or 0), reverse=True)
        limit = min(int(plan.get("limit") or 10), 100)
        if op == "list":
            return [{
                "code": r.get("code"), "item_name": r.get("item_name"),
                "quantity": r.get("quantity"), "package": r.get("package"),
            } for r in ranked[:limit]], {"source": "derived stock"}
        return [{
            "group": f"{r.get('item_name')} ({r.get('code')})",
            "value": round(float(r.get("quantity") or 0), 3),
        } for r in ranked[:limit]], {"source": "derived stock top"}
    return [{"value": len(rows)}], {"source": "derived stock"}


def _partners(plan, max_rows=500):
    from accounts.models import Partner
    qs = Partner.objects.filter(is_active=True)
    f = plan.get("filters", {})
    if f.get("name"):
        qs = qs.filter(name__icontains=f["name"])
    if f.get("partner_type") in {"customer", "supplier", "both"}:
        qs = qs.filter(partner_type=f["partner_type"])
    op = plan["operation"]
    if op in {"group_count", "group_sum", "top_n"} or (op == "count" and plan.get("group_by") == "partner_type"):
        groups = list(qs.values("partner_type").annotate(value=Count("pk")).order_by("-value"))
        return [{"group": g["partner_type"], "value": g["value"]} for g in groups], \
            {"source": "accounts.Partner grouped"}
    if op == "count":
        return [{"value": qs.count()}], {"source": "accounts.Partner"}
    limit = min(int(plan.get("limit") or 20), 100)
    return [{"name": p.name, "partner_type": p.partner_type} for p in qs[:limit]], \
        {"source": "accounts.Partner"}


def _payments(model_name: str, plan, max_rows=500):
    from accounting.models import ExpensePayment, ReceivedPayment, VendorPayment
    model = {"expense_payment": ExpensePayment, "received_payment": ReceivedPayment,
             "vendor_payment": VendorPayment}[model_name]
    qs = model.objects.all()
    f = plan.get("filters", {})
    number_field = {"expense_payment": "expense_number",
                    "received_payment": "payment_number",
                    "vendor_payment": "payment_number"}[model_name]
    date_field = {"expense_payment": "expense_date",
                  "received_payment": "payment_date",
                  "vendor_payment": "payment_date"}[model_name]
    for key in ("expense_number", "payment_number", "order_number",
                "purchase_number", "payee", "category"):
        if f.get(key) and hasattr(model, key):
            qs = qs.filter(**{f"{key}__icontains": f[key]})
    if f.get("status"):
        qs = qs.filter(status__iexact=f["status"])
    qs = _apply_date_range(qs, date_field, plan.get("date_range"))
    op = plan["operation"]
    if op == "list":
        limit = min(int(plan.get("limit") or 20), 100)
        rows = []
        for p in qs.order_by(f"-{date_field}")[:limit]:
            row = {
                "number": getattr(p, number_field),
                "date": str(getattr(p, date_field)),
                "amount": float(p.amount or 0),
                "status": p.status,
            }
            if hasattr(p, "supplier_name"):
                row["supplier_name"] = p.supplier_name
            if hasattr(p, "customer_name"):
                row["customer_name"] = p.customer_name
            rows.append(row)
        return rows, {f"source": f"accounting.{model.__name__}"}
    return _aggregate(qs, plan, date_field), {f"source": f"accounting.{model.__name__}"}


def _expense(plan, max_rows=500):
    return _payments("expense_payment", plan, max_rows)


def _vendor(plan, max_rows=500):
    return _payments("vendor_payment", plan, max_rows)


def _received(plan, max_rows=500):
    return _payments("received_payment", plan, max_rows)



def _payments_group_ops(plan, max_rows=500):
    """Combined read-only queries across money in, money out, and costs."""
    from accounting.models import ExpensePayment, ReceivedPayment, VendorPayment
    kinds = (("money in", ReceivedPayment, "payment_date"),
             ("money out", VendorPayment, "payment_date"),
             ("costs", ExpensePayment, "expense_date"))
    op = plan["operation"]
    filters = plan.get("filters", {})
    date_range = plan.get("date_range", {})

    def scoped(model, date_field):
        qs = model.objects.all()
        if filters.get("status"):
            qs = qs.filter(status__iexact=filters["status"])
        return _apply_date_range(qs, date_field, date_range)

    if op == "count":
        total = sum(scoped(model, df).count() for _, model, df in kinds)
        return [{"value": total}], {"source": "all payments (read-only)"}
    if op in {"sum", "avg", "min", "max"}:
        values = []
        for _, model, df in kinds:
            values += [float(a) for a in
                       scoped(model, df).values_list("amount", flat=True)[:2000]
                       if a is not None]
        if not values:
            return [{"value": 0}], {"source": "all payments (read-only)"}
        fn = {"sum": sum, "avg": lambda v: sum(v) / len(v),
              "min": min, "max": max}[op]
        return [{"value": round(float(fn(values)), 2)}], \
            {"source": "all payments (read-only)"}
    if op == "list":
        merged = []
        for label, model, df in kinds:
            number_field = ("expense_number" if model is ExpensePayment
                            else "payment_number")
            for p in scoped(model, df).order_by(f"-{df}")[:100]:
                merged.append({"kind": label,
                               "number": getattr(p, number_field),
                               "date": str(getattr(p, df)),
                               "amount": float(p.amount or 0),
                               "status": p.status})
        merged.sort(key=lambda r: r["date"], reverse=True)
        limit = min(int(plan.get("limit") or 20), 100)
        return merged[:limit], {"source": "all payments (read-only)"}

    group_by = plan.get("group_by") or "month"
    if group_by == "supplier_name":
        qs = scoped(VendorPayment, "payment_date")
        grouped = _aggregate(qs, {"entity": "vendor_payment",
                                  "operation": "group_sum" if op != "group_count" else "group_count",
                                  "field": "amount", "group_by": "supplier_name"},
                             "payment_date")
        return grouped, {"source": "supplier payments grouped (read-only)"}
    if group_by == "customer_name":
        qs = scoped(ReceivedPayment, "payment_date")
        grouped = _aggregate(qs, {"entity": "received_payment",
                                  "operation": "group_sum" if op != "group_count" else "group_count",
                                  "field": "amount", "group_by": "customer_name"},
                             "payment_date")
        return grouped, {"source": "customer payments grouped (read-only)"}
    if group_by == "status":
        merged: dict = {}
        for _, model, df in kinds:
            for row in _aggregate(scoped(model, df),
                                  {"entity": "x", "operation": "group_count",
                                   "group_by": "status"}, df):
                merged[row["group"]] = merged.get(row["group"], 0) + row["value"]
        ranked = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
        return [{"group": k, "value": v} for k, v in ranked], \
            {"source": "all payments grouped (read-only)"}
    # month (default): monthly totals across all three kinds.
    per_month: dict = {}
    for _, model, df in kinds:
        for row in _aggregate(scoped(model, df),
                              {"entity": "x", "operation": "group_count",
                               "group_by": "month"}, df):
            key = str(row["group"])[:10]
            per_month[key] = per_month.get(key, 0) + float(row["value"] or 0)
    ranked = sorted(per_month.items())
    if op == "top_n":
        ranked = ranked[-10:]
    return [{"group": k, "value": round(v, 2)} for k, v in ranked], \
        {"source": "all payments by month (read-only)"}


def _advise(plan, max_rows=500):
    """Scoped decision brief: totals, what is stuck, named oldest items,
    monthly trend. Read-only throughout."""
    entity = plan["entity"]
    if entity in {"order", "purchase"}:
        return _advise_orders_like(entity)
    if entity == "shipping_invoice":
        return _advise_invoices()
    if entity in {"dn", "grn"}:
        return _advise_movements(entity)
    if entity == "git":
        return _advise_git()
    if entity == "stock":
        return _advise_stock()
    if entity == "payments":
        return _advise_payments_group()
    return _advise_payments(entity)


def _advise_orders_like(entity: str):
    from inventory.models import Order, Purchase
    model = Order if entity == "order" else Purchase
    key = "order_number" if entity == "order" else "purchase_number"
    party_key = "buyer" if entity == "order" else "shipper"
    noun = "order" if entity == "order" else "purchase"

    total = model.objects.count()
    status_rows = _scalar(
        _orders if entity == "order" else _purchases, entity,
        "group_count", group_by="status")
    by_status = {r.get("group"): int(r.get("value") or 0) for r in status_rows}
    monthly = _scalar(
        _orders if entity == "order" else _purchases, entity,
        "group_count", group_by="month", date_range=_rolling_window(6))
    pending = list(model.objects.filter(status="pending")
                   .order_by("order_date")[:5])
    spotlight = [{
        "ref": getattr(p, key), "party": getattr(p, party_key),
        "date": str(p.order_date),
        "detail": f"{getattr(p, key)} for {getattr(p, party_key)}",
    } for p in pending]

    summary = [
        {"area": f"{noun.title()}s",
         "detail": f"{total} in total"},
        {"area": "Statuses",
         "detail": ", ".join(f"{v} {k}" for k, v in sorted(by_status.items())) or "none"},
        {"area": "Waiting",
         "detail": f"{by_status.get('pending', 0)} waiting for approval"},
    ]
    return summary, {"source": f"live {entity} records (read-only)",
                     "monthly": monthly, "spotlight": spotlight,
                     "pending_count": by_status.get("pending", 0)}


def _advise_invoices():
    from inventory.models import ShippingInvoice
    total = ShippingInvoice.objects.count()
    waiting = list(ShippingInvoice.objects.filter(authorized_by__isnull=True)
                   .select_related("order").order_by("invoice_date")[:5])
    spotlight = [{
        "ref": i.invoice_number, "party": i.order.order_number,
        "date": str(i.invoice_date),
        "detail": f"{i.invoice_number} for order {i.order.order_number}",
    } for i in waiting]
    summary = [
        {"area": "Shipping invoices", "detail": f"{total} in total"},
        {"area": "Waiting",
         "detail": f"{len(waiting)} waiting for authorization"},
    ]
    monthly = _scalar(_invoices, "shipping_invoice", "group_count",
                      group_by="month", date_range=_rolling_window(6))
    return summary, {"source": "live invoices (read-only)",
                     "monthly": monthly, "spotlight": spotlight,
                     "pending_count": len(waiting)}


def _advise_movements(entity: str):
    from inventory.models import DN, GRN
    is_dn = entity == "dn"
    model = DN if is_dn else GRN
    handler = _dns if is_dn else _grns
    noun = "delivery note" if is_dn else "goods received note"
    total_rows = _scalar(handler, entity, "count")
    total = int((total_rows[0].get("value") if total_rows else 0) or 0)
    open_docs = list(model.objects.filter(is_last=False).order_by("-date")[:5])
    spotlight = [{
        "ref": str(d.dn_no if is_dn else d.grn_no),
        "party": d.customer_name if is_dn else d.supplier_name,
        "date": str(d.date),
        "detail": f"{d.dn_no if is_dn else d.grn_no} "
                  f"for {d.customer_name if is_dn else d.supplier_name}",
    } for d in open_docs]
    summary = [
        {"area": "Deliveries" if is_dn else "Receipts",
         "detail": f"{total} {noun}s in total"},
        {"area": "Still open",
         "detail": f"{model.objects.filter(is_last=False).count()} not marked final"},
    ]
    monthly = _scalar(handler, entity, "group_count",
                      group_by="month", date_range=_rolling_window(6))
    return summary, {"source": f"live {entity} records (read-only)",
                     "monthly": monthly, "spotlight": spotlight,
                     "pending_count": 0}


def _advise_git():
    from inventory.models import GIT
    rows = list(GIT.objects.all().order_by("-updated_at")[:50])
    rows.sort(key=lambda g: abs(float(g.variance_quantity or 0)), reverse=True)
    top = rows[:5]
    spotlight = [{
        "ref": g.purchase_no, "party": g.item_name,
        "date": "", "variance": float(g.variance_quantity or 0),
        "detail": f"{g.item_name} on {g.purchase_no}: "
                  f"{float(g.variance_quantity or 0)} {g.variance_type}",
    } for g in top]
    over_n = GIT.objects.filter(variance_type="increased").count()
    under_n = GIT.objects.filter(variance_type="decreased").count()
    summary = [
        {"area": "Variance lines", "detail": f"{len(rows)} tracked"},
        {"area": "Over-deliveries", "detail": f"{over_n} lines"},
        {"area": "Under-deliveries", "detail": f"{under_n} lines"},
    ]
    return summary, {"source": "live variance records (read-only)",
                     "monthly": [], "spotlight": spotlight,
                     "pending_count": 0}


def _advise_stock():
    from inventory.api import _build_stock_by_code
    rows = _build_stock_by_code()
    negative = [r for r in rows if float(r.get("quantity") or 0) < 0][:5]
    spotlight = [{
        "ref": r.get("code"), "party": r.get("item_name"),
        "date": "", "detail": f"{r.get('item_name')} ({r.get('code')}): "
                              f"balance {r.get('quantity')}",
    } for r in negative]
    summary = [
        {"area": "Stock lines", "detail": f"{len(rows)} in total"},
        {"area": "Below zero", "detail": f"{len(negative)} lines"},
    ]
    return summary, {"source": "derived live stock (read-only)",
                     "monthly": [], "spotlight": spotlight,
                     "pending_count": 0}


def _advise_payments_group():
    """All three payment kinds together: waiting items named per kind."""
    from accounting.models import ExpensePayment, ReceivedPayment, VendorPayment
    kinds = (("money in", ReceivedPayment, "payment_number", "payment_date"),
             ("money out", VendorPayment, "payment_number", "payment_date"),
             ("costs", ExpensePayment, "expense_number", "expense_date"))
    summary, spotlight, waiting_total = [], [], 0
    for label, model, number_field, date_field in kinds:
        waiting = list(model.objects.filter(status="pending")
                       .order_by(date_field)[:3])
        waiting_total += len(waiting)
        summary.append({"area": label,
                        "detail": f"{model.objects.count()} in total, "
                                  f"{model.objects.filter(status='pending').count()} waiting"})
        for p in waiting:
            spotlight.append({
                "ref": getattr(p, number_field), "party": label,
                "date": str(getattr(p, date_field)),
                "detail": f"{getattr(p, number_field)} ({label}): "
                          f"{float(p.amount or 0)}",
            })
    per_month: dict = {}
    for label, model, number_field, date_field in kinds:
        rows = _scalar(
            _received if model is ReceivedPayment
            else _vendor if model is VendorPayment else _expense,
            "received_payment" if model is ReceivedPayment
            else "vendor_payment" if model is VendorPayment else "expense_payment",
            "group_count", group_by="month", date_range=_rolling_window(6))
        for r in rows:
            key = str(r.get("group") or "")[:10]
            per_month[key] = per_month.get(key, 0) + float(r.get("value") or 0)
    monthly = [{"group": month, "value": total}
               for month, total in sorted(per_month.items())]
    return summary, {"source": "live payments (read-only)",
                     "monthly": monthly, "spotlight": spotlight[:9],
                     "pending_count": waiting_total}


def _advise_payments(entity: str):
    from accounting.models import ExpensePayment, ReceivedPayment, VendorPayment
    model = {"expense_payment": ExpensePayment,
             "vendor_payment": VendorPayment,
             "received_payment": ReceivedPayment}[entity]
    number_field = {"expense_payment": "expense_number"}.get(entity, "payment_number")
    date_field = {"expense_payment": "expense_date"}.get(entity, "payment_date")
    total = model.objects.count()
    pending_qs = model.objects.filter(status="pending").order_by(date_field)[:5]
    spotlight = [{
        "ref": getattr(p, number_field), "party": "",
        "date": str(getattr(p, date_field)),
        "detail": f"{getattr(p, number_field)}: {float(p.amount or 0)} "
                  f"from {getattr(p, date_field)}",
    } for p in pending_qs]
    pending_sum = model.objects.filter(status="pending").aggregate(
        total=Sum("amount")
    )["total"] or 0
    summary = [
        {"area": "Payments", "detail": f"{total} in total"},
        {"area": "Waiting",
         "detail": f"{model.objects.filter(status='pending').count()} "
                   f"waiting, worth {float(pending_sum)}"},
    ]
    monthly = _scalar(
        _expense if entity == "expense_payment"
        else _vendor if entity == "vendor_payment" else _received,
        entity, "group_count", group_by="month",
        date_range=_rolling_window(6))
    return summary, {"source": f"live {entity} records (read-only)",
                     "monthly": monthly, "spotlight": spotlight,
                     "pending_count": model.objects.filter(status="pending").count()}


def _capabilities(plan, max_rows=500):
    """What the assistant can answer, with live totals. Read-only."""
    from .context import EXAMPLE_QUESTIONS
    entity = plan["entity"]
    if entity == "overview":
        snapshot = []
        for area in ("order", "purchase", "shipping_invoice", "dn", "grn",
                     "git", "stock", "item", "vendor_payment",
                     "received_payment", "expense_payment", "partner"):
            try:
                rows = _scalar(_HANDLERS[area], area, "count")
                snapshot.append({
                    "area": area.replace("_", " "),
                    "total": int((rows[0].get("value") if rows else 0) or 0),
                })
            except Exception:
                continue
        examples = [qs[0] for qs in EXAMPLE_QUESTIONS.values() if qs]
        return snapshot, {"source": "live totals (read-only)",
                          "examples": examples, "scope": "all"}
    if entity == "payments":
        per = []
        for kind, label in (("received_payment", "money in"),
                            ("vendor_payment", "money out"),
                            ("expense_payment", "costs")):
            rows = _scalar(_HANDLERS[kind], kind, "count")
            waiting = _scalar(_HANDLERS[kind], kind, "count",
                              filters={"status": "pending"})
            per.append({
                "kind": label,
                "total": int((rows[0].get("value") if rows else 0) or 0),
                "waiting": int((waiting[0].get("value") if waiting else 0) or 0),
            })
        return per, {"source": "live payments (read-only)",
                     "examples": EXAMPLE_QUESTIONS.get("payments", []),
                     "scope": "payments"}
    rows = _scalar(_HANDLERS[entity], entity, "count")
    total = int((rows[0].get("value") if rows else 0) or 0)
    return [{"total": total}], {
        "source": f"live {entity} records (read-only)",
        "examples": EXAMPLE_QUESTIONS.get(entity, []),
        "scope": entity,
    }


def _critical():
    """Most urgent issues across the business, ranked. Read-only."""
    from inventory.api import _build_stock_by_code
    from inventory.models import GIT, Order, ShippingInvoice
    from accounting.models import ExpensePayment, ReceivedPayment, VendorPayment

    issues = []  # (rank, headline, suggestion, spotlight_row)

    try:
        negative = [r for r in _build_stock_by_code()
                    if float(r.get("quantity") or 0) < 0]
    except Exception:
        negative = []
    if negative:
        top = negative[0]
        issues.append((0,
            f"{top.get('item_name')} ({top.get('code')}) sits at "
            f"{top.get('quantity')} — below zero, so something went out "
            f"that was never received.",
            f"Reconcile {top.get('code')} today: check its receipts against its deliveries.",
            {"ref": top.get("code"), "party": top.get("item_name"), "date": "",
             "detail": f"{top.get('item_name')}: {top.get('quantity')}"}))

    over = list(GIT.objects.filter(variance_type="increased")
                .order_by("-updated_at")[:1])
    if over:
        g = over[0]
        issues.append((1,
            f"{g.item_name} on {g.purchase_no} arrived "
            f"{float(g.variance_quantity or 0)} above the ordered quantity.",
            f"Agree the extra {g.item_name} on {g.purchase_no} with the supplier "
            f"before it is used or billed.",
            {"ref": g.purchase_no, "party": g.item_name, "date": "",
             "detail": f"{g.item_name}: +{float(g.variance_quantity or 0)}"}))

    pending_qs = Order.objects.filter(status="pending").order_by("order_date")
    pending_n = pending_qs.count()
    if pending_n:
        oldest = pending_qs.first()
        issues.append((2,
            f"{pending_n} sales orders are still waiting for approval.",
            f"Start with {oldest.order_number} for {oldest.buyer} — waiting longest.",
            {"ref": oldest.order_number, "party": oldest.buyer,
             "date": str(oldest.order_date),
             "detail": f"{oldest.order_number} for {oldest.buyer}"}))

    unauth_qs = ShippingInvoice.objects.filter(
        authorized_by__isnull=True).order_by("invoice_date")
    unauth_n = unauth_qs.count()
    if unauth_n:
        first = unauth_qs.first()
        issues.append((3,
            f"{unauth_n} shipping invoices are still waiting for authorization.",
            f"Authorize {first.invoice_number} first — waiting longest.",
            {"ref": first.invoice_number, "party": first.order.order_number,
             "date": str(first.invoice_date),
             "detail": f"{first.invoice_number} for order {first.order.order_number}"}))

    waiting_money = sum(
        model.objects.filter(status="pending").count()
        for model in (VendorPayment, ReceivedPayment, ExpensePayment)
    )
    if waiting_money:
        issues.append((4,
            f"{waiting_money} payments are still waiting.",
            "Clear the oldest waiting payment first, then work forward by date.",
            {"ref": "", "party": "", "date": "",
             "detail": f"{waiting_money} payments waiting"}))

    issues.sort(key=lambda item: item[0])
    spotlight = [issue[3] for issue in issues[:3] if issue[3].get("ref")]
    return spotlight, {"source": "live cross-business scan (read-only)",
                       "issues": [(headline, suggestion) for _, headline, suggestion, _ in issues[:3]]}


_HANDLERS = {
    "order": _orders,
    "purchase": _purchases,
    "shipping_invoice": _invoices,
    "dn": _dns,
    "grn": _grns,
    "git": _git,
    "item": _items,
    "stock": _stock,
    "partner": _partners,
    "expense_payment": _expense,
    "vendor_payment": _vendor,
    "received_payment": _received,
    "payments": _payments_group_ops,
    "overview": _overview,
}
