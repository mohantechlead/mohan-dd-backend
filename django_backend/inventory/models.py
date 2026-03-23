from django.db import models
import uuid
from django.conf import settings

# Create your models here.
class GRN(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    supplier_name = models.CharField(max_length=255)
    grn_no = models.IntegerField(unique=True)
    plate_no = models.CharField(max_length=255)
    purchase_no = models.CharField(max_length=255)
    date = models.DateField(null=False, blank=False, auto_now = True)
    ECD_no = models.CharField(max_length=255, blank=True, null=True)
    transporter_name = models.CharField(max_length=255, blank=True, null=True)
    storekeeper_name = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.grn_no} ({self.supplier_name})"
    
    class Meta:
        ordering = ['grn_no'] 

class GrnItems(models.Model):
    item_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    grn = models.ForeignKey(GRN, on_delete=models.CASCADE, related_name='items')
    item_name = models.CharField(max_length=255)
    quantity = models.IntegerField()
    unit_measurement = models.CharField(max_length=100)
    internal_code = models.CharField(max_length=100, blank=True, null=True)
    bags = models.FloatField(blank=True, null=True)

    def __str__(self):
        return f"{self.grn} - {self.item_name} "
    
    class Meta:
        ordering = ['grn'] 

class DN(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    customer_name = models.CharField(max_length=255)
    dn_no = models.CharField(max_length=255, unique=True)
    plate_no = models.CharField(max_length=255)
    sales_no = models.CharField(max_length=255)
    date = models.DateField(null=False, blank=False, auto_now=True)
    ECD_no = models.CharField(max_length=255, blank=True, null=True)
    invoice_no = models.CharField(max_length=255, blank=True, null=True)
    gatepass_no = models.CharField(max_length=255, blank=True, null=True)
    despathcher_name = models.CharField(max_length=255, blank=True, null=True)
    receiver_name = models.CharField(max_length=255, blank=True, null=True)
    receiver_phone = models.CharField(max_length=20, blank=True, null=True)
    authorized_by = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.dn_no} ({self.customer_name})"

class DNItems(models.Model):
    item_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    dn = models.ForeignKey(DN, on_delete=models.CASCADE, related_name='dn_items')
    item_name = models.CharField(max_length=255)
    quantity = models.IntegerField()
    unit_measurement = models.CharField(max_length=100)
    internal_code = models.CharField(max_length=100, blank=True, null=True)
    bags = models.FloatField(blank=True, null=True)

    def __str__(self):
        return f"{self.dn} - {self.item_name} "

class Items(models.Model):
    item_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    item_name = models.CharField(max_length=255)
    hscode = models.CharField(max_length=255)
    internal_code = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.item_name} - {self.item_name} - {self.internal_code}"

class Stock(models.Model):
    item_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    item_name = models.CharField(max_length=255)
    hscode = models.CharField(max_length=255)
    internal_code = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.FloatField(max_length=100, blank=True, null=True)
    unit_measurement = models.CharField(max_length=100)
    package = models.FloatField(blank=True, null=True)
    package_type = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.item_name} - {self.item_name} - {self.internal_code}"


class Order(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    order_number = models.CharField(max_length=255, unique=True)
    proforma_ref_no = models.CharField(max_length=255)
    buyer = models.CharField(max_length=255)
    add_consignee = models.CharField(max_length=255, blank=True, null=True)
    order_date = models.DateField()
    shipper = models.CharField(max_length=255)
    notify_party = models.CharField(max_length=255, blank=True, null=True)
    add_notify_party = models.CharField(max_length=255, blank=True, null=True)
    country_of_origin = models.CharField(max_length=255)
    final_destination = models.CharField(max_length=255)
    port_of_loading = models.CharField(max_length=255)
    port_of_discharge = models.CharField(max_length=255)
    measurement_type = models.CharField(max_length=50)
    payment_terms = models.CharField(max_length=100)
    mode_of_transport = models.CharField(max_length=50)
    freight = models.CharField(max_length=50)
    freight_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    shipment_type = models.CharField(max_length=50)
    status = models.CharField(max_length=20, default="pending")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_orders",
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="completed_orders",
    )
    completed_date = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_orders",
    )
    cancelled_date = models.DateTimeField(null=True, blank=True)
    status_remark = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.order_number} ({self.buyer})"


class OrderItem(models.Model):
    item_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=255)
    hs_code = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.IntegerField()
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    measurement = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.order.order_number} - {self.item_name}"


class ShippingInvoice(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipping_invoices")
    invoice_number = models.CharField(max_length=255, unique=True)
    invoice_date = models.DateField()
    waybill_number = models.CharField(max_length=255, blank=True, null=True)
    customer_order_number = models.CharField(max_length=255)
    container_number = models.CharField(max_length=255, blank=True, null=True)
    vessel = models.CharField(max_length=255, blank=True, null=True)
    invoice_remark = models.TextField(blank=True, null=True)
    packing_list_remark = models.TextField(blank=True, null=True)
    waybill_remark = models.TextField(blank=True, null=True)
    bill_of_lading_remark = models.TextField(blank=True, null=True)
    sr_no = models.PositiveIntegerField(blank=True, null=True)
    authorized_by = models.CharField(max_length=255, blank=True, null=True)
    authorized_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.invoice_number} ({self.order.order_number})"


class ShippingInvoiceItem(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    invoice = models.ForeignKey(ShippingInvoice, on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.IntegerField()
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    measurement = models.CharField(max_length=100)
    bags = models.FloatField(blank=True, null=True)
    net_weight = models.FloatField(blank=True, null=True)
    gross_weight = models.FloatField(blank=True, null=True)
    grade = models.CharField(max_length=255, blank=True, null=True)
    brand = models.CharField(max_length=255, blank=True, null=True)
    country_of_origin = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.item_name}"


class Purchase(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    purchase_number = models.CharField(max_length=255, unique=True)
    proforma_ref_no = models.CharField(max_length=255)
    buyer = models.CharField(max_length=255)
    add_consignee = models.CharField(max_length=255, blank=True, null=True)
    order_date = models.DateField()
    shipper = models.CharField(max_length=255)
    notify_party = models.CharField(max_length=255, blank=True, null=True)
    add_notify_party = models.CharField(max_length=255, blank=True, null=True)
    country_of_origin = models.CharField(max_length=255)
    final_destination = models.CharField(max_length=255)
    conditions = models.CharField(max_length=255, blank=True, null=True)
    port_of_loading = models.CharField(max_length=255)
    port_of_discharge = models.CharField(max_length=255)
    measurement_type = models.CharField(max_length=50)
    payment_terms = models.CharField(max_length=100)
    mode_of_transport = models.CharField(max_length=50)
    freight = models.CharField(max_length=50)
    freight_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    insurance = models.CharField(max_length=255, blank=True, null=True)
    shipment_type = models.CharField(max_length=50)
    status = models.CharField(max_length=20, default="pending")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_purchases",
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="completed_purchases",
    )
    completed_date = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_purchases",
    )
    cancelled_date = models.DateTimeField(null=True, blank=True)
    status_remark = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.purchase_number} ({self.buyer})"


class PurchaseItem(models.Model):
    item_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.IntegerField()
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    measurement = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.purchase.purchase_number} - {self.item_name}"
