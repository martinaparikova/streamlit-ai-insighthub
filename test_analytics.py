import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import duckdb
import pandas as pd

from analytics import (
    ANALYTICS_SQL_TOOL,
    build_analytics_result,
    build_bounded_select_sql,
    get_llm_sql,
    get_local_plan,
    get_openai_api_key,
    normalize_plan,
    validate_read_only_sql,
)


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

    def test_overdue_invoices_by_company_groups_counts(self):
        result = build_analytics_result({"intent": "overdue_invoices_by_company", "segment": None, "city": None, "limit": None, "sort_order": "highest"})
        self.assertEqual(result["kind"], "table")
        self.assertIn("COUNT(i.invoice_id) AS overdue_invoice_count", result["sql"])
        self.assertIn("GROUP BY c.company_name, c.segment", result["sql"])

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

    def test_local_fallback_does_not_guess_for_unsupported_questions(self):
        with self.assertRaises(ValueError):
            get_local_plan("What was our customer retention rate?")

    def test_local_fallback_understands_count_follow_up(self):
        previous = {"intent": "overdue_invoice_list", "segment": None, "city": None, "limit": None, "sort_order": "highest"}
        plan = get_local_plan("I want the count, one number only.", previous)
        self.assertEqual(plan["intent"], "overdue_invoice_count")

    def test_local_fallback_understands_czech_company_count_follow_up(self):
        previous = {"intent": "overdue_invoice_list", "segment": None, "city": None, "limit": None, "sort_order": "highest"}
        plan = get_local_plan("Chtěla jsem ke každé firmě počet faktur.", previous)
        self.assertEqual(plan["intent"], "overdue_invoices_by_company")

    def test_process_api_key_has_priority(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "process-test-key"}, clear=False):
            self.assertEqual(get_openai_api_key(), "process-test-key")

    def test_llm_sql_tool_returns_a_flexible_query(self):
        response = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="submit_analytics_query",
                    arguments=json.dumps({
                        "sql": "SELECT city, COUNT(*) AS company_count FROM companies GROUP BY city",
                        "clarification": None,
                    }),
                )
            ]
        )
        create = Mock(return_value=response)
        fake_openai = SimpleNamespace(
            APIError=type("APIError", (Exception,), {}),
            OpenAI=lambda **_: SimpleNamespace(
                responses=SimpleNamespace(create=create),
            ),
        )
        history = [{"role": "user", "content": "Show companies by city"}]

        with patch("analytics.get_openai_api_key", return_value="test-key"), patch.dict("sys.modules", {"openai": fake_openai}):
            result = get_llm_sql("How many companies are in each city?", history)

        self.assertEqual(result["clarification"], None)
        self.assertIn("GROUP BY city", result["sql"])
        self.assertEqual(create.call_args.kwargs["tools"], [ANALYTICS_SQL_TOOL])
        self.assertIn("DuckDB SQL syntax and functions only", create.call_args.kwargs["instructions"])
        self.assertIn("SQLite functions such as julianday()", create.call_args.kwargs["instructions"])
        self.assertIn("CURRENT_DATE", create.call_args.kwargs["instructions"])
        request_input = json.loads(create.call_args.kwargs["input"])
        self.assertEqual(request_input["conversation"], history)

    def test_llm_sql_tool_can_ask_for_clarification(self):
        response = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="submit_analytics_query",
                    arguments=json.dumps({"sql": None, "clarification": "Which date range should I use?"}),
                )
            ]
        )
        create = Mock(return_value=response)
        fake_openai = SimpleNamespace(
            APIError=type("APIError", (Exception,), {}),
            OpenAI=lambda **_: SimpleNamespace(
                responses=SimpleNamespace(create=create),
            ),
        )

        with patch("analytics.get_openai_api_key", return_value="test-key"), patch.dict("sys.modules", {"openai": fake_openai}):
            result = get_llm_sql("What was our revenue?", [])

        self.assertIsNone(result["sql"])
        self.assertEqual(result["clarification"], "Which date range should I use?")

    def test_llm_sql_repair_receives_database_binding_error(self):
        response = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="submit_analytics_query",
                    arguments=json.dumps({
                        "sql": "SELECT COUNT(*) FROM invoices WHERE payment_status = 'Overdue'",
                        "clarification": None,
                    }),
                )
            ]
        )
        create = Mock(return_value=response)
        fake_openai = SimpleNamespace(
            APIError=type("APIError", (Exception,), {}),
            OpenAI=lambda **_: SimpleNamespace(
                responses=SimpleNamespace(create=create),
            ),
        )
        feedback = {
            "sql": "SELECT COUNT(*) FROM invoices WHERE status = 'Overdue'",
            "error": 'Referenced column "status" not found; candidate: "payment_status"',
        }

        with patch("analytics.get_openai_api_key", return_value="test-key"), patch.dict("sys.modules", {"openai": fake_openai}):
            result = get_llm_sql("kolik faktur je po splatnosti", [], feedback)

        self.assertIn("payment_status", result["sql"])
        request_input = json.loads(create.call_args.kwargs["input"])
        self.assertEqual(request_input["failed_query"], feedback["sql"])
        self.assertEqual(request_input["database_error"], feedback["error"])
        self.assertIn("Correct the query", create.call_args.kwargs["instructions"])

    def test_read_only_sql_validation_accepts_one_select(self):
        connection = duckdb.connect(":memory:")
        self.assertEqual(validate_read_only_sql("SELECT 1;", connection), "SELECT 1")
        connection.close()

    def test_lowercase_not_paid_filter_excludes_paid_rows(self):
        connection = duckdb.connect(":memory:")
        connection.register(
            "invoices",
            pd.DataFrame({
                "payment_status": ["Paid", "Overdue", "Paid", "Overdue"],
            }),
        )
        sql = build_bounded_select_sql(
            "SELECT payment_status FROM invoices WHERE payment_status != 'paid'",
            connection,
        )

        self.assertIn("payment_status != 'Paid'", sql)
        self.assertEqual(
            connection.execute(sql).fetchall(),
            [("Overdue",), ("Overdue",)],
        )
        connection.close()

    def test_read_only_sql_validation_rejects_writes_and_multiple_statements(self):
        connection = duckdb.connect(":memory:")
        for sql in (
            "UPDATE companies SET city = 'Brno'",
            "DELETE FROM companies",
            "INSERT INTO companies VALUES (1)",
            "CREATE TABLE another_table (id INTEGER)",
            "COPY (SELECT 1) TO 'result.csv'",
            "SELECT 1; SELECT 2",
        ):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_read_only_sql(sql, connection)
        connection.close()

    def test_bounded_select_caps_returned_rows(self):
        connection = duckdb.connect(":memory:")
        sql = build_bounded_select_sql("SELECT * FROM range(1000) AS data", connection, row_limit=25)
        rows = connection.execute(sql).fetchall()
        self.assertEqual(len(rows), 25)
        connection.close()

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