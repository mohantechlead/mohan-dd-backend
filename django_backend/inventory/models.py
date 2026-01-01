from django.db import models
import uuid

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
