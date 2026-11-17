from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from inventory.api import (
    get_missing_marine_insurance_purchases,
    _comparison_unit_label,
    _comparison_variance_tolerance,
    _filter_negative_items_for_trigger,
    _maybe_notify_negative_stock,
    _quantity_for_comparison,
    _round_comparison_qty,
    _sum_movement_lines_for_comparison,
    _units_comparable_for_variance,
)
from inventory.schemas import MarineInsuranceSchema


class NegativeStockFilterTests(TestCase):
    def test_filters_unrelated_negative_items_for_dn(self):
        negative_items = [
            {
                "item_name": "HDPE",
                "internal_code": "PE100",
                "quantity": -5.0,
                "package": 0.0,
                "dn_nos": ["116"],
                "grn_nos": [],
            },
            {
                "item_name": "TITANIUM DIOXIDE",
                "internal_code": "TITANIUM DIOXIDE",
                "quantity": 0.0,
                "package": -1.0,
                "dn_nos": ["50"],
                "grn_nos": [],
            },
        ]
        dn = MagicMock()
        dn.dn_no = "116"
        line = MagicMock()
        line.code = "PE100"
        line.internal_code = "PE100"
        dn.dn_items.all.return_value = [line]

        filtered = _filter_negative_items_for_trigger(
            negative_items,
            trigger_dn=dn,
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["item_name"], "HDPE")

    def test_matches_trigger_codes_when_document_number_missing(self):
        negative_items = [
            {
                "item_name": "ZINC OXIDE",
                "internal_code": "ZNO-99",
                "quantity": -25000.0,
                "package": -1000.0,
                "dn_nos": [],
                "grn_nos": [],
            },
        ]
        grn = MagicMock()
        grn.grn_no = 42
        line = MagicMock()
        line.code = "ZNO-99"
        line.internal_code = "ZNO-99"
        grn.items.all.return_value = [line]

        filtered = _filter_negative_items_for_trigger(
            negative_items,
            trigger_grn=grn,
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["internal_code"], "ZNO-99")


class UnitComparisonTests(TestCase):
    def test_mt_purchase_converts_kg_grn_to_mt(self):
        self.assertEqual(_quantity_for_comparison(37000, "KG", "MT"), 37.0)
        self.assertEqual(_comparison_unit_label("MT", ["KG"]), "MT")
        self.assertTrue(_units_comparable_for_variance("MT", ["KG"]))

    def test_pc_purchase_keeps_kg_grn_as_kg(self):
        self.assertEqual(_quantity_for_comparison(2060, "KG", "PCs"), 2060.0)
        self.assertEqual(_comparison_unit_label("PCs", ["KG"]), "KG")
        self.assertFalse(_units_comparable_for_variance("PCs", ["KG"]))

    def test_same_non_mass_units_are_comparable(self):
        self.assertEqual(_quantity_for_comparison(75, "PCs", "PCs"), 75.0)
        self.assertEqual(_comparison_unit_label("PCs", ["PCs"]), "PCS")
        self.assertTrue(_units_comparable_for_variance("PCs", ["PCs"]))


class MaybeNotifyNegativeStockTests(TestCase):
    @patch("inventory.api._check_and_notify_negative_stock")
    def test_skips_grn_email_when_not_last(self, mock_notify):
        grn = MagicMock()
        grn.is_last = False
        _maybe_notify_negative_stock(trigger_grn=grn)
        mock_notify.assert_not_called()

    @patch("inventory.api._check_and_notify_negative_stock")
    def test_sends_grn_email_when_last(self, mock_notify):
        grn = MagicMock()
        grn.is_last = True
        _maybe_notify_negative_stock(trigger_grn=grn)
        mock_notify.assert_called_once_with(trigger_dn=None, trigger_grn=grn)


class MarineInsuranceSchemaTests(TestCase):
    def test_accepts_uuid_model_id(self):
        from inventory.models import MarineInsurance, Purchase

        purchase = Purchase.objects.create(
            purchase_number="MPDDFZE004",
            proforma_ref_no="PF-004",
            buyer="Buyer Four",
            order_date=date.today(),
            shipper="Supplier Four",
            country_of_origin="China",
            final_destination="Ethiopia",
            port_of_loading="Shanghai",
            port_of_discharge="Djibouti",
            payment_terms="TT",
            mode_of_transport="Sea",
            shipment_type="LCL",
            status="approved",
        )
        marine_insurance = MarineInsurance.objects.create(
            purchase=purchase,
            insurance_number="INS-004",
            insurance_date=date.today(),
        )

        schema = MarineInsuranceSchema(
            id=marine_insurance.id,
            insurance_number=marine_insurance.insurance_number,
            insurance_date=marine_insurance.insurance_date,
            created_at=marine_insurance.created_at,
            updated_at=marine_insurance.updated_at,
        )

        self.assertEqual(schema.id, str(marine_insurance.id))

    def test_accepts_legacy_integer_id(self):
        schema = MarineInsuranceSchema(
            id=2,
            insurance_number="INS-LEGACY",
            insurance_date=date.today(),
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

        self.assertEqual(schema.id, "2")


class MissingMarineInsuranceTests(TestCase):
    def test_returns_only_approved_purchases_without_insurance_for_current_or_prior_month(self):
        from inventory.models import MarineInsurance, Purchase

        now = timezone.now()
        current_month_purchase = Purchase.objects.create(
            purchase_number="MPDDFZE001",
            proforma_ref_no="PF-001",
            buyer="Buyer One",
            order_date=date.today(),
            shipper="Supplier One",
            country_of_origin="China",
            final_destination="Ethiopia",
            port_of_loading="Shanghai",
            port_of_discharge="Djibouti",
            payment_terms="TT",
            mode_of_transport="Sea",
            shipment_type="LCL",
            status="approved",
            approval_date=now,
        )
        prior_month_purchase = Purchase.objects.create(
            purchase_number="MPDDFZE002",
            proforma_ref_no="PF-002",
            buyer="Buyer Two",
            order_date=date.today(),
            shipper="Supplier Two",
            country_of_origin="China",
            final_destination="Ethiopia",
            port_of_loading="Shanghai",
            port_of_discharge="Djibouti",
            payment_terms="TT",
            mode_of_transport="Sea",
            shipment_type="LCL",
            status="approved",
            approval_date=now - timedelta(days=45),
        )
        future_month_purchase = Purchase.objects.create(
            purchase_number="MPDDFZE003",
            proforma_ref_no="PF-003",
            buyer="Buyer Three",
            order_date=date.today(),
            shipper="Supplier Three",
            country_of_origin="China",
            final_destination="Ethiopia",
            port_of_loading="Shanghai",
            port_of_discharge="Djibouti",
            payment_terms="TT",
            mode_of_transport="Sea",
            shipment_type="LCL",
            status="approved",
            approval_date=now + timedelta(days=30),
        )
        MarineInsurance.objects.create(
            purchase=prior_month_purchase,
            insurance_number="INS-002",
            insurance_date=date.today(),
        )

        result = get_missing_marine_insurance_purchases(now=now)

        self.assertEqual([item.purchase_number for item in result], [current_month_purchase.purchase_number])


class MovementComparisonTests(TestCase):
    def test_sums_kg_before_converting_to_mt(self):
        lines = [
            MagicMock(quantity=6675, unit_measurement="KG"),
            MagicMock(quantity=6675, unit_measurement="KG"),
            MagicMock(quantity=6650, unit_measurement="KG"),
        ]
        total = _sum_movement_lines_for_comparison(lines, "MT")
        self.assertEqual(total, 20.0)
        self.assertEqual(_round_comparison_qty(total, "MT"), 20.0)

    def test_mt_variance_tolerance_is_one_kg(self):
        self.assertEqual(_comparison_variance_tolerance("MT"), 0.001)
        self.assertGreater(0.025, _comparison_variance_tolerance("MT"))

    def test_normalize_comparison_variance_zeros_within_tolerance(self):
        from inventory.api import _normalize_comparison_variance

        self.assertEqual(_normalize_comparison_variance(0.0008, "MT"), 0.0)
        self.assertEqual(_normalize_comparison_variance(-0.001, "MT"), 0.0)
        self.assertEqual(_normalize_comparison_variance(0.025, "MT"), 0.025)


class PurchaseCheckpointTests(TestCase):
    def setUp(self):
        import json

        from django.contrib.auth import get_user_model

        from inventory.models import Purchase

        self.User = get_user_model()
        self.Purchase = Purchase

        def make_user(username, role):
            user = self.User.objects.create_user(username=username, password="Passw0rd!")
            user.role = role
            user.save()
            return user

        self.admin = make_user("pc_admin", "admin")
        self.sales = make_user("pc_sales", "sales")
        self.transitor = make_user("pc_transitor", "transitor")
        self.transitor2 = make_user("pc_transitor2", "transitor")
        self.purchasing = make_user("pc_purchasing", "purchasing")
        self.inactive_transitor = make_user("pc_inactive", "transitor")
        self.inactive_transitor.is_active = False
        self.inactive_transitor.save()

        self.purchase = self._make_purchase("MPDDFZE901")
        self.other_purchase = self._make_purchase("MPDDFZE902")

        from django.test import Client

        self.client = Client()
        self._json = json

    def _make_purchase(self, purchase_number):
        from inventory.models import BillOfLading, BillOfLadingContainer

        purchase = self.Purchase.objects.create(
            purchase_number=purchase_number,
            proforma_ref_no="PF-" + purchase_number[-3:],
            buyer="Checkpoint Buyer",
            order_date=date.today(),
            shipper="Checkpoint Shipper",
            country_of_origin="China",
            final_destination="Ethiopia",
            port_of_loading="Shanghai",
            port_of_discharge="Djibouti",
            payment_terms="TT",
            mode_of_transport="Sea",
            shipment_type="LCL",
            status="pending",
        )
        bl = BillOfLading.objects.create(
            purchase=purchase,
            bl_number="BL-" + purchase_number[-3:],
            bl_date=date.today(),
            declaration_number="8-000" + purchase_number[-3:],
            declaration_date=date.today(),
            container_count=1,
            shipping_company_name="MSC",
        )
        BillOfLadingContainer.objects.create(
            bill_of_lading=bl,
            container_number="MSCU" + purchase_number[-3:] + "001",
            size="40",
            cargo_type="non_hazardous",
        )
        return purchase

    def _auth_headers(self, username, password="Passw0rd!"):
        resp = self.client.post(
            "/api/token/pair",
            data=self._json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        token = resp.json()["access"]
        return {"HTTP_AUTHORIZATION": "Bearer " + token}

    def _post_stage(self, purchase_number, body, username):
        return self.client.post(
            "/api/inventory/purchases/" + purchase_number + "/stage",
            data=self._json.dumps(body),
            content_type="application/json",
            **self._auth_headers(username),
        )

    def _post_assign(self, purchase_number, body, username):
        return self.client.post(
            "/api/inventory/purchases/" + purchase_number + "/assign-transitor",
            data=self._json.dumps(body),
            content_type="application/json",
            **self._auth_headers(username),
        )

    def _post_advance(self, purchase_number, body, username):
        return self.client.post(
            "/api/inventory/purchases/" + purchase_number + "/advance",
            data=self._json.dumps(body),
            content_type="application/json",
            **self._auth_headers(username),
        )

    def _review_advance(self, advance_id, action, username, body=None):
        return self.client.post(
            "/api/inventory/transit-advances/" + advance_id + "/" + action,
            data=self._json.dumps(body or {}),
            content_type="application/json",
            **self._auth_headers(username),
        )

    def _approve_advance_for(self, purchase_number, username="pc_transitor"):
        """Ask for the next stage as the transitor and approve it as the admin."""
        resp = self._post_advance(purchase_number, {}, username)
        self.assertEqual(resp.status_code, 200, resp.content)
        advance_id = resp.json()["id"]
        resp = self._review_advance(advance_id, "approve", "pc_admin")
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def test_transitor_advances_one_step_forward(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.save()

        # Every step of the walk needs its own admin-approved advance.
        self._approve_advance_for("MPDDFZE901")
        resp = self._post_stage("MPDDFZE901", {"stage": "ecd_im8"}, "pc_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["stage"], "ecd_im8")
        self.assertEqual(data["stage_label"], "ECD / IM8")
        self.assertEqual(data["stage_updated_by"], "pc_transitor")
        self.assertEqual(data["assigned_transitor"], "pc_transitor")
        self.assertIsNotNone(data["stage_updated_at"])

        # The next step is only reachable once the admin approves its advance.
        self._approve_advance_for("MPDDFZE901")

        resp = self._post_stage("MPDDFZE901", {"stage": "transit_permit"}, "pc_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["stage"], "transit_permit")
        self.assertEqual(data["stage_label"], "Transit Permit")
        self.assertEqual(data["bill_of_lading"]["bl_number"], "BL-901")
        self.assertEqual(data["bill_of_lading"]["declaration_number"], "8-000901")
        documents = {d["document_type"]: d for d in data["transit_documents"]}
        self.assertEqual(
            set(documents),
            {"container_guarantee", "letter_guarantee"},
        )
        self.assertNotEqual(
            documents["container_guarantee"]["reference_number"],
            documents["letter_guarantee"]["reference_number"],
        )
        for document in documents.values():
            self.assertTrue(document["reference_number"].startswith("MPN/DDFT/"))
        # The new series counts from 001: 001/26 then 002/26 for 2026.
        self.assertEqual(
            documents["container_guarantee"]["reference_number"], "MPN/DDFT/001/26"
        )
        self.assertEqual(
            documents["letter_guarantee"]["reference_number"], "MPN/DDFT/002/26"
        )
        self.assertEqual(
            documents["container_guarantee"]["snapshot"]["containers"][0][
                "container_number"
            ],
            "MSCU901001",
        )

        # Advancing to Closure Guarantee needs its own approval too.
        self._approve_advance_for("MPDDFZE901")
        resp = self._post_stage("MPDDFZE901", {"stage": "closure_guarantee"}, "pc_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["stage"], "closure_guarantee")
        self.assertEqual(data["stage_label"], "Closure Guarantee")
        documents = {d["document_type"]: d for d in data["transit_documents"]}
        self.assertEqual(len(documents), 3)
        closure = documents["closure_guarantee"]
        self.assertEqual(
            closure["snapshot"]["previous_letter_reference"],
            documents["letter_guarantee"]["reference_number"],
        )
        self.assertEqual(
            closure["snapshot"]["declaration_number"], "8-000901"
        )
        self.assertEqual(
            len({d["reference_number"] for d in documents.values()}), 3
        )

    def test_transit_permit_requires_bill_of_lading(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.stage = "ecd_im8"
        self.purchase.save()
        self.purchase.bill_of_lading.delete()
        self._approve_advance_for("MPDDFZE901")

        resp = self._post_stage(
            "MPDDFZE901", {"stage": "transit_permit"}, "pc_transitor"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("bill of lading", resp.json()["detail"].lower())
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.stage, "ecd_im8")

    def test_transitor_blocked_from_done_and_cancelling(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.stage = "closure_guarantee"
        self.purchase.save()

        resp = self._post_stage("MPDDFZE901", {"stage": "done"}, "pc_transitor")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("done or cancelled", resp.json()["detail"])

        resp = self._post_stage("MPDDFZE901", {"stage": "cancelled"}, "pc_transitor")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("done or cancelled", resp.json()["detail"])

    def test_transitor_blocked_from_skipping_steps(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.save()

        resp = self._post_stage("MPDDFZE901", {"stage": "transit_permit"}, "pc_transitor")
        self.assertEqual(resp.status_code, 403)

    def test_transitor_blocked_until_advance_approved(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.stage = "ecd_im8"
        self.purchase.save()

        # Nothing filed yet: the stage will not move.
        resp = self._post_stage("MPDDFZE901", {"stage": "transit_permit"}, "pc_transitor")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("approve", resp.json()["detail"].lower())

        advance = self._post_advance("MPDDFZE901", {}, "pc_transitor")
        self.assertEqual(advance.status_code, 200, advance.content)
        self.assertEqual(advance.json()["target_stage"], "transit_permit")

        # Pending: still blocked.
        resp = self._post_stage("MPDDFZE901", {"stage": "transit_permit"}, "pc_transitor")
        self.assertEqual(resp.status_code, 403)

        # Approved: the transitor advances and the letters are generated.
        resp = self._review_advance(advance.json()["id"], "approve", "pc_admin")
        self.assertEqual(resp.status_code, 200, resp.content)

        resp = self._post_stage("MPDDFZE901", {"stage": "transit_permit"}, "pc_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["stage"], "transit_permit")
        self.assertEqual(
            {d["document_type"] for d in data["transit_documents"]},
            {"container_guarantee", "letter_guarantee"},
        )
    def test_transitor_blocked_from_non_assigned_purchase(self):
        self.other_purchase.assigned_transitor = self.transitor2
        self.other_purchase.save()

        resp = self._post_stage("MPDDFZE901", {"stage": "ecd_im8"}, "pc_transitor")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("not assigned", resp.json()["detail"])

    def test_other_role_blocked_from_stage(self):
        resp = self._post_stage("MPDDFZE901", {"stage": "ecd_im8"}, "pc_purchasing")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "Not permitted.")

    def test_invalid_stage_value_rejected(self):
        resp = self._post_stage("MPDDFZE901", {"stage": "bogus"}, "pc_sales")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid stage value", resp.json()["detail"])

    def test_sales_full_override_any_direction(self):
        resp = self._post_stage("MPDDFZE901", {"stage": "done"}, "pc_sales")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["stage"], "done")
        self.assertEqual(data["stage_label"], "Done")
        self.assertEqual(data["stage_updated_by"], "pc_sales")

        resp = self._post_stage("MPDDFZE901", {"stage": None}, "pc_sales")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.json()["stage"])
        self.assertIsNone(resp.json()["stage_label"])

        resp = self._post_stage("MPDDFZE901", {"stage": "transit_permit"}, "pc_sales")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["stage"], "transit_permit")

    def test_admin_can_set_stage(self):
        resp = self._post_stage("MPDDFZE901", {"stage": "cancelled"}, "pc_admin")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["stage"], "cancelled")

    def test_assign_transitor_and_unassign(self):
        resp = self._post_assign(
            "MPDDFZE901", {"transitor_id": self.transitor.id}, "pc_sales"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["assigned_transitor_id"], self.transitor.id)
        self.assertEqual(data["assigned_transitor"], "pc_transitor")

        resp = self._post_assign("MPDDFZE901", {"transitor_id": None}, "pc_sales")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.json()["assigned_transitor_id"])
        self.assertIsNone(resp.json()["assigned_transitor"])

    def test_assign_to_non_transitor_rejected(self):
        resp = self._post_assign(
            "MPDDFZE901", {"transitor_id": self.purchasing.id}, "pc_sales"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("transitor role", resp.json()["detail"])

    def test_assign_to_inactive_transitor_rejected(self):
        resp = self._post_assign(
            "MPDDFZE901", {"transitor_id": self.inactive_transitor.id}, "pc_sales"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not active", resp.json()["detail"])

    def test_assign_non_sales_role_blocked(self):
        resp = self._post_assign(
            "MPDDFZE901", {"transitor_id": self.transitor.id}, "pc_purchasing"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "Not permitted.")

    def test_my_transits_scoped_per_user(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.save()
        self.other_purchase.assigned_transitor = self.transitor2
        self.other_purchase.save()

        resp = self.client.get(
            "/api/inventory/purchases/my-transits",
            **self._auth_headers("pc_transitor"),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        numbers = [p["purchase_number"] for p in resp.json()]
        self.assertEqual(numbers, ["MPDDFZE901"])

        resp = self.client.get(
            "/api/inventory/purchases/my-transits",
            **self._auth_headers("pc_transitor2"),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        numbers = [p["purchase_number"] for p in resp.json()]
        self.assertEqual(numbers, ["MPDDFZE902"])

    def test_my_transits_includes_bl_details_and_letters(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.stage = "ecd_im8"
        self.purchase.save()
        self._approve_advance_for("MPDDFZE901")
        resp = self._post_stage(
            "MPDDFZE901", {"stage": "transit_permit"}, "pc_transitor"
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        resp = self.client.get(
            "/api/inventory/purchases/my-transits",
            **self._auth_headers("pc_transitor"),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row = resp.json()[0]
        self.assertEqual(row["bill_of_lading"]["bl_number"], "BL-901")
        self.assertEqual(
            {document["document_type"] for document in row["transit_documents"]},
            {"container_guarantee", "letter_guarantee"},
        )

    def test_users_transitors_role_gate_and_listing(self):
        resp = self.client.get(
            "/api/partners/users/transitors",
            **self._auth_headers("pc_purchasing"),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "Not permitted.")

        resp = self.client.get("/api/partners/users/transitors")
        self.assertEqual(resp.status_code, 401)

        resp = self.client.get(
            "/api/partners/users/transitors",
            **self._auth_headers("pc_sales"),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        usernames = [u["username"] for u in resp.json()]
        self.assertEqual(usernames, ["pc_transitor", "pc_transitor2"])

        resp = self.client.get(
            "/api/partners/users/transitors",
            **self._auth_headers("pc_admin"),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(resp.json()), 2)

    def test_full_walk_through_to_done_via_sales(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.save()

        steps = ["ecd_im8", "transit_permit", "closure_guarantee"]
        for step in steps:
            self._approve_advance_for("MPDDFZE901")
            resp = self._post_stage("MPDDFZE901", {"stage": step}, "pc_transitor")
            self.assertEqual(resp.status_code, 200, resp.content)
            self.assertEqual(resp.json()["stage"], step)

        resp = self._post_stage("MPDDFZE901", {"stage": "done"}, "pc_sales")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["stage"], "done")
        self.assertEqual(data["stage_label"], "Done")
        self.assertEqual(data["stage_updated_by"], "pc_sales")

class StockAdjustmentTests(TestCase):
    def setUp(self):
        import json

        from django.contrib.auth import get_user_model
        from django.test import Client

        from inventory.models import GRN, GrnItems

        User = get_user_model()
        self.client = Client()
        self._json = json

        def make_user(username, role):
            user = User.objects.create_user(username=username, password="Passw0rd!")
            user.role = role
            user.save()
            return user

        self.admin = make_user("sa_admin", "admin")
        self.store = make_user("sa_store", "store")

        grn = GRN.objects.create(
            supplier_name="Supplier",
            grn_no=9001,
            purchase_no="MPDDFZE900",
            date=date.today(),
        )
        GrnItems.objects.create(
            grn=grn,
            grn_no=9001,
            item_name="HDPE",
            code="PE100",
            quantity=100.0,
            unit_measurement="KG",
            bags=10.0,
        )

    def _auth_headers(self, username, password="Passw0rd!"):
        resp = self.client.post(
            "/api/token/pair",
            data=self._json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return {"HTTP_AUTHORIZATION": "Bearer " + resp.json()["access"]}

    def _create_adjustment(self, **overrides):
        from inventory.models import StockAdjustment

        data = {
            "code": "PE100",
            "item_name": "HDPE",
            "quantity": 25.0,
            "bags": 2.0,
            "reason": "lost",
            "date": date.today(),
        }
        data.update(overrides)
        return StockAdjustment.objects.create(**data)

    def _stock_row(self):
        from inventory.api import _build_stock_by_code

        rows = _build_stock_by_code()
        return next(r for r in rows if r["code"] == "PE100")

    def test_pending_adjustment_does_not_reduce_stock(self):
        self._create_adjustment()

        row = self._stock_row()
        self.assertEqual(row["quantity"], 100.0)
        self.assertEqual(row["package"], 10.0)

    def test_approved_adjustment_reduces_stock_and_bags(self):
        self._create_adjustment(status="approved")

        row = self._stock_row()
        self.assertEqual(row["quantity"], 75.0)
        self.assertEqual(row["package"], 8.0)

    def test_rejected_adjustment_does_not_reduce_stock(self):
        self._create_adjustment(status="rejected")

        row = self._stock_row()
        self.assertEqual(row["quantity"], 100.0)
        self.assertEqual(row["package"], 10.0)

    def test_approve_endpoint_marks_adjustment_approved(self):
        adjustment = self._create_adjustment()
        headers = self._auth_headers("sa_admin")

        resp = self.client.post(
            f"/api/inventory/stock/adjustments/{adjustment.id}/approve",
            **headers,
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["reviewed_by"], "sa_admin")
        self.assertIsNotNone(body["reviewed_at"])
        self.assertEqual(self._stock_row()["quantity"], 75.0)

    def test_reject_endpoint_marks_adjustment_rejected(self):
        adjustment = self._create_adjustment()
        headers = self._auth_headers("sa_admin")

        resp = self.client.post(
            f"/api/inventory/stock/adjustments/{adjustment.id}/reject",
            data=self._json.dumps({"remark": "Not verified"}),
            content_type="application/json",
            **headers,
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "rejected")
        self.assertEqual(body["review_remark"], "Not verified")
        self.assertEqual(self._stock_row()["quantity"], 100.0)

    def test_store_role_cannot_approve(self):
        adjustment = self._create_adjustment()
        headers = self._auth_headers("sa_store")

        resp = self.client.post(
            f"/api/inventory/stock/adjustments/{adjustment.id}/approve",
            **headers,
        )

        self.assertEqual(resp.status_code, 403, resp.content)

    def test_reviewing_twice_is_rejected(self):
        adjustment = self._create_adjustment(status="approved")
        headers = self._auth_headers("sa_admin")

        resp = self.client.post(
            f"/api/inventory/stock/adjustments/{adjustment.id}/approve",
            **headers,
        )

        self.assertEqual(resp.status_code, 400, resp.content)



class TransitAdvanceTests(TestCase):
    """Admin approval flow for transit advances + letter printing gate."""

    def setUp(self):
        import json

        from django.contrib.auth import get_user_model
        from django.test import Client

        from inventory.models import BillOfLading, BillOfLadingContainer, Purchase

        self._json = json
        self.client = Client()
        User = get_user_model()

        def make_user(username, role):
            user = User.objects.create_user(username=username, password="Passw0rd!")
            user.role = role
            user.save()
            return user

        self.admin = make_user("ta_admin", "admin")
        self.transitor = make_user("ta_transitor", "transitor")
        self.other_transitor = make_user("ta_other_transitor", "transitor")
        self.sales = make_user("ta_sales", "sales")

        self.purchase = Purchase.objects.create(
            purchase_number="MPDDFZE801",
            proforma_ref_no="PF-801",
            buyer="Advance Buyer",
            order_date=date.today(),
            shipper="Advance Shipper",
            country_of_origin="China",
            final_destination="Ethiopia",
            port_of_loading="Shanghai",
            port_of_discharge="Djibouti",
            payment_terms="TT",
            mode_of_transport="Sea",
            shipment_type="LCL",
            status="pending",
        )
        bl = BillOfLading.objects.create(
            purchase=self.purchase,
            bl_number="BL-801",
            bl_date=date.today(),
            declaration_number="8-000801",
            declaration_date=date.today(),
            container_count=1,
            shipping_company_name="MSC",
        )
        BillOfLadingContainer.objects.create(
            bill_of_lading=bl,
            container_number="MSCU801001",
            size="40",
            cargo_type="non_hazardous",
        )
        self.purchase.assigned_transitor = self.transitor
        self.purchase.stage = "ecd_im8"
        self.purchase.save()

    def _auth_headers(self, username, password="Passw0rd!"):
        resp = self.client.post(
            "/api/token/pair",
            data=self._json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return {"HTTP_AUTHORIZATION": "Bearer " + resp.json()["access"]}

    def _post(self, path, body, username):
        return self.client.post(
            path,
            data=self._json.dumps(body),
            content_type="application/json",
            **self._auth_headers(username),
        )

    def _get(self, path, username):
        return self.client.get(path, **self._auth_headers(username))

    def _request_advance(self, body=None, username="ta_transitor"):
        return self._post(
            "/api/inventory/purchases/MPDDFZE801/advance",
            body if body is not None else {},
            username,
        )

    def _approve(self, advance_id, username="ta_admin"):
        return self._post(
            "/api/inventory/transit-advances/" + advance_id + "/approve", {}, username
        )

    def _reject(self, advance_id, body, username="ta_admin"):
        return self._post(
            "/api/inventory/transit-advances/" + advance_id + "/reject", body, username
        )

    def _stage(self, stage, username="ta_transitor"):
        return self._post(
            "/api/inventory/purchases/MPDDFZE801/stage", {"stage": stage}, username
        )

    # ------------------------------------------------------------
    # Requesting an advance
    # ------------------------------------------------------------

    def test_transitor_requests_and_views_advance(self):
        resp = self._request_advance()
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["status_label"], "Pending")
        # A plain request: it only names the stage being asked for.
        self.assertEqual(data["target_stage"], "transit_permit")
        self.assertEqual(data["target_stage_label"], "Transit Permit")
        for money_field in ("amount", "currency", "note"):
            self.assertNotIn(money_field, data)
        self.assertEqual(data["purchase_number"], "MPDDFZE801")
        self.assertEqual(data["requested_by"], "ta_transitor")

        resp = self._get("/api/inventory/purchases/MPDDFZE801/advance", "ta_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["id"], data["id"])

        # Embedded in the purchase detail so the transitor can track the status.
        resp = self._get("/api/inventory/purchases/MPDDFZE801", "ta_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["advance"]["status"], "pending")

    def test_advance_request_role_gates(self):
        resp = self._request_advance(username="ta_other_transitor")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("assigned transitor", resp.json()["detail"])

        resp = self._request_advance(username="ta_sales")
        self.assertEqual(resp.status_code, 403)

        resp = self.client.post(
            "/api/inventory/purchases/MPDDFZE801/advance",
            data=self._json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

        # The admin can file an advance on the transitor's behalf.
        resp = self._request_advance(username="ta_admin")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["requested_by"], "ta_admin")

        resp = self._get("/api/inventory/purchases/MPDDFZE801/advance", "ta_sales")
        self.assertEqual(resp.status_code, 403)

    def test_no_request_once_the_final_stage_is_reached(self):
        self.purchase.stage = "closure_guarantee"
        self.purchase.save()

        resp = self._request_advance()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("final stage", resp.json()["detail"])

        resp = self._get("/api/inventory/purchases/MPDDFZE801/advance", "ta_transitor")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json())  # nothing persisted

    # ------------------------------------------------------------
    # Admin review
    # ------------------------------------------------------------

    def test_admin_lists_pending_advances_with_purchase_detail(self):
        self._request_advance()

        resp = self._get("/api/inventory/transit-advances?status=pending", "ta_admin")
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["advance"]["status"], "pending")
        self.assertEqual(rows[0]["purchase"]["purchase_number"], "MPDDFZE801")
        self.assertEqual(rows[0]["purchase"]["buyer"], "Advance Buyer")
        self.assertEqual(rows[0]["purchase"]["assigned_transitor"], "ta_transitor")

        resp = self._get("/api/inventory/transit-advances", "ta_sales")
        self.assertEqual(resp.status_code, 403)
        resp = self._get("/api/inventory/transit-advances", "ta_transitor")
        self.assertEqual(resp.status_code, 403)

    def test_admin_approve_returns_advance_and_purchase_detail(self):
        advance = self._request_advance().json()

        resp = self._approve(advance["id"])
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["advance"]["status"], "approved")
        self.assertEqual(data["advance"]["status_label"], "Approved")
        self.assertEqual(data["advance"]["target_stage"], "transit_permit")
        self.assertEqual(data["advance"]["reviewed_by"], "ta_admin")
        self.assertIsNotNone(data["advance"]["reviewed_at"])
        # Full purchase detail accompanies the approval.
        self.assertEqual(data["purchase"]["purchase_number"], "MPDDFZE801")
        self.assertEqual(data["purchase"]["buyer"], "Advance Buyer")
        self.assertEqual(data["purchase"]["stage"], "ecd_im8")
        self.assertEqual(data["purchase"]["assigned_transitor"], "ta_transitor")
        self.assertEqual(len(data["purchase"]["items"]), 0)
        self.assertEqual(data["purchase"]["advance"]["status"], "approved")

        # Already reviewed -> rejected on second attempt.
        resp = self._approve(advance["id"])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already been reviewed", resp.json()["detail"])

    def test_non_admin_cannot_review_advances(self):
        advance = self._request_advance().json()

        for username in ("ta_sales", "ta_transitor"):
            resp = self._approve(advance["id"], username)
            self.assertEqual(resp.status_code, 403, username)
            resp = self._reject(advance["id"], {"remark": "no"}, username)
            self.assertEqual(resp.status_code, 403, username)

    def test_rejected_advance_can_be_resubmitted(self):
        advance = self._request_advance().json()

        resp = self._reject(advance["id"], {"remark": "hold off for now"})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["advance"]["status"], "rejected")
        self.assertEqual(data["advance"]["review_remark"], "hold off for now")
        self.assertEqual(data["advance"]["reviewed_by"], "ta_admin")

        # Rejected -> the transitor can simply ask again.
        resp = self._request_advance()
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["target_stage"], "transit_permit")
        self.assertIsNone(data["reviewed_by"])
        self.assertIsNone(data["review_remark"])

        resp = self._approve(advance["id"])
        self.assertEqual(resp.status_code, 200, resp.content)

        # Approved advances are final for that stage.
        resp = self._request_advance()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already been approved", resp.json()["detail"])

    # ------------------------------------------------------------
    # Stage advance + letter printing gate
    # ------------------------------------------------------------

    def test_letters_locked_until_advance_approved(self):
        # Nothing filed yet: no move, no letters to print.
        resp = self._stage("transit_permit")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("approve", resp.json()["detail"].lower())

        resp = self._get(
            "/api/inventory/purchases/MPDDFZE801/transit-documents", "ta_transitor"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("advance", resp.json()["detail"])

        resp = self._get("/api/inventory/purchases/MPDDFZE801", "ta_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["transit_documents"], [])

        # Transitor requests the advance; still locked while pending.
        advance = self._request_advance().json()
        resp = self._stage("transit_permit")
        self.assertEqual(resp.status_code, 403)
        resp = self._get(
            "/api/inventory/purchases/MPDDFZE801/transit-documents", "ta_transitor"
        )
        self.assertEqual(resp.status_code, 403)

        # Admin approves -> the move happens and the letters it creates print.
        resp = self._approve(advance["id"])
        self.assertEqual(resp.status_code, 200, resp.content)

        resp = self._stage("transit_permit")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            {d["document_type"] for d in resp.json()["transit_documents"]},
            {"container_guarantee", "letter_guarantee"},
        )

        resp = self._get(
            "/api/inventory/purchases/MPDDFZE801/transit-documents", "ta_transitor"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        documents = resp.json()
        self.assertEqual(
            {d["document_type"] for d in documents},
            {"container_guarantee", "letter_guarantee"},
        )

        resp = self._get("/api/inventory/purchases/MPDDFZE801", "ta_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(len(data["transit_documents"]), 2)
        self.assertEqual(data["advance"]["status"], "approved")

        # Admin still sees the letters (needed for review).
        resp = self._get(
            "/api/inventory/purchases/MPDDFZE801/transit-documents", "ta_admin"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(resp.json()), 2)

    def test_rejection_keeps_letters_locked(self):
        advance = self._request_advance().json()
        self._reject(advance["id"], {"remark": "not approved"})

        resp = self._stage("transit_permit")
        self.assertEqual(resp.status_code, 403)

        resp = self._get(
            "/api/inventory/purchases/MPDDFZE801/transit-documents", "ta_transitor"
        )
        self.assertEqual(resp.status_code, 403)


class BillOfLadingTests(TestCase):
    def _make_bl(self, **kwargs):
        from inventory.models import BillOfLading, Purchase

        purchase = Purchase.objects.create(
            purchase_number=kwargs.pop("purchase_number", "MPDDFZEBL1"),
            proforma_ref_no="PF-BL1",
            buyer="BL Buyer",
            order_date=date.today(),
            shipper="BL Supplier",
            country_of_origin="China",
            final_destination="Ethiopia",
            port_of_loading="Shanghai",
            port_of_discharge="Djibouti",
            payment_terms="TT",
            mode_of_transport="Sea",
            shipment_type="FCL",
            status="approved",
        )
        bl = BillOfLading.objects.create(purchase=purchase, **kwargs)
        return bl

    def test_tracking_url_replaces_placeholder(self):
        from inventory.api import _build_bl_tracking_url

        bl = self._make_bl(
            bl_number="MAEU1234567",
            bl_date=date.today(),
            container_count=1,
            shipping_company_url="https://www.maersk.com/tracking/{bl}",
        )
        self.assertEqual(
            _build_bl_tracking_url(bl),
            "https://www.maersk.com/tracking/MAEU1234567",
        )

    def test_tracking_url_without_placeholder_returned_as_is(self):
        from inventory.api import _build_bl_tracking_url

        bl = self._make_bl(
            purchase_number="MPDDFZEBL2",
            bl_number="CMAU7654321",
            bl_date=date.today(),
            container_count=0,
            shipping_company_url="https://www.cma-cgm.com/ebusiness/tracking",
        )
        self.assertEqual(
            _build_bl_tracking_url(bl),
            "https://www.cma-cgm.com/ebusiness/tracking",
        )

    def test_tracking_url_none_without_company_url(self):
        from inventory.api import _build_bl_tracking_url

        bl = self._make_bl(
            purchase_number="MPDDFZEBL3",
            bl_number="MSCU1111111",
            bl_date=date.today(),
            container_count=0,
        )
        self.assertIsNone(_build_bl_tracking_url(bl))

    def test_bl_to_schema_includes_containers_and_status_label(self):
        from inventory.api import _bl_to_schema
        from inventory.models import BillOfLadingContainer

        bl = self._make_bl(
            purchase_number="MPDDFZEBL4",
            bl_number="OOLU9988776",
            bl_date=date.today(),
            container_count=2,
            shipping_company_name="OOCL",
            shipping_company_url="https://www.oocl.com/tracking/{bl}",
        )
        BillOfLadingContainer.objects.create(
            bill_of_lading=bl, container_number="OOCU1234561", size="20", cargo_type="hazardous"
        )
        BillOfLadingContainer.objects.create(
            bill_of_lading=bl, container_number="OOCU1234562", size="40", cargo_type="non_hazardous"
        )

        schema = _bl_to_schema(bl)
        self.assertEqual(schema.bl_number, "OOLU9988776")
        self.assertEqual(schema.transit_status_label, "Pending")
        self.assertEqual(
            schema.tracking_url, "https://www.oocl.com/tracking/OOLU9988776"
        )
        self.assertEqual(len(schema.containers), 2)
        numbers = {c.container_number for c in schema.containers}
        self.assertEqual(numbers, {"OOCU1234561", "OOCU1234562"})

    def test_validate_bl_payload_rejects_container_count_mismatch(self):
        from inventory.api import _validate_bl_payload
        from inventory.schemas import (
            BillOfLadingCreateSchema,
            BillOfLadingContainerInputSchema,
        )

        payload = BillOfLadingCreateSchema(
            bl_number="BL-1",
            bl_date=date.today(),
            container_count=2,
            containers=[
                BillOfLadingContainerInputSchema(
                    container_number="TESTU0000001", size="40", cargo_type="non_hazardous"
                )
            ],
        )
        error = _validate_bl_payload(payload)
        self.assertIn("Expected 2 container(s)", error)

    def test_validate_bl_payload_rejects_invalid_size_and_cargo(self):
        from inventory.api import _validate_bl_payload
        from inventory.schemas import (
            BillOfLadingCreateSchema,
            BillOfLadingContainerInputSchema,
        )

        payload = BillOfLadingCreateSchema(
            bl_number="BL-2",
            bl_date=date.today(),
            container_count=1,
            containers=[
                BillOfLadingContainerInputSchema(
                    container_number="TESTU0000002", size="50", cargo_type="non_hazardous"
                )
            ],
        )
        self.assertIn("Invalid container size", _validate_bl_payload(payload))

        payload = BillOfLadingCreateSchema(
            bl_number="BL-3",
            bl_date=date.today(),
            container_count=1,
            containers=[
                BillOfLadingContainerInputSchema(
                    container_number="TESTU0000003", size="20", cargo_type="fragile"
                )
            ],
        )
        self.assertIn("Invalid cargo type", _validate_bl_payload(payload))

    def test_validate_bl_payload_accepts_valid_payload(self):
        from inventory.api import _validate_bl_payload
        from inventory.schemas import (
            BillOfLadingCreateSchema,
            BillOfLadingContainerInputSchema,
        )

        payload = BillOfLadingCreateSchema(
            bl_number="BL-4",
            bl_date=date.today(),
            container_count=1,
            containers=[
                BillOfLadingContainerInputSchema(
                    container_number="TESTU0000004", size="40", cargo_type="hazardous"
                )
            ],
        )
        self.assertIsNone(_validate_bl_payload(payload))


class TransitScraperTests(TestCase):
    def test_build_tracking_url_substitutes_placeholder(self):
        from inventory.transit_scraper import build_tracking_url

        url = build_tracking_url("https://example.com/track/{bl}", "MAEU1")
        self.assertEqual(url, "https://example.com/track/MAEU1")

    def test_build_tracking_url_without_placeholder(self):
        from inventory.transit_scraper import build_tracking_url

        url = build_tracking_url("https://example.com/track", "MAEU1")
        self.assertEqual(url, "https://example.com/track")

    def test_build_tracking_url_cleans_loose_reference_parameter(self):
        from inventory.transit_scraper import build_tracking_url

        url = build_tracking_url(
            "https://www.hapag-lloyd.com/en/online-business/track/"
            "track-by-container-solution.html?container=FDCU++0322820",
            "FDCU0322820",
        )
        self.assertTrue(url.endswith("?container=FDCU0322820"), url)

    def test_build_tracking_url_keeps_unrelated_parameters(self):
        from inventory.transit_scraper import build_tracking_url

        url = build_tracking_url(
            "https://example.com/t?tab=customer&refNo=SGN601741200", "SGN601741200"
        )
        self.assertIn("tab=customer", url)
        self.assertIn("refNo=SGN601741200", url)

    def test_map_status_text_in_transit(self):
        from inventory.transit_scraper import _map_status_text

        self.assertEqual(_map_status_text("Vessel departed Shanghai, In Transit"), "in_transit")
        self.assertEqual(_map_status_text("Loaded on board vessel"), "in_transit")

    def test_map_status_text_delivered(self):
        from inventory.transit_scraper import _map_status_text

        self.assertEqual(_map_status_text("Cargo Released to consignee"), "delivered")
        self.assertEqual(_map_status_text("Delivered"), "delivered")

    def test_map_status_text_at_destination(self):
        from inventory.transit_scraper import _map_status_text

        self.assertEqual(_map_status_text("Discharged at Port of Djibouti"), "at_destination")
        self.assertEqual(_map_status_text("Awaiting Pickup at destination"), "at_destination")

    def test_map_status_text_at_transhipment(self):
        from inventory.transit_scraper import _map_status_text

        self.assertEqual(_map_status_text("Transhipment at Singapore"), "at_transhipment")

    def test_map_status_text_arrived(self):
        from inventory.transit_scraper import _map_status_text

        self.assertEqual(_map_status_text("Available for Pickup"), "arrived")
        self.assertEqual(_map_status_text("Customs Cleared"), "arrived")

    def test_map_status_text_pending(self):
        from inventory.transit_scraper import _map_status_text

        self.assertEqual(_map_status_text("Gate In at terminal"), "pending")
        self.assertEqual(_map_status_text("Booking Confirmed"), "pending")

    def test_map_status_text_gate_out_uses_location(self):
        from inventory.transit_scraper import _map_status_text

        # ESL reports "Gated Out" at the Djibouti discharge port.
        self.assertEqual(
            _map_status_text("Gated Out • Djibouti · DJIBOUTI (DJJIB) • 17 Oct 2026"),
            "at_destination",
        )
        # The same milestone at the origin terminal starts the ocean leg.
        self.assertEqual(
            _map_status_text("Gate Out • Nhava Sheva · NHAVA SHEVA (INNSA) • 18 Sep 2026"),
            "in_transit",
        )

    def test_map_status_text_unknown_returns_none(self):
        from inventory.transit_scraper import _map_status_text

        self.assertIsNone(_map_status_text("Something completely different"))

    def test_map_status_text_carrier_phrases(self):
        from inventory.transit_scraper import _map_status_text

        self.assertEqual(_map_status_text("Gate Out Full at terminal"), "in_transit")
        self.assertEqual(_map_status_text("Container Gated In"), "pending")
        self.assertEqual(_map_status_text("Awaiting Loading"), "pending")
        self.assertEqual(_map_status_text("Customs Hold"), "at_destination")
        self.assertEqual(_map_status_text("Transshipment Port Singapore"), "at_transhipment")
        self.assertEqual(_map_status_text("Delivered to consignee"), "delivered")
        self.assertEqual(_map_status_text("Ready for Pickup"), "arrived")

    def test_extract_status_labels_from_dom(self):
        from bs4 import BeautifulSoup

        from inventory.transit_scraper import _extract_status_labels, _map_status_text

        html = """
        <html><body>
          <div class="widget">
            <span class="label">Status</span>:
            <span class="value">Gate Out Full</span>
          </div>
          <div data-status="In Transit">x</div>
          <div class="step current milestone">Vessel Departed</div>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        hit = _extract_status_labels(soup)
        self.assertIsNotNone(hit)
        self.assertEqual(_map_status_text(hit), "in_transit")

    def test_parse_status_error_includes_text_sample(self):
        from inventory.transit_scraper import _parse_status_from_text

        long_text = (
            "Tracking reference ABC123 "
            "some carrier chrome that is not a status phrase "
            + ("word " * 80)
        )
        result = _parse_status_from_text(long_text, "html")
        self.assertIsNone(result.transit_status)
        self.assertIsNotNone(result.error)
        self.assertIn("Page text sample:", result.error or "")
        self.assertIn("Tracking reference", result.error or "")

    def test_scrape_rejects_non_http_url(self):
        from inventory.transit_scraper import scrape_transit_status

        result = scrape_transit_status("ftp://example.com/x")
        self.assertIsNone(result.transit_status)
        self.assertIsNotNone(result.error)

    def test_scrape_parses_static_html(self):
        from inventory.transit_scraper import scrape_transit_status

        html = """
        <html><body>
          <h1>Tracking MAEU123</h1>
          <div class="status">Current Status: Vessel Departed, In Transit</div>
          <div>Vessel: Maersk Essex</div>
        </body></html>
        """
        with patch(
            "inventory.transit_scraper.requests.get"
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"Content-Type": "text/html"}
            mock_resp.content = html.encode("utf-8")
            mock_resp.encoding = "utf-8"
            mock_get.return_value = mock_resp
            result = scrape_transit_status("https://example.com/track/MAEU123")
        self.assertEqual(result.transit_status, "in_transit")
        self.assertEqual(result.source, "html")
        self.assertIsNone(result.error)

    def test_scrape_parses_embedded_next_data(self):
        import json as json_mod

        from inventory.transit_scraper import scrape_transit_status

        next_data = {
            "props": {
                "pageProps": {
                    "tracking": {"status": "Delivered", "vessel": "MSC LENA"}
                }
            }
        }
        html = (
            '<html><head><script id="__NEXT_DATA__" type="application/json">'
            + json_mod.dumps(next_data)
            + "</script></head><body></body></html>"
        )
        with patch(
            "inventory.transit_scraper.requests.get"
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"Content-Type": "text/html"}
            mock_resp.content = html.encode("utf-8")
            mock_resp.encoding = "utf-8"
            mock_get.return_value = mock_resp
            result = scrape_transit_status("https://example.com/track/MAEU123")
        self.assertEqual(result.transit_status, "delivered")
        self.assertEqual(result.source, "embedded-json")

    def test_scrape_http_error(self):
        from inventory.transit_scraper import scrape_transit_status

        with patch("inventory.transit_scraper.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_get.return_value = mock_resp
            with patch(
                "inventory.transit_scraper._browser_fetch_status"
            ) as mock_browser:
                mock_browser.return_value = None
                result = scrape_transit_status("https://example.com/track/X")
        self.assertIsNone(result.transit_status)
        self.assertIn("404", result.error)
        mock_browser.assert_not_called()  # 404 = bad URL, browser won't help

    def test_scrape_403_falls_back_to_browser(self):
        from inventory.transit_scraper import ScrapeResult, scrape_transit_status

        with patch("inventory.transit_scraper.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_resp.content = b"Please enable JS to continue (DataDome)"
            mock_resp.encoding = "utf-8"
            mock_resp.headers = {"Content-Type": "text/html"}
            mock_get.return_value = mock_resp
            with patch(
                "inventory.transit_scraper._browser_fetch_status"
            ) as mock_browser:
                mock_browser.return_value = ScrapeResult(
                    "in_transit", "Vessel departed", "browser", None
                )
                result = scrape_transit_status(
                    "https://example.com/track/{bl}", bl_number="BL1"
                )
        self.assertEqual(result.transit_status, "in_transit")
        self.assertEqual(result.source, "browser")
        mock_browser.assert_called_once_with("https://example.com/track/{bl}", "BL1")

    def test_scrape_browser_disabled_keeps_plain_error(self):
        from inventory.transit_scraper import scrape_transit_status

        with patch.dict("os.environ", {"BL_BROWSER_SCRAPER": "0"}):
            with patch("inventory.transit_scraper.requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 403
                mock_resp.content = b"Please enable JS to continue"
                mock_resp.encoding = "utf-8"
                mock_resp.headers = {"Content-Type": "text/html"}
                mock_get.return_value = mock_resp
                with patch(
                    "inventory.transit_scraper._browser_fetch_status"
                ) as mock_browser:
                    result = scrape_transit_status("https://example.com/t", "BL1")
        mock_browser.assert_not_called()
        self.assertIsNone(result.transit_status)
        self.assertIn("403", result.error)

    def test_scrape_browser_unavailable_keeps_plain_error(self):
        from inventory.transit_scraper import scrape_transit_status

        with patch("inventory.transit_scraper.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_resp.content = b"Please enable JS"
            mock_resp.encoding = "utf-8"
            mock_resp.headers = {"Content-Type": "text/html"}
            mock_get.return_value = mock_resp
            with patch(
                "inventory.transit_scraper._browser_fetch_status"
            ) as mock_browser:
                mock_browser.return_value = None  # e.g. Chrome not installed
                result = scrape_transit_status("https://example.com/t", "BL1")
        self.assertIsNone(result.transit_status)
        self.assertIn("403", result.error)

    def test_parse_status_not_found_returns_error(self):
        from inventory.transit_scraper import _parse_status_from_text

        result = _parse_status_from_text(
            "Container search: Your shipment was not found. "
            "Please check your reference and try again.",
            "browser",
        )
        self.assertIsNone(result.transit_status)
        self.assertIn("not found", (result.error or "").lower())

    def test_parse_status_not_found_but_status_phrase_wins(self):
        from inventory.transit_scraper import _parse_status_from_text

        # A real status phrase that happens to coexist with "not found" text
        # should still map to a status.
        result = _parse_status_from_text(
            "History: booking not found earlier, now Loaded on board vessel",
            "html",
        )
        self.assertEqual(result.transit_status, "in_transit")

    def test_page_without_reference_never_yields_a_status(self):
        from inventory.transit_scraper import _parse_status_from_text

        # Marketing/schedule copy says "at destination" but this is not the
        # shipment page for CULV7654321.
        result = _parse_status_from_text(
            "Our services cover every leg, from origin port to the destination "
            "port. Containers are available at destination terminals on arrival.",
            "html",
            "CULV7654321",
        )
        self.assertIsNone(result.transit_status)
        self.assertIn("was not found on the tracking page", result.error or "")
        self.assertIsNone(result.details)

    def test_reference_match_ignores_spacing_and_case(self):
        from inventory.transit_scraper import _parse_status_from_text

        result = _parse_status_from_text(
            "B/L medu 7654321: Container discharged at Djibouti terminal.",
            "html",
            "MEDU7654321",
        )
        self.assertEqual(result.transit_status, "at_destination")

    def test_generic_details_ignore_navigation_copy(self):
        from inventory.tracking_details import extract_generic_details

        details = extract_generic_details(
            "mentTrack Shipment Now Self-Services About Us ping End-To-End "
            "Solutions Air Freight News TRACK / TRACE"
        )
        self.assertNotIn("vessel_name", details)
        self.assertNotIn("vessel_voyage", details)


class CarrierRegistryTests(TestCase):
    def test_resolve_msc_by_name(self):
        from inventory.carriers import resolve_carrier

        profile = resolve_carrier("Mediterranean Shipping Company", None)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.key, "msc")
        self.assertEqual(profile.hard_adapter, "msc")

    def test_resolve_msc_by_url_host(self):
        from inventory.carriers import resolve_carrier

        profile = resolve_carrier(None, "https://www.msc.com/en/track-a-shipment")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.key, "msc")

    def test_resolve_maersk_uses_adapter_with_browser_fallback(self):
        from inventory.carriers import resolve_carrier

        profile = resolve_carrier("Maersk Line", "https://www.maersk.com/tracking/{bl}")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.key, "maersk")
        # curl_cffi adapter first (often Akamai-403), browser fallback after.
        self.assertEqual(profile.hard_adapter, "maersk")

    def test_resolve_cma_by_host(self):
        from inventory.carriers import resolve_carrier

        profile = resolve_carrier(
            "CMA CGM", "https://www.cma-cgm.com/ebusiness/tracking?reference={bl}"
        )
        self.assertIsNotNone(profile)
        self.assertEqual(profile.key, "cma-cgm")

    def test_resolve_hapag(self):
        from inventory.carriers import resolve_carrier

        profile = resolve_carrier("Hapag-Lloyd", None)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.key, "hapag-lloyd")

    def test_resolve_pil(self):
        from inventory.carriers import resolve_carrier

        profile = resolve_carrier("PIL", "https://www.pilship.com/digital-solutions/?x={bl}")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.key, "pil")

    def test_resolve_unknown_returns_none(self):
        from inventory.carriers import resolve_carrier

        self.assertIsNone(resolve_carrier("Some Local Trucking", "https://example.com"))


class HardCarrierMSCAdapterTests(TestCase):
    def _msc_payload(self):
        return {
            "IsSuccess": True,
            "Data": {
                "BillOfLadings": [
                    {
                        "BillOfLadingNumber": "MEDUACR61912",
                        "GeneralTrackingInfo": {
                            "ShippedFrom": "NINGBO, CN",
                            "ShippedTo": "GDANSK, PL",
                        },
                        "ContainersInfo": [
                            {
                                "ContainerNumber": "MSDU6574161",
                                "PodEtaDate": "31/10/2026",
                                "Events": [
                                    {
                                        "Order": 1,
                                        "Description": "Empty to Shipper",
                                        "Location": "DAMAIYU, CN",
                                        "Detail": ["EMPTY"],
                                        "Date": "01/10/2026",
                                    },
                                    {
                                        "Order": 2,
                                        "Description": "Gate In",
                                        "Location": "NINGBO, CN",
                                        "Detail": ["EMPTY"],
                                        "Date": "02/10/2026",
                                    },
                                    {
                                        "Order": 3,
                                        "Description": "Loaded on Board",
                                        "Location": "NINGBO, CN",
                                        "Detail": ["MSC DENMARK VI", "NY603R"],
                                        "Date": "05/10/2026",
                                    },
                                ],
                            }
                        ],
                    }
                ]
            },
        }

    def test_map_msc_description(self):
        from inventory.hard_carriers import _map_msc_description

        self.assertEqual(_map_msc_description("Loaded on Board"), "in_transit")
        self.assertEqual(_map_msc_description("Discharged"), "at_destination")
        self.assertEqual(_map_msc_description("Cargo Released"), "delivered")
        self.assertEqual(_map_msc_description("Empty to Shipper"), "pending")
        self.assertIsNone(_map_msc_description("Something odd"))

    def test_parse_msc_date(self):
        from inventory.hard_carriers import _parse_msc_date

        self.assertEqual(_parse_msc_date("31/10/2026"), "2026-10-31")
        self.assertIsNone(_parse_msc_date("not-a-date"))

    def test_track_msc_parses_success_payload(self):
        from inventory.carriers import ScrapedTransit
        from inventory.hard_carriers import track_msc

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._msc_payload()

        mock_session = MagicMock()
        mock_session.get.return_value = MagicMock(status_code=200)
        mock_session.post.return_value = mock_resp

        with patch.dict("os.environ", {"CURL_CFFI_ENABLED": "1"}):
            with patch(
                "curl_cffi.requests.Session",
                return_value=mock_session,
            ):
                result = track_msc("MSDU6574161")

        self.assertIsInstance(result, ScrapedTransit)
        self.assertEqual(result.transit_status, "in_transit")
        self.assertEqual(result.source, "msc-api")
        self.assertEqual(result.vessel_name, "MSC DENMARK VI")
        self.assertEqual(result.eta_text, "2026-10-31")
        self.assertIn("MSDU6574161", result.containers)
        self.assertIn("NINGBO", result.status_detail or "")

    def test_track_msc_disabled_when_env_off(self):
        from inventory.hard_carriers import track_msc

        with patch.dict("os.environ", {"CURL_CFFI_ENABLED": "0"}):
            result = track_msc("MSDU6574161")
        self.assertIsNone(result.transit_status)
        self.assertIn("disabled", (result.error or "").lower())

    def test_track_msc_unsuccessful(self):
        from inventory.hard_carriers import track_msc

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"IsSuccess": False, "Data": None}
        mock_session = MagicMock()
        mock_session.get.return_value = MagicMock(status_code=200)
        mock_session.post.return_value = mock_resp

        with patch.dict("os.environ", {"CURL_CFFI_ENABLED": "1"}):
            with patch("curl_cffi.requests.Session", return_value=mock_session):
                result = track_msc("BADREF000")
        self.assertIsNone(result.transit_status)
        self.assertIn("not find", (result.error or "").lower())

    def test_try_hard_carrier_unknown_adapter(self):
        from inventory.hard_carriers import try_hard_carrier

        self.assertIsNone(try_hard_carrier("nope", "X"))


class EslTrackingTests(TestCase):
    """ESL's public unified-tracking JSON API (no browser needed)."""

    def _payload(self, *, gate_location="Djibouti", gate_title="Gated Out"):
        def event(seq, title, classifier, when, location, code="GTOT"):
            return {
                "eventID": f"event-{seq}",
                "title": title,
                "eventType": "EQUIPMENT",
                "eventDateTime": when,
                "eventCreatedDateTime": when,
                "eventClassifierCode": classifier,
                "displaySequence": seq,
                "equipmentEventTypeCode": code,
                "equipmentReference": "ESLU9802845",
                "transportCall": {
                    "UNLocationCode": "DJJIB",
                    "modeOfTransport": "TRUCK",
                    "location": {"locationName": location},
                },
            }

        return {
            "contractVersion": "2.0",
            "outcome": "FOUND",
            "reference": {"value": "SAMCB26003830", "type": "BILL_OF_LADING"},
            "events": [
                event(1, "Planned final destination", "PLN", "2026-09-18T00:00:00.000Z", "DIRE DAWA", "GTIN"),
                event(2, "Loaded", "ACT", "2026-09-18T00:00:00.000Z", "NHAVA SHEVA", "LOAD"),
                event(3, gate_title, "ACT", "2026-10-05T00:00:00.000Z", gate_location),
                event(4, "Under Clearance", "ACT", "2026-09-28T00:00:00.000Z", "Djibouti", "GTIN"),
            ],
            "containers": [
                {
                    "containerNumber": "ESLU9802845",
                    "containerSize": "20",
                    "containerType": "GP",
                    "pol": "NHAVA SHEVA",
                    "pod": "Djibouti",
                    "destination": "ETDIR",
                    "status": "Ship on Board",
                    "vessel": "14",
                    "voyage": "140WB",
                }
            ],
            "shipment": {
                "blNo": "SAMCB26003830",
                "pol": "NHAVA SHEVA",
                "pod": "DJIBOUTI",
                "destination": "ETDIR",
                "vessel": "14",
                "voyage": "140WB",
            },
        }

    def test_normalize_esl_gated_out_at_destination(self):
        from inventory.tracking_details import normalize_esl

        details = normalize_esl(self._payload())
        self.assertEqual(details["transit_status"], "at_destination")
        self.assertEqual(details["origin"], "NHAVA SHEVA")
        self.assertEqual(details["destination"], "DIRE DAWA")
        self.assertEqual(details["source"], "esl-api")
        # Planned rows are not milestones; the 3 actual events remain.
        self.assertEqual(len(details["events"]), 3)
        self.assertEqual(
            [c["container_number"] for c in details["containers"]], ["ESLU9802845"]
        )
        # "14" is an internal vessel id, not a ship name.
        self.assertIsNone(details["vessel_name"])
        self.assertIn("Gated Out", details["last_event"])

    def test_normalize_esl_gated_out_at_origin_is_in_transit(self):
        from inventory.tracking_details import normalize_esl

        details = normalize_esl(self._payload(gate_location="NHAVA SHEVA"))
        self.assertEqual(details["transit_status"], "in_transit")

    def test_normalize_esl_gated_in_at_pod(self):
        from inventory.tracking_details import normalize_esl

        details = normalize_esl(self._payload(gate_title="Gated In"))
        self.assertEqual(details["transit_status"], "at_destination")

    def test_track_esl_parses_api_payload(self):
        from inventory.hard_carriers import track_esl

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._payload()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.dict("os.environ", {"CURL_CFFI_ENABLED": "1"}):
            with patch("curl_cffi.requests.Session", return_value=mock_session):
                result = track_esl("SAMCB26003830")

        self.assertEqual(result.transit_status, "at_destination")
        self.assertEqual(result.source, "esl-api")
        self.assertIsNone(result.error)
        self.assertIn("ESLU9802845", result.containers)
        self.assertIn("Gated Out", result.last_event or "")

    def test_track_esl_reports_unknown_reference(self):
        from inventory.hard_carriers import track_esl

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"outcome": "NOT_FOUND", "events": []}
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.dict("os.environ", {"CURL_CFFI_ENABLED": "1"}):
            with patch("curl_cffi.requests.Session", return_value=mock_session):
                result = track_esl("NOPE0000000")

        self.assertIsNone(result.transit_status)
        self.assertIn("could not find", (result.error or "").lower())

    def test_resolve_esl_by_host_and_name(self):
        from inventory.carriers import resolve_carrier

        by_host = resolve_carrier(
            "Some forwarder",
            "https://esl.et/en/tracking-unified?mode=import&reference=SAMCB26003830",
        )
        self.assertEqual(by_host.key, "esl")
        self.assertEqual(by_host.hard_adapter, "esl")
        self.assertEqual(resolve_carrier("Ethiopian Shipping and Logistics").key, "esl")


class TrackingDetailsTests(TestCase):
    def _maersk_payload(self):
        return {
            "tpdoc_num": "721632537",
            "last_update_time": "2026-10-26T10:00:00Z",
            "origin": {
                "city": "Antwerp",
                "terminal": "Antwerp Container Terminal 730",
                "country": "Belgium",
                "country_code": "BE",
            },
            "destination": {
                "city": "Djibouti",
                "terminal": "Djibouti Container Terminal SGTD",
                "country": "Djibouti",
                "country_code": "DJ",
            },
            "containers": [
                {
                    "container_num": "SELU4008090",
                    "container_size": "40",
                    "container_type": "Dry High",
                    "locations": [
                        {
                            "city": "Antwerp",
                            "terminal": "Antwerp Container Terminal 730",
                            "country": "Belgium",
                            "country_code": "BE",
                            "events": [
                                {
                                    "activity": "CONTAINER DEPARTURE",
                                    "event_time": "2026-08-18T00:00:00Z",
                                    "event_time_type": "ACTUAL",
                                    "vessel_name": "AL ZUBARA",
                                    "voyage_num": "636E",
                                }
                            ],
                        },
                        {
                            "city": "Salalah",
                            "terminal": "Salalah Terminal",
                            "country": "Oman",
                            "country_code": "OM",
                            "events": [
                                {
                                    "activity": "DISCHARG",
                                    "event_time": "2026-10-10T03:37:00Z",
                                    "event_time_type": "ACTUAL",
                                    "vessel_name": "AL ZUBARA",
                                    "voyage_num": "636E",
                                },
                                {
                                    "activity": "CONTAINER ARRIVAL",
                                    "event_time": "2026-10-29T22:00:00Z",
                                    "event_time_type": "EXPECTED",
                                    "vessel_name": "HUI DA 9",
                                    "voyage_num": "643N",
                                },
                            ],
                        },
                    ],
                }
            ],
        }

    def test_normalize_maersk_extracts_route_vessel_eta_events(self):
        from inventory.tracking_details import normalize_maersk, summarize_details

        details = normalize_maersk(self._maersk_payload())
        self.assertEqual(details["transit_status"], "at_destination")
        self.assertIn("Antwerp", details["origin"])
        self.assertIn("Djibouti", details["destination"])
        self.assertEqual(details["vessel_name"], "AL ZUBARA")
        self.assertEqual(details["vessel_voyage"], "636E")
        self.assertEqual(details["eta"], "2026-10-29T22:00:00Z")
        self.assertIn("DISCHARG", details["last_event"])
        self.assertEqual(details["containers"][0]["container_number"], "SELU4008090")
        self.assertTrue(details["events"])

        summary = summarize_details(details)
        self.assertIn("DISCHARG", summary)
        self.assertIn("AL ZUBARA/636E", summary)
        self.assertIn("ETA 29 Oct 2026 22:00", summary)
        self.assertIn("->", summary)

    def test_extract_maersk_rendered_text(self):
        from inventory.tracking_details import extract_generic_details

        text = (
            "BL number 721632537 ANTWERP, BE DJIBOUTI, DJ 1 container "
            "SELU4008090 40' Dry High ANTWERP, BE Departs ANTWERP CONTAINER "
            "TERMINAL 730 18 Aug 2026 DJIBOUTI, DJ Arrives DJIBOUTI CONTAINER "
            "TERMINAL SGTD Note: All times are given in local time. "
            "Last updated: 1 day ago SALALAH SALALAH TERMINAL "
            "Discharge (AL ZUBARA / 636E) Latest event 10 Oct 2026 03:37 "
            "Feeder departure (HUI DA 9 / 643N) 27 Oct 2026 06:00 DJIBOUTI "
            "DJIBOUTI CONTAINER TERMINAL SGTD Feeder arrival (HUI DA 9 / 643N) "
            "29 Oct 2026 22:00"
        )
        details = extract_generic_details(text)
        self.assertEqual(details["vessel_name"], "AL ZUBARA")
        self.assertEqual(details["vessel_voyage"], "636E")
        self.assertIn("Discharge", details["last_event"])
        self.assertIn("10 Oct 2026", details["last_event"])
        self.assertIn("ANTWERP", details["origin"])
        self.assertIn("DJIBOUTI", details["destination"])
        self.assertEqual(details["eta"], "29 Oct 2026 22:00")

    def test_maersk_container_vessel_prefers_actual_events(self):
        from inventory.tracking_details import normalize_maersk

        details = normalize_maersk(self._maersk_payload())
        container = details["containers"][0]
        self.assertEqual(container["vessel"], "AL ZUBARA")
        self.assertEqual(container["voyage"], "636E")

    def test_noise_tooltip_does_not_map_to_pending(self):
        from inventory.transit_scraper import _parse_status_from_text

        text = (
            "title=View bookings, see latest tracking details, BL status, ETA "
            "updates and pending tasks with Manage Bookings."
        ) + (" filler" * 40)
        result = _parse_status_from_text(text, "browser")
        self.assertIsNone(result.transit_status)

    def test_track_maersk_403_mentions_browser(self):
        from inventory.hard_carriers import track_maersk

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_session = MagicMock()
        mock_session.get.return_value = MagicMock(status_code=200)
        mock_session.get.side_effect = [
            MagicMock(status_code=200),  # warm-up
            mock_resp,  # api
        ]
        # `session.get` is used for both warm-up and api call.
        with patch.dict("os.environ", {"CURL_CFFI_ENABLED": "1"}):
            with patch("curl_cffi.requests.Session", return_value=mock_session):
                result = track_maersk("721632537")
        self.assertIsNone(result.transit_status)
        self.assertIn("browser", (result.error or "").lower())


class CheckStatusCarrierWiringTests(TestCase):
    def _make_msc_bl(self):
        from inventory.models import BillOfLading, BillOfLadingContainer, Purchase

        purchase = Purchase.objects.create(
            purchase_number="MPDDFZMSC1",
            proforma_ref_no="PF-MSC1",
            buyer="MSC Buyer",
            order_date=date.today(),
            shipper="MSC Supplier",
            country_of_origin="China",
            final_destination="Ethiopia",
            port_of_loading="Ningbo",
            port_of_discharge="Djibouti",
            payment_terms="TT",
            mode_of_transport="Sea",
            shipment_type="FCL",
            status="approved",
        )
        bl = BillOfLading.objects.create(
            purchase=purchase,
            bl_number="MEDUACR61912",
            bl_date=date.today(),
            container_count=1,
            shipping_company_name="Mediterranean Shipping Company",
            shipping_company_url="https://www.msc.com/en/track-a-shipment",
        )
        BillOfLadingContainer.objects.create(
            bill_of_lading=bl,
            container_number="MSDU6574161",
            size="40",
            cargo_type="non_hazardous",
        )
        return bl

    def test_check_status_uses_msc_adapter_and_updates_status(self):
        from inventory.api import check_purchase_bl_status
        from inventory.carriers import ScrapedTransit

        bl = self._make_msc_bl()
        fake = ScrapedTransit(
            transit_status="in_transit",
            status_detail="Loaded on Board @ NINGBO, CN; ETA 2026-10-31",
            source="msc-api",
            error=None,
            vessel_name="MSC DENMARK VI",
            eta_text="2026-10-31",
            containers=["MSDU6574161"],
        )

        request = MagicMock()

        with patch("inventory.api._require_roles", return_value=None):
            with patch(
                "inventory.hard_carriers.try_hard_carrier", return_value=fake
            ) as mock_try:
                with patch("inventory.api._start_ais_lookup", return_value=None):
                    with patch(
                        "inventory.api._build_bl_tracking_url",
                        return_value="https://www.msc.com/en/track-a-shipment",
                    ):
                        response = check_purchase_bl_status(request, "MPDDFZMSC1")

        bl.refresh_from_db()
        self.assertEqual(bl.transit_status, "in_transit")
        self.assertEqual(bl.vessel_name, "MSC DENMARK VI")
        self.assertEqual(response.scrape_source, "msc-api")
        self.assertEqual(response.transit_status, "in_transit")
        mock_try.assert_called_once()

    def test_reference_not_found_clears_stale_shipment_data(self):
        from inventory.api import check_purchase_bl_status
        from inventory.transit_scraper import ScrapeResult

        bl = self._make_msc_bl()
        bl.transit_status = "at_destination"
        bl.status_detail = "stale detail from an older scrape"
        bl.tracking_details = {"origin": "OLD PORT", "vessel_name": "STALE VESSEL"}
        bl.vessel_name = "STALE VESSEL"
        bl.save()

        missing = ScrapeResult(
            None,
            None,
            "browser",
            "Reference MEDUACR61912 was not found on the tracking page. "
            "Check the BL / container number and the shipping line.",
        )
        request = MagicMock()
        with patch("inventory.api._require_roles", return_value=None):
            with patch(
                "inventory.hard_carriers.try_hard_carrier", return_value=None
            ):
                with patch("inventory.api._start_ais_lookup", return_value=None):
                    with patch(
                        "inventory.transit_scraper.scrape_transit_status",
                        return_value=missing,
                    ):
                        response = check_purchase_bl_status(request, "MPDDFZMSC1")

        bl.refresh_from_db()
        self.assertEqual(bl.transit_status, "pending")
        self.assertIsNone(bl.status_detail)
        self.assertEqual(bl.tracking_details, {})
        self.assertIsNone(bl.vessel_name)
        self.assertIn("was not found on the tracking page", response.scrape_error or "")

    def test_ais_enrichment_soft_overrides_to_in_transit(self):
        from inventory.api import _apply_ais_enrichment
        from inventory.ais_stream import AisPosition
        from datetime import datetime, timezone as dt_tz

        bl = self._make_msc_bl()
        bl.transit_status = "pending"
        bl.vessel_mmsi = "563000000"
        bl.save(update_fields=["transit_status", "vessel_mmsi", "updated_at"])

        position = AisPosition(
            mmsi="563000000",
            lat=12.5,
            lng=43.1,
            sog=14.2,
            cog=310.0,
            nav_status="Under way using engine",
            last_seen_at=datetime.now(dt_tz.utc),
        )
        with patch("inventory.ais_stream.fetch_position", return_value=position):
            _apply_ais_enrichment(bl)

        bl.refresh_from_db()
        self.assertEqual(bl.transit_status, "in_transit")
        self.assertEqual(bl.ais_lat, 12.5)
        self.assertEqual(bl.ais_lng, 43.1)
        self.assertEqual(bl.ais_sog, 14.2)
        self.assertIsNotNone(bl.ais_last_seen_at)

    def test_ais_enrichment_skipped_without_mmsi(self):
        from inventory.api import _apply_ais_enrichment

        bl = self._make_msc_bl()
        bl.vessel_mmsi = None
        bl.ais_lat = None
        bl.save(update_fields=["vessel_mmsi", "ais_lat", "updated_at"])
        with patch("inventory.ais_stream.fetch_position") as mock_fetch:
            _apply_ais_enrichment(bl)
        mock_fetch.assert_not_called()

    def test_ais_enrichment_works_with_vessel_name_only(self):
        from inventory.api import _apply_ais_enrichment
        from inventory.ais_stream import AisPosition
        from datetime import datetime, timezone as dt_tz

        bl = self._make_msc_bl()
        bl.vessel_mmsi = None
        bl.vessel_name = "AL ZUBARA"
        bl.transit_status = "in_transit"
        bl.save(update_fields=["vessel_mmsi", "vessel_name", "transit_status", "updated_at"])

        position = AisPosition(
            mmsi="211886500",
            lat=30.1,
            lng=122.5,
            sog=10.7,
            cog=90.0,
            nav_status="0",
            last_seen_at=datetime.now(dt_tz.utc),
            name="AL ZUBARA",
        )
        with patch(
            "inventory.ais_stream.fetch_position", return_value=position
        ) as mock_fetch:
            _apply_ais_enrichment(bl)

        bl.refresh_from_db()
        self.assertEqual(bl.ais_lat, 30.1)
        self.assertEqual(bl.ais_lng, 122.5)
        self.assertEqual(bl.ais_sog, 10.7)
        kwargs = mock_fetch.call_args.kwargs
        self.assertEqual(kwargs.get("vessel_name"), "AL ZUBARA")
        self.assertEqual(kwargs.get("mmsi"), "")
