from unittest.mock import MagicMock

from django.test import TestCase

from inventory.api import _filter_negative_items_for_trigger


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
