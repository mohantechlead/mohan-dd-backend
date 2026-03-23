import html
import logging
from ninja import Router
from typing import List, Optional
from datetime import datetime
from datetime import datetime
from django.shortcuts import get_object_or_404
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


def _get_customer_address(name: str) -> Optional[str]:
    """Look up customer address by name (partner_type in customer, both)."""
    p = Partner.objects.filter(name__iexact=name.strip()).filter(
        partner_type__in=("customer", "both")
    ).first()
    return p.address if p and p.address else None


def _get_supplier_address(name: str) -> Optional[str]:
    """Look up supplier address by name (partner_type in supplier, both)."""
    p = Partner.objects.filter(name__iexact=name.strip()).filter(
        partner_type__in=("supplier", "both")
    ).first()
    return p.address if p and p.address else None


def _check_and_notify_negative_stock():
    """Check if any item has negative stock and send email notification if so."""
    items = Items.objects.all()
    negative_items = []

    for item in items:
        grn_totals = GrnItems.objects.filter(
            internal_code=item.internal_code
        ).aggregate(
            quantity=Sum("quantity"),
            bags=Sum("bags")
        )
        dn_totals = DNItems.objects.filter(
            internal_code=item.internal_code
        ).aggregate(
            quantity=Sum("quantity"),
            bags=Sum("bags")
        )

        grn_qty = grn_totals["quantity"] or 0
        grn_bags = grn_totals["bags"] or 0
        dn_qty = dn_totals["quantity"] or 0
        dn_bags = dn_totals["bags"] or 0

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
                "sol@mohanplc.com",
                "Kapil@mohanint.com",
                "Harsh@mohanplc.com",
                "Mayuraddis@gmail.com",
                "Amritakaur2612@gmail.com",
            ],
            fail_silently=True,
        )
        if sent > 0:
            logger.info("Negative stock alert email sent to recipients")
        else:
            logger.warning("Negative stock alert email sent count was 0")
    except Exception as e:
        logger.exception("Failed to send negative stock alert email: %s", e)


def _check_and_notify_over_under_delivery(dn):
    """
    Compare DN total delivered quantities vs Invoice (ShippingInvoice) quantities for sales_no.
    Uses the invoice linked by dn.invoice_no when present; otherwise skips.
    Send email if any item has over delivery (delivered > invoiced) or under delivery (delivered < invoiced).
    Returns (over_items, under_items) for API response.
    """
    over_items = []
    under_items = []
    try:
        invoice_no = (dn.invoice_no or "").strip()
        if not invoice_no:
            logger.info(
                "Over/under delivery check skipped: no invoice_no on DN %s (sales_no=%s)",
                dn.dn_no,
                dn.sales_no,
            )
            return over_items, under_items

        order = Order.objects.filter(order_number=dn.sales_no).first()
        if not order:
            logger.info(
                "Over/under delivery check skipped: no Order found with order_number=%s (DN %s)",
                dn.sales_no,
                dn.dn_no,
            )
            return over_items, under_items

        invoice = ShippingInvoice.objects.filter(
            order=order,
            invoice_number__iexact=invoice_no,
        ).prefetch_related("items").first()

        if not invoice:
            logger.info(
                "Over/under delivery check skipped: no ShippingInvoice found with invoice_number=%s for order %s (DN %s)",
                invoice_no,
                dn.sales_no,
                dn.dn_no,
            )
            return over_items, under_items

        # Aggregate invoice quantities by item_name (invoice can have same item on multiple lines)
        invoiced_by_item = {}
        for inv_item in invoice.items.all():
            name = inv_item.item_name
            qty = int(inv_item.quantity)
            invoiced_by_item[name] = invoiced_by_item.get(name, 0) + qty

        # Compare total invoiced vs total delivered per item
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

        if not over_items and not under_items:
            logger.info(
                "Over/under delivery check: no variance for DN %s (sales_no=%s) - all quantities match invoice",
                dn.dn_no,
                dn.sales_no,
            )
            return over_items, under_items

        lines = [
            f"Delivery Note: {dn.dn_no}",
            f"Order/Sales No: {dn.sales_no}",
            f"Invoice: {invoice.invoice_number}",
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


def _check_and_notify_negative_stock():
    """Check if any item has negative stock and send email notification if so."""
    items = Items.objects.all()
    negative_items = []

    for item in items:
        grn_totals = GrnItems.objects.filter(
            internal_code=item.internal_code
        ).aggregate(
            quantity=Sum("quantity"),
            bags=Sum("bags")
        )
        dn_totals = DNItems.objects.filter(
            internal_code=item.internal_code
        ).aggregate(
            quantity=Sum("quantity"),
            bags=Sum("bags")
        )

        grn_qty = grn_totals["quantity"] or 0
        grn_bags = grn_totals["bags"] or 0
        dn_qty = dn_totals["quantity"] or 0
        dn_bags = dn_totals["bags"] or 0

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
                "sol@mohanplc.com",
                "Kapil@mohanint.com",
                "Harsh@mohanplc.com",
                "Mayuraddis@gmail.com",
                "Amritakaur2612@gmail.com",
            ],
            fail_silently=True,
        )
        if sent > 0:
            logger.info("Negative stock alert email sent to recipients")
        else:
            logger.warning("Negative stock alert email sent count was 0")
    except Exception as e:
        logger.exception("Failed to send negative stock alert email: %s", e)


def _check_and_notify_over_under_delivery(dn):
    """
    Compare DN total delivered quantities vs Invoice (ShippingInvoice) quantities for sales_no.
    Uses the invoice linked by dn.invoice_no when present; otherwise skips.
    Send email if any item has over delivery (delivered > invoiced) or under delivery (delivered < invoiced).
    Returns (over_items, under_items) for API response.
    """
    over_items = []
    under_items = []
    try:
        invoice_no = (dn.invoice_no or "").strip()
        if not invoice_no:
            logger.info(
                "Over/under delivery check skipped: no invoice_no on DN %s (sales_no=%s)",
                dn.dn_no,
                dn.sales_no,
            )
            return over_items, under_items

        order = Order.objects.filter(order_number=dn.sales_no).first()
        if not order:
            logger.info(
                "Over/under delivery check skipped: no Order found with order_number=%s (DN %s)",
                dn.sales_no,
                dn.dn_no,
            )
            return over_items, under_items

        invoice = ShippingInvoice.objects.filter(
            order=order,
            invoice_number__iexact=invoice_no,
        ).prefetch_related("items").first()

        if not invoice:
            logger.info(
                "Over/under delivery check skipped: no ShippingInvoice found with invoice_number=%s for order %s (DN %s)",
                invoice_no,
                dn.sales_no,
                dn.dn_no,
            )
            return over_items, under_items

        # Aggregate invoice quantities by item_name (invoice can have same item on multiple lines)
        invoiced_by_item = {}
        for inv_item in invoice.items.all():
            name = inv_item.item_name
            qty = int(inv_item.quantity)
            invoiced_by_item[name] = invoiced_by_item.get(name, 0) + qty

        # Compare total invoiced vs total delivered per item
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

        if not over_items and not under_items:
            logger.info(
                "Over/under delivery check: no variance for DN %s (sales_no=%s) - all quantities match invoice",
                dn.dn_no,
                dn.sales_no,
            )
            return over_items, under_items

        lines = [
            f"Delivery Note: {dn.dn_no}",
            f"Order/Sales No: {dn.sales_no}",
            f"Invoice: {invoice.invoice_number}",
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

        grn = GRN.objects.create(
            id=uuid.uuid4(),
            supplier_name=payload.supplier_name,
            grn_no=grn_no_val,
            plate_no=payload.plate_no,
            purchase_no=payload.purchase_no,
            date=payload.date,
            ECD_no=payload.ECD_no,
            transporter_name=payload.transporter_name,
            storekeeper_name=payload.storekeeper_name,
        )

        created_items = []
        for item in payload.items:
            bags_val = None
            if item.bags is not None and str(item.bags).strip():
                try:
                    bags_val = float(item.bags)
                except (ValueError, TypeError):
                    pass

            new_item = GrnItems.objects.create(
                item_id=uuid.uuid4(),
                grn=grn,
                item_name=item.item_name,
                quantity=int(item.quantity) if item.quantity is not None else 0,
                unit_measurement=item.unit_measurement or "",
                internal_code=item.internal_code or None,
                bags=bags_val,
            )
            created_items.append(new_item)

        _check_and_notify_negative_stock()

        grn.refresh_from_db()
        return _grn_to_detail(grn)
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
                    items=[
                        GrnItemSchema(
                            item_name=item.item_name,
                            quantity=item.quantity
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
    if payload.plate_no is not None:
        grn.plate_no = payload.plate_no
    if payload.purchase_no is not None:
        grn.purchase_no = payload.purchase_no
    if payload.ECD_no is not None:
        grn.ECD_no = payload.ECD_no
    if payload.transporter_name is not None:
        grn.transporter_name = payload.transporter_name
    if payload.storekeeper_name is not None:
        grn.storekeeper_name = payload.storekeeper_name
    if payload.items is not None:
        grn.items.all().delete()
        for item in payload.items:
            GrnItems.objects.create(
                item_id=uuid.uuid4(),
                grn=grn,
                item_name=item.item_name,
                quantity=item.quantity,
                unit_measurement=item.unit_measurement,
                internal_code=item.internal_code,
                bags=getattr(item, "bags", None),
            )
    grn.save()
    grn.refresh_from_db()
    if payload.items is not None:
        _check_and_notify_negative_stock()
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
    _check_and_notify_negative_stock()
    return {"detail": "GRN deleted successfully."}


def _grn_to_detail(grn):
    return {
        "id": grn.id,
        "supplier_name": grn.supplier_name,
        "grn_no": str(grn.grn_no),
        "plate_no": grn.plate_no,
        "purchase_no": grn.purchase_no,
        "items": [
            {"item_name": item.item_name, "quantity": item.quantity}
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
    for item in payload.items:
        new_item = DNItems.objects.create(
            item_id=uuid.uuid4(),
            dn=dn,
            item_name=item.item_name,
            quantity=item.quantity,
            unit_measurement=item.unit_measurement,
            internal_code = item.internal_code,
            bags = item.bags
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
            {"item_name": i.item_name, "quantity": i.quantity}
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
    dn = get_object_or_404(DN, dn_no=dn_no)
    return _dn_to_detail(dn)


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
        dn.dn_items.all().delete()
        for item in payload.items:
            DNItems.objects.create(
                item_id=uuid.uuid4(),
                dn=dn,
                item_name=item.item_name,
                quantity=item.quantity,
                unit_measurement=item.unit_measurement,
                internal_code=getattr(item, "internal_code", None),
                bags=getattr(item, "bags", None),
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
        "items": [
            {"item_name": item.item_name, "quantity": item.quantity}
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
                            item_name=item.item_name,
                            quantity=item.quantity
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
def display_stock(request):
    grns = GrnItems.objects.all()
    dns = DNItems.objects.all()
    items = Items.objects.all()

    stock_list = []

    for item in items:
        # matching GRN and DN for this item
        grn_totals = GrnItems.objects.filter(
            internal_code=item.internal_code
        ).aggregate(
            quantity=Sum("quantity"),
            bags=Sum("bags")
        )

        dn_totals = DNItems.objects.filter(
            internal_code=item.internal_code
        ).aggregate(
            quantity=Sum("quantity"),
            bags=Sum("bags")
        )

        grn_qty = grn_totals["quantity"] or 0
        grn_bags = grn_totals["bags"] or 0

        dn_qty = dn_totals["quantity"] or 0
        dn_bags = dn_totals["bags"] or 0

        stock_quantity = 0
        stock_bags = 0
        item_name = item.item_name

        stock_quantity = grn_qty - dn_qty
        stock_bags = grn_bags - dn_bags

        stock_list.append({
            "item_name": item_name,
            "quantity": stock_quantity,
            "package": stock_bags,
            "hscode": item.hscode,
            "internal_code": item.internal_code,
        })

    return stock_list


@router.post("/orders", response=OrderDetailSchema)
def create_order(request, payload: OrderCreateSchema):
    # Prevent duplicate order numbers
    if Order.objects.filter(order_number=payload.order_number).exists():
        return JsonResponse(
            {"detail": "Order number already exists."},
            status=400,
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
    )

    created_items: list[OrderItem] = []
    for item in payload.items:
        new_item = OrderItem.objects.create(
            item_id=uuid.uuid4(),
            order=order,
            item_name=item.item_name,
            hs_code=item.hs_code,
            price=item.price,
            quantity=item.quantity,
            total_price=item.total_price,
            measurement=item.measurement,
        )
        created_items.append(new_item)

    return {
        "id": order.id,
        "order_number": order.order_number,
        "order_date": order.order_date,
        "buyer": order.buyer,
        "buyer_address": _get_customer_address(order.buyer),
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
        "status": order.status,
        "approved_by": order.approved_by.username if order.approved_by else None,
        "approval_date": order.approval_date.isoformat() if order.approval_date else None,
        "completed_by": order.completed_by.username if order.completed_by else None,
        "completed_date": order.completed_date.isoformat() if order.completed_date else None,
        "cancelled_by": order.cancelled_by.username if order.cancelled_by else None,
        "cancelled_date": order.cancelled_date.isoformat() if order.cancelled_date else None,
        "status_remark": order.status_remark,
        "items": [
            OrderItemSchema(
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                measurement=i.measurement,
            )
            for i in created_items
        ],
    }


@router.get("/orders", response=List[OrderDetailSchema])
def list_orders(request):
    orders = Order.objects.prefetch_related("items").all()
    result: list[OrderDetailSchema] = []
    for o in orders:
        result.append(
            OrderDetailSchema(
                id=o.id,
                order_number=o.order_number,
                order_date=o.order_date,
                buyer=o.buyer,
                buyer_address=_get_customer_address(o.buyer),
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
                status=o.status,
                approved_by=o.approved_by.username if o.approved_by else None,
                approval_date=o.approval_date.isoformat() if o.approval_date else None,
                completed_by=o.completed_by.username if o.completed_by else None,
                completed_date=o.completed_date.isoformat() if o.completed_date else None,
                cancelled_by=o.cancelled_by.username if o.cancelled_by else None,
                cancelled_date=o.cancelled_date.isoformat() if o.cancelled_date else None,
                status_remark=o.status_remark,
                items=[
                    OrderItemSchema(
                        item_name=i.item_name,
                        hs_code=i.hs_code,
                        price=float(i.price),
                        quantity=i.quantity,
                        total_price=float(i.total_price),
                        measurement=i.measurement,
                    )
                    for i in o.items.all()
                ],
            )
        )
    return result


@router.get("/orders/{order_number}", response=OrderDetailSchema)
def get_order_detail(request, order_number: str):
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
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
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
    order.save()

    if payload.items is not None:
        order.items.all().delete()
        for item in payload.items:
            OrderItem.objects.create(
                order=order,
                item_name=item.item_name,
                hs_code=item.hs_code,
                price=item.price,
                quantity=item.quantity,
                total_price=item.total_price,
                measurement=item.measurement,
            )

    if payload.items is not None:
        order.items.all().delete()
        for item in payload.items:
            OrderItem.objects.create(
                order=order,
                item_name=item.item_name,
                hs_code=item.hs_code,
                price=item.price,
                quantity=item.quantity,
                total_price=item.total_price,
                measurement=item.measurement,
            )

    return OrderDetailSchema(
        id=order.id,
        order_number=order.order_number,
        order_date=order.order_date,
        buyer=order.buyer,
        buyer_address=_get_customer_address(order.buyer),
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
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
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
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
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
                item_name=i.item_name,
                hs_code=i.hs_code,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
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
        payment_terms=payload.payment_terms,
        mode_of_transport=payload.mode_of_transport,
        freight=payload.freight,
        freight_price=payload.freight_price,
        insurance=payload.insurance,
        shipment_type=payload.shipment_type,
        status="pending",
    )

    created_items: list[PurchaseItem] = []
    for item in payload.items:
        new_item = PurchaseItem.objects.create(
            item_id=uuid.uuid4(),
            purchase=purchase,
            item_name=item.item_name,
            price=item.price,
            quantity=item.quantity,
            total_price=item.total_price,
            measurement=item.measurement,
        )
        created_items.append(new_item)

    return _purchase_to_detail_schema(purchase)


@router.get("/purchases/{purchase_number}", response=PurchaseDetailSchema)
def get_purchase_detail(request, purchase_number: str):
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related("items"),
        purchase_number__iexact=purchase_number.strip(),
    )
    return _purchase_to_detail_schema(purchase)


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
    return _purchase_to_detail_schema(purchase)


def _purchase_to_detail_schema(purchase):
    return PurchaseDetailSchema(
        id=purchase.id,
        purchase_number=purchase.purchase_number,
        order_date=purchase.order_date,
        buyer=purchase.buyer,
        buyer_address=_get_customer_address(purchase.buyer),
        proforma_ref_no=purchase.proforma_ref_no,
        status=purchase.status,
        approved_by=purchase.approved_by.username if purchase.approved_by else None,
        approval_date=purchase.approval_date.isoformat() if purchase.approval_date else None,
        completed_by=purchase.completed_by.username if purchase.completed_by else None,
        completed_date=purchase.completed_date.isoformat() if purchase.completed_date else None,
        cancelled_by=purchase.cancelled_by.username if purchase.cancelled_by else None,
        cancelled_date=purchase.cancelled_date.isoformat() if purchase.cancelled_date else None,
        status_remark=purchase.status_remark,
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
        payment_terms=purchase.payment_terms,
        mode_of_transport=purchase.mode_of_transport,
        freight=purchase.freight,
        freight_price=float(purchase.freight_price) if purchase.freight_price is not None else None,
        insurance=purchase.insurance,
        shipment_type=purchase.shipment_type,
        items=[
            PurchaseItemSchema(
                item_name=i.item_name,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
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
    purchase.payment_terms = payload.payment_terms
    purchase.mode_of_transport = payload.mode_of_transport
    purchase.freight = payload.freight
    purchase.freight_price = payload.freight_price
    purchase.insurance = payload.insurance
    purchase.shipment_type = payload.shipment_type
    purchase.save()

    purchase.items.all().delete()
    for item in payload.items:
        PurchaseItem.objects.create(
            item_id=uuid.uuid4(),
            purchase=purchase,
            item_name=item.item_name,
            price=item.price,
            quantity=item.quantity,
            total_price=item.total_price,
            measurement=item.measurement,
        )

    purchase.refresh_from_db()
    return _purchase_to_detail_schema(purchase)


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
    return _purchase_to_detail_schema(purchase)


@router.get("/purchases", response=List[PurchaseDetailSchema])
def list_purchases(request):
    purchases = Purchase.objects.prefetch_related("items").all()
    result: list[PurchaseDetailSchema] = []
    for p in purchases:
        result.append(_purchase_to_detail_schema(p))
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
        invoice_remark=payload.invoice_remark,
        packing_list_remark=payload.packing_list_remark,
        waybill_remark=payload.waybill_remark,
        bill_of_lading_remark=payload.bill_of_lading_remark,
        sr_no=payload.sr_no,
    )

    for item in payload.items:
        ShippingInvoiceItem.objects.create(
            id=uuid.uuid4(),
            invoice=invoice,
            item_name=item.item_name,
            price=item.price,
            quantity=item.quantity,
            total_price=item.total_price,
            measurement=item.measurement,
            bags=item.bags,
            net_weight=item.net_weight,
            gross_weight=item.gross_weight,
            grade=item.grade,
            brand=item.brand,
            country_of_origin=getattr(item, "country_of_origin", None),
        )

    return ShippingInvoiceSummarySchema(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        order_number=invoice.order.order_number,
        invoice_date=invoice.invoice_date,
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
        invoice_remark=invoice.invoice_remark,
        packing_list_remark=invoice.packing_list_remark,
        waybill_remark=invoice.waybill_remark,
        bill_of_lading_remark=invoice.bill_of_lading_remark,
        sr_no=invoice.sr_no,
        authorized_by=invoice.authorized_by,
        authorized_at=invoice.authorized_at.isoformat() if invoice.authorized_at else None,
        items=[
            ShippingInvoiceItemSchema(
                item_name=i.item_name,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                measurement=i.measurement,
                bags=i.bags,
                net_weight=i.net_weight,
                gross_weight=i.gross_weight,
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
    invoice.invoice_remark = payload.invoice_remark
    invoice.packing_list_remark = payload.packing_list_remark
    invoice.waybill_remark = payload.waybill_remark
    invoice.bill_of_lading_remark = payload.bill_of_lading_remark
    invoice.sr_no = payload.sr_no
    invoice.save()

    # Replace items
    invoice.items.all().delete()
    for item in payload.items:
        ShippingInvoiceItem.objects.create(
            id=uuid.uuid4(),
            invoice=invoice,
            item_name=item.item_name,
            price=item.price,
            quantity=item.quantity,
            total_price=item.total_price,
            measurement=item.measurement,
            bags=item.bags,
            net_weight=item.net_weight,
            gross_weight=item.gross_weight,
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
        invoice_remark=invoice.invoice_remark,
        packing_list_remark=invoice.packing_list_remark,
        waybill_remark=invoice.waybill_remark,
        bill_of_lading_remark=invoice.bill_of_lading_remark,
        sr_no=invoice.sr_no,
        authorized_by=invoice.authorized_by,
        authorized_at=invoice.authorized_at.isoformat() if invoice.authorized_at else None,
        items=[
            ShippingInvoiceItemSchema(
                item_name=i.item_name,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                measurement=i.measurement,
                bags=i.bags,
                net_weight=i.net_weight,
                gross_weight=i.gross_weight,
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
        invoice_remark=invoice.invoice_remark,
        packing_list_remark=invoice.packing_list_remark,
        waybill_remark=invoice.waybill_remark,
        bill_of_lading_remark=invoice.bill_of_lading_remark,
        sr_no=invoice.sr_no,
        authorized_by=invoice.authorized_by,
        authorized_at=invoice.authorized_at.isoformat() if invoice.authorized_at else None,
        items=[
            ShippingInvoiceItemSchema(
                item_name=i.item_name,
                price=float(i.price),
                quantity=i.quantity,
                total_price=float(i.total_price),
                measurement=i.measurement,
                bags=i.bags,
                net_weight=i.net_weight,
                gross_weight=i.gross_weight,
                grade=i.grade,
                brand=i.brand,
                country_of_origin=i.country_of_origin,
            )
            for i in invoice.items.all()
        ],
    )

