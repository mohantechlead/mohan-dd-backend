"""Unit tests for the AI assistant (no network, DB only where marked)."""

from django.test import SimpleTestCase

from ai_assistant.analytics import (
    _fill_monthly,
    _linear_projection,
    build_response,
)
from ai_assistant.planner import _filters_grounded, _operation_fits, parse_message
from ai_assistant.validators import validate_query_plan


class PlannerTests(SimpleTestCase):
    def test_count_orders_this_month(self):
        plan, confidence, _ = parse_message("How many orders did we receive this month?", [])
        self.assertEqual(plan["entity"], "order")
        self.assertEqual(plan["operation"], "count")
        self.assertTrue(plan["date_range"].get("start"))

    def test_top_products(self):
        plan, _, _ = parse_message("Show me the top 5 products by quantity.", [])
        self.assertIn(plan["entity"], {"item", "dn", "grn", "stock"})
        self.assertEqual(plan["operation"], "top_n")

    def test_ambiguous_list_asks_clarification(self):
        plan, _, note = parse_message("Show me the deliveries.", [])
        self.assertIsNone(plan)
        self.assertIn("date range", note.lower())

    def test_order_lookup(self):
        plan, _, _ = parse_message("Show me deliveries for order M1122.", [])
        self.assertEqual(plan["entity"], "dn")
        self.assertEqual(plan["filters"].get("order_number"), "M1122")

    def test_monthly_sales_trend_means_orders_by_month(self):
        plan, _, _ = parse_message("Monthly sales trend", [])
        self.assertEqual(plan["entity"], "order")
        self.assertEqual(plan["operation"], "group_count")
        self.assertEqual(plan["group_by"], "month")
        self.assertEqual(plan["chart"], "line")

    def test_monthly_trend_for_purchases(self):
        plan, _, _ = parse_message("Monthly sales trend, for purchases", [])
        self.assertEqual(plan["entity"], "purchase")
        self.assertEqual(plan["operation"], "group_count")
        self.assertEqual(plan["group_by"], "month")
        self.assertEqual(plan["chart"], "line")

    def test_over_delivered_goes_to_variances(self):
        plan, _, _ = parse_message(
            "by how much was it over delivered, and can you detect the issue as well", [])
        self.assertEqual(plan["entity"], "git")
        self.assertEqual(plan["operation"], "list")
        self.assertEqual(plan["filters"].get("variance_type"), "increased")

    def test_list_them_all_after_count_proceeds(self):
        first, _, _ = parse_message("how many orders there is", [])
        self.assertEqual(first["operation"], "count")
        history = [{"entity": "order", "filters": {}, "date_range": {},
                    "plan": first}]
        plan, _, note = parse_message("can you list them all", history)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["entity"], "order")
        self.assertEqual(plan["operation"], "list")
        self.assertEqual(note, "rule-based")

    def test_bare_list_still_asks_for_details(self):
        plan, _, note = parse_message("Show me the deliveries.", [])
        self.assertIsNone(plan)
        self.assertIn("date range", note.lower())

    def test_deep_analytics_returns_whole_brief(self):
        plan, _, _ = parse_message(
            "can you do a deep analytics and show me the whole thing "
            "so that it can help me make descisions", [])
        self.assertEqual(plan["entity"], "overview")
        self.assertEqual(plan["operation"], "brief")

    def test_predict_orders_is_forecast(self):
        plan, _, _ = parse_message("predict next month orders", [])
        self.assertEqual(plan["entity"], "order")
        self.assertEqual(plan["operation"], "forecast")
        self.assertEqual(plan["group_by"], "month")
        self.assertEqual(plan["chart"], "line")

    def test_decision_for_sales_is_scoped_advice(self):
        plan, _, _ = parse_message(
            "can you help me make a decision for the sales and orders", [])
        self.assertEqual(plan["entity"], "order")
        self.assertEqual(plan["operation"], "advise")

    def test_tell_me_about_payments(self):
        plan, _, _ = parse_message("Tell me about payments.", [], use_llm=False)
        self.assertEqual(plan["entity"], "payments")
        self.assertEqual(plan["operation"], "advise")

    def test_how_much_paid_last_month(self):
        plan, _, _ = parse_message("How much did we pay last month?", [], use_llm=False)
        self.assertEqual(plan["entity"], "payments")
        self.assertEqual(plan["operation"], "sum")
        self.assertTrue(plan["date_range"].get("start"))

    def test_pending_payments(self):
        plan, _, _ = parse_message("Show me pending payments.", [], use_llm=False)
        self.assertEqual(plan["entity"], "payments")
        self.assertEqual(plan["operation"], "list")
        self.assertEqual(plan["filters"].get("status"), "pending")

    def test_payments_by_supplier(self):
        plan, _, _ = parse_message("Show me payments by supplier.", [], use_llm=False)
        self.assertEqual(plan["entity"], "vendor_payment")
        self.assertEqual(plan["group_by"], "supplier_name")

    def test_payments_by_month(self):
        plan, _, _ = parse_message("Show me payments by month.", [], use_llm=False)
        self.assertEqual(plan["entity"], "payments")
        self.assertEqual(plan["group_by"], "month")
        self.assertEqual(plan["chart"], "line")

    def test_top_supplier_by_payments(self):
        plan, _, _ = parse_message(
            "Which supplier received the most payments?", [], use_llm=False)
        self.assertEqual(plan["entity"], "vendor_payment")
        self.assertEqual(plan["operation"], "top_n")

    def test_payments_this_year_count(self):
        plan, _, _ = parse_message(
            "How many payments were made this year?", [], use_llm=False)
        self.assertEqual(plan["entity"], "payments")
        self.assertEqual(plan["operation"], "count")
        self.assertTrue(plan["date_range"].get("start", "").startswith("2026"))

    def test_bare_order_digits(self):
        plan, _, _ = parse_message("Show me order 22722.", [], use_llm=False)
        self.assertEqual(plan["entity"], "order")
        self.assertEqual(plan["filters"].get("order_number_contains"), "22722")

    def test_deliveries_for_it_resolves_order(self):
        first, _, _ = parse_message("Show me order M9001.", [], use_llm=False)
        history = [{"entity": "order", "message": "Show me order M9001.",
                    "filters": {"order_number": "M9001"}, "date_range": {},
                    "plan": first}]
        plan, _, _ = parse_message("What was delivered for it?", history, use_llm=False)
        self.assertEqual(plan["entity"], "dn")
        self.assertEqual(plan["filters"].get("order_number"), "M9001")

    def test_fulfilment_question(self):
        first, _, _ = parse_message("Show me order M9001.", [], use_llm=False)
        history = [{"entity": "order", "message": "Show me order M9001.",
                    "filters": {"order_number": "M9001"}, "date_range": {},
                    "plan": first}]
        plan, _, _ = parse_message(
            "How much of that order has been delivered?", history, use_llm=False)
        self.assertEqual(plan["entity"], "order")
        self.assertEqual(plan["operation"], "fulfilment")
        self.assertEqual(plan["filters"].get("order_number"), "M9001")

    def test_compare_without_area_asks_specifically(self):
        plan, _, note = parse_message("Compare this month with last month.", [], use_llm=False)
        self.assertIsNone(plan)
        self.assertIn("orders", note)

    def test_bare_trend_asks_specifically(self):
        plan, _, note = parse_message("Show me the trend.", [], use_llm=False)
        self.assertIsNone(plan)
        self.assertIn("chart", note)

    def test_private_fields_refused(self):
        plan, _, note = parse_message("Show me customer phone numbers.", [], use_llm=False)
        self.assertIsNone(plan)
        self.assertIn("private", note)

    def test_customers_most_orders_not_payments(self):
        plan, _, _ = parse_message(
            "Which customers had the most orders?", [], use_llm=False)
        self.assertEqual(plan["entity"], "order")
        self.assertEqual(plan["operation"], "top_n")

    def test_ungrounded_llm_filter_rejected(self):
        plan = {"entity": "vendor_payment", "operation": "sum",
                "field": "amount", "group_by": None,
                "filters": {"status": "completed"}, "date_range": {},
                "limit": None, "chart": "none"}
        self.assertFalse(_filters_grounded(
            plan, "which supplier received the most payments?"))

    def test_grounded_llm_filter_accepted(self):
        plan = {"entity": "order", "operation": "list",
                "field": None, "group_by": None,
                "filters": {"order_number": "M9001"}, "date_range": {},
                "limit": 20, "chart": "none"}
        self.assertTrue(_filters_grounded(plan, "show me order m9001"))

    def test_wrong_operation_type_rejected(self):
        plan = {"entity": "vendor_payment", "operation": "list",
                "field": None, "group_by": None, "filters": {},
                "date_range": {}, "limit": 20, "chart": "none"}
        self.assertFalse(_operation_fits(
            plan, "which supplier received the most payments?"))
        plan["operation"] = "top_n"
        self.assertTrue(_operation_fits(
            plan, "which supplier received the most payments?"))

    def test_something_critical_scans_everything(self):
        plan, _, _ = parse_message("can you tell me something critical", [])
        self.assertEqual(plan["entity"], "overview")
        self.assertEqual(plan["operation"], "advise")

    def test_payments_capabilities_question(self):
        plan, _, _ = parse_message("what can you answer about payments", [])
        self.assertEqual(plan["entity"], "payments")
        self.assertEqual(plan["operation"], "capabilities")

    def test_payment_detail_is_payments_advice(self):
        plan, _, _ = parse_message(
            "I meant payment can you tell me about that in detail", [])
        self.assertEqual(plan["entity"], "payments")
        self.assertEqual(plan["operation"], "advise")

    def test_followup_line_graph_continues_context(self):
        first, _, _ = parse_message("Monthly sales trend, for purchases", [])
        history = [{"entity": "purchase", "filters": {}, "date_range": {},
                    "plan": first}]
        plan, _, note = parse_message(
            "can you show me the line graph do an analytics", history)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["entity"], "purchase")
        self.assertEqual(plan["group_by"], "month")
        self.assertEqual(plan["chart"], "line")
        self.assertEqual(note, "continued")


class ValidatorTests(SimpleTestCase):
    def test_rejects_unknown_entity(self):
        ok, _ = validate_query_plan({"entity": "salary", "operation": "count"})
        self.assertFalse(ok)

    def test_rejects_forbidden_field(self):
        ok, _ = validate_query_plan({
            "entity": "order", "operation": "list",
            "filters": {"bank": "x"},
        })
        self.assertFalse(ok)

    def test_rejects_huge_limit(self):
        ok, _ = validate_query_plan({
            "entity": "order", "operation": "list", "limit": 10000,
        })
        self.assertFalse(ok)

    def test_allows_month_grouping(self):
        ok, error = validate_query_plan({
            "entity": "dn", "operation": "group_count", "group_by": "month",
        })
        self.assertTrue(ok, error)


class AnalyticsTests(SimpleTestCase):
    def test_count_headline_uses_real_number(self):
        plan = {"entity": "order", "operation": "count", "filters": {},
                "date_range": {"start": "2026-09-01", "end": "2026-09-30"}}
        message, _, viz = build_response(plan, [{"value": 142}], {}, False)
        self.assertIn("142", message)
        self.assertEqual(viz["type"], "none")

    def test_group_chart_from_rows(self):
        plan = {"entity": "order", "operation": "group_count",
                "group_by": "status", "filters": {}, "date_range": {},
                "chart": "bar"}
        rows = [{"group": "pending", "value": 10}, {"group": "approved", "value": 5}]
        message, _, viz = build_response(plan, rows, {}, False)
        self.assertEqual(viz["type"], "bar")
        self.assertEqual(len(viz["series"]), 2)
        self.assertIn("pending", message)

    def test_projection_rises_with_upward_trend(self):
        self.assertGreater(_linear_projection([2.0, 4.0, 6.0]), 6.0)

    def test_projection_needs_history(self):
        self.assertIsNone(_linear_projection([0.0, 0.0, 0.0]))
        self.assertIsNone(_linear_projection([5.0]))

    def test_fill_monthly_completes_gaps(self):
        filled = _fill_monthly([{"group": "2026-09-01", "value": 3.0}], n=3)
        self.assertEqual(len(filled), 3)
        self.assertEqual(sum(r["value"] for r in filled), 3.0)

    def test_forecast_without_history_says_so(self):
        plan = {"entity": "order", "operation": "forecast", "filters": {},
                "date_range": {}, "chart": "line"}
        message, _, viz = build_response(plan, [], {}, False)
        self.assertIn("isn't enough history", message)
        self.assertEqual(viz["type"], "line")

    def test_brief_lists_watchouts_from_real_flags(self):
        plan = {"entity": "overview", "operation": "brief", "filters": {},
                "date_range": {}, "chart": "line"}
        rows = [{"area": "Sales orders", "detail": "3 in total"}]
        provenance = {"by_status": {"pending": 2}, "money": {},
                      "watchouts": ["2 orders are still waiting for approval."],
                      "monthly": []}
        message, _, viz = build_response(plan, rows, provenance, False)
        self.assertIn("full picture", message)
        self.assertIn("waiting for approval", message)
        self.assertEqual(viz["type"], "line")

    def test_advise_names_oldest_waiting_order(self):
        plan = {"entity": "order", "operation": "advise", "filters": {},
                "date_range": {}, "chart": "line"}
        rows = [{"area": "Sales orders", "detail": "3 in total"}]
        provenance = {
            "monthly": [{"group": "2026-09-01", "value": 2.0}],
            "spotlight": [{"ref": "M9002", "party": "DEMO CUSTOMER TWO",
                           "date": "2026-09-12",
                           "detail": "M9002 for DEMO CUSTOMER TWO"}],
            "pending_count": 1,
        }
        message, data, viz = build_response(plan, rows, provenance, False)
        self.assertIn("M9002", message)
        self.assertIn("12 September 2026", message)
        self.assertIn("What I would do next", message)
        self.assertEqual(viz["type"], "line")
        self.assertEqual(data, provenance["spotlight"])
