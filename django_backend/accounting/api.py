import uuid
from typing import List
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router

from .models import (
    ExpensePayment,
    ReceivedPayment,
    VendorPayment,
    next_expense_number,
    next_vendor_payment_number,
)
from inventory.models import Order, Purchase
from .schemas import (
    ExpensePaymentApproveSchema,
    ExpensePaymentCreateSchema,
    ExpensePaymentDetailSchema,
    ExpensePaymentStatusUpdateSchema,
    ExpensePaymentUpdateSchema,
    VendorPaymentCreateSchema,
    VendorPaymentDetailSchema,
    VendorPaymentApproveSchema,
    VendorPaymentStatusUpdateSchema,
    VendorPaymentUpdateSchema,
    ReceivedPaymentCreateSchema,
    ReceivedPaymentDetailSchema,
    ReceivedPaymentApproveSchema,
    ReceivedPaymentStatusUpdateSchema,
    ReceivedPaymentUpdateSchema,
)

router = Router()


def _to_schema(expense: ExpensePayment) -> ExpensePaymentDetailSchema:
    return ExpensePaymentDetailSchema(
        id=expense.id,
        expense_number=expense.expense_number,
        expense_date=expense.expense_date,
        payee=expense.payee,
        category=expense.category,
        amount=float(expense.amount),
        description=expense.description,
        status=expense.status,
        approved_by=expense.approved_by.username if expense.approved_by else None,
        approval_date=expense.approval_date.isoformat() if expense.approval_date else None,
        completed_by=expense.completed_by.username if expense.completed_by else None,
        completed_date=expense.completed_date.isoformat() if expense.completed_date else None,
        cancelled_by=expense.cancelled_by.username if expense.cancelled_by else None,
        cancelled_date=expense.cancelled_date.isoformat() if expense.cancelled_date else None,
        reference_number=expense.reference_number,
        status_remark=expense.status_remark,
    )


def _payment_totals_for_purchase(purchase_number: str, exclude_id=None) -> tuple[Decimal, Decimal, Decimal, str]:
    purchase = get_object_or_404(
        Purchase,
        purchase_number__iexact=purchase_number.strip(),
    )
    purchase_total = Decimal(str(purchase.before_vat or 0))
    qs = VendorPayment.objects.filter(
        purchase__purchase_number__iexact=purchase.purchase_number,
        status__in=("approved", "completed"),
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    already_paid = sum(Decimal(str(v.amount)) for v in qs)
    remaining = purchase_total - already_paid
    if remaining < Decimal("0"):
        remaining = Decimal("0")
    completion = "full" if remaining == Decimal("0") else "partial"
    return purchase_total, already_paid, remaining, completion


def _vendor_payment_to_schema(vp: VendorPayment) -> VendorPaymentDetailSchema:
    purchase_total, already_paid_without_me, _, _ = _payment_totals_for_purchase(vp.purchase_id, exclude_id=vp.id)
    total_paid = already_paid_without_me + Decimal(str(vp.amount))
    remaining = purchase_total - total_paid
    if remaining < Decimal("0"):
        remaining = Decimal("0")
    completion = "full" if remaining == Decimal("0") else "partial"
    return VendorPaymentDetailSchema(
        id=vp.id,
        payment_number=vp.payment_number,
        installment_number=vp.installment_number,
        payment_date=vp.payment_date,
        purchase_number=vp.purchase_id,
        supplier_name=vp.supplier_name,
        payment_type=vp.payment_type,
        amount=float(vp.amount),
        status=vp.status,
        approved_by=vp.approved_by.username if vp.approved_by else None,
        approval_date=vp.approval_date.isoformat() if vp.approval_date else None,
        completed_by=vp.completed_by.username if vp.completed_by else None,
        completed_date=vp.completed_date.isoformat() if vp.completed_date else None,
        cancelled_by=vp.cancelled_by.username if vp.cancelled_by else None,
        cancelled_date=vp.cancelled_date.isoformat() if vp.cancelled_date else None,
        reference_number=vp.reference_number,
        status_remark=vp.status_remark,
        purchase_total=float(purchase_total),
        total_paid=float(total_paid),
        remaining_amount=float(remaining),
        payment_completion_status=completion,
        remark=vp.remark,
    )


def _payment_totals_for_order(order_number: str, exclude_id=None) -> tuple[Decimal, Decimal, Decimal, str]:
    order = get_object_or_404(
        Order,
        order_number__iexact=order_number.strip(),
    )
    order_total = Decimal(str(order.PR_before_VAT or 0))
    qs = ReceivedPayment.objects.filter(
        order__order_number__iexact=order.order_number,
        status__in=("approved", "completed"),
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    already_paid = sum(Decimal(str(v.amount)) for v in qs)
    remaining = order_total - already_paid
    if remaining < Decimal("0"):
        remaining = Decimal("0")
    completion = "full" if remaining == Decimal("0") else "partial"
    return order_total, already_paid, remaining, completion


def _received_payment_to_schema(rp: ReceivedPayment) -> ReceivedPaymentDetailSchema:
    order_total, already_paid_without_me, _, _ = _payment_totals_for_order(rp.order_id, exclude_id=rp.id)
    total_paid = already_paid_without_me + Decimal(str(rp.amount))
    remaining = order_total - total_paid
    if remaining < Decimal("0"):
        remaining = Decimal("0")
    completion = "full" if remaining == Decimal("0") else "partial"
    return ReceivedPaymentDetailSchema(
        id=rp.id,
        payment_number=rp.payment_number,
        installment_number=rp.installment_number,
        payment_date=rp.payment_date,
        order_number=rp.order_id,
        customer_name=rp.customer_name,
        payment_type=rp.payment_type,
        amount=float(rp.amount),
        status=rp.status,
        approved_by=rp.approved_by.username if rp.approved_by else None,
        approval_date=rp.approval_date.isoformat() if rp.approval_date else None,
        completed_by=rp.completed_by.username if rp.completed_by else None,
        completed_date=rp.completed_date.isoformat() if rp.completed_date else None,
        cancelled_by=rp.cancelled_by.username if rp.cancelled_by else None,
        cancelled_date=rp.cancelled_date.isoformat() if rp.cancelled_date else None,
        reference_number=rp.reference_number,
        status_remark=rp.status_remark,
        order_total=float(order_total),
        total_paid=float(total_paid),
        remaining_amount=float(remaining),
        payment_completion_status=completion,
        remark=rp.remark,
    )


@router.post("/expense-payments", response=ExpensePaymentDetailSchema)
def create_expense_payment(request, payload: ExpensePaymentCreateSchema):
    if ExpensePayment.objects.filter(expense_number__iexact=payload.expense_number.strip()).exists():
        return JsonResponse({"detail": "Expense number already exists."}, status=400)

    expense = ExpensePayment.objects.create(
        id=uuid.uuid4(),
        expense_number=payload.expense_number.strip(),
        expense_date=payload.expense_date,
        payee=payload.payee.strip(),
        category=payload.category.strip(),
        amount=payload.amount,
        description=(payload.description or "").strip() or None,
        status="pending",
    )
    return _to_schema(expense)


@router.get("/expense-payments", response=List[ExpensePaymentDetailSchema])
def list_expense_payments(request):
    rows = ExpensePayment.objects.all().order_by("-expense_number")
    return [_to_schema(x) for x in rows]


@router.get("/expense-payments/next-number")
def expense_payment_next_number(request):
    values = ExpensePayment.objects.values_list("expense_number", flat=True)
    return {"next_number": next_expense_number(values)}


@router.get("/expense-payments/{expense_number}", response=ExpensePaymentDetailSchema)
def get_expense_payment(request, expense_number: str):
    expense = get_object_or_404(
        ExpensePayment,
        expense_number__iexact=expense_number.strip(),
    )
    return _to_schema(expense)


@router.put("/expense-payments/{expense_number}", response=ExpensePaymentDetailSchema)
def update_expense_payment(request, expense_number: str, payload: ExpensePaymentUpdateSchema):
    expense = get_object_or_404(
        ExpensePayment,
        expense_number__iexact=expense_number.strip(),
    )
    expense.expense_date = payload.expense_date
    expense.payee = payload.payee.strip()
    expense.category = payload.category.strip()
    expense.amount = payload.amount
    expense.description = (payload.description or "").strip() or None
    expense.save()
    return _to_schema(expense)


@router.delete("/expense-payments/{expense_number}")
def delete_expense_payment(request, expense_number: str):
    expense = get_object_or_404(
        ExpensePayment,
        expense_number__iexact=expense_number.strip(),
    )
    expense.delete()
    return {"detail": "Expense payment deleted successfully."}


@router.post("/expense-payments/{expense_number}/approve", response=ExpensePaymentDetailSchema)
def approve_expense_payment(request, expense_number: str, payload: ExpensePaymentApproveSchema):
    expense = get_object_or_404(
        ExpensePayment,
        expense_number__iexact=expense_number.strip(),
    )
    expense.status = "approved"
    expense.approved_by_id = payload.approved_by_id
    expense.approval_date = timezone.now()
    expense.save()
    return _to_schema(expense)


@router.post("/expense-payments/{expense_number}/update-status", response=ExpensePaymentDetailSchema)
def update_expense_payment_status(request, expense_number: str, payload: ExpensePaymentStatusUpdateSchema):
    expense = get_object_or_404(
        ExpensePayment,
        expense_number__iexact=expense_number.strip(),
    )
    if expense.status != "approved":
        return JsonResponse(
            {"detail": "Only approved expense payments can be marked as completed or cancelled."},
            status=400,
        )
    if payload.status not in ("completed", "cancelled"):
        return JsonResponse(
            {"detail": "Status must be 'completed' or 'cancelled'."},
            status=400,
        )
    if payload.status == "completed" and not (payload.reference_number or "").strip():
        return JsonResponse({"detail": "reference_number is required when completing expense payment."}, status=400)
    if payload.status == "cancelled" and not (payload.remark or "").strip():
        return JsonResponse({"detail": "remark is required when cancelling expense payment."}, status=400)

    expense.status = payload.status
    if payload.status == "completed":
        expense.completed_by_id = payload.user_id
        expense.completed_date = timezone.now()
        expense.reference_number = (payload.reference_number or "").strip()
        expense.status_remark = None
    else:
        expense.cancelled_by_id = payload.user_id
        expense.cancelled_date = timezone.now()
        expense.status_remark = (payload.remark or "").strip()
        expense.reference_number = None
    expense.save()
    return _to_schema(expense)


@router.post("/vendor-payments", response=VendorPaymentDetailSchema)
def create_vendor_payment(request, payload: VendorPaymentCreateSchema):
    purchase = get_object_or_404(
        Purchase,
        purchase_number__iexact=payload.purchase_number.strip(),
    )
    purchase_total, already_paid, remaining, _ = _payment_totals_for_purchase(purchase.purchase_number)
    if remaining <= Decimal("0"):
        return JsonResponse({"detail": "This purchase is already fully paid."}, status=400)

    payment_type = (payload.payment_type or "").strip().lower()
    if payment_type not in ("partial", "full", "paritial"):
        return JsonResponse({"detail": "payment_type must be 'Partial' or 'Full'."}, status=400)
    if payment_type == "paritial":
        payment_type = "partial"

    if payment_type == "full":
        amount = remaining
    else:
        if payload.amount is None:
            return JsonResponse({"detail": "amount is required for partial payment."}, status=400)
        amount = Decimal(str(payload.amount))
        if amount <= Decimal("0"):
            return JsonResponse({"detail": "amount must be greater than 0."}, status=400)
        if amount > remaining:
            return JsonResponse(
                {"detail": f"Partial amount cannot exceed remaining amount ({remaining})."},
                status=400,
            )

    last_installment = (
        VendorPayment.objects.filter(purchase__purchase_number__iexact=purchase.purchase_number)
        .order_by("-installment_number")
        .values_list("installment_number", flat=True)
        .first()
        or 0
    )
    next_installment = int(last_installment) + 1
    generated_payment_number = f"{purchase.purchase_number}-PAY-{next_installment}"

    vp = VendorPayment.objects.create(
        id=uuid.uuid4(),
        payment_number=generated_payment_number,
        installment_number=next_installment,
        payment_date=payload.payment_date,
        purchase=purchase,
        supplier_name=purchase.shipper,
        payment_type=payment_type,
        amount=amount,
        remark=(payload.remark or "").strip() or None,
        status="pending",
    )
    return _vendor_payment_to_schema(vp)


@router.get("/vendor-payments", response=List[VendorPaymentDetailSchema])
def list_vendor_payments(request):
    rows = VendorPayment.objects.select_related("purchase").all().order_by("-payment_number")
    return [_vendor_payment_to_schema(vp) for vp in rows]


@router.get("/vendor-payments/next-number")
def vendor_payment_next_number(request):
    values = VendorPayment.objects.values_list("payment_number", flat=True)
    return {"next_number": next_vendor_payment_number(values)}


@router.get("/vendor-payments/{payment_number}", response=VendorPaymentDetailSchema)
def get_vendor_payment(request, payment_number: str):
    vp = get_object_or_404(VendorPayment, payment_number__iexact=payment_number.strip())
    return _vendor_payment_to_schema(vp)


@router.put("/vendor-payments/{payment_number}", response=VendorPaymentDetailSchema)
def update_vendor_payment(request, payment_number: str, payload: VendorPaymentUpdateSchema):
    vp = get_object_or_404(VendorPayment, payment_number__iexact=payment_number.strip())
    purchase_total, already_paid_without_me, remaining_without_me, _ = _payment_totals_for_purchase(vp.purchase_id, exclude_id=vp.id)

    payment_type = (payload.payment_type or "").strip().lower()
    if payment_type not in ("partial", "full", "paritial"):
        return JsonResponse({"detail": "payment_type must be 'Partial' or 'Full'."}, status=400)
    if payment_type == "paritial":
        payment_type = "partial"

    if payment_type == "full":
        amount = remaining_without_me
    else:
        if payload.amount is None:
            return JsonResponse({"detail": "amount is required for partial payment."}, status=400)
        amount = Decimal(str(payload.amount))
        if amount <= Decimal("0"):
            return JsonResponse({"detail": "amount must be greater than 0."}, status=400)
        if amount > remaining_without_me:
            return JsonResponse(
                {"detail": f"Partial amount cannot exceed remaining amount ({remaining_without_me})."},
                status=400,
            )

    vp.payment_date = payload.payment_date
    vp.payment_type = payment_type
    vp.amount = amount
    vp.remark = (payload.remark or "").strip() or None
    vp.save()
    return _vendor_payment_to_schema(vp)


@router.delete("/vendor-payments/{payment_number}")
def delete_vendor_payment(request, payment_number: str):
    vp = get_object_or_404(VendorPayment, payment_number__iexact=payment_number.strip())
    vp.delete()
    return {"detail": "Vendor payment deleted successfully."}


@router.post("/vendor-payments/{payment_number}/approve", response=VendorPaymentDetailSchema)
def approve_vendor_payment(request, payment_number: str, payload: VendorPaymentApproveSchema):
    vp = get_object_or_404(VendorPayment, payment_number__iexact=payment_number.strip())
    vp.status = "approved"
    vp.approved_by_id = payload.approved_by_id
    vp.approval_date = timezone.now()
    vp.save()
    return _vendor_payment_to_schema(vp)


@router.post("/vendor-payments/{payment_number}/update-status", response=VendorPaymentDetailSchema)
def update_vendor_payment_status(request, payment_number: str, payload: VendorPaymentStatusUpdateSchema):
    vp = get_object_or_404(VendorPayment, payment_number__iexact=payment_number.strip())
    if vp.status != "approved":
        return JsonResponse(
            {"detail": "Only approved vendor payments can be marked as completed or cancelled."},
            status=400,
        )
    if payload.status not in ("completed", "cancelled"):
        return JsonResponse({"detail": "Status must be 'completed' or 'cancelled'."}, status=400)
    if payload.status == "completed" and not (payload.reference_number or "").strip():
        return JsonResponse({"detail": "reference_number is required when completing vendor payment."}, status=400)
    if payload.status == "cancelled" and not (payload.remark or "").strip():
        return JsonResponse({"detail": "remark is required when cancelling vendor payment."}, status=400)

    vp.status = payload.status
    if payload.status == "completed":
        vp.completed_by_id = payload.user_id
        vp.completed_date = timezone.now()
        vp.reference_number = (payload.reference_number or "").strip()
        vp.status_remark = None
    else:
        vp.cancelled_by_id = payload.user_id
        vp.cancelled_date = timezone.now()
        vp.status_remark = (payload.remark or "").strip()
        vp.reference_number = None
    vp.save()
    return _vendor_payment_to_schema(vp)


@router.post("/received-payments", response=ReceivedPaymentDetailSchema)
def create_received_payment(request, payload: ReceivedPaymentCreateSchema):
    order = get_object_or_404(
        Order,
        order_number__iexact=payload.order_number.strip(),
    )
    order_total, _, remaining, _ = _payment_totals_for_order(order.order_number)
    if remaining <= Decimal("0"):
        return JsonResponse({"detail": "This order is already fully paid."}, status=400)

    payment_type = (payload.payment_type or "").strip().lower()
    if payment_type not in ("partial", "full", "paritial"):
        return JsonResponse({"detail": "payment_type must be 'Partial' or 'Full'."}, status=400)
    if payment_type == "paritial":
        payment_type = "partial"

    if payment_type == "full":
        amount = remaining
    else:
        if payload.amount is None:
            return JsonResponse({"detail": "amount is required for partial payment."}, status=400)
        amount = Decimal(str(payload.amount))
        if amount <= Decimal("0"):
            return JsonResponse({"detail": "amount must be greater than 0."}, status=400)
        if amount > remaining:
            return JsonResponse(
                {"detail": f"Partial amount cannot exceed remaining amount ({remaining})."},
                status=400,
            )

    last_installment = (
        ReceivedPayment.objects.filter(order__order_number__iexact=order.order_number)
        .order_by("-installment_number")
        .values_list("installment_number", flat=True)
        .first()
        or 0
    )
    next_installment = int(last_installment) + 1
    generated_payment_number = f"{order.order_number}-RCV-{next_installment}"

    rp = ReceivedPayment.objects.create(
        id=uuid.uuid4(),
        payment_number=generated_payment_number,
        installment_number=next_installment,
        payment_date=payload.payment_date,
        order=order,
        customer_name=order.buyer,
        payment_type=payment_type,
        amount=amount,
        remark=(payload.remark or "").strip() or None,
        status="pending",
    )
    return _received_payment_to_schema(rp)


@router.get("/received-payments", response=List[ReceivedPaymentDetailSchema])
def list_received_payments(request):
    rows = ReceivedPayment.objects.select_related("order").all().order_by("-payment_number")
    return [_received_payment_to_schema(rp) for rp in rows]


@router.get("/received-payments/next-number")
def received_payment_next_number(request):
    return {"next_number": "AUTO"}


@router.get("/received-payments/{payment_number}", response=ReceivedPaymentDetailSchema)
def get_received_payment(request, payment_number: str):
    rp = get_object_or_404(ReceivedPayment, payment_number__iexact=payment_number.strip())
    return _received_payment_to_schema(rp)


@router.put("/received-payments/{payment_number}", response=ReceivedPaymentDetailSchema)
def update_received_payment(request, payment_number: str, payload: ReceivedPaymentUpdateSchema):
    rp = get_object_or_404(ReceivedPayment, payment_number__iexact=payment_number.strip())
    _, _, remaining_without_me, _ = _payment_totals_for_order(rp.order_id, exclude_id=rp.id)

    payment_type = (payload.payment_type or "").strip().lower()
    if payment_type not in ("partial", "full", "paritial"):
        return JsonResponse({"detail": "payment_type must be 'Partial' or 'Full'."}, status=400)
    if payment_type == "paritial":
        payment_type = "partial"

    if payment_type == "full":
        amount = remaining_without_me
    else:
        if payload.amount is None:
            return JsonResponse({"detail": "amount is required for partial payment."}, status=400)
        amount = Decimal(str(payload.amount))
        if amount <= Decimal("0"):
            return JsonResponse({"detail": "amount must be greater than 0."}, status=400)
        if amount > remaining_without_me:
            return JsonResponse(
                {"detail": f"Partial amount cannot exceed remaining amount ({remaining_without_me})."},
                status=400,
            )

    rp.payment_date = payload.payment_date
    rp.payment_type = payment_type
    rp.amount = amount
    rp.remark = (payload.remark or "").strip() or None
    rp.save()
    return _received_payment_to_schema(rp)


@router.delete("/received-payments/{payment_number}")
def delete_received_payment(request, payment_number: str):
    rp = get_object_or_404(ReceivedPayment, payment_number__iexact=payment_number.strip())
    rp.delete()
    return {"detail": "Received payment deleted successfully."}


@router.post("/received-payments/{payment_number}/approve", response=ReceivedPaymentDetailSchema)
def approve_received_payment(request, payment_number: str, payload: ReceivedPaymentApproveSchema):
    rp = get_object_or_404(ReceivedPayment, payment_number__iexact=payment_number.strip())
    rp.status = "approved"
    rp.approved_by_id = payload.approved_by_id
    rp.approval_date = timezone.now()
    rp.save()
    return _received_payment_to_schema(rp)


@router.post("/received-payments/{payment_number}/update-status", response=ReceivedPaymentDetailSchema)
def update_received_payment_status(request, payment_number: str, payload: ReceivedPaymentStatusUpdateSchema):
    rp = get_object_or_404(ReceivedPayment, payment_number__iexact=payment_number.strip())
    if rp.status != "approved":
        return JsonResponse(
            {"detail": "Only approved received payments can be marked as completed or cancelled."},
            status=400,
        )
    if payload.status not in ("completed", "cancelled"):
        return JsonResponse({"detail": "Status must be 'completed' or 'cancelled'."}, status=400)
    if payload.status == "completed" and not (payload.reference_number or "").strip():
        return JsonResponse({"detail": "reference_number is required when completing received payment."}, status=400)
    if payload.status == "cancelled" and not (payload.remark or "").strip():
        return JsonResponse({"detail": "remark is required when cancelling received payment."}, status=400)

    rp.status = payload.status
    if payload.status == "completed":
        rp.completed_by_id = payload.user_id
        rp.completed_date = timezone.now()
        rp.reference_number = (payload.reference_number or "").strip()
        rp.status_remark = None
    else:
        rp.cancelled_by_id = payload.user_id
        rp.cancelled_date = timezone.now()
        rp.status_remark = (payload.remark or "").strip()
        rp.reference_number = None
    rp.save()
    return _received_payment_to_schema(rp)
