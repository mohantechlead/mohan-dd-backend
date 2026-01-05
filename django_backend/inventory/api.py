from ninja import Router
from typing import List
from django.shortcuts import get_object_or_404
from .models import GRN, GrnItems, DN, DNItems
from .schemas import GrnCreateSchema, GrnDetailSchema, GRNListSchema, GrnItemSchema
from .schemas import DnCreateSchema, DnDetailSchema, DnItemSchema
from .schemas import ItemCreateSchema, ItemSchema, StockSchema
from .models import Items, Stock
import uuid
from django.http import JsonResponse
import traceback

router = Router()


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
                GrnDetailSchema(
                    supplier_name=grn.supplier_name,
                    grn_no=grn.grn_no,
                    plate_no=grn.plate_no,
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
    return get_object_or_404(GRN, grn_no=grn_no)


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
        receiver_phone = payload.receiver_phone,
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
            internal_code = item.internal_code
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

@router.get("/dn", response=List[DnDetailSchema])
def list_DN(request):
    try:
        dns = DN.objects.prefetch_related("dn_items").all()
        result = []
        for dn in dns:
            result.append(
                DnDetailSchema(
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
    return items

@router.get("/stock", response=list[StockSchema])
def display_stock(request):
    grns = GrnItems.objects.all()
    dns = DNItems.objects.all()
    items = Items.objects.all()

    stock_list = []

    for item in items:
        # matching GRN and DN for this item
        grn = grns.filter(internal_code=item.internal_code).first()
        dn = dns.filter(internal_code=item.internal_code).first()

        stock_quantity = 0
        stock_bags = 0
        item_name = item.item_name

        if grn and dn:
            stock_quantity = grn.quantity - dn.quantity
            stock_bags = grn.bags - dn.bags

        elif grn:
            stock_quantity = grn.quantity
            stock_bags = grn.bags

        elif dn:
            stock_quantity = -dn.quantity
            stock_bags = -dn.bags

        stock_list.append({
            "item_name": item_name,
            "quantity": stock_quantity,
            "package": stock_bags,
            "hscode": item.hscode,
            "internal_code": item.internal_code,
            "unit_measurement": grn.unit_measurement if grn else (dn.unit_measurement if dn else ""),
        })

    return stock_list
  

    
