from django.test import TestCase
from types import SimpleNamespace
from decimal import Decimal
from datetime import date
from django.http import JsonResponse

from .api import create_vendor_payment
from .models import VendorPayment
from inventory.models import Purchase


class VendorPaymentInlandTransportTests(TestCase):
    def setUp(self):
        self.purchase = Purchase.objects.create(
            purchase_number="P001",
            proforma_ref_no="PR1",
            buyer="Buyer",
            order_date=date.today(),
            shipper="Shipper",
            country_of_origin="CO",
            final_destination="FD",
            port_of_loading="PL",
            port_of_discharge="PD",
            payment_terms="PT",
            mode_of_transport="Sea",
            shipment_type="Type",
            before_vat=Decimal("1000"),
        )

    def make_payload(self, **kwargs):
        data = {
            "payment_date": date.today(),
            "purchase_number": self.purchase.purchase_number,
            "payment_type": "partial",
            "amount": 100,
            "insurance": 0,
            "freight": 0,
            "inland_transport": 0,
            "remark": None,
        }
        data.update(kwargs)
        return SimpleNamespace(**data)

    def test_inland_transport_must_be_non_negative(self):
        payload = self.make_payload(inland_transport=-5)
        result = create_vendor_payment(None, payload)
        self.assertIsInstance(result, JsonResponse)
        self.assertEqual(result.status_code, 400)
        self.assertIn("inland_transport", result.content.decode())

    def test_grand_total_saved_values(self):
        payload = self.make_payload(amount=200, insurance=50, freight=20, inland_transport=30)
        result = create_vendor_payment(None, payload)
        # should create payment for purchase P001 -> payment number P001-PAY-1
        vp = VendorPayment.objects.get(payment_number=f"{self.purchase.purchase_number}-PAY-1")
        self.assertEqual(Decimal(str(vp.amount)), Decimal("200"))
        self.assertEqual(Decimal(str(vp.insurance)), Decimal("50"))
        self.assertEqual(Decimal(str(vp.freight)), Decimal("20"))
        self.assertEqual(Decimal(str(vp.inland_transport)), Decimal("30"))
        expected_grand = Decimal("200") + Decimal("50") + Decimal("20") + Decimal("30")
        actual_grand = Decimal(str(vp.amount)) + Decimal(str(vp.insurance)) + Decimal(str(vp.freight)) + Decimal(str(vp.inland_transport))
        self.assertEqual(expected_grand, actual_grand)

    def test_full_partial_amount_rules(self):
        # full payment should set amount to remaining
        p2 = Purchase.objects.create(
            purchase_number="P002",
            proforma_ref_no="PR2",
            buyer="Buyer2",
            order_date=date.today(),
            shipper="Shipper2",
            country_of_origin="CO",
            final_destination="FD",
            port_of_loading="PL",
            port_of_discharge="PD",
            payment_terms="PT",
            mode_of_transport="Sea",
            shipment_type="Type",
            before_vat=Decimal("500"),
        )
        payload_full = SimpleNamespace(
            payment_date=date.today(),
            purchase_number=p2.purchase_number,
            payment_type="full",
            amount=None,
            insurance=0,
            freight=0,
            inland_transport=0,
            remark=None,
        )
        res = create_vendor_payment(None, payload_full)
        vp_full = VendorPayment.objects.get(payment_number=f"{p2.purchase_number}-PAY-1")
        self.assertEqual(Decimal(str(vp_full.amount)), Decimal("500"))

        # partial cannot exceed remaining
        # create an existing payment of 400
        VendorPayment.objects.create(
            id="00000000-0000-0000-0000-000000000001",
            payment_number=f"{p2.purchase_number}-PAY-2",
            installment_number=2,
            payment_date=date.today(),
            purchase=p2,
            supplier_name=p2.shipper,
            payment_type="partial",
            amount=Decimal("400"),
            insurance=0,
            freight=0,
            inland_transport=0,
            status="approved",
        )

        payload_partial = SimpleNamespace(
            payment_date=date.today(),
            purchase_number=p2.purchase_number,
            payment_type="partial",
            amount=300,
            insurance=0,
            freight=0,
            inland_transport=0,
            remark=None,
        )
        res2 = create_vendor_payment(None, payload_partial)
        self.assertIsInstance(res2, JsonResponse)
        self.assertEqual(res2.status_code, 400)