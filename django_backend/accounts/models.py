from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid

class User(AbstractUser):
    ROLE_CHOICES = (
        ("admin", "Admin"),
        ("sales", "Sales"),
        ("purchasing", "Purchasing"),
        ("inventory", "Inventory"),
        ("viewer", "Viewer"),
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="viewer")

    def __str__(self):
        return f"{self.username} ({self.role})"

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True

class Partner(BaseModel):
    partnerid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    PARTNER_TYPES = (
        ("customer", "Customer"),
        ("supplier", "Supplier"),
        ("both", "Both Customer & Supplier"),
    )

    name = models.CharField(max_length=255)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    tin_number = models.CharField(max_length=100, null=True, blank=True)
    partner_type = models.CharField(max_length=20, choices=PARTNER_TYPES)

    def __str__(self):
        return f"{self.name} ({self.partner_type})"
