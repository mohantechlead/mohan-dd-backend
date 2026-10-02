"""AI context/metadata layer: entities, safe fields, relationships, terminology.

Derived from the actual codebase (models + API), not assumptions.
Sensitive/PII fields are deliberately absent here so the planner can never
request them.
"""

ENTITIES = {
    "order": {
        "label": "Sales order (proforma)",
        "description": "Customer sales order identified by order_number like M1001. Status defaults to pending.",
        "safe_fields": [
            "order_number", "order_date", "buyer", "shipper",
            "final_destination", "port_of_loading", "port_of_discharge",
            "payment_terms", "mode_of_transport", "shipment_type",
            "total_quantity", "PR_before_VAT", "remaining", "status",
        ],
        "date_fields": ["order_date"],
        "numeric_fields": ["total_quantity", "PR_before_VAT", "remaining"],
        "status_values": ["pending", "approved", "completed", "cancelled"],
        "keywords": ["order", "orders", "sales order", "sale", "sales", "proforma", "buyer", "customer order"],
    },
    "purchase": {
        "label": "Purchase order",
        "description": "Purchase from a supplier identified by purchase_number like MPDDFZE001. Status defaults to pending.",
        "safe_fields": [
            "purchase_number", "order_date", "shipper", "buyer",
            "port_of_loading", "port_of_discharge",
            "total_quantity", "before_vat", "remaining", "status",
        ],
        "date_fields": ["order_date"],
        "numeric_fields": ["total_quantity", "before_vat", "remaining"],
        "status_values": ["pending", "approved", "completed", "cancelled"],
        "keywords": ["purchase", "purchases", "po", "supplier order", "buy order"],
    },
    "shipping_invoice": {
        "label": "Shipping invoice",
        "description": "Invoice linked to one sales order. Authorized when authorized_by/at are set.",
        "safe_fields": [
            "invoice_number", "order_number", "invoice_date",
            "final_price", "sr_no", "authorized_by", "authorized_at",
        ],
        "date_fields": ["invoice_date"],
        "numeric_fields": ["final_price", "sr_no"],
        "status_values": [],
        "keywords": ["invoice", "invoices", "shipping invoice", "shipped", "shipment"],
    },
    "dn": {
        "label": "Delivery note (dispatch)",
        "description": "Goods dispatched to a customer. sales_no links to Order.order_number; invoice_no links to ShippingInvoice.invoice_number. is_last marks the final delivery for its invoice.",
        "safe_fields": [
            "dn_no", "sales_no", "customer_name", "date",
            "invoice_no", "is_last", "item_count", "total_quantity",
        ],
        "date_fields": ["date"],
        "numeric_fields": ["total_quantity", "item_count"],
        "status_values": [],
        "keywords": ["deliver", "deliveries", "delivery", "dn", "dispatch", "dispatched"],
    },
    "grn": {
        "label": "Goods received note (receipt)",
        "description": "Goods received from a supplier. purchase_no links to Purchase.purchase_number as text. is_last marks the final receipt for its purchase.",
        "safe_fields": [
            "grn_no", "supplier_name", "purchase_no", "date",
            "total_quantity", "is_last", "item_count",
        ],
        "date_fields": ["date"],
        "numeric_fields": ["total_quantity", "item_count"],
        "status_values": [],
        "keywords": ["grn", "receipt", "received", "goods received"],
    },
    "git": {
        "label": "Goods-in-transit variance",
        "description": "Running variance per purchase/item between ordered and received quantities. variance_type is increased or decreased.",
        "safe_fields": [
            "purchase_no", "grn_no", "item_name",
            "purchase_quantity", "received_quantity",
            "variance_quantity", "variance_type",
        ],
        "date_fields": [],
        "numeric_fields": ["purchase_quantity", "received_quantity", "variance_quantity"],
        "status_values": [],
        "keywords": ["git", "variance", "over receipt", "under receipt",
                     "over-deliver", "overdeliver", "over deliver", "over delivered",
                     "over delivery", "under-deliver", "underdeliver",
                     "under deliver", "under delivered", "under delivery", "short"],
    },
    "item": {
        "label": "Catalog item",
        "description": "Master item list referenced by GRN/DN lines.",
        "safe_fields": ["item_name", "hscode", "internal_code"],
        "date_fields": [],
        "numeric_fields": [],
        "status_values": [],
        "keywords": ["item", "items", "product", "products", "catalog"],
    },
    "stock": {
        "label": "Derived stock (GRN minus DN by code)",
        "description": "Computed from GRN lines minus DN lines grouped by business code. Not a stored balance.",
        "safe_fields": ["code", "item_name", "quantity", "package"],
        "date_fields": [],
        "numeric_fields": ["quantity", "package"],
        "status_values": [],
        "keywords": ["stock", "inventory", "balance", "on hand", "remaining stock"],
    },
    "vendor_payment": {
        "label": "Payment to supplier for a purchase",
        "description": "Installments linked to Purchase.purchase_number. Status defaults to pending.",
        "safe_fields": [
            "payment_number", "purchase_number", "supplier_name", "payment_date",
            "amount", "payment_type", "status",
        ],
        "date_fields": ["payment_date"],
        "numeric_fields": ["amount"],
        "status_values": ["pending", "approved", "completed", "cancelled"],
        "keywords": ["vendor payment", "supplier payment", "paid to supplier",
                     "vendor"],
    },
    "received_payment": {
        "label": "Payment received from a customer for an order",
        "description": "Installments linked to Order.order_number. Status defaults to pending.",
        "safe_fields": [
            "payment_number", "order_number", "customer_name", "payment_date",
            "amount", "payment_type", "status",
        ],
        "date_fields": ["payment_date"],
        "numeric_fields": ["amount"],
        "status_values": ["pending", "approved", "completed", "cancelled"],
        "keywords": ["received payment", "customer payment", "payment received",
                     "collection", "receive", "collected"],
    },
    "expense_payment": {
        "label": "General expense payment",
        "description": "Overhead expenses not tied to a specific order or purchase.",
        "safe_fields": [
            "expense_number", "expense_date", "payee",
            "category", "amount", "status",
        ],
        "date_fields": ["expense_date"],
        "numeric_fields": ["amount"],
        "status_values": ["pending", "approved", "completed", "cancelled"],
        "keywords": ["expense", "expenses", "overhead", "cost"],
    },
    "partner": {
        "label": "Customer or supplier master",
        "description": "Business partners. Only name and type are exposed to the AI; contact/PII fields are excluded.",
        "safe_fields": ["name", "partner_type"],
        "date_fields": [],
        "numeric_fields": [],
        "status_values": [],
        "keywords": ["customer", "customers", "supplier", "suppliers", "partner", "partners", "buyer", "buyers"],
    },
    "payments": {
        "label": "All payments together",
        "description": "Customer payments, supplier payments, and costs combined. Used when the question does not name one kind.",
        "safe_fields": [],
        "date_fields": [],
        "numeric_fields": [],
        "status_values": [],
        "keywords": ["payments", "payment", "money", "paid", "pay"],
    },
    "overview": {
        "label": "Whole-business brief",
        "description": "Cross-entity executive summary: sales, buying, deliveries, receipts, invoices, stock, money, and variances. Never a single table.",
        "safe_fields": [],
        "date_fields": [],
        "numeric_fields": [],
        "status_values": [],
        "keywords": ["overview", "dashboard", "whole thing", "entire business",
                     "deep analytics", "deep analysis", "summary of everything",
                     "how is the business", "make decisions", "make a decision",
                     "help me decide", "decide", "decision", "advice",
                     "full picture", "everything"],
    },
}

RELATIONSHIPS = [
    "Order.order_number -> ShippingInvoice.order -> DN.sales_no + DN.invoice_no",
    "Purchase.purchase_number -> GRN.purchase_no (text match) -> GIT.purchase_no",
    "Items.item_id/item_name -> GrnItems/DNItems catalog_item_id (logical link)",
    "Order.order_number -> ReceivedPayment.order; Purchase.purchase_number -> VendorPayment.purchase",
    "Stock is derived: sum(GrnItems.quantity by code) minus sum(DNItems.quantity by code)",
]

BUSINESS_RULES = [
    "Order/Purchase status defaults to pending; only admins see status detail in list views.",
    "DN.invoice_no, when set, must belong to the same sales order or creation is rejected.",
    "Only one final (is_last=true) GRN per purchase and one final DN per invoice.",
    "Over/under delivery and receipt emails fire only when the triggering DN/GRN is marked is_last.",
    "GIT rows are running variances maintained per purchase/item/code; wipe-off zeroes a variance.",
    "ShippingInvoice authorization sets authorized_by/at; sr_no is an auto-increment integer.",
]

STATUS_MEANINGS = {
    "pending": "Created but not yet approved.",
    "approved": "Approved by an authorized user.",
    "completed": "Fully processed/closed.",
    "cancelled": "Voided; excluded from active-work questions unless asked.",
}

# Plain-language nouns so answers never say "3 dns".
ENTITY_NOUNS = {
    "order": ("order", "orders"),
    "purchase": ("purchase", "purchases"),
    "shipping_invoice": ("shipping invoice", "shipping invoices"),
    "dn": ("delivery note", "delivery notes"),
    "grn": ("goods received note", "goods received notes"),
    "git": ("variance record", "variance records"),
    "item": ("item", "items"),
    "stock": ("stock line", "stock lines"),
    "vendor_payment": ("supplier payment", "supplier payments"),
    "received_payment": ("customer payment", "customer payments"),
    "expense_payment": ("expense", "expenses"),
    "partner": ("partner", "partners"),
    "payments": ("payment", "payments"),
    "overview": ("business brief", "business briefs"),
}

EXAMPLE_QUESTIONS = {
    "order": ["How many orders this month?", "Which customers order most?",
              "Predict next month orders", "Help me decide on sales orders"],
    "purchase": ["How many purchases are pending?", "Monthly buying trend",
                 "Help me decide on purchases"],
    "shipping_invoice": ["Show me invoice A9001", "Which invoices wait for authorization?"],
    "dn": ["Show me deliveries for order M9001", "Deliveries by month"],
    "grn": ["Show me receipts for MPDDFZE901", "Which receipts are still open?"],
    "git": ["By how much was it over delivered?", "Show me under-deliveries"],
    "stock": ["How much stock do we have?", "Which lines are below zero?"],
    "item": ["How many items are in the catalog?", "Top products by quantity"],
    "vendor_payment": ["How much did we pay suppliers?", "Which supplier payments wait?"],
    "received_payment": ["How much came in from customers?", "Which customer payments wait?"],
    "expense_payment": ["What did we spend this month?", "Costs by category"],
    "partner": ["How many customers do we have?", "List our suppliers"],
    "payments": ["How much came in vs went out?", "Which payments wait?",
                 "Tell me about payments in detail"],
    "overview": ["Give me the whole business picture", "Anything critical right now?",
                 "Predict next month orders"],
}

# Entities whose monthly counts can be projected forward. Pure counts only.
FORECASTABLE_ENTITIES = {
    "order", "purchase", "shipping_invoice", "dn", "grn",
    "vendor_payment", "received_payment", "expense_payment",
}

# Entities the assistant can analyse closely and recommend next steps for.
ADVISABLE_ENTITIES = {
    "order", "purchase", "shipping_invoice", "dn", "grn",
    "git", "stock", "vendor_payment", "received_payment",
    "expense_payment", "payments", "overview",
}


# Fields that must never be requested by or returned to the AI layer.
FORBIDDEN_FIELDS = {
    "email", "phone", "tin_number", "contact_person", "comments",
    "buyer_address", "buyer_tin_number", "shipper_address",
    "destination_contact_name", "destination_contact_number",
    "bank", "invoice_remark", "packing_list_remark", "waybill_remark",
    "bill_of_lading_remark", "remark", "status_remark", "reference_number",
    "truck_no", "transporter_name", "store_keeper", "receiver_phone",
    "password", "is_active", "username",
}
