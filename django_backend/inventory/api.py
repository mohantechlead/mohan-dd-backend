import html
import logging
import re
from decimal import Decimal
from ninja import Router
from typing import List, Optional
from datetime import datetime
from datetime import datetime
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)
from ninja_jwt.authentication import JWTAuth
from accounts.models import Partner
from .models import (
    GRN,
    GrnItems,
    DN,
    DNItems,
    Items,
    Stock,
    Order,
    OrderItem,
    Purchase,
    PurchaseItem,
    GIT,
    ShippingInvoice,
    ShippingInvoiceItem,
)
from .schemas import (
    GrnCreateSchema,
    GrnDetailSchema,
    GrnUpdateSchema,
    GRNListSchema,
    GrnItemSchema,
    GrnItemCreateSchema,
    DnCreateSchema,
    DnDetailSchema,
    DnUpdateSchema,
    DnItemSchema,
    DnItemCreateSchema,
    ItemCreateSchema,
    ItemUpdateSchema,
    ItemSchema,
    StockSchema,
    GitSchema,
    GitCreateSchema,
    GitUpdateSchema,
    OrderCreateSchema,
    OrderDetailSchema,
    OrderItemSchema,
    OrderApproveSchema,
    OrderStatusUpdateSchema,
    OrderUpdateSchema,
    PurchaseCreateSchema,
    PurchaseDetailSchema,
    PurchaseItemSchema,
    PurchaseApproveSchema,
    PurchaseStatusUpdateSchema,
    PurchaseUpdateSchema,
    ShippingInvoiceCreateSchema,
    ShippingInvoiceSummarySchema,
    ShippingInvoiceDetailSchema,
    ShippingInvoiceItemSchema,
    ShippingInvoiceUpdateSchema,
)
import uuid
from django.http import JsonResponse
import traceback
from django.db.models import Sum
from django.utils import timezone

router = Router()

# M1085, M1086, ... (case-insensitive M + digits)
_M_ORDER_NUMBER_RE = re.compile(r"^M\s*(\d+)$", re.IGNORECASE)

# Purchases: MPDDFZE001, MPDDFZE002, ... (case-insensitive prefix)
_PURCHASE_NUMBER_RE = re.compile(r"^MPDDFZE(\d+)$", re.IGNORECASE)


def _purchase_aggregate_from_line_items(items) -> tuple[Decimal, int, int]:
    """before_vat = sum(total_price); total_quantity and remaining = sum(quantity) (same for now)."""
    before_vat = sum(Decimal(str(i.total_price)) for i in items)
    qty_sum = sum(int(i.quantity) for i in items)
    return before_vat, qty_sum, qty_sum


def _order_aggregate_from_line_items(items) -> tuple[Decimal, float, float]:
    """PR_before_VAT = sum(total_price); remaining mirrors total_quantity for now."""
    pr_before_vat = sum(Decimal(str(i.total_price)) for i in items)
    qty_sum = sum(float(i.quantity) for i in items)
    return pr_before_vat, qty_sum, qty_sum


def _next_m_series_number(values) -> str:
    """Next M#### after max existing M-prefixed value; default M1001 if none."""
    max_n = None
    for val in values:
        if val is None:
            continue
        m = _M_ORDER_NUMBER_RE.match(str(val).strip())
        if m:
            n = int(m.group(1))
            max_n = n if max_n is None else max(max_n, n)
    if max_n is None:
        return "M1001"
    return "M{0}".format(max_n + 1)


def _next_mpddfze_purchase_number(values) -> str:
    """Next MPDDFZE### after max existing purchase number; default MPDDFZE001 if none."""
    max_n = None
    for val in values:
        if val is None:
            continue
        m = _PURCHASE_NUMBER_RE.match(str(val).strip())
        if m:
            n = int(m.group(1))
            max_n = n if max_n is None else max(max_n, n)
    if max_n is None:
        return "MPDDFZE001"
    next_n = max_n + 1
    return "MPDDFZE{0:03d}".format(next_n)


def _require_admin(request):
    """Return None if allowed, or JsonResponse with 403 if not admin."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    role = getattr(user, "role", "logistics")
    role = getattr(user, "role", "logistics")
    if role != "admin" and not getattr(user, "is_superuser", False):
        return JsonResponse({"detail": "Admin role required to access this resource."}, status=403)
    return None


def _is_admin(request) -> bool:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", "logistics")
    return role == "admin" or getattr(user, "is_superuser", False)


def _normalize_partner_lookup_name(name: str) -> str:
    """Collapse internal whitespace and trim; case-insensitive matching uses .lower()."""
    if not name:
        return ""
    return " ".join(str(name).strip().split()).lower()


def _get_customer_address(name: str) -> Optional[str]:
    """Look up customer address by name (partner_type in customer, both).

    Uses whitespace-normalized comparison so order.buyer can still match Partner.name
    when spacing differs (e.g. double spaces, trailing space). Plain iexact alone
    often fails for imported or hand-typed names.
    """
    key = _normalize_partner_lookup_name(name)
    if not key:
        return None
    for p in Partner.objects.filter(partner_type__in=("customer", "both")).only(
        "name", "address"
    ):
        if _normalize_partner_lookup_name(p.name) == key:
            addr = (p.address or "").strip()
            return addr or None
    return None


def _get_customer_tin_number(name: str) -> Optional[str]:
    """Look up customer TIN by name (same matching rules as address)."""
    key = _normalize_partner_lookup_name(name)
    if not key:
        return None
    for p in Partner.objects.filter(partner_type__in=("customer", "both")).only(
        "name", "tin_number"
    ):
        if _normalize_partner_lookup_name(p.name) == key:
            tin = (p.tin_number or "").strip()
            return tin or None
    return None


def _get_supplier_address(name: str) -> Optional[str]:
    """Look up supplier address by name (partner_type in supplier, both)."""
    key = _normalize_partner_lookup_name(name)
    if not key:
        return None
    for p in Partner.objects.filter(partner_type__in=("supplier", "both")).only(
        "name", "address"
    ):
        if _normalize_partner_lookup_name(p.name) == key:
            addr = (p.address or "").strip()
            return addr or None
    return None


def _resolve_catalog_item(row) -> Items:
    """Map a GRN/DN payload row to a catalog Items row (prefer item_id from UI)."""
    item_name = str(getattr(row, "item_name", "") or "").strip()
    internal_code = str(getattr(row, "internal_code", "") or "").strip()
    if not item_name:
        raise ValueError("Each line must be selected from the item list.")

    raw_uid = getattr(row, "item_id", None)
    if raw_uid is not None and str(raw_uid).strip():
        try:
            uid = uuid.UUID(str(raw_uid))
        except (ValueError, TypeError, AttributeError):
            uid = None
        if uid:
            catalog = Items.objects.filter(item_id=uid).first()
            if not catalog:
                raise ValueError(f"Unknown item_id for '{item_name}'.")
            if catalog.item_name.strip().lower() != item_name.lower():
                raise ValueError(
                    "Item name does not match the selected inventory item (item_id)."
                )
            return catalog

    if internal_code:
        catalog = Items.objects.filter(
            internal_code=internal_code,
            item_name__iexact=item_name,
        ).first()
    else:
        catalog = (
            Items.objects.filter(item_name__iexact=item_name)
            .filter(Q(internal_code__isnull=True) | Q(internal_code=""))
            .first()
        )
    if not catalog:
        raise ValueError(f"Item '{item_name}' is not in the item list.")
    return catalog


def _stock_totals_for_catalog_row(item: Items, catalog_ids: list) -> tuple[int, float, int, float]:
    """Return (grn_qty, grn_bags, dn_qty, dn_bags) for one catalog item.

    Stock identity should follow business code first (internal_code), because item_id
    may be generic or unstable across workflows.
    """
    code = (item.internal_code or "").strip()
    if code:
        grn_filter = Q(code__iexact=code)
        dn_filter = Q(code__iexact=code)
    else:
        # Legacy fallback for rows created before code-based identity.
        grn_filter = Q(item_id=item.item_id) | (
            Q(item_name__iexact=item.item_name) & ~Q(item_id__in=catalog_ids)
        )
        dn_filter = Q(catalog_item_id=item.item_id) | (
            Q(catalog_item_id__isnull=True) & Q(item_name__iexact=item.item_name)
        )

    grn_totals = GrnItems.objects.filter(grn_filter).aggregate(
        quantity=Sum("quantity"), bags=Sum("bags")
    )
    dn_totals = DNItems.objects.filter(dn_filter).aggregate(
        quantity=Sum("quantity"), bags=Sum("bags")
    )

    grn_qty = grn_totals["quantity"] or 0
    grn_bags = float(grn_totals["bags"] or 0)
    dn_qty = dn_totals["quantity"] or 0
    dn_bags = float(dn_totals["bags"] or 0)
    return grn_qty, grn_bags, dn_qty, dn_bags


def _check_and_notify_over_under_delivery(dn):
    """
    Compare DN total delivered quantities vs Invoice. Send email if variances exist.
    Returns (over_items, under_items) for API response.
    """
    over_items, under_items = _get_over_under_delivery(dn)
    if not over_items and not under_items:
        return over_items, under_items
    try:
        invoice_no = (dn.invoice_no or "").strip()
        invoice_num = invoice_no or "N/A"
        if invoice_no:
            order = Order.objects.filter(order_number=dn.sales_no).first()
            if order:
                inv = ShippingInvoice.objects.filter(
                    order=order,
                    invoice_number__iexact=invoice_no,
                ).first()
                if inv:
                    invoice_num = inv.invoice_number
        lines = [
            f"Delivery Note: {dn.dn_no}",
            f"Order/Sales No: {dn.sales_no}",
            f"Invoice: {invoice_num}",
            f"Customer: {dn.customer_name}",
            "",
        ]

        if over_items:
            lines.append("OVER DELIVERY:")
            for it in over_items:
                lines.append(
                    f"  - {it['item_name']}: invoiced={it['invoiced']}, delivered={it['delivered']} "
                    f"(over by {it['variance']})"
                )
            lines.append("")

        if under_items:
            lines.append("UNDER DELIVERY:")
            for it in under_items:
                lines.append(
                    f"  - {it['item_name']}: invoiced={it['invoiced']}, delivered={it['delivered']} "
                    f"(short by {it['variance']})"
                )

        message = "\n".join(lines)
        subject = "Over/Under Delivery Notification"

        recipient_list = getattr(settings, "OVER_UNDER_DELIVERY_RECIPIENTS", [])

        if recipient_list:
            sent = send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipient_list,
                fail_silently=True,
            )
            if sent > 0:
                logger.info("Over/under delivery notification sent to %s", recipient_list)
            else:
                logger.warning("Over/under delivery email sent count was 0")
    except Exception as e:
        logger.exception("Failed to send over/under delivery notification: %s", e)

    return over_items, under_items


def _get_over_under_delivery(dn):
    """
    Compute over/under delivery variances vs invoice. Does NOT send email.
    Returns (over_items, under_items) for display (e.g. GET DN detail).
    """
    over_items = []
    under_items = []
    try:
        invoice_no = (dn.invoice_no or "").strip()
        if not invoice_no:
            return over_items, under_items
        order = Order.objects.filter(order_number=dn.sales_no).first()
        if not order:
            return over_items, under_items
        invoice = ShippingInvoice.objects.filter(
            order=order,
            invoice_number__iexact=invoice_no,
        ).prefetch_related("items").first()
        if not invoice:
            return over_items, under_items
        invoiced_by_item = {}
        for inv_item in invoice.items.all():
            name = inv_item.item_name
            qty = int(inv_item.quantity)
            invoiced_by_item[name] = invoiced_by_item.get(name, 0) + qty
        for item_name, total_invoiced in invoiced_by_item.items():
            total_delivered = DNItems.objects.filter(
                dn__sales_no=dn.sales_no,
                item_name=item_name,
            ).aggregate(total=Sum("quantity"))["total"] or 0
            if total_delivered > total_invoiced:
                over_items.append({
                    "item_name": item_name,
                    "invoiced": total_invoiced,
                    "delivered": total_delivered,
                    "variance": total_delivered - total_invoiced,
                })
            elif total_delivered < total_invoiced:
                under_items.append({
                    "item_name": item_name,
                    "invoiced": total_invoiced,
                    "delivered": total_delivered,
                    "variance": total_invoiced - total_delivered,
                })
    except Exception as e:
        logger.exception("Over/under delivery compute failed: %s", e)
    return over_items, under_items


def _check_and_notify_negative_stock():
    """Check if any item has negative stock and send email notification if so."""
    items = Items.objects.all()
    negative_items = []
    catalog_ids = list(Items.objects.values_list("item_id", flat=True))

    for item in items:
        grn_qty, grn_bags, dn_qty, dn_bags = _stock_totals_for_catalog_row(
            item, catalog_ids
        )
        stock_quantity = grn_qty - dn_qty
        stock_bags = grn_bags - dn_bags

        if stock_quantity < 0 or stock_bags < 0:
            negative_items.append({
                "item_name": item.item_name,
                "internal_code": item.internal_code or "",
                "quantity": stock_quantity,
                "package": stock_bags,
            })

    if not negative_items:
        return

    try:
        lines = [
            "The following items have negative stock:",
            "",
        ]
        for ni in negative_items:
            lines.append(
                f"  - {ni['item_name']} (code: {ni['internal_code']}): "
                f"quantity={ni['quantity']}, package={ni['package']}"
            )
        message = "\n".join(lines)

        sent = send_mail(
            subject="Negative Stock Alert",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[
"mekdi1610@gmail.com"
            ],
            fail_silently=True,
        )
        if sent > 0:
            logger.info("Negative stock alert email sent to recipients")
        else:
            logger.warning("Negative stock alert email sent count was 0")
    except Exception as e:
        logger.exception("Failed to send negative stock alert email: %s", e)


def _validate_grn_items(items):
    """
    Ensure every GRN item row maps to a catalog Items row (prefer payload item_id).
    """
    if not items:
        raise ValueError("At least one GRN item is required.")

    validated = []
    for item in items:
        try:
            quantity = int(getattr(item, "quantity", 0) or 0)
        except (TypeError, ValueError):
            raise ValueError("Invalid GRN item quantity.")

        if quantity <= 0:
            raise ValueError("Each GRN item quantity must be greater than 0.")

        catalog = _resolve_catalog_item(item)
        item_name = catalog.item_name
        internal_code = str(catalog.internal_code or "").strip()
        code = str(getattr(item, "code", "") or "").strip()
        if not code:
            raise ValueError(f"Code is required for item '{item_name}'.")

        unit_measurement = getattr(item, "unit_measurement", "") or ""

        bags_val = None
        raw_bags = getattr(item, "bags", None)
        if raw_bags is not None and str(raw_bags).strip():
            try:
                bags_val = float(raw_bags)
            except (ValueError, TypeError):
                bags_val = None

        validated.append(
            {
                "item_name": item_name,
                "quantity": quantity,
                "unit_measurement": unit_measurement,
                "code": code,
                "internal_code": internal_code,
                "bags": bags_val,
                "catalog_item_id": catalog.item_id,
            }
        )

    return validated


def _validate_dn_items(items):
    """Ensure every DN item row maps to a catalog Items row (prefer payload item_id)."""
    if not items:
        raise ValueError("At least one DN item is required.")

    validated = []
    for item in items:
        try:
            quantity = int(getattr(item, "quantity", 0) or 0)
        except (TypeError, ValueError):
            raise ValueError("Invalid DN item quantity.")

        if quantity <= 0:
            raise ValueError("Each DN item quantity must be greater than 0.")

        catalog = _resolve_catalog_item(item)
        item_name = catalog.item_name
        internal_code = str(catalog.internal_code or "").strip()
        code = str(getattr(item, "code", "") or "").strip()
        if not code:
            raise ValueError(f"Code is required for item '{item_name}'.")

        unit_measurement = getattr(item, "unit_measurement", "") or ""

        bags_val = getattr(item, "bags", None)
        if bags_val is not None:
            try:
                bags_val = float(bags_val)
            except (ValueError, TypeError):
                bags_val = None

        validated.append(
            {
                "item_name": item_name,
                "quantity": quantity,
                "unit_measurement": unit_measurement,
                "code": code,
                "internal_code": internal_code,
                "bags": bags_val,
                "catalog_item_id": catalog.item_id,
            }
        )

    return validated


def _git_key(item_name: str, code: str | None) -> str:
    return f"{(item_name or '').strip().lower()}|{(code or '').strip().lower()}"


def _grn_qty_map(grn: GRN) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for gi in grn.items.all():
        key = _git_key(gi.item_name, gi.code)
        if key not in out:
            out[key] = {
                "item_name": gi.item_name,
                "code": gi.code,
                "qty": 0.0,
            }
        out[key]["qty"] += float(gi.quantity or 0)
    return out


def _purchase_qty_map(purchase: Purchase) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in purchase.items.all():
        key = _git_key(p.item_name, None)
        out[key] = out.get(key, 0.0) + float(p.quantity or 0)
    return out


def _upsert_git_running_variance(
    *,
    grn: GRN,
    purchase: Purchase,
    item_name: str,
    code: str | None,
    delta_received_qty: float,
):
    if abs(delta_received_qty) < 1e-9:
        return

    code_value = (code or "").strip() or None
    purchase_key = _git_key(item_name, None)
    purchase_qty = float(_purchase_qty_map(purchase).get(purchase_key, 0.0))

    rows = list(
        GIT.objects.filter(
            purchase_no=grn.purchase_no,
            item_name__iexact=(item_name or "").strip(),
            code=code_value,
        ).order_by("created_at")
    )
    row = rows[0] if rows else None

    if row is None:
        received_qty = delta_received_qty
        variance = received_qty - purchase_qty
        if abs(variance) < 1e-9:
            return
        GIT.objects.create(
            grn=grn,
            purchase_no=grn.purchase_no,
            item_name=item_name,
            code=code_value,
            purchase_quantity=purchase_qty,
            received_quantity=received_qty,
            variance_quantity=abs(variance),
            variance_type="increased" if variance > 0 else "decreased",
        )
        return

    # Merge duplicates into one running row if any already exist.
    if len(rows) > 1:
        for extra in rows[1:]:
            row.received_quantity = float(row.received_quantity or 0) + float(extra.received_quantity or 0)
            extra.delete()

    row.grn = grn
    row.purchase_no = grn.purchase_no
    row.item_name = item_name
    row.code = code_value
    row.purchase_quantity = purchase_qty
    row.received_quantity = float(row.received_quantity or 0) + delta_received_qty
    variance = float(row.received_quantity or 0) - float(row.purchase_quantity or 0)
    row.variance_quantity = abs(variance)
    row.variance_type = "increased" if variance >= 0 else "decreased"
    row.save()


def _sync_git_rows_for_grn(grn: GRN, previous_qty_by_key: dict[str, float] | None = None):
    """Maintain running GIT variance per purchase/item/code (no duplicate rows)."""
    purchase_no = (grn.purchase_no or "").strip()
    if not purchase_no:
        return
    purchase = Purchase.objects.filter(purchase_number__iexact=purchase_no).first()
    if not purchase:
        return

    previous_qty_by_key = previous_qty_by_key or {}
    current_map = _grn_qty_map(grn)
    current_qty_by_key = {k: float(v["qty"]) for k, v in current_map.items()}

    all_keys = set(previous_qty_by_key.keys()) | set(current_qty_by_key.keys())
    for key in all_keys:
        prev_qty = float(previous_qty_by_key.get(key, 0.0))
        now_qty = float(current_qty_by_key.get(key, 0.0))
        delta = now_qty - prev_qty
        if abs(delta) < 1e-9:
            continue

        if key in current_map:
            item_name = current_map[key]["item_name"]
            code = current_map[key]["code"]
        else:
            # Removed on GRN update: recover item_name/code from composite key.
            name_part, code_part = key.split("|", 1)
            item_name = name_part
            code = code_part or None

        _upsert_git_running_variance(
            grn=grn,
            purchase=purchase,
            item_name=item_name,
            code=code,
            delta_received_qty=delta,
        )


@router.post("/grn", response=GrnDetailSchema)
def create_grn(request, payload: GrnCreateSchema):
    try:
        if not payload.date:
            return JsonResponse(
                {"detail": "Date is required."},
                status=400,
            )
        grn_no_val = int(payload.grn_no) if str(payload.grn_no).strip().isdigit() else None
        if grn_no_val is None:
            return JsonResponse(
                {"detail": "GRN No must be a valid number."},
                status=400,
            )
        if GRN.objects.filter(grn_no=grn_no_val).exists():
            return JsonResponse(
                {"detail": f"GRN No '{payload.grn_no}' already exists."},
                status=400,
            )

        # purchase is stored on GRN as plain text (`purchase_no`) - no FK link.
        if not payload.purchase_no:
            return JsonResponse(
                {"detail": "purchase_no is required."},
                status=400,
            )

        # Optional existence check (do not block if you don't want strict validation)
        Purchase.objects.filter(
            purchase_number__iexact=str(payload.purchase_no).strip()
        ).exists()

        validated_items = _validate_grn_items(payload.items)
        computed_total_quantity = sum(item["quantity"] for item in validated_items)

        grn = GRN.objects.create(
            id=uuid.uuid4(),
            supplier_name=payload.supplier_name,
            grn_no=grn_no_val,
            received_from=payload.received_from,
            truck_no=payload.truck_no,
            purchase_no=str(payload.purchase_no).strip(),
            total_quantity=computed_total_quantity if computed_total_quantity is not None else 0,
            store_name=payload.store_name or "",
            store_keeper=payload.store_keeper or "",
            date=payload.date,
            ECD_no=payload.ECD_no,
            transporter_name=payload.transporter_name,
        )

        created_items = []
        for item in validated_items:
            new_item = GrnItems.objects.create(
                item_id=item["catalog_item_id"],
                grn=grn,
                grn_no=grn.grn_no,
                item_name=item["item_name"],
                quantity=item["quantity"],
                unit_measurement=item["unit_measurement"],
                code=item["code"],
                internal_code=item["internal_code"],
                bags=item["bags"],
            )
            created_items.append(new_item)

        _sync_git_rows_for_grn(grn)
        _check_and_notify_negative_stock()

        grn.refresh_from_db()
        return _grn_to_detail(grn)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)
    except Exception as e:
        logger.exception("GRN create failed: %s", e)
        return JsonResponse(
            {"detail": str(e), "message": "Failed to create GRN."},
            status=500,
        )


@router.get("/grn", response=List[GRNListSchema])
def list_GRN(request):
    try:
        grns = GRN.objects.prefetch_related("items").all()
        result = []
        for grn in grns:
            result.append(
                GRNListSchema(
                    supplier_name=grn.supplier_name,
                    grn_no=grn.grn_no,
                    purchase_no=grn.purchase_no,
                    received_from=grn.received_from,
                    truck_no=grn.truck_no,
                    total_quantity=grn.total_quantity,
                    store_name=grn.store_name,
                    store_keeper=grn.store_keeper,
                    items=[
                        GrnItemSchema(
                            grn_no=item.grn_no,
                            code=item.code,
                            item_name=item.item_name,
                            quantity=item.quantity,
                            unit_measurement=item.unit_measurement,
                            internal_code=item.internal_code,
                            bags=float(item.bags) if item.bags is not None else None,
                        )
                        for item in grn.items.all()
                    ]
                )
            )
        return result
    except Exception as e:
        print("GRN endpoint error:", e)
        traceback.print_exc()
        return JsonResponse(
            {"message": "GRN endpoint failed", "error": str(e)},
            status=500
        )

@router.get("/grn/{grn_no}", response=GrnDetailSchema)
def get_GRN(request, grn_no: str):
    grn = get_object_or_404(GRN, grn_no=int(grn_no) if grn_no.isdigit() else grn_no)
    return _grn_to_detail(grn)


@router.put("/grn/{grn_no}", response=GrnDetailSchema, auth=JWTAuth())
def update_GRN(request, grn_no: str, payload: GrnUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    grn = get_object_or_404(GRN, grn_no=int(grn_no) if grn_no.isdigit() else grn_no)
    if payload.supplier_name is not None:
        grn.supplier_name = payload.supplier_name
    if payload.date is not None:
        grn.date = payload.date

    if payload.received_from is not None:
        grn.received_from = payload.received_from
    if payload.truck_no is not None:
        grn.truck_no = payload.truck_no

    if payload.store_name is not None:
        grn.store_name = payload.store_name

    if payload.store_keeper is not None:
        grn.store_keeper = payload.store_keeper

    if payload.purchase_no is not None:
        grn.purchase_no = str(payload.purchase_no).strip()

    if payload.total_quantity is not None:
        grn.total_quantity = payload.total_quantity

    if payload.ECD_no is not None:
        grn.ECD_no = payload.ECD_no
    if payload.transporter_name is not None:
        grn.transporter_name = payload.transporter_name
    previous_qty_by_key = (
        {k: float(v["qty"]) for k, v in _grn_qty_map(grn).items()} if payload.items is not None else None
    )
    if payload.items is not None:
        try:
            validated_items = _validate_grn_items(payload.items)
        except ValueError as e:
            return JsonResponse({"detail": str(e)}, status=400)

        grn.items.all().delete()
        computed_total_quantity = sum(item["quantity"] for item in validated_items)

        for item in validated_items:
            GrnItems.objects.create(
                item_id=item["catalog_item_id"],
                grn=grn,
                grn_no=grn.grn_no,
                item_name=item["item_name"],
                quantity=item["quantity"],
                unit_measurement=item["unit_measurement"],
                code=item["code"],
                internal_code=item["internal_code"],
                bags=item["bags"],
            )

        # Items are the source of truth for total quantity
        grn.total_quantity = computed_total_quantity
    grn.save()
    grn.refresh_from_db()
    _sync_git_rows_for_grn(grn, previous_qty_by_key)
    if payload.items is not None:
        _check_and_notify_negative_stock()
    return _grn_to_detail(grn)


@router.delete("/grn/{grn_no}", auth=JWTAuth())
def delete_GRN(request, grn_no: str):
    err = _require_admin(request)
    if err:
        return err
    grn = get_object_or_404(GRN, grn_no=int(grn_no) if grn_no.isdigit() else grn_no)
    grn.delete()
    _check_and_notify_negative_stock()
    return {"detail": "GRN deleted successfully."}


def _grn_to_detail(grn):
    return {
        "id": grn.id,
        "supplier_name": grn.supplier_name,
        "grn_no": str(grn.grn_no),
        "received_from": grn.received_from,
        "truck_no": grn.truck_no,
        "total_quantity": grn.total_quantity,
        "store_name": grn.store_name,
        "store_keeper": grn.store_keeper,
        "purchase_no": grn.purchase_no,
        "date": grn.date.isoformat() if grn.date else None,
        "ECD_no": grn.ECD_no,
        "transporter_name": grn.transporter_name,
        "items": [
            {
                "grn_no": item.grn_no,
                "code": item.code,
                "item_name": item.item_name,
                "quantity": item.quantity,
                "unit_measurement": item.unit_measurement,
                "internal_code": item.internal_code,
                "bags": float(item.bags) if item.bags is not None else None,
            }
            for item in grn.items.all()
        ],
    }


# Add more endpoints as needed for DN and other functionalities

@router.post("/dn", response=DnDetailSchema)
def create_dn(request, payload: DnCreateSchema):
    if DN.objects.filter(dn_no=payload.dn_no).exists():
        return JsonResponse(
            {"detail": f"Delivery number '{payload.dn_no}' already exists."},
            status=400,
        )

    invoice_no = (payload.invoice_no or "").strip()
    if invoice_no:
        # Verify invoice belongs to this order
        invoice = ShippingInvoice.objects.filter(
            invoice_number__iexact=invoice_no,
        ).select_related("order").first()
        if not invoice:
            return JsonResponse(
                {"detail": f"Invoice '{invoice_no}' not found."},
                status=400,
            )
        if invoice.order.order_number != payload.sales_no:
            return JsonResponse(
                {
                    "detail": f"Invoice '{invoice_no}' does not belong to order '{payload.sales_no}'. "
                    "Order number and invoice number must match."
                },
                status=400,
            )
        # One DN per invoice: cannot create if DN already exists for this invoice
        existing = DN.objects.filter(
            sales_no=payload.sales_no,
            invoice_no__iexact=invoice_no,
        ).first()
        if existing:
            return JsonResponse(
                {
                    "detail": f"A Delivery Note (DN {existing.dn_no}) already exists for this invoice. "
                    "Please edit the existing one instead of creating a new one."
                },
                status=400,
            )
    if DN.objects.filter(dn_no=payload.dn_no).exists():
        return JsonResponse(
            {"detail": f"Delivery number '{payload.dn_no}' already exists."},
            status=400,
        )

    invoice_no = (payload.invoice_no or "").strip()
    if invoice_no:
        # Verify invoice belongs to this order
        invoice = ShippingInvoice.objects.filter(
            invoice_number__iexact=invoice_no,
        ).select_related("order").first()
        if not invoice:
            return JsonResponse(
                {"detail": f"Invoice '{invoice_no}' not found."},
                status=400,
            )
        if invoice.order.order_number != payload.sales_no:
            return JsonResponse(
                {
                    "detail": f"Invoice '{invoice_no}' does not belong to order '{payload.sales_no}'. "
                    "Order number and invoice number must match."
                },
                status=400,
            )
        # One DN per invoice: cannot create if DN already exists for this invoice
        existing = DN.objects.filter(
            sales_no=payload.sales_no,
            invoice_no__iexact=invoice_no,
        ).first()
        if existing:
            return JsonResponse(
                {
                    "detail": f"A Delivery Note (DN {existing.dn_no}) already exists for this invoice. "
                    "Please edit the existing one instead of creating a new one."
                },
                status=400,
            )

    try:
        validated_items = _validate_dn_items(payload.items)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    # Create DN
    dn = DN.objects.create(
        id=uuid.uuid4(),
        customer_name=payload.customer_name,
        dn_no=payload.dn_no,
        plate_no=payload.plate_no,
        sales_no=payload.sales_no,
        date = payload.date,
        ECD_no = payload.ECD_no,
        invoice_no = payload.invoice_no,
        gatepass_no = payload.gatepass_no,
        despathcher_name = payload.despathcher_name,
        receiver_name = payload.receiver_name,
        authorized_by = payload.authorized_by,
    )

    # Create Items
    created_items = []
    for item in validated_items:
        new_item = DNItems.objects.create(
            item_id=uuid.uuid4(),
            catalog_item_id=item["catalog_item_id"],
            dn=dn,
            item_name=item["item_name"],
            quantity=item["quantity"],
            unit_measurement=item["unit_measurement"],
            internal_code=item["internal_code"],
            code=item["code"],
            bags=item["bags"],
        )
        created_items.append(new_item)

    _check_and_notify_negative_stock()
    over_items, under_items = _check_and_notify_over_under_delivery(dn)

    # Return structured response
    result = {
        "id": dn.id,
        "customer_name": dn.customer_name,
        "dn_no": dn.dn_no,
        "plate_no": dn.plate_no,
        "sales_no": dn.sales_no,
        "items": [
            {
                "code": i.code,
                "item_name": i.item_name,
                "quantity": i.quantity,
                "unit_measurement": i.unit_measurement,
                "internal_code": i.internal_code,
                "bags": float(i.bags) if i.bags is not None else None,
            }
            for i in created_items
        ],
    }
    if over_items:
        result["over_items"] = over_items
    if under_items:
        result["under_items"] = under_items
    return result


@router.get("/dn/{dn_no}", response=DnDetailSchema)
def get_DN(request, dn_no: str):
    dn = get_object_or_404(DN.objects.prefetch_related("dn_items"), dn_no=dn_no)
    result = _dn_to_detail(dn)
    over_items, under_items = _get_over_under_delivery(dn)
    if over_items:
        result["over_items"] = over_items
    if under_items:
        result["under_items"] = under_items
    return result


@router.put("/dn/{dn_no}", response=DnDetailSchema, auth=JWTAuth())
def update_DN(request, dn_no: str, payload: DnUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    dn = get_object_or_404(DN, dn_no=dn_no)

    new_sales_no = payload.sales_no if payload.sales_no is not None else dn.sales_no
    new_invoice_no = (payload.invoice_no or "").strip() if payload.invoice_no is not None else (dn.invoice_no or "")
    if new_invoice_no:
        invoice = ShippingInvoice.objects.filter(
            invoice_number__iexact=new_invoice_no,
        ).select_related("order").first()
        if not invoice:
            return JsonResponse(
                {"detail": f"Invoice '{new_invoice_no}' not found."},
                status=400,
            )
        if invoice.order.order_number != new_sales_no:
            return JsonResponse(
                {
                    "detail": f"Invoice '{new_invoice_no}' does not belong to order '{new_sales_no}'. "
                    "Order number and invoice number must match."
                },
                status=400,
            )
        existing = DN.objects.filter(
            sales_no=new_sales_no,
            invoice_no__iexact=new_invoice_no,
        ).exclude(dn_no=dn.dn_no).first()
        if existing:
            return JsonResponse(
                {
                    "detail": f"A Delivery Note (DN {existing.dn_no}) already exists for this invoice. "
                    "Please edit that one instead."
                },
                status=400,
            )


    new_sales_no = payload.sales_no if payload.sales_no is not None else dn.sales_no
    new_invoice_no = (payload.invoice_no or "").strip() if payload.invoice_no is not None else (dn.invoice_no or "")
    if new_invoice_no:
        invoice = ShippingInvoice.objects.filter(
            invoice_number__iexact=new_invoice_no,
        ).select_related("order").first()
        if not invoice:
            return JsonResponse(
                {"detail": f"Invoice '{new_invoice_no}' not found."},
                status=400,
            )
        if invoice.order.order_number != new_sales_no:
            return JsonResponse(
                {
                    "detail": f"Invoice '{new_invoice_no}' does not belong to order '{new_sales_no}'. "
                    "Order number and invoice number must match."
                },
                status=400,
            )
        existing = DN.objects.filter(
            sales_no=new_sales_no,
            invoice_no__iexact=new_invoice_no,
        ).exclude(dn_no=dn.dn_no).first()
        if existing:
            return JsonResponse(
                {
                    "detail": f"A Delivery Note (DN {existing.dn_no}) already exists for this invoice. "
                    "Please edit that one instead."
                },
                status=400,
            )

    if payload.customer_name is not None:
        dn.customer_name = payload.customer_name
    if payload.date is not None:
        dn.date = payload.date
    if payload.plate_no is not None:
        dn.plate_no = payload.plate_no
    if payload.sales_no is not None:
        dn.sales_no = payload.sales_no
    if payload.ECD_no is not None:
        dn.ECD_no = payload.ECD_no
    if payload.invoice_no is not None:
        dn.invoice_no = payload.invoice_no
    if payload.gatepass_no is not None:
        dn.gatepass_no = payload.gatepass_no
    if payload.despathcher_name is not None:
        dn.despathcher_name = payload.despathcher_name
    if payload.receiver_name is not None:
        dn.receiver_name = payload.receiver_name
    if payload.authorized_by is not None:
        dn.authorized_by = payload.authorized_by
    if payload.items is not None:
        try:
            validated_items = _validate_dn_items(payload.items)
        except ValueError as e:
            return JsonResponse({"detail": str(e)}, status=400)

        dn.dn_items.all().delete()
        for item in validated_items:
            DNItems.objects.create(
                item_id=uuid.uuid4(),
                catalog_item_id=item["catalog_item_id"],
                dn=dn,
                item_name=item["item_name"],
                quantity=item["quantity"],
                unit_measurement=item["unit_measurement"],
                code=item["code"],
                internal_code=item["internal_code"],
                bags=item["bags"],
            )
    dn.save()
    dn.refresh_from_db()
    _check_and_notify_negative_stock()
    over_items, under_items = _check_and_notify_over_under_delivery(dn)

    result = _dn_to_detail(dn)
    if over_items:
        result["over_items"] = over_items
    if under_items:
        result["under_items"] = under_items
    return result


@router.delete("/dn/{dn_no}", auth=JWTAuth())
def delete_DN(request, dn_no: str):
    err = _require_admin(request)
    if err:
        return err
    dn = get_object_or_404(DN, dn_no=dn_no)
    dn.delete()
    return {"detail": "DN deleted successfully."}


def _dn_to_detail(dn):
    return {
        "id": dn.id,
        "customer_name": dn.customer_name,
        "dn_no": dn.dn_no,
        "sales_no": dn.sales_no,
        "plate_no": dn.plate_no or "",
        "date": dn.date.isoformat() if dn.date else None,
        "ECD_no": dn.ECD_no,
        "invoice_no": dn.invoice_no,
        "gatepass_no": dn.gatepass_no,
        "despathcher_name": dn.despathcher_name,
        "receiver_name": dn.receiver_name,
        "authorized_by": dn.authorized_by,
        "items": [
            {
                "code": item.code,
                "item_name": item.item_name,
                "quantity": item.quantity,
                "unit_measurement": item.unit_measurement,
                "internal_code": item.internal_code,
                "bags": float(item.bags) if item.bags is not None else None,
            }
            for item in dn.dn_items.all()
        ],
    }


@router.get("/dn", response=List[DnDetailSchema])
def list_DN(request):
    try:
        dns = DN.objects.prefetch_related("dn_items").all()
        result = []
        for dn in dns:
            result.append(
                DnDetailSchema(
                    id=dn.id,
                    customer_name=dn.customer_name,
                    dn_no=dn.dn_no,
                    sales_no=dn.sales_no,
                    items=[
                        DnItemSchema(
                            code=item.code,
                            item_name=item.item_name,
                            quantity=item.quantity,
                            unit_measurement=item.unit_measurement,
                            internal_code=item.internal_code,
                            bags=float(item.bags) if item.bags is not None else None,
                        )
                        for item in dn.dn_items.all()
                    ]
                )
            )
        return result
    except Exception as e:
        print("DN endpoint error:", e)
        traceback.print_exc()
        return JsonResponse(
            {"message": "DN endpoint failed", "error": str(e)},
            status=500
        )

@router.post("/items", response=ItemCreateSchema)
def create_item(request, payload: ItemCreateSchema):

    # Create DN
    item = Items.objects.create(
        item_id=uuid.uuid4(),
        item_name = payload.item_name,
        hscode = payload.hscode,
        internal_code = payload.internal_code
    )


    # Return structured response
    return {
        "item_name": item.item_name,
        "hscode": item.hscode,
        "internal_code": item.internal_code
    }

@router.get("/items", response=list[ItemSchema])
def display_item(request):
    items = Items.objects.all()
    return list(items)


@router.get("/items/{item_id}", response=ItemSchema)
def get_item(request, item_id: uuid.UUID):
    return get_object_or_404(Items, item_id=item_id)


@router.put("/items/{item_id}", response=ItemSchema, auth=JWTAuth())
def update_item(request, item_id: uuid.UUID, payload: ItemUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    item = get_object_or_404(Items, item_id=item_id)
    if payload.item_name is not None:
        item.item_name = payload.item_name
    if payload.hscode is not None:
        item.hscode = payload.hscode
    if payload.internal_code is not None:
        item.internal_code = payload.internal_code
    item.save()
    return item


@router.delete("/items/{item_id}", auth=JWTAuth())
def delete_item(request, item_id: uuid.UUID):
    err = _require_admin(request)
    if err:
        return err
    item = get_object_or_404(Items, item_id=item_id)
    item.delete()
    return {"detail": "Item deleted successfully."}


@router.get("/stock", response=list[StockSchema])
def display_stock(
    request,
    as_of_date: Optional[str] = None,
    code: Optional[str] = None,
    item: Optional[str] = None,
    min_quantity: Optional[float] = None,
    grn_no: Optional[str] = None,
    dn_no: Optional[str] = None,
):
    # Stock is keyed by GRN/DN line code (business code), not catalog item_id.
    stock_map: dict[str, dict] = {}

    grn_qs = GrnItems.objects.select_related("grn").all()
    dn_qs = DNItems.objects.select_related("dn").all()

    if as_of_date:
        # Date format expected: YYYY-MM-DD
        grn_qs = grn_qs.filter(grn__date__lte=as_of_date)
        dn_qs = dn_qs.filter(dn__date__lte=as_of_date)

    for row in grn_qs:
        code = (row.code or row.internal_code or "").strip()
        if not code:
            continue
        bucket = stock_map.setdefault(
            code,
            {
                "item_id": row.item_id,
                "item_name": row.item_name,
                "code": code,
                "internal_code": code,
                "quantity": 0.0,
                "package": 0.0,
                "grn_nos": set(),
                "dn_nos": set(),
            },
        )
        bucket["quantity"] += float(row.quantity or 0)
        bucket["package"] += float(row.bags or 0)
        if row.grn_id:
            bucket["grn_nos"].add(str(row.grn.grn_no))

    for row in dn_qs:
        code = (row.code or row.internal_code or "").strip()
        if not code:
            continue
        bucket = stock_map.setdefault(
            code,
            {
                "item_id": row.catalog_item_id or row.item_id,
                "item_name": row.item_name,
                "code": code,
                "internal_code": code,
                "quantity": 0.0,
                "package": 0.0,
                "grn_nos": set(),
                "dn_nos": set(),
            },
        )
        bucket["quantity"] -= float(row.quantity or 0)
        bucket["package"] -= float(row.bags or 0)
        if row.dn_id:
            bucket["dn_nos"].add(str(row.dn.dn_no))

    rows = list(stock_map.values())
    for r in rows:
        r["grn_nos"] = sorted(list(r.get("grn_nos", set())))
        r["dn_nos"] = sorted(list(r.get("dn_nos", set())))

    if code:
        code_q = code.strip().lower()
        rows = [r for r in rows if code_q in str(r.get("code", "")).lower()]

    if item:
        item_q = item.strip().lower()
        rows = [r for r in rows if item_q in str(r.get("item_name", "")).lower()]

    if min_quantity is not None:
        rows = [r for r in rows if float(r.get("quantity") or 0) >= float(min_quantity)]

    if grn_no:
        grn_q = grn_no.strip().lower()
        rows = [
            r
            for r in rows
            if any(grn_q in str(no).lower() for no in (r.get("grn_nos") or []))
        ]

    if dn_no:
        dn_q = dn_no.strip().lower()
        rows = [
            r
            for r in rows
            if any(dn_q in str(no).lower() for no in (r.get("dn_nos") or []))
        ]

    return rows


def _git_to_schema(row: GIT) -> GitSchema:
    return GitSchema(
        id=row.id,
        grn_no=str(row.grn.grn_no),
        purchase_no=row.purchase_no,
        item_name=row.item_name,
        code=row.code,
        purchase_quantity=float(row.purchase_quantity or 0),
        received_quantity=float(row.received_quantity or 0),
        variance_quantity=float(row.variance_quantity or 0),
        variance_type=row.variance_type,
    )


@router.get("/git", response=List[GitSchema])
def list_git_rows(request):
    rows = GIT.objects.select_related("grn").all().order_by("-updated_at")
    return [_git_to_schema(r) for r in rows]


@router.get("/git/{git_id}", response=GitSchema)
def get_git_row(request, git_id: uuid.UUID):
    row = get_object_or_404(GIT.objects.select_related("grn"), id=git_id)
    return _git_to_schema(row)


@router.post("/git", response=GitSchema)
def create_git_row(request, payload: GitCreateSchema):
    grn = get_object_or_404(GRN, grn_no=int(payload.grn_no) if str(payload.grn_no).isdigit() else payload.grn_no)
    variance_type = (payload.variance_type or "").strip().lower()
    if variance_type not in ("increased", "decreased"):
        return JsonResponse({"detail": "variance_type must be increased or decreased."}, status=400)
    row = GIT.objects.create(
        grn=grn,
        purchase_no=payload.purchase_no,
        item_name=payload.item_name,
        code=payload.code,
        purchase_quantity=payload.purchase_quantity,
        received_quantity=payload.received_quantity,
        variance_quantity=payload.variance_quantity,
        variance_type=variance_type,
    )
    return _git_to_schema(row)


@router.put("/git/{git_id}", response=GitSchema, auth=JWTAuth())
def update_git_row(request, git_id: uuid.UUID, payload: GitUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    row = get_object_or_404(GIT.objects.select_related("grn"), id=git_id)
    if payload.purchase_no is not None:
        row.purchase_no = payload.purchase_no
    if payload.item_name is not None:
        row.item_name = payload.item_name
    if payload.code is not None:
        row.code = payload.code
    if payload.purchase_quantity is not None:
        row.purchase_quantity = payload.purchase_quantity
    if payload.received_quantity is not None:
        row.received_quantity = payload.received_quantity
    if payload.variance_quantity is not None:
        row.variance_quantity = payload.variance_quantity
    if payload.variance_type is not None:
        vt = payload.variance_type.strip().lower()
        if vt not in ("increased", "decreased"):
            return JsonResponse({"detail": "variance_type must be increased or decreased."}, status=400)
        row.variance_type = vt
    row.save()
    row.refresh_from_db()
    return _git_to_schema(row)


@router.delete("/git/{git_id}", auth=JWTAuth())
def delete_git_row(request, git_id: uuid.UUID):
    err = _require_admin(request)
    if err:
        return err
    row = get_object_or_404(GIT, id=git_id)
    row.delete()
    return {"detail": "GIT row deleted successfully."}


@router.post("/git/{git_id}/wipe-off", response=GitSchema, auth=JWTAuth())
def wipe_off_git_row(request, git_id: uuid.UUID):
    err = _require_admin(request)
    if err:
        return err
    row = get_object_or_404(GIT.objects.select_related("grn"), id=git_id)
    row.variance_quantity = 0
    row.received_quantity = row.purchase_quantity
    row.save()
    row.refresh_from_db()
    return _git_to_schema(row)


@router.post("/orders", response=OrderDetailSchema)
def create_order(request, payload: OrderCreateSchema):
    # Prevent duplicate order numbers
    if Order.objects.filter(order_number=payload.order_number).exists():
        return JsonResponse(
            {"detail": "Order number already exists."},
            status=400,
        )

    pr_before_vat, total_quantity, remaining = _order_aggregate_from_line_items(
        payload.items
    )

    order = Order.objects.create(
        id=uuid.uuid4(),
        order_number=payload.order_number,
        proforma_ref_no=payload.proforma_ref_no,
        buyer=payload.buyer,
        add_consignee=payload.add_consignee,
        order_date=payload.order_date,
        shipper=payload.shipper,
        notify_party=payload.notify_party,
        add_notify_party=payload.add_notify_party,
        country_of_origin=payload.country_of_origin,
        final_destination=payload.final_destination,
        port_of_loading=payload.port_of_loading,
        port_of_discharge=payload.port_of_discharge,
        measurement_type=payload.measurement_type,
        payment_terms=payload.payment_terms,
        mode_of_transport=payload.mode_of_transport,
        freight=payload.freight,
        freight_price=payload.freight_price,
        shipment_type=payload.shipment_type,
        PR_before_VAT=pr_before_vat,
        total_quantity=total_quantity,
        remaining=remaining,
    )

    created_items: list[OrderItem] = []
    for item in payload.items:
        new_item = OrderItem.objects.create(
            item_id=uuid.uuid4(),
            order=order,
            order_no=order.order_number,
            item_name=item.item_name,
            hs_code=item.hs_code,
            price=item.price,
            quantity=item.quantity,
            total_price=item.total_price,
            before_vat=item.total_price,
            measurement=item.measurement,
        )
        created_items.append(new_item)

    return {
        "id": order.id,
        "order_number": order.order_number,
        "order_date": order.order_date,
        "buyer": order.buyer,
        "buyer_address": _get_customer_address(order.buyer),
        "buyer_tin_number": _get_customer_tin_number(order.buyer),
        "proforma_ref_no": order.proforma_ref_no,
        "add_consignee": order.add_consignee,
        "shipper": order.shipper,
        "shipper_address": _get_supplier_address(order.shipper),
        "notify_party": order.notify_party,
        "add_notify_party": order.add_notify_party,
        "country_of_origin": order.country_of_origin,
        "final_destination": order.final_destination,
        "port_of_loading": order.port_of_loading,
        "port_of_discharge": order.port_of_discharge,
        "measurement_type": order.measurement_type,
        "payment_terms": order.payment_terms,
        "mode_of_transport": order.mode_of_transport,
        "freight": order.freight,
        "freight_price": float(order.freight_price) if order.freight_price is not None else None,
        "shipment_type": order.shipment_type,
        "PR_before_VAT": float(order.PR_before_VAT),
        "total_quantity": order.total_quantity,
        "remaining": order.remaining,
        "status": order.status if admin_view else None,
        "approved_by": order.approved_by.username if admin_view and order.approved_by else None,
        "approval_date": order.approval_date.isoformat() if admin_view and order.approval_date else None,
        "completed_by": order.completed_by.username if admin_view and order.completed_by else None,
        "completed_date": order.completed_date.isoformat() if admin_view and order.completed_date else None,
        "cancelled_by": order.cancelled_by.username if admin_view and order.cancelled_by else None,
        "cancelled_date": order.cancelled_date.isoformat() if admin_view and order.cancelled_date else None,
        "status_remark": order.status_remark if admin_view else None,
        "items": [
            OrderItemSchema(
                order_no=i.order_no,
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                before_vat=float(i.before_vat),
                measurement=i.measurement,
            )
            for i in created_items
        ],
    }


@router.get("/orders", response=List[OrderDetailSchema])
def list_orders(request):
    # Sort newest orders first by order number (descending).
    orders = Order.objects.prefetch_related("items").order_by("-order_number")
    admin_view = _is_admin(request)
    result: list[OrderDetailSchema] = []
    for o in orders:
        result.append(
            OrderDetailSchema(
                id=o.id,
                order_number=o.order_number,
                order_date=o.order_date,
                buyer=o.buyer,
                buyer_address=_get_customer_address(o.buyer),
                buyer_tin_number=_get_customer_tin_number(o.buyer),
                proforma_ref_no=o.proforma_ref_no,
                add_consignee=o.add_consignee,
                shipper=o.shipper,
                shipper_address=_get_supplier_address(o.shipper),
                notify_party=o.notify_party,
                add_notify_party=o.add_notify_party,
                country_of_origin=o.country_of_origin,
                final_destination=o.final_destination,
                port_of_loading=o.port_of_loading,
                port_of_discharge=o.port_of_discharge,
                measurement_type=o.measurement_type,
                payment_terms=o.payment_terms,
                mode_of_transport=o.mode_of_transport,
                freight=o.freight,
                freight_price=float(o.freight_price) if o.freight_price is not None else None,
                shipment_type=o.shipment_type,
                PR_before_VAT=float(o.PR_before_VAT),
                total_quantity=o.total_quantity,
                remaining=o.remaining,
                status=o.status if admin_view else None,
                approved_by=o.approved_by.username if admin_view and o.approved_by else None,
                approval_date=o.approval_date.isoformat() if admin_view and o.approval_date else None,
                completed_by=o.completed_by.username if admin_view and o.completed_by else None,
                completed_date=o.completed_date.isoformat() if admin_view and o.completed_date else None,
                cancelled_by=o.cancelled_by.username if admin_view and o.cancelled_by else None,
                cancelled_date=o.cancelled_date.isoformat() if admin_view and o.cancelled_date else None,
                status_remark=o.status_remark if admin_view else None,
                items=[
                    OrderItemSchema(
                        order_no=i.order_no,
                        item_name=i.item_name,
                        hs_code=i.hs_code,
                        price=float(i.price),
                        quantity=i.quantity,
                        total_price=float(i.total_price),
                        before_vat=float(i.before_vat),
                        measurement=i.measurement,
                    )
                    for i in o.items.all()
                ],
            )
        )
    return result


@router.get("/orders/next-number")
def next_order_number(request):
    """Suggest next order number from max existing M#### (sales)."""
    values = Order.objects.values_list("order_number", flat=True)
    return {"next_number": _next_m_series_number(values)}


@router.get("/orders/{order_number}", response=OrderDetailSchema)
def get_order_detail(request, order_number: str):
    admin_view = _is_admin(request)
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        order_number__iexact=order_number.strip(),
    )
    return OrderDetailSchema(
        id=order.id,
        order_number=order.order_number,
        order_date=order.order_date,
        buyer=order.buyer,
        buyer_address=_get_customer_address(order.buyer),
        buyer_tin_number=_get_customer_tin_number(order.buyer),
        proforma_ref_no=order.proforma_ref_no,
        add_consignee=order.add_consignee,
        shipper=order.shipper,
        shipper_address=_get_supplier_address(order.shipper),
        notify_party=order.notify_party,
        add_notify_party=order.add_notify_party,
        country_of_origin=order.country_of_origin,
        final_destination=order.final_destination,
        port_of_loading=order.port_of_loading,
        port_of_discharge=order.port_of_discharge,
        measurement_type=order.measurement_type,
        payment_terms=order.payment_terms,
        mode_of_transport=order.mode_of_transport,
        freight=order.freight,
        freight_price=float(order.freight_price) if order.freight_price is not None else None,
        shipment_type=order.shipment_type,
        PR_before_VAT=float(order.PR_before_VAT),
        total_quantity=order.total_quantity,
        remaining=order.remaining,
        status=order.status if admin_view else None,
        approved_by=order.approved_by.username if admin_view and order.approved_by else None,
        approval_date=order.approval_date.isoformat() if admin_view and order.approval_date else None,
        completed_by=order.completed_by.username if admin_view and order.completed_by else None,
        completed_date=order.completed_date.isoformat() if admin_view and order.completed_date else None,
        cancelled_by=order.cancelled_by.username if admin_view and order.cancelled_by else None,
        cancelled_date=order.cancelled_date.isoformat() if admin_view and order.cancelled_date else None,
        status_remark=order.status_remark if admin_view else None,
        items=[
            OrderItemSchema(
                order_no=i.order_no,
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                before_vat=float(i.before_vat),
                measurement=i.measurement,
            )
            for i in order.items.all()
        ],
    )


@router.put("/orders/{order_number}", response=OrderDetailSchema, auth=JWTAuth())
def update_order(request, order_number: str, payload: OrderUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        order_number__iexact=order_number.strip(),
    )

    order.proforma_ref_no = payload.proforma_ref_no
    order.buyer = payload.buyer
    order.add_consignee = payload.add_consignee
    order.order_date = payload.order_date
    order.shipper = payload.shipper
    order.notify_party = payload.notify_party
    order.add_notify_party = payload.add_notify_party
    order.country_of_origin = payload.country_of_origin
    order.final_destination = payload.final_destination
    order.port_of_loading = payload.port_of_loading
    order.port_of_discharge = payload.port_of_discharge
    order.measurement_type = payload.measurement_type
    order.payment_terms = payload.payment_terms
    order.mode_of_transport = payload.mode_of_transport
    order.freight = payload.freight
    order.freight_price = payload.freight_price
    order.shipment_type = payload.shipment_type
    order_line_items = payload.items if payload.items is not None else order.items.all()
    pr_before_vat, total_quantity, remaining = _order_aggregate_from_line_items(
        order_line_items
    )
    order.PR_before_VAT = pr_before_vat
    order.total_quantity = total_quantity
    order.remaining = remaining
    order.save()

    if payload.items is not None:
        order.items.all().delete()
        for item in payload.items:
            OrderItem.objects.create(
                order=order,
                order_no=order.order_number,
                item_name=item.item_name,
                hs_code=item.hs_code,
                price=item.price,
                quantity=item.quantity,
                total_price=item.total_price,
                before_vat=item.total_price,
                measurement=item.measurement,
            )

    return OrderDetailSchema(
        id=order.id,
        order_number=order.order_number,
        order_date=order.order_date,
        buyer=order.buyer,
        buyer_address=_get_customer_address(order.buyer),
        buyer_tin_number=_get_customer_tin_number(order.buyer),
        proforma_ref_no=order.proforma_ref_no,
        add_consignee=order.add_consignee,
        shipper=order.shipper,
        shipper_address=_get_supplier_address(order.shipper),
        notify_party=order.notify_party,
        add_notify_party=order.add_notify_party,
        country_of_origin=order.country_of_origin,
        final_destination=order.final_destination,
        port_of_loading=order.port_of_loading,
        port_of_discharge=order.port_of_discharge,
        measurement_type=order.measurement_type,
        payment_terms=order.payment_terms,
        mode_of_transport=order.mode_of_transport,
        freight=order.freight,
        freight_price=float(order.freight_price) if order.freight_price is not None else None,
        shipment_type=order.shipment_type,
        PR_before_VAT=float(order.PR_before_VAT),
        total_quantity=order.total_quantity,
        remaining=order.remaining,
        status=order.status,
        approved_by=order.approved_by.username if order.approved_by else None,
        approval_date=order.approval_date.isoformat() if order.approval_date else None,
        completed_by=order.completed_by.username if order.completed_by else None,
        completed_date=order.completed_date.isoformat() if order.completed_date else None,
        cancelled_by=order.cancelled_by.username if order.cancelled_by else None,
        cancelled_date=order.cancelled_date.isoformat() if order.cancelled_date else None,
        status_remark=order.status_remark,
        items=[
            OrderItemSchema(
                order_no=i.order_no,
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                before_vat=float(i.before_vat),
                measurement=i.measurement,
            )
            for i in order.items.all()
        ],
    )

@router.delete("/orders/{order_number}", auth=JWTAuth())
def delete_order(request, order_number: str):
    err = _require_admin(request)
    if err:
        return err
    order = get_object_or_404(Order, order_number__iexact=order_number.strip())
    order.delete()
    return {"detail": "Order deleted successfully."}


@router.post("/orders/{order_number}/approve", response=OrderDetailSchema, auth=JWTAuth())
def approve_order(request, order_number: str, payload: OrderApproveSchema):
    err = _require_admin(request)
    if err:
        return err
    # Use case-insensitive, trimmed lookup to be robust against formatting differences
    order = get_object_or_404(Order, order_number__iexact=order_number.strip())
    order.status = "approved"
    order.approved_by_id = payload.approved_by_id
    order.approval_date = timezone.now()
    order.save()

    return OrderDetailSchema(
        id=order.id,
        order_number=order.order_number,
        order_date=order.order_date,
        buyer=order.buyer,
        buyer_address=_get_customer_address(order.buyer),
        buyer_tin_number=_get_customer_tin_number(order.buyer),
        proforma_ref_no=order.proforma_ref_no,
        add_consignee=order.add_consignee,
        shipper=order.shipper,
        shipper_address=_get_supplier_address(order.shipper),
        notify_party=order.notify_party,
        add_notify_party=order.add_notify_party,
        country_of_origin=order.country_of_origin,
        final_destination=order.final_destination,
        port_of_loading=order.port_of_loading,
        port_of_discharge=order.port_of_discharge,
        measurement_type=order.measurement_type,
        payment_terms=order.payment_terms,
        mode_of_transport=order.mode_of_transport,
        freight=order.freight,
        freight_price=float(order.freight_price) if order.freight_price is not None else None,
        shipment_type=order.shipment_type,
        PR_before_VAT=float(order.PR_before_VAT),
        total_quantity=order.total_quantity,
        remaining=order.remaining,
        status=order.status,
        approved_by=order.approved_by.username if order.approved_by else None,
        approval_date=order.approval_date.isoformat() if order.approval_date else None,
        completed_by=order.completed_by.username if order.completed_by else None,
        completed_date=order.completed_date.isoformat() if order.completed_date else None,
        cancelled_by=order.cancelled_by.username if order.cancelled_by else None,
        cancelled_date=order.cancelled_date.isoformat() if order.cancelled_date else None,
        status_remark=order.status_remark,
        items=[
            OrderItemSchema(
                order_no=i.order_no,
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                before_vat=float(i.before_vat),
                measurement=i.measurement,
            )
            for i in order.items.all()
        ],
    )


@router.post("/orders/{order_number}/update-status", response=OrderDetailSchema, auth=JWTAuth())
def update_order_status(request, order_number: str, payload: OrderStatusUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        order_number__iexact=order_number.strip(),
    )
    if order.status != "approved":
        return JsonResponse(
            {"detail": "Only approved orders can be marked as completed or cancelled."},
            status=400,
        )
    if payload.status not in ("completed", "cancelled"):
        return JsonResponse(
            {"detail": "Status must be 'completed' or 'cancelled'."},
            status=400,
        )
    order.status = payload.status
    order.status_remark = payload.remark or ""
    if payload.status == "completed":
        order.completed_by_id = payload.user_id
        order.completed_date = timezone.now()
    else:
        order.cancelled_by_id = payload.user_id
        order.cancelled_date = timezone.now()
    order.save()

    return OrderDetailSchema(
        id=order.id,
        order_number=order.order_number,
        order_date=order.order_date,
        buyer=order.buyer,
        buyer_address=_get_customer_address(order.buyer),
        buyer_tin_number=_get_customer_tin_number(order.buyer),
        proforma_ref_no=order.proforma_ref_no,
        add_consignee=order.add_consignee,
        shipper=order.shipper,
        shipper_address=_get_supplier_address(order.shipper),
        notify_party=order.notify_party,
        add_notify_party=order.add_notify_party,
        country_of_origin=order.country_of_origin,
        final_destination=order.final_destination,
        port_of_loading=order.port_of_loading,
        port_of_discharge=order.port_of_discharge,
        measurement_type=order.measurement_type,
        payment_terms=order.payment_terms,
        mode_of_transport=order.mode_of_transport,
        freight=order.freight,
        freight_price=float(order.freight_price) if order.freight_price is not None else None,
        shipment_type=order.shipment_type,
        PR_before_VAT=float(order.PR_before_VAT),
        total_quantity=order.total_quantity,
        remaining=order.remaining,
        status=order.status,
        approved_by=order.approved_by.username if order.approved_by else None,
        approval_date=order.approval_date.isoformat() if order.approval_date else None,
        completed_by=order.completed_by.username if order.completed_by else None,
        completed_date=order.completed_date.isoformat() if order.completed_date else None,
        cancelled_by=order.cancelled_by.username if order.cancelled_by else None,
        cancelled_date=order.cancelled_date.isoformat() if order.cancelled_date else None,
        status_remark=order.status_remark,
        items=[
            OrderItemSchema(
                order_no=i.order_no,
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                before_vat=float(i.before_vat),
                measurement=i.measurement,
            )
            for i in order.items.all()
        ],
    )


@router.post("/purchases", response=PurchaseDetailSchema)
def create_purchase(request, payload: PurchaseCreateSchema):
    # Prevent duplicate purchase numbers
    if Purchase.objects.filter(purchase_number=payload.purchase_number).exists():
        return JsonResponse(
            {"detail": "Purchase number already exists."},
            status=400,
        )

    payment_value = payload.payment_type or payload.payment_terms
    if not payment_value:
        return JsonResponse({"detail": "payment_type is required."}, status=400)

    before_vat, total_quantity, remaining = _purchase_aggregate_from_line_items(
        payload.items
    )

    purchase = Purchase.objects.create(
        id=uuid.uuid4(),
        purchase_number=payload.purchase_number,
        proforma_ref_no=payload.proforma_ref_no,
        buyer=payload.buyer,
        add_consignee=payload.add_consignee,
        order_date=payload.order_date,
        shipper=payload.shipper,
        notify_party=payload.notify_party,
        add_notify_party=payload.add_notify_party,
        country_of_origin=payload.country_of_origin,
        final_destination=payload.final_destination,
        conditions=payload.conditions,
        port_of_loading=payload.port_of_loading,
        port_of_discharge=payload.port_of_discharge,
        measurement_type=payload.measurement_type,
        payment_terms=payment_value,  # DB column name (legacy)
        mode_of_transport=payload.mode_of_transport,
        freight=payload.freight,
        freight_price=payload.freight_price,
        insurance=payload.insurance,
        shipment_type=payload.shipment_type,
        before_vat=before_vat,
        total_quantity=total_quantity,
        remaining=remaining,
        status="pending",
    )

    created_items: list[PurchaseItem] = []
    for item in payload.items:
        line_remaining = (
            item.remaining if item.remaining is not None else item.quantity
        )
        line_before_vat = (
            item.before_vat if item.before_vat is not None else item.total_price
        )
        hs = (item.hscode or "").strip() or None
        line_item_id = item.item_id if item.item_id is not None else uuid.uuid4()
        new_item = PurchaseItem.objects.create(
            item_id=line_item_id,
            purchase=purchase,
            item_name=item.item_name,
            price=item.price,
            quantity=item.quantity,
            remaining=line_remaining,
            total_price=item.total_price,
            before_vat=Decimal(str(line_before_vat)),
            hscode=hs,
            measurement=item.measurement,
        )
        created_items.append(new_item)

    return _purchase_to_detail_schema(purchase, request)


@router.get("/purchases/next-number")
def next_purchase_number(request):
    """Suggest next purchase number from max existing MPDDFZE### (e.g. MPDDFZE003)."""
    values = Purchase.objects.values_list("purchase_number", flat=True)
    return {"next_number": _next_mpddfze_purchase_number(values)}


@router.get("/purchases/{purchase_number}", response=PurchaseDetailSchema)
def get_purchase_detail(request, purchase_number: str):
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related("items"),
        purchase_number__iexact=purchase_number.strip(),
    )
    return _purchase_to_detail_schema(purchase, request)


@router.delete("/purchases/{purchase_number}", auth=JWTAuth())
def delete_purchase(request, purchase_number: str):
    err = _require_admin(request)
    if err:
        return err
    purchase = get_object_or_404(Purchase, purchase_number__iexact=purchase_number.strip())
    purchase.delete()
    return {"detail": "Purchase deleted successfully."}


@router.post("/purchases/{purchase_number}/approve", response=PurchaseDetailSchema, auth=JWTAuth())
def approve_purchase(request, purchase_number: str, payload: PurchaseApproveSchema):
    err = _require_admin(request)
    if err:
        return err
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related("items"),
        purchase_number__iexact=purchase_number.strip(),
    )
    purchase.status = "approved"
    purchase.approved_by_id = payload.approved_by_id
    purchase.approval_date = timezone.now()
    purchase.save()
    return _purchase_to_detail_schema(purchase, request)


def _purchase_to_detail_schema(purchase, request=None):
    payment_value = purchase.payment_terms
    admin_view = _is_admin(request) if request is not None else False
    return PurchaseDetailSchema(
        id=purchase.id,
        purchase_number=purchase.purchase_number,
        order_date=purchase.order_date,
        buyer=purchase.buyer,
        buyer_address=_get_customer_address(purchase.buyer),
        proforma_ref_no=purchase.proforma_ref_no,
        status=purchase.status if admin_view else None,
        approved_by=purchase.approved_by.username if admin_view and purchase.approved_by else None,
        approval_date=purchase.approval_date.isoformat() if admin_view and purchase.approval_date else None,
        completed_by=purchase.completed_by.username if admin_view and purchase.completed_by else None,
        completed_date=purchase.completed_date.isoformat() if admin_view and purchase.completed_date else None,
        cancelled_by=purchase.cancelled_by.username if admin_view and purchase.cancelled_by else None,
        cancelled_date=purchase.cancelled_date.isoformat() if admin_view and purchase.cancelled_date else None,
        status_remark=purchase.status_remark if admin_view else None,
        add_consignee=purchase.add_consignee,
        shipper=purchase.shipper,
        shipper_address=_get_supplier_address(purchase.shipper),
        notify_party=purchase.notify_party,
        add_notify_party=purchase.add_notify_party,
        country_of_origin=purchase.country_of_origin,
        final_destination=purchase.final_destination,
        conditions=purchase.conditions,
        port_of_loading=purchase.port_of_loading,
        port_of_discharge=purchase.port_of_discharge,
        measurement_type=purchase.measurement_type,
        payment_type=payment_value,
        payment_terms=payment_value,  # legacy response key
        mode_of_transport=purchase.mode_of_transport,
        freight=purchase.freight,
        freight_price=float(purchase.freight_price) if purchase.freight_price is not None else None,
        insurance=purchase.insurance,
        shipment_type=purchase.shipment_type,
        before_vat=float(purchase.before_vat),
        total_quantity=purchase.total_quantity,
        remaining=purchase.remaining,
        items=[
            PurchaseItemSchema(
                item_id=i.item_id,
                purchase_number=str(i.purchase_id),
                item_name=i.item_name,
                price=float(i.price),
                quantity=i.quantity,
                remaining=i.remaining,
                total_price=float(i.total_price),
                before_vat=float(i.before_vat),
                hscode=i.hscode,
                measurement=i.measurement,
            )
            for i in purchase.items.all()
        ],
    )


@router.put("/purchases/{purchase_number}", response=PurchaseDetailSchema, auth=JWTAuth())
def update_purchase(request, purchase_number: str, payload: PurchaseUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related("items"),
        purchase_number__iexact=purchase_number.strip(),
    )
    purchase.proforma_ref_no = payload.proforma_ref_no
    purchase.buyer = payload.buyer
    purchase.add_consignee = payload.add_consignee
    purchase.order_date = payload.order_date
    purchase.shipper = payload.shipper
    purchase.notify_party = payload.notify_party
    purchase.add_notify_party = payload.add_notify_party
    purchase.country_of_origin = payload.country_of_origin
    purchase.final_destination = payload.final_destination
    purchase.conditions = payload.conditions
    purchase.port_of_loading = payload.port_of_loading
    purchase.port_of_discharge = payload.port_of_discharge
    purchase.measurement_type = payload.measurement_type
    payment_value = payload.payment_type or payload.payment_terms
    if not payment_value:
        return JsonResponse({"detail": "payment_type is required."}, status=400)
    purchase.payment_terms = payment_value  # DB column name (legacy)
    purchase.mode_of_transport = payload.mode_of_transport
    purchase.freight = payload.freight
    purchase.freight_price = payload.freight_price
    purchase.insurance = payload.insurance
    purchase.shipment_type = payload.shipment_type
    before_vat, total_quantity, remaining = _purchase_aggregate_from_line_items(
        payload.items
    )
    purchase.before_vat = before_vat
    purchase.total_quantity = total_quantity
    purchase.remaining = remaining
    purchase.save()

    purchase.items.all().delete()
    for item in payload.items:
        line_remaining = (
            item.remaining if item.remaining is not None else item.quantity
        )
        line_before_vat = (
            item.before_vat if item.before_vat is not None else item.total_price
        )
        hs = (item.hscode or "").strip() or None
        line_item_id = item.item_id if item.item_id is not None else uuid.uuid4()
        PurchaseItem.objects.create(
            item_id=line_item_id,
            purchase=purchase,
            item_name=item.item_name,
            price=item.price,
            quantity=item.quantity,
            remaining=line_remaining,
            total_price=item.total_price,
            before_vat=Decimal(str(line_before_vat)),
            hscode=hs,
            measurement=item.measurement,
        )

    purchase.refresh_from_db()
    return _purchase_to_detail_schema(purchase, request)


@router.post("/purchases/{purchase_number}/update-status", response=PurchaseDetailSchema, auth=JWTAuth())
def update_purchase_status(request, purchase_number: str, payload: PurchaseStatusUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related("items"),
        purchase_number__iexact=purchase_number.strip(),
    )
    if purchase.status != "approved":
        return JsonResponse(
            {"detail": "Only approved purchases can be marked as completed or cancelled."},
            status=400,
        )
    if payload.status not in ("completed", "cancelled"):
        return JsonResponse(
            {"detail": "Status must be 'completed' or 'cancelled'."},
            status=400,
        )
    purchase.status = payload.status
    purchase.status_remark = payload.remark or ""
    if payload.status == "completed":
        purchase.completed_by_id = payload.user_id
        purchase.completed_date = timezone.now()
    else:
        purchase.cancelled_by_id = payload.user_id
        purchase.cancelled_date = timezone.now()
    purchase.save()
    return _purchase_to_detail_schema(purchase, request)


@router.get("/purchases", response=List[PurchaseDetailSchema])
def list_purchases(request):
    # Sort newest purchases first by purchase/order number (descending).
    purchases = Purchase.objects.prefetch_related("items").order_by("-purchase_number")
    result: list[PurchaseDetailSchema] = []
    for p in purchases:
        result.append(_purchase_to_detail_schema(p, request))
    return result


@router.post("/shipping-invoices", response=ShippingInvoiceSummarySchema)
def create_shipping_invoice(request, payload: ShippingInvoiceCreateSchema):
    # Prevent duplicate invoice numbers (case-insensitive)
    if ShippingInvoice.objects.filter(
        invoice_number__iexact=payload.invoice_number.strip()
    ).exists():
        return JsonResponse(
            {"detail": "Invoice number already exists."},
            status=400,
        )

    # Find related order by unique order number
    order = get_object_or_404(
        Order, order_number__iexact=payload.order_number.strip()
    )

    invoice = ShippingInvoice.objects.create(
        id=uuid.uuid4(),
        order=order,
        invoice_number=payload.invoice_number,
        invoice_date=payload.invoice_date,
        waybill_number=payload.waybill_number,
        customer_order_number=payload.customer_order_number,
        container_number=payload.container_number,
        vessel=payload.vessel,
        freight_amount=payload.freight_amount,
        reference_no=payload.reference_no,
        total_bags=payload.total_bags,
        total_net_weight=payload.total_net_weight,
        total_gross_weight=payload.total_gross_weight,
        final_price=payload.final_price,
        invoice_remark=payload.invoice_remark,
        packing_list_remark=payload.packing_list_remark,
        waybill_remark=payload.waybill_remark,
        bill_of_lading_remark=payload.bill_of_lading_remark,
        bank=payload.bank,
        sr_no=payload.sr_no,
    )

    for item in payload.items:
        ShippingInvoiceItem.objects.create(
            id=uuid.uuid4(),
            invoice=invoice,
            item_id=getattr(item, "item_id", None),
            item_name=item.item_name,
            price=item.price,
            quantity=item.quantity,
            total_price=item.total_price,
            measurement=item.measurement,
            bags=item.bags,
            net_weight=item.net_weight,
            gross_weight=item.gross_weight,
            hscode=getattr(item, "hscode", None),
            grade=item.grade,
            brand=item.brand,
            country_of_origin=getattr(item, "country_of_origin", None),
        )

    return ShippingInvoiceSummarySchema(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        order_number=invoice.order.order_number,
        invoice_date=invoice.invoice_date,
        reference_no=invoice.reference_no,
        final_price=float(invoice.final_price) if invoice.final_price is not None else None,
    )


@router.get("/shipping-invoices", response=List[ShippingInvoiceSummarySchema])
def list_shipping_invoices(request, order_number: Optional[str] = None):
    invoices = ShippingInvoice.objects.select_related("order").all()
    if order_number:
        invoices = invoices.filter(
            order__order_number__iexact=order_number.strip()
        )

    result: list[ShippingInvoiceSummarySchema] = []
    for inv in invoices:
        result.append(
            ShippingInvoiceSummarySchema(
                id=inv.id,
                invoice_number=inv.invoice_number,
                order_number=inv.order.order_number,
                invoice_date=inv.invoice_date,
                reference_no=inv.reference_no,
                final_price=float(inv.final_price) if inv.final_price is not None else None,
                authorized_by=inv.authorized_by,
                authorized_at=inv.authorized_at.isoformat() if inv.authorized_at else None,
            )
        )
    return result


@router.get("/shipping-invoices/{invoice_id}", response=ShippingInvoiceDetailSchema)
def get_shipping_invoice_detail(request, invoice_id: uuid.UUID):
    invoice = get_object_or_404(
        ShippingInvoice.objects.prefetch_related("items", "order"), id=invoice_id
    )
    return ShippingInvoiceDetailSchema(
        id=invoice.id,
        order_number=invoice.order.order_number,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        waybill_number=invoice.waybill_number,
        customer_order_number=invoice.customer_order_number,
        container_number=invoice.container_number,
        vessel=invoice.vessel,
        freight_amount=float(invoice.freight_amount) if invoice.freight_amount is not None else None,
        reference_no=invoice.reference_no,
        total_bags=invoice.total_bags,
        total_net_weight=invoice.total_net_weight,
        total_gross_weight=invoice.total_gross_weight,
        final_price=float(invoice.final_price) if invoice.final_price is not None else None,
        invoice_remark=invoice.invoice_remark,
        packing_list_remark=invoice.packing_list_remark,
        waybill_remark=invoice.waybill_remark,
        bill_of_lading_remark=invoice.bill_of_lading_remark,
        bank=invoice.bank,
        sr_no=invoice.sr_no,
        authorized_by=invoice.authorized_by,
        authorized_at=invoice.authorized_at.isoformat() if invoice.authorized_at else None,
        items=[
            ShippingInvoiceItemSchema(
                item_id=i.item_id,
                item_name=i.item_name,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                measurement=i.measurement,
                bags=i.bags,
                net_weight=i.net_weight,
                gross_weight=i.gross_weight,
                hscode=i.hscode,
                grade=i.grade,
                brand=i.brand,
                country_of_origin=i.country_of_origin,
            )
            for i in invoice.items.all()
        ],
    )


@router.put("/shipping-invoices/{invoice_id}", response=ShippingInvoiceDetailSchema)
def update_shipping_invoice(
    request, invoice_id: uuid.UUID, payload: ShippingInvoiceUpdateSchema
):
    invoice = get_object_or_404(
        ShippingInvoice.objects.prefetch_related("items", "order"), id=invoice_id
    )

    invoice.invoice_date = payload.invoice_date
    invoice.waybill_number = payload.waybill_number
    invoice.customer_order_number = payload.customer_order_number
    invoice.container_number = payload.container_number
    invoice.vessel = payload.vessel
    invoice.freight_amount = payload.freight_amount
    invoice.reference_no = payload.reference_no
    invoice.total_bags = payload.total_bags
    invoice.total_net_weight = payload.total_net_weight
    invoice.total_gross_weight = payload.total_gross_weight
    invoice.final_price = payload.final_price
    invoice.invoice_remark = payload.invoice_remark
    invoice.packing_list_remark = payload.packing_list_remark
    invoice.waybill_remark = payload.waybill_remark
    invoice.bill_of_lading_remark = payload.bill_of_lading_remark
    invoice.bank = payload.bank
    invoice.sr_no = payload.sr_no
    invoice.save()

    # Replace items
    invoice.items.all().delete()
    for item in payload.items:
        ShippingInvoiceItem.objects.create(
            id=uuid.uuid4(),
            invoice=invoice,
            item_id=getattr(item, "item_id", None),
            item_name=item.item_name,
            price=item.price,
            quantity=item.quantity,
            total_price=item.total_price,
            measurement=item.measurement,
            bags=item.bags,
            net_weight=item.net_weight,
            gross_weight=item.gross_weight,
            hscode=getattr(item, "hscode", None),
            grade=item.grade,
            brand=item.brand,
            country_of_origin=getattr(item, "country_of_origin", None),
        )

    invoice.refresh_from_db()

    return ShippingInvoiceDetailSchema(
        id=invoice.id,
        order_number=invoice.order.order_number,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        waybill_number=invoice.waybill_number,
        customer_order_number=invoice.customer_order_number,
        container_number=invoice.container_number,
        vessel=invoice.vessel,
        freight_amount=float(invoice.freight_amount) if invoice.freight_amount is not None else None,
        reference_no=invoice.reference_no,
        total_bags=invoice.total_bags,
        total_net_weight=invoice.total_net_weight,
        total_gross_weight=invoice.total_gross_weight,
        final_price=float(invoice.final_price) if invoice.final_price is not None else None,
        invoice_remark=invoice.invoice_remark,
        packing_list_remark=invoice.packing_list_remark,
        waybill_remark=invoice.waybill_remark,
        bill_of_lading_remark=invoice.bill_of_lading_remark,
        bank=invoice.bank,
        sr_no=invoice.sr_no,
        authorized_by=invoice.authorized_by,
        authorized_at=invoice.authorized_at.isoformat() if invoice.authorized_at else None,
        items=[
            ShippingInvoiceItemSchema(
                item_id=i.item_id,
                item_name=i.item_name,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                measurement=i.measurement,
                bags=i.bags,
                net_weight=i.net_weight,
                gross_weight=i.gross_weight,
                hscode=i.hscode,
                grade=i.grade,
                brand=i.brand,
                country_of_origin=i.country_of_origin,
            )
            for i in invoice.items.all()
        ],
    )


@router.post("/shipping-invoices/{invoice_id}/authorize", response=ShippingInvoiceDetailSchema, auth=JWTAuth())
def authorize_shipping_invoice(request, invoice_id: uuid.UUID):
    invoice = get_object_or_404(
        ShippingInvoice.objects.prefetch_related("items", "order"), id=invoice_id
    )
    authorized_by = getattr(request.user, "username", None) or str(request.user)
    invoice.authorized_by = authorized_by
    invoice.authorized_at = datetime.now()
    invoice.save()
    invoice.refresh_from_db()

    # Send notification email
    try:
        authorized_at_str = (
            invoice.authorized_at.strftime("%Y-%m-%d %H:%M:%S")
            if invoice.authorized_at
            else ""
        )
        invoice_date_str = (
            invoice.invoice_date.strftime("%Y-%m-%d")
            if invoice.invoice_date
            else ""
        )
        customer_name = invoice.order.buyer or ""
        items_lines = "\n".join(
            f"  - {i.item_name}: {i.quantity}"
            for i in invoice.items.all()
        )
        recipient_list = [
            "mekdi1610@gmail.com",
        ]
        frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000")
        view_url = f"{frontend_base.rstrip('/')}/diredawa/orders/{invoice.order.order_number}/loading-instruction?invoiceId={invoice.id}"

        # Plain text fallback
        plain_message = (
            f"LOADING INSTRUCTION AUTHORIZED\n"
            f"{'=' * 40}\n\n"
            f"A loading instruction has been authorized and is ready for use.\n\n"
            f"ORDER DETAILS\n"
            f"  Invoice Number:       {invoice.invoice_number}\n"
            f"  Order Number:         {invoice.order.order_number}\n"
            f"  Customer Order No:    {invoice.customer_order_number}\n"
            f"  Customer Name:        {customer_name}\n"
            f"  Invoice Date:         {invoice_date_str}\n"
            f"  Waybill Number:       {invoice.waybill_number or '—'}\n"
            f"  Container Number:     {invoice.container_number or '—'}\n"
            f"  Vessel:               {invoice.vessel or '—'}\n\n"
            f"ITEMS ({invoice.items.count()} line(s))\n"
            f"{items_lines}\n\n"
            f"AUTHORIZATION\n"
            f"  Authorized by:        {authorized_by}\n"
            f"  Authorized at:        {authorized_at_str}\n\n"
            f"View in system: {view_url}\n"
        )

        # HTML email (escape user content for safety)
        def _esc(s):
            return html.escape(str(s) if s is not None else "")

        items_rows = "".join(
            f"""
            <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{_esc(i.item_name)}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">{_esc(i.quantity)}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{_esc(i.measurement or '—')}</td>
            </tr>"""
            for i in invoice.items.all()
        )
        html_message = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Loading Instruction Authorized</title>
</head>
<body style="margin:0;font-family:Arial,sans-serif;background-color:#f4f4f5;padding:24px;">
  <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
    <div style="background:linear-gradient(135deg,#2563eb 0%,#1d4ed8 100%);color:#fff;padding:20px 24px;">
      <h1 style="margin:0;font-size:20px;font-weight:600;">Loading Instruction Authorized</h1>
      <p style="margin:8px 0 0;font-size:14px;opacity:0.95;">Invoice #{_esc(invoice.invoice_number)}</p>
    </div>
    <div style="padding:24px;">
      <p style="margin:0 0 16px;color:#374151;font-size:15px;line-height:1.5;">
        A loading instruction has been authorized and is ready for use.
      </p>
      <table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-size:14px;">
        <tr><td style="padding:6px 0;color:#6b7280;width:45%;">Invoice Number</td><td style="padding:6px 0;color:#111827;font-weight:500;">{_esc(invoice.invoice_number)}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Order Number</td><td style="padding:6px 0;color:#111827;font-weight:500;">{_esc(invoice.order.order_number)}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Customer Order No</td><td style="padding:6px 0;color:#111827;">{_esc(invoice.customer_order_number)}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Customer Name</td><td style="padding:6px 0;color:#111827;">{_esc(customer_name or '—')}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Invoice Date</td><td style="padding:6px 0;color:#111827;">{_esc(invoice_date_str)}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Waybill Number</td><td style="padding:6px 0;color:#111827;">{_esc(invoice.waybill_number or '—')}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Container Number</td><td style="padding:6px 0;color:#111827;">{_esc(invoice.container_number or '—')}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Vessel</td><td style="padding:6px 0;color:#111827;">{_esc(invoice.vessel or '—')}</td></tr>
      </table>
      <h3 style="margin:0 0 12px;font-size:14px;color:#374151;">Items ({invoice.items.count()} line(s))</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;border:1px solid #e5e7eb;border-radius:6px;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="padding:10px 12px;text-align:left;font-weight:600;color:#374151;">Item</th>
            <th style="padding:10px 12px;text-align:right;font-weight:600;color:#374151;">Qty</th>
            <th style="padding:10px 12px;text-align:left;font-weight:600;color:#374151;">Measurement</th>
          </tr>
        </thead>
        <tbody>{items_rows}
        </tbody>
      </table>
      <div style="margin-top:20px;padding:16px;background:#f0fdf4;border-radius:6px;border:1px solid #bbf7d0;">
        <p style="margin:0 0 8px;font-size:13px;color:#166534;font-weight:600;">Authorization Details</p>
        <p style="margin:0;font-size:14px;color:#374151;">
          <strong>Authorized by:</strong> {_esc(authorized_by)} &nbsp;|&nbsp;
          <strong>Authorized at:</strong> {_esc(authorized_at_str)}
        </p>
      </div>
      <p style="margin:24px 0 0;text-align:center;">
        <a href="{view_url}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-size:14px;font-weight:500;">View Loading Instruction</a>
      </p>
    </div>
    <div style="padding:12px 24px;background:#f9fafb;font-size:12px;color:#6b7280;text-align:center;">
      This is an automated notification from the Mohan loading instruction system.
    </div>
  </div>
</body>
</html>
"""
        sent = send_mail(
            subject=f"Loading Instruction Authorized – Invoice #{invoice.invoice_number} (Order {invoice.order.order_number})",
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
            html_message=html_message,
        )
        if sent == 0:
            logger.warning("Email sent count was 0 for authorize notification")
        else:
            logger.info("Authorize notification email sent successfully to recipients")
    except Exception as e:
        logger.exception("Failed to send authorize notification email: %s", e)

    return ShippingInvoiceDetailSchema(
        id=invoice.id,
        order_number=invoice.order.order_number,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        waybill_number=invoice.waybill_number,
        customer_order_number=invoice.customer_order_number,
        container_number=invoice.container_number,
        vessel=invoice.vessel,
        freight_amount=float(invoice.freight_amount) if invoice.freight_amount is not None else None,
        reference_no=invoice.reference_no,
        total_bags=invoice.total_bags,
        total_net_weight=invoice.total_net_weight,
        total_gross_weight=invoice.total_gross_weight,
        final_price=float(invoice.final_price) if invoice.final_price is not None else None,
        invoice_remark=invoice.invoice_remark,
        packing_list_remark=invoice.packing_list_remark,
        waybill_remark=invoice.waybill_remark,
        bill_of_lading_remark=invoice.bill_of_lading_remark,
        bank=invoice.bank,
        sr_no=invoice.sr_no,
        authorized_by=invoice.authorized_by,
        authorized_at=invoice.authorized_at.isoformat() if invoice.authorized_at else None,
        items=[
            ShippingInvoiceItemSchema(
                item_id=i.item_id,
                item_name=i.item_name,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                measurement=i.measurement,
                bags=i.bags,
                net_weight=i.net_weight,
                gross_weight=i.gross_weight,
                hscode=i.hscode,
                grade=i.grade,
                brand=i.brand,
                country_of_origin=i.country_of_origin,
            )
            for i in invoice.items.all()
        ],
    )

