from ninja import Schema
from typing import List, Optional
import uuid
from datetime import date

# Item schema sent from React
class GrnItemCreateSchema(Schema):
    item_name: str
    quantity: int
    unit_measurement: str
    bags: str
    internal_code: str
   

# Main GRN creation schema
class GrnCreateSchema(Schema):
    supplier_name: str
    grn_no: str
    plate_no: str
    purchase_no: str
    date: date
    ECD_no: str
    transporter_name: str
    storekeeper_name: str 
    items: List[GrnItemCreateSchema]

# Response schema
class GrnItemSchema(Schema):
    item_name: str
    quantity: int
    

class GrnDetailSchema(Schema):
    id: uuid.UUID
    supplier_name: str
    grn_no: str
    plate_no: str
    purchase_no: str
    items: List[GrnItemSchema]

class GRNListSchema(Schema):
    supplier_name: str
    grn_no: int
    purchase_no: str
    items: List[GrnItemSchema]

# DN Schemas
class DnItemCreateSchema(Schema):
    item_name: str
    quantity: int
    unit_measurement: str
    internal_code: str
    bags: float

# Main DN creation schema
class DnCreateSchema(Schema):
    customer_name: str
    dn_no: str
    plate_no: str
    sales_no: str
    date: date
    ECD_no: str
    invoice_no: str
    gatepass_no: str
    despathcher_name: str
    receiver_name: str
    authorized_by: str
    items: List[DnItemCreateSchema]

# Response schema
class DnItemSchema(Schema):
    item_name: str
    quantity: int
    
class DnDetailSchema(Schema):
    customer_name: str
    dn_no: str
    sales_no: str
    items: Optional[List[DnItemSchema]] = []

class ItemCreateSchema(Schema):
    item_name: str
    hscode: str
    internal_code: str

class ItemSchema(Schema):
    item_name: str
    hscode: str
    internal_code: str
    
class StockSchema(Schema):
    item_name: str
    internal_code: Optional[str]
    quantity: Optional[float]
    package: Optional[float]


class OrderItemCreateSchema(Schema):
    item_name: str
    hs_code: str
    price: float
    quantity: int
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
    measurement_type: str
    payment_terms: str
    mode_of_transport: str
    freight: str
    freight_price: Optional[float]
    shipment_type: str
    items: List[OrderItemCreateSchema]


class OrderItemSchema(Schema):
    item_name: str
    hs_code: str
    price: float
    quantity: int
    total_price: float
    measurement: str


class OrderDetailSchema(Schema):
    id: uuid.UUID
    order_number: str
    order_date: date
    buyer: str
    proforma_ref_no: str
    add_consignee: Optional[str]
    shipper: str
    notify_party: Optional[str]
    add_notify_party: Optional[str]
    country_of_origin: str
    final_destination: str
    port_of_loading: str
    port_of_discharge: str
    measurement_type: str
    payment_terms: str
    mode_of_transport: str
    freight: str
    freight_price: Optional[float]
    shipment_type: str
    status: str
    approved_by: Optional[str] = None
    items: List[OrderItemSchema]


class OrderApproveSchema(Schema):
    approved_by_id: int


class PurchaseItemCreateSchema(Schema):
    item_name: str
    price: float
    quantity: int
    total_price: float
    measurement: str


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
    measurement_type: str
    payment_terms: str
    mode_of_transport: str
    freight: str
    freight_price: Optional[float]
    insurance: Optional[str]
    shipment_type: str
    items: List[PurchaseItemCreateSchema]


class PurchaseItemSchema(Schema):
    item_name: str
    price: float
    quantity: int
    total_price: float
    measurement: str


class PurchaseDetailSchema(Schema):
    id: uuid.UUID
    purchase_number: str
    order_date: date
    buyer: str
    proforma_ref_no: str
    status: str
    items: List[PurchaseItemSchema]


class ShippingInvoiceItemCreateSchema(Schema):
    item_name: str
    price: float
    quantity: int
    total_price: float
    measurement: str
    bags: Optional[float]
    net_weight: Optional[float]
    gross_weight: Optional[float]


class ShippingInvoiceCreateSchema(Schema):
    order_number: str
    invoice_number: str
    invoice_date: date
    waybill_number: Optional[str]
    customer_order_number: str
    container_number: Optional[str]
    vessel: Optional[str]
    invoice_remark: Optional[str]
    packing_list_remark: Optional[str]
    waybill_remark: Optional[str]
    bill_of_lading_remark: Optional[str]
    items: List[ShippingInvoiceItemCreateSchema]


class ShippingInvoiceSummarySchema(Schema):
    id: uuid.UUID
    invoice_number: str
    order_number: str
    invoice_date: date


class ShippingInvoiceItemSchema(Schema):
    item_name: str
    price: float
    quantity: int
    total_price: float
    measurement: str
    bags: Optional[float]
    net_weight: Optional[float]
    gross_weight: Optional[float]


class ShippingInvoiceDetailSchema(Schema):
    id: uuid.UUID
    order_number: str
    invoice_number: str
    invoice_date: date
    waybill_number: Optional[str]
    customer_order_number: str
    container_number: Optional[str]
    vessel: Optional[str]
    invoice_remark: Optional[str]
    packing_list_remark: Optional[str]
    waybill_remark: Optional[str]
    bill_of_lading_remark: Optional[str]
    items: List[ShippingInvoiceItemSchema]
