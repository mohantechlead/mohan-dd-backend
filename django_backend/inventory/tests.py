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
