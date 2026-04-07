import uuid
from datetime import date
from typing import Optional
from ninja import Schema


class ExpensePaymentCreateSchema(Schema):
    expense_number: str
    expense_date: date
    payee: str
    category: str
    amount: float
    description: Optional[str] = None


class ExpensePaymentUpdateSchema(Schema):
    expense_date: date
    payee: str
    category: str
    amount: float
    description: Optional[str] = None


class ExpensePaymentApproveSchema(Schema):
    approved_by_id: int


class ExpensePaymentStatusUpdateSchema(Schema):
    status: str  # completed | cancelled
    user_id: int
    reference_number: Optional[str] = None
    remark: Optional[str] = None


class ExpensePaymentDetailSchema(Schema):
    id: uuid.UUID
    expense_number: str
    expense_date: date
    payee: str
    category: str
    amount: float
    description: Optional[str] = None
    status: str
    approved_by: Optional[str] = None
    approval_date: Optional[str] = None
    completed_by: Optional[str] = None
    completed_date: Optional[str] = None
    cancelled_by: Optional[str] = None
    cancelled_date: Optional[str] = None
    reference_number: Optional[str] = None
    status_remark: Optional[str] = None


class VendorPaymentCreateSchema(Schema):
    payment_date: date
    purchase_number: str
    payment_type: str  # partial | full
    amount: Optional[float] = None
    remark: Optional[str] = None


class VendorPaymentUpdateSchema(Schema):
    payment_date: date
    payment_type: str  # partial | full
    amount: Optional[float] = None
    remark: Optional[str] = None


class VendorPaymentApproveSchema(Schema):
    approved_by_id: int


class VendorPaymentStatusUpdateSchema(Schema):
    status: str  # completed | cancelled
    user_id: int
    reference_number: Optional[str] = None
    remark: Optional[str] = None


class VendorPaymentDetailSchema(Schema):
    id: uuid.UUID
    payment_number: str
    installment_number: int
    payment_date: date
    purchase_number: str
    supplier_name: str
    payment_type: str
    amount: float
    status: str
    approved_by: Optional[str] = None
    approval_date: Optional[str] = None
    completed_by: Optional[str] = None
    completed_date: Optional[str] = None
    cancelled_by: Optional[str] = None
    cancelled_date: Optional[str] = None
    reference_number: Optional[str] = None
    status_remark: Optional[str] = None
    purchase_total: float
    total_paid: float
    remaining_amount: float
    payment_completion_status: str
    remark: Optional[str] = None


class ReceivedPaymentCreateSchema(Schema):
    payment_date: date
    order_number: str
    payment_type: str  # partial | full
    amount: Optional[float] = None
    remark: Optional[str] = None


class ReceivedPaymentUpdateSchema(Schema):
    payment_date: date
    payment_type: str  # partial | full
    amount: Optional[float] = None
    remark: Optional[str] = None


class ReceivedPaymentApproveSchema(Schema):
    approved_by_id: int


class ReceivedPaymentStatusUpdateSchema(Schema):
    status: str  # completed | cancelled
    user_id: int
    reference_number: Optional[str] = None
    remark: Optional[str] = None


class ReceivedPaymentDetailSchema(Schema):
    id: uuid.UUID
    payment_number: str
    installment_number: int
    payment_date: date
    order_number: str
    customer_name: str
    payment_type: str
    amount: float
    status: str
    approved_by: Optional[str] = None
    approval_date: Optional[str] = None
    completed_by: Optional[str] = None
    completed_date: Optional[str] = None
    cancelled_by: Optional[str] = None
    cancelled_date: Optional[str] = None
    reference_number: Optional[str] = None
    status_remark: Optional[str] = None
    order_total: float
    total_paid: float
    remaining_amount: float
    payment_completion_status: str
    remark: Optional[str] = None
