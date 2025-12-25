from typing import List
from ninja import Router, Schema
import uuid
from .models import Partner
from .schemas import CustomerListSchema,CustomerCreateSchema, CustomerDetailSchema
from .schemas import SupplierListSchema,SupplierCreateSchema, SupplierDetailSchema
from django.shortcuts import get_object_or_404
router = Router()

class UserSchema(Schema):
    username: str
    is_authenticated: bool
    # is not requst.user.is_authenticated
    email: str = None

@router.get("/customer", response=List[CustomerListSchema])
def list_customers(request):
    qs = Partner.objects.filter(partner_type="customer")
    return qs

@router.get("/customer/{customer_id}", response=CustomerDetailSchema)
def get_customers(request, customer_id:uuid.UUID):
    return get_object_or_404(Partner, partnerid=customer_id)


@router.post("/customer", response = CustomerDetailSchema)
def create_customer(request, payload: CustomerCreateSchema):
    # Create Customer
    customer = Partner.objects.create(
        partnerid=uuid.uuid4(),
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        address=payload.address,
        tin_number=payload.tin_number,
        partner_type=payload.partner_type
    )
    return {
        "id": customer.partnerid,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "address": customer.address,
        "tin_number": customer.tin_number,
        "partner_type": customer.partner_type
    }

@router.get("/supplier", response=List[SupplierListSchema])
def list_suppliers(request):
    qs = Partner.objects.filter(partner_type="supplier")
    return qs

@router.get("/supplier/{supplier_id}", response=SupplierDetailSchema)
def get_suppliers(request, supplier_id:uuid.UUID):
    return get_object_or_404(Partner, partnerid=supplier_id)


@router.post("/supplier", response = SupplierDetailSchema)
def create_supplier(request, payload: SupplierCreateSchema):
    # Create supplier
    supplier = Partner.objects.create(
        partnerid=uuid.uuid4(),
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        address=payload.address,
        tin_number=payload.tin_number,
        partner_type=payload.partner_type
    )
    return {
        "id": supplier.partnerid,
        "name": supplier.name,
        "email": supplier.email,
        "phone": supplier.phone,
        "address": supplier.address,
        "tin_number": supplier.tin_number,
        "partner_type": supplier.partner_type
    }