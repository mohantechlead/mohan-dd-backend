import re
import uuid
from django.conf import settings
from django.db import models
from inventory.models import Order, Purchase, WarehouseStorageNote


class ExpensePayment(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    expense_number = models.CharField(max_length=64, unique=True)
    expense_date = models.DateField()
    payee = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, default="pending")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_expense_payments",
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="completed_expense_payments",
    )
    completed_date = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_expense_payments",
    )
    cancelled_date = models.DateTimeField(null=True, blank=True)
    reference_number = models.CharField(max_length=255, blank=True, null=True)
    status_remark = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.expense_number} ({self.payee})"


_EXPENSE_NUMBER_RE = re.compile(r"^EXP(\d+)$", re.IGNORECASE)


def next_expense_number(values) -> str:
    max_n = None
    for value in values:
        if value is None:
            continue
        match = _EXPENSE_NUMBER_RE.match(str(value).strip())
        if match:
            n = int(match.group(1))
            max_n = n if max_n is None else max(max_n, n)
    if max_n is None:
        return "EXP0001"
    return f"EXP{max_n + 1:04d}"


class VendorPayment(models.Model):
    PAYMENT_TYPE_CHOICES = (
        ("partial", "Partial"),
        ("full", "Full"),
    )

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    payment_number = models.CharField(max_length=64, unique=True)
    installment_number = models.PositiveIntegerField(default=1)
    payment_date = models.DateField()
    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        to_field="purchase_number",
        db_column="purchase_number",
        related_name="vendor_payments",
    )
    supplier_name = models.CharField(max_length=255)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    insurance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    freight = models.DecimalField(max_digits=15, decimal_places=2, default=0, blank=True)
    inland_transport = models.DecimalField(max_digits=15, decimal_places=2, default=0, blank=True)
    remark = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default="pending")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_vendor_payments",
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="completed_vendor_payments",
    )
    completed_date = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_vendor_payments",
    )
    cancelled_date = models.DateTimeField(null=True, blank=True)
    reference_number = models.CharField(max_length=255, blank=True, null=True)
    status_remark = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.payment_number} ({self.purchase_id})"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["purchase", "installment_number"],
                name="uniq_vendor_payment_installment_per_purchase",
            )
        ]


_VENDOR_PAYMENT_NUMBER_RE = re.compile(r"^VP(\d+)$", re.IGNORECASE)


def next_vendor_payment_number(values) -> str:
    max_n = None
    for value in values:
        if value is None:
            continue
        match = _VENDOR_PAYMENT_NUMBER_RE.match(str(value).strip())
        if match:
            n = int(match.group(1))
            max_n = n if max_n is None else max(max_n, n)
    if max_n is None:
        return "VP0001"
    return f"VP{max_n + 1:04d}"


class ReceivedPayment(models.Model):
    PAYMENT_TYPE_CHOICES = (
        ("partial", "Partial"),
        ("full", "Full"),
    )

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    payment_number = models.CharField(max_length=64, unique=True)
    installment_number = models.PositiveIntegerField(default=1)
    payment_date = models.DateField()
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        to_field="order_number",
        db_column="order_number",
        related_name="received_payments",
    )
    customer_name = models.CharField(max_length=255)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    remark = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default="pending")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_received_payments",
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="completed_received_payments",
    )
    completed_date = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_received_payments",
    )
    cancelled_date = models.DateTimeField(null=True, blank=True)
    reference_number = models.CharField(max_length=255, blank=True, null=True)
    status_remark = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.payment_number} ({self.order_id})"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "installment_number"],
                name="uniq_received_payment_installment_per_order",
            )
        ]


# ============================================================
# Warehouse Storage Payments
# ============================================================

_WSP_NUMBER_RE = re.compile(r"^WSP(\d+)$", re.IGNORECASE)


def next_warehouse_storage_payment_number(values) -> str:
    max_n = None
    for value in values:
        if value is None:
            continue
        match = _WSP_NUMBER_RE.match(str(value).strip())
        if match:
            n = int(match.group(1))
            max_n = n if max_n is None else max(max_n, n)
    if max_n is None:
        return "WSP0001"
    return f"WSP{max_n + 1:04d}"


class WarehouseStoragePayment(models.Model):
    """Payment ledger for warehouse storage fees (mirrors VendorPayment/ReceivedPayment pattern)."""
    PAYMENT_TYPE_CHOICES = (
        ("partial", "Partial"),
        ("full", "Full"),
    )

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    payment_number = models.CharField(max_length=64, unique=True)
    installment_number = models.PositiveIntegerField(default=1)
    payment_date = models.DateField()
    storage_note = models.ForeignKey(
        WarehouseStorageNote,
        on_delete=models.CASCADE,
        to_field="wsn_no",
        db_column="wsn_no",
        related_name="storage_payments",
    )
    customer_name = models.CharField(max_length=255)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    remark = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, default="pending")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_storage_payments",
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="completed_storage_payments",
    )
    completed_date = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_storage_payments",
    )
    cancelled_date = models.DateTimeField(null=True, blank=True)
    reference_number = models.CharField(max_length=255, blank=True, null=True)
    status_remark = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.payment_number} ({self.storage_note_id})"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["storage_note", "installment_number"],
                name="uniq_storage_payment_installment_per_note",
            )
        ]
