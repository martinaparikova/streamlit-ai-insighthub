import unittest

from dashboard import apply_filters_to_sql, apply_time_granularity, normalize_dashboard, parse_editor_command


class DashboardTests(unittest.TestCase):
    def test_migrates_legacy_card_list_to_overview_page(self):
        document = normalize_dashboard([{"title": "Revenue", "kind": "bar", "sql": "SELECT 1", "x": "x", "y": "y"}])
        self.assertEqual(document["version"], 2)
        self.assertEqual(document["pages"][0]["name"], "Přehled")
        self.assertEqual(document["pages"][0]["cards"][0]["title"], "Revenue")
        self.assertIn("id", document["pages"][0]["cards"][0])

    def test_filter_sql_uses_only_whitelisted_values(self):
        sql = "SELECT i.product, SUM(i.net_amount_czk) AS revenue FROM invoices i WHERE 1 = 1 GROUP BY i.product"
        filtered = apply_filters_to_sql(sql, {"segments": ["Enterprise"], "cities": ["Praha"], "date_from": "2026-02-01", "date_to": "2026-04-30", "period": "monthly"})
        self.assertIn("JOIN companies c USING (company_id)", filtered)
        self.assertIn("c.segment IN ('Enterprise')", filtered)
        self.assertIn("c.city IN ('Praha')", filtered)
        self.assertIn("i.invoice_date", filtered)

    def test_editor_adds_page_and_edits_selected_card(self):
        document = normalize_dashboard([{"title": "Revenue", "kind": "bar", "sql": "SELECT 1", "x": "x", "y": "y"}])
        page = document["pages"][0]
        updated, notice = parse_editor_command(document, page["id"], "Přidej stránku Finance")
        self.assertEqual(updated["pages"][-1]["name"], "Finance")
        self.assertIn("Přidána", notice)

        card_id = page["cards"][0]["id"]
        updated, _ = parse_editor_command(document, page["id"], "Změň graf na line", card_id)
        self.assertEqual(updated["pages"][0]["cards"][0]["kind"], "line")

    def test_editor_sets_page_period(self):
        document = normalize_dashboard([])
        page = document["pages"][0]
        updated, _ = parse_editor_command(document, page["id"], "Nastav weekly")
        self.assertEqual(updated["pages"][0]["filters"]["period"], "weekly")

    def test_weekly_granularity_rewrites_known_monthly_query(self):
        monthly = "SELECT strftime(CAST(i.invoice_date AS DATE), '%Y-%m') AS month FROM invoices i GROUP BY month ORDER BY month"
        weekly = apply_time_granularity(monthly, "weekly")
        self.assertIn("date_trunc('week'", weekly)
        self.assertIn("GROUP BY week", weekly)
        self.assertIn("ORDER BY week", weekly)


if __name__ == "__main__":
    unittest.main()