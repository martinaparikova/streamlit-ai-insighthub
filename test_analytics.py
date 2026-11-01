import os
import unittest
from unittest.mock import patch

from analytics import build_analytics_result, get_local_plan, get_openai_api_key, normalize_plan


class AnalyticsPlanTests(unittest.TestCase):
    def test_overdue_count_is_a_single_metric(self):
        result = build_analytics_result({"intent": "overdue_invoice_count", "segment": None, "city": None, "limit": None, "sort_order": "highest"})
        self.assertEqual(result["kind"], "metric")
        self.assertIn("COUNT(*) AS overdue_invoice_count", result["sql"])
        self.assertIn("payment_status = 'Overdue'", result["sql"])

    def test_overdue_list_uses_a_detail_query(self):
        result = build_analytics_result({"intent": "overdue_invoice_list", "segment": None, "city": None, "limit": None, "sort_order": "highest"})
        self.assertEqual(result["kind"], "table")
        self.assertIn("company_name AS company", result["sql"])
        self.assertIn("LIMIT 100", result["sql"])

    def test_overdue_total_uses_sum(self):
        result = build_analytics_result({"intent": "overdue_amount_total", "segment": "Enterprise", "city": None, "limit": None, "sort_order": "highest"})
        self.assertEqual(result["kind"], "metric")
        self.assertIn("SUM(i.net_amount_czk)", result["sql"])
        self.assertIn("c.segment = 'Enterprise'", result["sql"])

    def test_rejects_unapproved_filter_value(self):
        with self.assertRaises(ValueError):
            normalize_plan({"intent": "overdue_invoice_count", "segment": "Other", "city": None, "limit": None, "sort_order": "highest"})

    def test_local_fallback_understands_overdue_count(self):
        plan = get_local_plan("How many overdue invoices do we have?")
        self.assertEqual(plan["intent"], "overdue_invoice_count")

    def test_local_fallback_understands_overdue_total(self):
        plan = get_local_plan("What is the total overdue amount for Enterprise?")
        self.assertEqual(plan["intent"], "overdue_amount_total")
        self.assertEqual(plan["segment"], "Enterprise")

    def test_local_fallback_understands_count_follow_up(self):
        previous = {"intent": "overdue_invoice_list", "segment": None, "city": None, "limit": None, "sort_order": "highest"}
        plan = get_local_plan("I want the count, one number only.", previous)
        self.assertEqual(plan["intent"], "overdue_invoice_count")

    def test_process_api_key_has_priority(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "process-test-key"}, clear=False):
            self.assertEqual(get_openai_api_key(), "process-test-key")

    def test_local_fallback_understands_three_worst_products(self):
        previous = {"intent": "revenue_by_product", "segment": None, "city": None, "limit": None, "sort_order": "highest"}
        plan = get_local_plan("The are 3 with most revenue. I wanted 3 with the least revenue.", previous)
        result = build_analytics_result(plan)
        self.assertEqual(plan["intent"], "revenue_by_product")
        self.assertEqual(plan["sort_order"], "lowest")
        self.assertEqual(plan["limit"], 3)
        self.assertIn("ORDER BY revenue_czk ASC", result["sql"])


if __name__ == "__main__":
    unittest.main()