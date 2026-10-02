"""Seed DEMO data for local AI-assistant testing.

EMAIL SAFETY (read before running):
- Uses ORM creates ONLY. It never calls API views, never calls
  _send_notification_mail / _check_and_notify_*, so no notification code runs.
- Belt-and-braces: forces EMAIL_BACKEND to locmem and empties
  NOTIFICATION_EMAIL_RECIPIENTS / OVER_UNDER_DELIVERY_RECIPIENTS for the run,
  then asserts django.core.mail.outbox is empty.
- Idempotent: exits without changes if DEMO rows already exist.
- Demo rows are namespaced (M900x, DEMO ...) so they never collide with real data.

Run:  python seed_ai_demo.py
"""
import os
import sys
from datetime import date
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_backend.settings")

import django  # noqa: E402

django.setup()

from django.test.utils import override_settings  # noqa: E402

D = Decimal


def main():
    from inventory.models import (
        DN, DNItems, GIT, GRN, GrnItems, Items,
        Order, OrderItem, Purchase, PurchaseItem,
        ShippingInvoice, ShippingInvoiceItem,
    )
    from accounts.models import Partner
    from accounting.models import ExpensePayment, ReceivedPayment, VendorPayment

    if Order.objects.filter(order_number__startswith="M900").exists():
        print("DEMO seed already present (M900x orders exist). Nothing to do.")
        return

    with override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        NOTIFICATION_EMAIL_RECIPIENTS=[],
        OVER_UNDER_DELIVERY_RECIPIENTS=[],
    ):
        # --- catalog + partners ---
        pvc = Items.objects.create(item_name="DEMO PVC RESIN", hscode="39041000", internal_code="PVC-001")
        steel = Items.objects.create(item_name="DEMO STEEL RODS", hscode="72131000", internal_code="STL-002")
        cement = Items.objects.create(item_name="DEMO CEMENT", hscode="25232900", internal_code="CEM-003")
        Partner.objects.create(name="DEMO CUSTOMER ONE", partner_type="customer", address="Demo City")
        Partner.objects.create(name="DEMO CUSTOMER TWO", partner_type="customer", address="Demo Town")
        Partner.objects.create(name="DEMO SUPPLIER ONE", partner_type="supplier", address="Demo Port")

        def make_order(number, day, buyer, shipper, status, lines):
            # lines: [(catalog_item, qty, price, measurement)]
            total_qty = sum(q for _, q, _, _ in lines)
            prv = sum(D(str(q)) * D(str(p)) for _, q, p, _ in lines)
            order = Order.objects.create(
                order_number=number, proforma_ref_no=f"DEMO-PI-{number}",
                buyer=buyer, order_date=date(2026, day[0], day[1]),
                shipper=shipper, country_of_origin="Demo Land",
                final_destination="Dire Dawa", port_of_loading="Demo Port",
                port_of_discharge="Djibouti", payment_terms="LC at sight",
                mode_of_transport="Sea", shipment_type="FCL",
                PR_before_VAT=prv, total_quantity=total_qty,
                remaining=total_qty, status=status,
            )
            for item, qty, price, measure in lines:
                total = D(str(qty)) * D(str(price))
                OrderItem.objects.create(
                    order=order, order_no=number, item_name=item.item_name,
                    hs_code=item.hscode, price=D(str(price)), quantity=qty,
                    total_price=total, before_vat=total, measurement=measure,
                )
            return order

        o1 = make_order("M9001", (9, 5), "DEMO CUSTOMER ONE", "DEMO SUPPLIER ONE",
                        "approved", [(pvc, 80.0, 1200.0, "MT"), (cement, 40.0, 150.0, "MT")])
        o2 = make_order("M9002", (9, 12), "DEMO CUSTOMER TWO", "DEMO SUPPLIER ONE",
                        "pending", [(steel, 25.0, 900.0, "MT")])
        o3 = make_order("M9003", (9, 18), "DEMO CUSTOMER ONE", "DEMO SUPPLIER ONE",
                        "completed", [(pvc, 50.0, 1200.0, "MT")])
        o4 = make_order("M9004", (8, 22), "DEMO CUSTOMER TWO", "DEMO SUPPLIER ONE",
                        "completed", [(cement, 100.0, 150.0, "MT")])
        o5 = make_order("M9005", (10, 1), "DEMO CUSTOMER ONE", "DEMO SUPPLIER ONE",
                        "pending", [(steel, 10.0, 950.0, "MT")])
        o6 = make_order("M9006", (9, 25), "DEMO CUSTOMER TWO", "DEMO SUPPLIER ONE",
                        "approved", [(pvc, 20.0, 1250.0, "MT")])

        def make_purchase(number, day, status, lines):
            total_qty = sum(q for _, q, _, _ in lines)
            bv = sum(D(str(q)) * D(str(p)) for _, q, p, _ in lines)
            purchase = Purchase.objects.create(
                purchase_number=number, proforma_ref_no=f"DEMO-PO-{number}",
                buyer="MOHAN PLC", order_date=date(2026, day[0], day[1]),
                shipper="DEMO SUPPLIER ONE", country_of_origin="Demo Land",
                final_destination="Dire Dawa", port_of_loading="Demo Port",
                port_of_discharge="Djibouti", payment_terms="LC at sight",
                mode_of_transport="Sea", shipment_type="FCL",
                before_vat=bv, total_quantity=total_qty,
                remaining=total_qty, status=status,
            )
            for item, qty, price, measure in lines:
                total = D(str(qty)) * D(str(price))
                PurchaseItem.objects.create(
                    purchase=purchase, item_name=item.item_name,
                    price=D(str(price)), quantity=qty, remaining=qty,
                    total_price=total, before_vat=total,
                    hscode=item.hscode, measurement=measure,
                )
            return purchase

        pu1 = make_purchase("MPDDFZE901", (8, 10), "approved", [(pvc, 80.0, 1150.0, "MT")])
        pu2 = make_purchase("MPDDFZE902", (9, 2), "pending", [(steel, 25.0, 880.0, "MT")])
        pu3 = make_purchase("MPDDFZE903", (9, 15), "completed", [(cement, 100.0, 140.0, "MT")])

        def make_grn(grn_no, day, purchase_no, supplier, is_last, lines):
            grn = GRN.objects.create(
                supplier_name=supplier, grn_no=grn_no, purchase_no=purchase_no,
                total_quantity=sum(q for _, q, _ in lines),
                date=date(2026, day[0], day[1]), is_last=is_last,
            )
            for item, qty, measure in lines:
                GrnItems.objects.create(
                    grn=grn, grn_no=grn_no, item_name=item.item_name,
                    code=item.internal_code, quantity=qty,
                    unit_measurement=measure, internal_code=item.internal_code,
                )
            return grn

        g1 = make_grn(9001, (9, 6), "MPDDFZE901", "DEMO SUPPLIER ONE", True,
                      [(pvc, 82.0, "MT")])
        make_grn(9002, (9, 10), "MPDDFZE902", "DEMO SUPPLIER ONE", False,
                 [(steel, 10.0, "MT")])
        make_grn(9003, (9, 20), "MPDDFZE903", "DEMO SUPPLIER ONE", True,
                 [(cement, 98.0, "MT")])

        GIT.objects.create(grn=g1, purchase_no="MPDDFZE901", item_name=pvc.item_name,
                           code="PVC-001", purchase_quantity=80.0,
                           received_quantity=82.0, variance_quantity=2.0,
                           variance_type="increased")
        GIT.objects.create(grn=g1, purchase_no="MPDDFZE903", item_name=cement.item_name,
                           code="CEM-003", purchase_quantity=100.0,
                           received_quantity=98.0, variance_quantity=2.0,
                           variance_type="decreased")

        def make_invoice(number, day, order, sr_no, authorized, lines):
            inv = ShippingInvoice.objects.create(
                order=order, invoice_number=number,
                invoice_date=date(2026, day[0], day[1]),
                customer_order_number=f"DEMO-CO-{number}",
                final_price=sum(D(str(q)) * D(str(p)) for _, q, p in lines),
                sr_no=sr_no,
                destination_contact_name="Demo Receiver",
                destination_contact_number="0911000000",
                authorized_by="Demo Manager" if authorized else None,
            )
            for item, qty, price in lines:
                total = D(str(qty)) * D(str(price))
                ShippingInvoiceItem.objects.create(
                    invoice=inv, item_name=item.item_name, code=item.internal_code,
                    price=D(str(price)), quantity=qty, total_price=total,
                    measurement="MT", hscode=item.hscode,
                )
            return inv

        inv1 = make_invoice("A9001", (9, 7), o1, 1, True, [(pvc, 80.0, 1200.0)])
        make_invoice("A9002", (9, 19), o3, 2, False, [(pvc, 50.0, 1200.0)])

        def make_dn(dn_no, day, customer, sales_no, invoice_no, is_last, lines):
            dn = DN.objects.create(
                customer_name=customer, dn_no=dn_no, plate_no="DEMO-PLATE",
                sales_no=sales_no, date=date(2026, day[0], day[1]),
                invoice_no=invoice_no, is_last=is_last,
            )
            for item, qty, measure in lines:
                DNItems.objects.create(
                    dn=dn, catalog_item_id=item.item_id, item_name=item.item_name,
                    code=item.internal_code, quantity=qty,
                    unit_measurement=measure, internal_code=item.internal_code,
                )
            return dn

        make_dn("DN9001", (9, 8), "DEMO CUSTOMER ONE", "M9001", "A9001", False,
                [(pvc, 50.0, "MT")])
        make_dn("DN9002", (9, 9), "DEMO CUSTOMER ONE", "M9001", "A9001", True,
                [(pvc, 30.0, "MT")])
        make_dn("DN9003", (9, 20), "DEMO CUSTOMER ONE", "M9003", "A9002", True,
                [(pvc, 50.0, "MT")])

        ExpensePayment.objects.create(
            expense_number="EXP9001", expense_date=date(2026, 9, 5),
            payee="Demo Transporter", category="Transport", amount=D("1200.00"),
            status="approved",
        )
        VendorPayment.objects.create(
            payment_number="MPDDFZE901-PAY-1", installment_number=1,
            payment_date=date(2026, 9, 8), purchase=pu1,
            supplier_name="DEMO SUPPLIER ONE", payment_type="partial",
            amount=D("40000.00"), status="approved",
        )
        ReceivedPayment.objects.create(
            payment_number="M9001-RCV-1", installment_number=1,
            payment_date=date(2026, 9, 10), order=o1,
            customer_name="DEMO CUSTOMER ONE", payment_type="partial",
            amount=D("50000.00"), status="approved",
        )

        from django.core import mail
        sent = len(getattr(mail, "outbox", []))
        assert sent == 0, f"SAFETY: {sent} emails were queued during seeding!"
        print("Seed complete: 6 orders, 3 purchases, 3 GRNs, 2 invoices, "
              "3 DNs, 2 GIT rows, 3 payments, 3 items, 3 partners.")
        print("Emails queued during seeding: 0 (verified).")


if __name__ == "__main__":
    sys.exit(main())
