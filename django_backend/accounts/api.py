from typing import List
from ninja import Router, Schema
import uuid
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from .models import Partner
from .schemas import CustomerListSchema,CustomerCreateSchema, CustomerDetailSchema
from .schemas import SupplierListSchema,SupplierCreateSchema, SupplierDetailSchema
from django.shortcuts import get_object_or_404
from ninja_jwt.authentication import JWTAuth

router = Router()

User = get_user_model()

ROLE_CHOICES = ["admin", "sales", "purchasing", "inventory", "viewer"]


def _require_admin(request):
    """Return None if allowed, or JsonResponse with 403 if not admin."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    role = getattr(user, "role", "viewer")
    if role != "admin" and not getattr(user, "is_superuser", False):
        return JsonResponse({"detail": "Admin role required."}, status=403)
    return None


class UserSchema(Schema):
    id: int
    username: str
    email: str | None = None
    role: str
    is_active: bool = True


class UserCreateSchema(Schema):
    username: str
    password: str
    email: str = ""
    role: str = "viewer"


class UserUpdateSchema(Schema):
    username: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None


class ChangePasswordSchema(Schema):
    new_password: str


@router.get("/users", response=List[UserSchema], auth=JWTAuth())
def list_users(request):
    err = _require_admin(request)
    if err:
        return err
    return list(User.objects.all())


@router.post("/users", response=UserSchema, auth=JWTAuth())
def create_user(request, payload: UserCreateSchema):
    err = _require_admin(request)
    if err:
        return err
    if User.objects.filter(username=payload.username).exists():
        return JsonResponse({"detail": "Username already exists."}, status=400)
    if payload.role not in ROLE_CHOICES:
        return JsonResponse({"detail": f"Invalid role. Must be one of: {ROLE_CHOICES}"}, status=400)
    user = User.objects.create_user(
        username=payload.username,
        password=payload.password,
        email=payload.email or "",
    )
    user.role = payload.role
    user.save()
    return {"id": user.id, "username": user.username, "email": user.email or None, "role": user.role, "is_active": user.is_active}


@router.get("/users/{user_id}", response=UserSchema, auth=JWTAuth())
def get_user(request, user_id: int):
    err = _require_admin(request)
    if err:
        return err
    user = get_object_or_404(User, id=user_id)
    return {"id": user.id, "username": user.username, "email": user.email or None, "role": user.role, "is_active": user.is_active}


@router.put("/users/{user_id}", response=UserSchema, auth=JWTAuth())
def update_user(request, user_id: int, payload: UserUpdateSchema):
    err = _require_admin(request)
    if err:
        return err
    user = get_object_or_404(User, id=user_id)
    if payload.username is not None:
        if User.objects.filter(username=payload.username).exclude(id=user_id).exists():
            return JsonResponse({"detail": "Username already exists."}, status=400)
        user.username = payload.username
    if payload.email is not None:
        user.email = payload.email
    if payload.role is not None:
        if payload.role not in ROLE_CHOICES:
            return JsonResponse({"detail": f"Invalid role. Must be one of: {ROLE_CHOICES}"}, status=400)
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    user.save()
    return {"id": user.id, "username": user.username, "email": user.email or None, "role": user.role, "is_active": user.is_active}


@router.post("/users/{user_id}/change-password", auth=JWTAuth())
def change_password(request, user_id: int, payload: ChangePasswordSchema):
    err = _require_admin(request)
    if err:
        return err
    user = get_object_or_404(User, id=user_id)
    if not payload.new_password or len(payload.new_password) < 6:
        return JsonResponse({"detail": "Password must be at least 6 characters."}, status=400)
    user.set_password(payload.new_password)
    user.save()
    return {"detail": "Password updated successfully."}


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