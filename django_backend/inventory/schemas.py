from ninja import Schema
from typing import List, Optional
import uuid
from datetime import date as datetime_date

# Keep legacy `date` name for existing schema annotations in this file.
date = datetime_date

# Item schema sent from React
class GrnItemCreateSchema(Schema):
    item_id: Optional[uuid.UUID] = None
    code: Optional[str] = None
    item_name: str
    quantity: int
    unit_measurement: str
    bags: Optional[float] = None
    internal_code: Optional[str] = None
   

# Main GRN creation schema
class GrnCreateSchema(Schema):
    supplier_name: str
    grn_no: str

    received_from: str
    truck_no: str

    # Either purchase_id or purchase_no can be provided; purchase_id is linked to Purchase -> purchase_number
    purchase_no: str | None = None

    total_quantity: int | None = None
    store_name: str = ""
    store_keeper: str = ""

    date: datetime_date
    ECD_no: str = ""
    transporter_name: str = ""
    items: List[GrnItemCreateSchema]

# Response schema
class GrnItemSchema(Schema):
    grn_no: int | None = None
    code: Optional[str] = None
    item_name: str
    quantity: int
    unit_measurement: Optional[str] = None
    internal_code: Optional[str] = None
    bags: Optional[float] = None


class GrnDetailSchema(Schema):
    id: uuid.UUID
    supplier_name: str
    grn_no: str

    received_from: str | None = None
    truck_no: str | None = None
    total_quantity: int | None = None
    store_name: str | None = None
    store_keeper: str | None = None

    purchase_no: str | None = None

    date: Optional[str] = None
    ECD_no: Optional[str] = None
    transporter_name: Optional[str] = None
    items: List[GrnItemSchema]


class GrnUpdateSchema(Schema):
    supplier_name: str | None = None
    date: Optional[datetime_date] = None

    received_from: str | None = None
    truck_no: str | None = None

    purchase_no: str | None = None

    total_quantity: int | None = None
    store_name: str | None = None
    store_keeper: str | None = None

    ECD_no: str | None = None
    transporter_name: str | None = None
    items: List[GrnItemCreateSchema] | None = None


class GRNListSchema(Schema):
    supplier_name: str
    grn_no: int

    received_from: str | None = None
    truck_no: str | None = None
    total_quantity: int | None = None
    store_name: str | None = None
    store_keeper: str | None = None

    purchase_no: str | None = None

    items: List[GrnItemSchema]

# DN Schemas
class DnItemCreateSchema(Schema):
    item_id: Optional[uuid.UUID] = None
    code: Optional[str] = None
    item_name: str
    quantity: int
    unit_measurement: str
    internal_code: Optional[str] = None
    bags: Optional[float] = None

# Main DN creation schema
class DnCreateSchema(Schema):
    customer_name: str
    dn_no: str
    plate_no: str
    sales_no: str
    date: datetime_date
    ECD_no: str
    invoice_no: str
    gatepass_no: str
    despathcher_name: str
    receiver_name: str
    authorized_by: str
    items: List[DnItemCreateSchema]

# Response schema
class DnItemSchema(Schema):
    code: Optional[str] = None
    item_name: str
    quantity: int
    unit_measurement: Optional[str] = None
    internal_code: Optional[str] = None
    bags: Optional[float] = None


class OverUnderItemSchema(Schema):
    item_name: str
    invoiced: int
    delivered: int
    variance: int


class DnDetailSchema(Schema):
    id: uuid.UUID | None = None
    customer_name: str
    dn_no: str
    sales_no: str
    plate_no: Optional[str] = None
    date: Optional[str] = None
    ECD_no: Optional[str] = None
    invoice_no: Optional[str] = None
    gatepass_no: Optional[str] = None
    despathcher_name: Optional[str] = None
    receiver_name: Optional[str] = None
    authorized_by: Optional[str] = None
    items: Optional[List[DnItemSchema]] = []
    over_items: Optional[List[OverUnderItemSchema]] = None
    under_items: Optional[List[OverUnderItemSchema]] = None


class DnUpdateSchema(Schema):
    customer_name: str | None = None
    date: Optional[datetime_date] = None
    plate_no: str | None = None
    sales_no: str | None = None
    ECD_no: str | None = None
    invoice_no: str | None = None
    gatepass_no: str | None = None
    despathcher_name: str | None = None
    receiver_name: str | None = None
    authorized_by: str | None = None
    items: List[DnItemCreateSchema] | None = None


class ItemCreateSchema(Schema):
    item_name: str
    hscode: str
    internal_code: str


class ItemUpdateSchema(Schema):
    item_name: str | None = None
    hscode: str | None = None
    internal_code: str | None = None


class ItemSchema(Schema):
    item_id: uuid.UUID | None = None
    item_name: str
    hscode: str
    internal_code: str | None = None
    
class StockSchema(Schema):
    item_id: Optional[uuid.UUID] = None
    item_name: str
    code: Optional[str] = None
    internal_code: Optional[str]
    quantity: Optional[float]
    package: Optional[float]
    grn_nos: Optional[List[str]] = None
    dn_nos: Optional[List[str]] = None


class GitBaseSchema(Schema):
    purchase_no: str
    item_name: str
    code: Optional[str] = None
    purchase_quantity: float
    received_quantity: float
    variance_quantity: float
    variance_type: str


class GitCreateSchema(GitBaseSchema):
    grn_no: str


class GitUpdateSchema(Schema):
    purchase_no: Optional[str] = None
    item_name: Optional[str] = None
    code: Optional[str] = None
    purchase_quantity: Optional[float] = None
    received_quantity: Optional[float] = None
    variance_quantity: Optional[float] = None
    variance_type: Optional[str] = None


class GitSchema(GitBaseSchema):
    id: uuid.UUID
    grn_no: str


class OrderItemCreateSchema(Schema):
    item_name: str
    hs_code: str
    price: float
    quantity: float
    total_price: float
    measurement: str


class OrderCreateSchema(Schema):
    order_number: str
    proforma_ref_no: str
    buyer: str
    add_consignee: Optional[str]
    order_date: date
    shipper: str
    notify_party: Optional[str]
    add_notify_party: Optional[str]
    country_of_origin: str
    final_destination: str
    port_of_loading: str
    port_of_discharge: str
    measurement_type: Optional[str] = None
    payment_terms: str
    mode_of_transport: str
    freight: Optional[str] = None
    freight_price: Optional[float]
    shipment_type: str
    items: List[OrderItemCreateSchema]


class OrderItemSchema(Schema):
    order_no: str | None = None
    item_name: str
    hs_code: str
    price: float
    quantity: float
    total_price: float
    before_vat: float
    measurement: str


class OrderDetailSchema(Schema):
    id: uuid.UUID
    order_number: str
    order_date: date
    buyer: str
    buyer_address: Optional[str] = None
    buyer_tin_number: Optional[str] = None
    shipper: str
    shipper_address: Optional[str] = None
    proforma_ref_no: str
    add_consignee: Optional[str]
    notify_party: Optional[str]
    add_notify_party: Optional[str]
    country_of_origin: str
    final_destination: str
    port_of_loading: str
    port_of_discharge: str
    measurement_type: Optional[str] = None
    payment_terms: str
    mode_of_transport: str
    freight: Optional[str] = None
    freight_price: Optional[float]
    shipment_type: str
    PR_before_VAT: float
    total_quantity: float
    remaining: float
    status: Optional[str] = None
    approved_by: Optional[str] = None
    approval_date: Optional[str] = None
    completed_by: Optional[str] = None
    completed_date: Optional[str] = None
    cancelled_by: Optional[str] = None
    cancelled_date: Optional[str] = None
    status_remark: Optional[str] = None
    items: List[OrderItemSchema]


class OrderUpdateSchema(Schema):
    proforma_ref_no: str
    buyer: str
    add_consignee: Optional[str]
    order_date: date
    shipper: str
    notify_party: Optional[str]
    add_notify_party: Optional[str]
    country_of_origin: str
    final_destination: str
    port_of_loading: str
    port_of_discharge: str
    measurement_type: Optional[str] = None
    payment_terms: str
    mode_of_transport: str
    freight: Optional[str] = None
    freight_price: Optional[float]
    shipment_type: str
    items: Optional[List[OrderItemCreateSchema]] = None

class OrderApproveSchema(Schema):
    approved_by_id: int


class OrderStatusUpdateSchema(Schema):
    status: str  # "completed" or "cancelled"
    user_id: int  # completed_by_id or cancelled_by_id
    remark: Optional[str] = None


class PurchaseItemCreateSchema(Schema):
    item_id: uuid.UUID | None = None
    item_name: str
    price: float
    quantity: int
    total_price: float
    measurement: str
    # If omitted, server sets remaining = quantity
    remaining: Optional[int] = None
    # Line before VAT; if omitted, server sets = total_price
    before_vat: Optional[float] = None
    hscode: Optional[str] = None


class PurchaseCreateSchema(Schema):
    purchase_number: str
    proforma_ref_no: str
    buyer: str
    add_consignee: Optional[str]
    order_date: date
    shipper: str
    notify_party: Optional[str]
    add_notify_party: Optional[str]
    country_of_origin: str
    final_destination: str
    conditions: Optional[str]
    port_of_loading: str
    port_of_discharge: str
    measurement_type: Optional[str] = None
    # Updated naming to match frontend: payment_type (legacy: payment_terms)
    payment_type: str | None = None
    payment_terms: str | None = None
    mode_of_transport: str
    freight: Optional[str] = None
    freight_price: Optional[float]
    insurance: Optional[str]
    shipment_type: str
    items: List[PurchaseItemCreateSchema]


class PurchaseItemSchema(Schema):
    item_id: uuid.UUID | None = None
    purchase_number: str
    item_name: str
    price: float
    quantity: int
    remaining: int
    total_price: float
    before_vat: float
    hscode: Optional[str] = None
    measurement: str


class PurchaseDetailSchema(Schema):
    id: uuid.UUID
    purchase_number: str
    order_date: date
    buyer: str
    buyer_address: Optional[str] = None
    proforma_ref_no: str
    status: Optional[str] = None
    approved_by: Optional[str] = None
    approval_date: Optional[str] = None
    completed_by: Optional[str] = None
    completed_date: Optional[str] = None
    cancelled_by: Optional[str] = None
    cancelled_date: Optional[str] = None
    status_remark: Optional[str] = None
    add_consignee: Optional[str] = None
    shipper: Optional[str] = None
    shipper_address: Optional[str] = None
    notify_party: Optional[str] = None
    add_notify_party: Optional[str] = None
    country_of_origin: Optional[str] = None
    final_destination: Optional[str] = None
    conditions: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    measurement_type: Optional[str] = None
    payment_type: Optional[str] = None
    # Kept for backward compatibility (older frontend)
    payment_terms: Optional[str] = None
    mode_of_transport: Optional[str] = None
    freight: Optional[str] = None
    freight_price: Optional[float] = None
    insurance: Optional[str] = None
    shipment_type: Optional[str] = None
    before_vat: float
    total_quantity: int
    remaining: int
    items: List[PurchaseItemSchema]


class PurchaseApproveSchema(Schema):
    approved_by_id: int


class PurchaseStatusUpdateSchema(Schema):
    status: str  # "completed" or "cancelled"
    user_id: int
    remark: Optional[str] = None


class PurchaseUpdateSchema(Schema):
    proforma_ref_no: str
    buyer: str
    add_consignee: Optional[str]
    order_date: date
    shipper: str
    notify_party: Optional[str]
    add_notify_party: Optional[str]
    country_of_origin: str
    final_destination: str
    conditions: Optional[str]
    port_of_loading: str
    port_of_discharge: str
    measurement_type: Optional[str] = None
    payment_type: str | None = None
    payment_terms: str | None = None
    mode_of_transport: str
    freight: Optional[str] = None
    freight_price: Optional[float]
    insurance: Optional[str]
    shipment_type: str
    items: List[PurchaseItemCreateSchema]


class ShippingInvoiceItemCreateSchema(Schema):
    item_id: uuid.UUID | None = None
    item_name: str
    price: float
    quantity: float
    total_price: float
    measurement: str
    bags: Optional[float]
    net_weight: Optional[float]
    gross_weight: Optional[float]
    hscode: Optional[str] = None
    grade: Optional[str] = None
    brand: Optional[str] = None
    country_of_origin: Optional[str] = None


class ShippingInvoiceCreateSchema(Schema):
    order_number: str
    invoice_number: str
    invoice_date: date
    waybill_number: Optional[str]
    customer_order_number: str
    container_number: Optional[str]
    vessel: Optional[str]
    freight_amount: Optional[float]
    reference_no: Optional[str]
    total_bags: Optional[float]
    total_net_weight: Optional[float]
    total_gross_weight: Optional[float]
    final_price: Optional[float]
    invoice_remark: Optional[str]
    packing_list_remark: Optional[str]
    waybill_remark: Optional[str]
    bill_of_lading_remark: Optional[str]
    bank: Optional[str] = None
    sr_no: Optional[int] = None
    items: List[ShippingInvoiceItemCreateSchema]


class ShippingInvoiceUpdateSchema(Schema):
    invoice_date: date
    waybill_number: Optional[str]
    customer_order_number: str
    container_number: Optional[str]
    vessel: Optional[str]
    freight_amount: Optional[float]
    reference_no: Optional[str]
    total_bags: Optional[float]
    total_net_weight: Optional[float]
    total_gross_weight: Optional[float]
    final_price: Optional[float]
    invoice_remark: Optional[str]
    packing_list_remark: Optional[str]
    waybill_remark: Optional[str]
    bill_of_lading_remark: Optional[str]
    bank: Optional[str] = None
    sr_no: Optional[int] = None
    items: List[ShippingInvoiceItemCreateSchema]


class ShippingInvoiceSummarySchema(Schema):
    id: uuid.UUID
    invoice_number: str
    order_number: str
    invoice_date: date
    reference_no: Optional[str] = None
    final_price: Optional[float] = None
    authorized_by: Optional[str] = None
    authorized_at: Optional[str] = None


class ShippingInvoiceItemSchema(Schema):
    item_id: uuid.UUID | None = None
    item_name: str
    price: float
    quantity: float
    total_price: float
    measurement: str
    bags: Optional[float]
    net_weight: Optional[float]
    gross_weight: Optional[float]
    hscode: Optional[str] = None
    grade: Optional[str] = None
    brand: Optional[str] = None
    country_of_origin: Optional[str] = None


class ShippingInvoiceDetailSchema(Schema):
    id: uuid.UUID
    order_number: str
    invoice_number: str
    invoice_date: date
    waybill_number: Optional[str]
    customer_order_number: str
    container_number: Optional[str]
    vessel: Optional[str]
    freight_amount: Optional[float]
    reference_no: Optional[str]
    total_bags: Optional[float]
    total_net_weight: Optional[float]
    total_gross_weight: Optional[float]
    final_price: Optional[float]
    invoice_remark: Optional[str]
    packing_list_remark: Optional[str]
    waybill_remark: Optional[str]
    bill_of_lading_remark: Optional[str]
    bank: Optional[str] = None
    sr_no: Optional[int] = None
    authorized_by: Optional[str] = None
    authorized_at: Optional[str] = None
    items: List[ShippingInvoiceItemSchema]
