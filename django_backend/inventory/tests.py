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
        return self.Purchase.objects.create(
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

    def test_transitor_advances_one_step_forward(self):
        self.purchase.assigned_transitor = self.transitor
        self.purchase.save()

        resp = self._post_stage("MPDDFZE901", {"stage": "ecd_im8"}, "pc_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["stage"], "ecd_im8")
        self.assertEqual(data["stage_label"], "ECD / IM8")
        self.assertEqual(data["stage_updated_by"], "pc_transitor")
        self.assertEqual(data["assigned_transitor"], "pc_transitor")
        self.assertIsNotNone(data["stage_updated_at"])

        resp = self._post_stage("MPDDFZE901", {"stage": "transit_permit"}, "pc_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["stage"], "transit_permit")
        self.assertEqual(resp.json()["stage_label"], "Transit Permit")

        resp = self._post_stage("MPDDFZE901", {"stage": "closure_guarantee"}, "pc_transitor")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["stage"], "closure_guarantee")
        self.assertEqual(resp.json()["stage_label"], "Closure Guarantee")

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
            resp = self._post_stage("MPDDFZE901", {"stage": step}, "pc_transitor")
            self.assertEqual(resp.status_code, 200, resp.content)
            self.assertEqual(resp.json()["stage"], step)

        resp = self._post_stage("MPDDFZE901", {"stage": "done"}, "pc_sales")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["stage"], "done")
        self.assertEqual(data["stage_label"], "Done")
        self.assertEqual(data["stage_updated_by"], "pc_sales")
