from ninja import Router
from typing import List, Optional
from django.shortcuts import get_object_or_404
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
    role = getattr(user, "role", "viewer")
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


@router.post("/grn", response=GrnDetailSchema)
def create_grn(request, payload: GrnCreateSchema):

    # Create GRN
    grn = GRN.objects.create(
        id=uuid.uuid4(),
        supplier_name=payload.supplier_name,
        grn_no=payload.grn_no,
        plate_no=payload.plate_no,
        purchase_no=payload.purchase_no,
        date = payload.date,
        ECD_no = payload.ECD_no,
        transporter_name = payload.transporter_name,
        storekeeper_name = payload.storekeeper_name,
    )

    # Create Items
    created_items = []
    for item in payload.items:
        new_item = GrnItems.objects.create(
            item_id=uuid.uuid4(),
            grn=grn,
            item_name=item.item_name,
            quantity=item.quantity,
            unit_measurement=item.unit_measurement,
            internal_code = item.internal_code,
            bags = item.bags
        )
        created_items.append(new_item)

    # Return structured response
    return {
        "id": grn.id,
        "supplier_name": grn.supplier_name,
        "grn_no": grn.grn_no,
        "plate_no": grn.plate_no,
        "purchase_no": grn.purchase_no,
        "items": created_items
    }

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
    return _grn_to_detail(grn)


@router.delete("/grn/{grn_no}", auth=JWTAuth())
def delete_GRN(request, grn_no: str):
    err = _require_admin(request)
    if err:
        return err
    grn = get_object_or_404(GRN, grn_no=int(grn_no) if grn_no.isdigit() else grn_no)
    grn.delete()
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

    # Return structured response
    return {
        "id": dn.id,
        "customer_name": dn.customer_name,
        "dn_no": dn.dn_no,
        "plate_no": dn.plate_no,
        "sales_no": dn.sales_no,
        "items": created_items
    }


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
    return _dn_to_detail(dn)


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
            )
            for i in invoice.items.all()
        ],
    )

    
