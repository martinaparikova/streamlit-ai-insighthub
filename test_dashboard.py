import unittest

import duckdb

from dashboard import (
    add_card_to_page,
    add_dashboard,
    add_page,
    apply_filters_to_sql,
    apply_time_granularity,
    dashboard_by_id,
    dashboard_name_exists,
    normalize_dashboard,
    normalize_workspace,
    page_name_exists,
    parse_editor_command,
    previous_period_filters,
    restore_latest_dashboard_snapshot,
    save_dashboard_snapshot,
)


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
        self.assertIn("segment IN ('Enterprise')", filtered)
        self.assertIn("city IN ('Praha')", filtered)
        self.assertIn("invoice_date", filtered)
        self.assertIn("AS i", filtered)

    def test_filter_sql_adds_one_join_when_source_already_has_alias(self):
        sql = "SELECT i.product FROM invoices i WHERE 1 = 1"
        filtered = apply_filters_to_sql(sql, {"segments": [], "cities": ["Praha"], "date_from": None, "date_to": None, "period": "monthly"})
        self.assertEqual(filtered.count("SELECT company_id FROM companies"), 1)
        self.assertIn("AS i", filtered)

    def test_editor_adds_page_and_edits_selected_card(self):
        document = normalize_dashboard([{"title": "Revenue", "kind": "bar", "sql": "SELECT 1", "x": "x", "y": "y"}])
        page = document["pages"][0]
        updated, notice = parse_editor_command(document, page["id"], "Přidej stránku Finance")
        self.assertEqual(updated["pages"][-1]["name"], "Finance")
        self.assertIn("Přidána", notice)

        card_id = page["cards"][0]["id"]
        updated, _ = parse_editor_command(document, page["id"], "Změň graf na line", card_id)
        self.assertEqual(updated["pages"][0]["cards"][0]["kind"], "line")

    def test_editor_changes_pie_color_without_treating_czech_barvy_as_bar_chart(self):
        document = normalize_dashboard([{"title": "Revenue by segment", "kind": "pie", "sql": "SELECT 1", "x": "x", "y": "y"}])
        page = document["pages"][0]
        card_id = page["cards"][0]["id"]

        updated, notice = parse_editor_command(document, page["id"], "Změň barvy v koláči na zelené", card_id)
        card = updated["pages"][0]["cards"][0]

        self.assertEqual(card["kind"], "pie")
        self.assertEqual(card["color"], "#0B3B2E")
        self.assertIn("barva", notice)

    def test_editor_applies_chart_type_and_color_from_one_instruction(self):
        document = normalize_dashboard([{"title": "Revenue", "kind": "bar", "sql": "SELECT 1", "x": "x", "y": "y"}])
        page = document["pages"][0]
        card_id = page["cards"][0]["id"]

        updated, _ = parse_editor_command(document, page["id"], "Změň graf na pie a nastav růžovou", card_id)
        card = updated["pages"][0]["cards"][0]

        self.assertEqual(card["kind"], "pie")
        self.assertEqual(card["color"], "#C2185B")

    def test_editor_renames_selected_card_without_changing_it_to_a_table(self):
        document = normalize_dashboard([{"title": "Lowest-revenue products", "kind": "bar", "sql": "SELECT 1", "x": "x", "y": "y"}])
        page = document["pages"][0]
        card_id = page["cards"][0]["id"]

        updated, notice = parse_editor_command(document, page["id"], "Uprav název tabulky na Number of invoices overdue", card_id)
        card = updated["pages"][0]["cards"][0]

        self.assertEqual(card["title"], "Number of invoices overdue")
        self.assertEqual(card["kind"], "bar")
        self.assertIn("název", notice)

    def test_editor_changes_type_only_for_explicit_change_chart_command(self):
        document = normalize_dashboard([{"title": "Revenue", "kind": "bar", "sql": "SELECT 1", "x": "x", "y": "y"}])
        page = document["pages"][0]
        card_id = page["cards"][0]["id"]

        updated, _ = parse_editor_command(document, page["id"], "Změň graf na tabulku", card_id)

        self.assertEqual(updated["pages"][0]["cards"][0]["kind"], "table")

    def test_legacy_cards_receive_full_width_layout_rows(self):
        document = normalize_dashboard([
            {"title": "Revenue", "kind": "bar", "sql": "SELECT 1", "x": "x", "y": "y"},
            {"title": "Pipeline", "kind": "bar", "sql": "SELECT 2", "x": "x", "y": "y"},
        ])

        layouts = [card["layout"] for card in document["pages"][0]["cards"]]
        self.assertEqual(layouts, [{"row": 0, "width": 12}, {"row": 1, "width": 12}])

    def test_editor_adds_text_block_and_changes_selected_card_width(self):
        document = normalize_dashboard([{"title": "Revenue", "kind": "bar", "sql": "SELECT 1", "x": "x", "y": "y"}])
        page = document["pages"][0]
        card_id = page["cards"][0]["id"]

        updated, _ = parse_editor_command(document, page["id"], "Přidej komentář: Tržby rostou díky Enterprise.")
        text_card = updated["pages"][0]["cards"][-1]
        self.assertEqual(text_card["kind"], "text")
        self.assertEqual(text_card["text"], "Tržby rostou díky Enterprise.")

        updated, _ = parse_editor_command(document, page["id"], "Dej kartu vedle jiné karty", card_id)
        self.assertEqual(updated["pages"][0]["cards"][0]["layout"]["width"], 6)

    def test_previous_period_has_the_same_inclusive_length(self):
        previous = previous_period_filters({"date_from": "2026-02-01", "date_to": "2026-04-30", "segments": ["Enterprise"]})
        self.assertEqual(previous["date_from"], "2025-11-04")
        self.assertEqual(previous["date_to"], "2026-01-31")
        self.assertEqual(previous["segments"], ["Enterprise"])

    def test_editor_sets_page_period(self):
        document = normalize_dashboard([])
        page = document["pages"][0]
        updated, _ = parse_editor_command(document, page["id"], "Nastav weekly")
        self.assertEqual(updated["pages"][0]["filters"]["period"], "weekly")

    def test_chat_card_is_added_to_the_selected_page(self):
        document = normalize_dashboard([])
        overview = document["pages"][0]
        finance = {"id": "finance", "name": "Finance", "filters": {}, "cards": []}
        document["pages"].append(finance)
        card = {"title": "Overdue invoices", "kind": "table", "sql": "SELECT 1", "x": "value", "y": "value"}

        added_page = add_card_to_page(document, "finance", card)

        self.assertEqual(added_page["name"], "Finance")
        self.assertEqual(overview["cards"], [])
        self.assertEqual(added_page["cards"][0]["title"], "Overdue invoices")
        self.assertEqual(added_page["cards"][0]["kind"], "table")

    def test_adding_chat_card_rejects_unknown_page(self):
        document = normalize_dashboard([])
        with self.assertRaises(ValueError):
            add_card_to_page(document, "missing-page", {"title": "Result", "sql": "SELECT 1"})

    def test_dashboard_name_check_ignores_case_and_surrounding_spaces(self):
        document = normalize_dashboard(None)
        document["pages"][0]["name"] = "Finance"
        self.assertTrue(page_name_exists(document, " finance "))
        self.assertFalse(page_name_exists(document, "Sales"))
        self.assertFalse(page_name_exists(document, " "))

    def test_workspace_migration_preserves_all_legacy_pages_and_ids(self):
        legacy = normalize_dashboard([{
            "id": "card", "title": "Revenue", "kind": "bar", "sql": "SELECT 1",
        }])
        add_page(legacy, "Finance")
        legacy["pages"][0]["filters"]["cities"] = ["Praha"]
        workspace = normalize_workspace(legacy)
        self.assertEqual(workspace["version"], 4)
        self.assertEqual(len(workspace["dashboards"]), 1)
        dashboard = workspace["dashboards"][0]
        self.assertEqual(dashboard["name"], "Můj dashboard")
        self.assertEqual(dashboard["pages"], legacy["pages"])
        self.assertEqual(normalize_workspace(workspace), workspace)
        self.assertEqual(normalize_workspace(legacy), workspace)

    def test_dashboard_history_restores_latest_snapshot_for_only_that_dashboard(self):
        workspace = normalize_workspace(None)
        dashboard = workspace["dashboards"][0]
        original_name = dashboard["pages"][0]["name"]
        save_dashboard_snapshot(workspace, dashboard, "Přejmenování stránky")
        dashboard["pages"][0]["name"] = "Finance"

        restored = restore_latest_dashboard_snapshot(workspace, dashboard["id"])

        self.assertEqual(restored["pages"][0]["name"], original_name)
        self.assertEqual(workspace["dashboards"][0]["pages"][0]["name"], original_name)
        self.assertEqual(workspace["dashboard_history"], [])

    def test_workspace_migrates_legacy_cards(self):
        workspace = normalize_workspace([{"id": "one", "title": "Result", "sql": "SELECT 1"}])
        overview = workspace["dashboards"][0]["pages"][0]
        self.assertEqual(overview["name"], "Přehled")
        self.assertEqual(overview["cards"][0]["id"], "one")
        self.assertEqual(workspace["saved_chats"], [])

    def test_workspace_preserves_valid_saved_chats_and_ignores_invalid_entries(self):
        history = [{"role": "user", "content": "Kolik je faktur po splatnosti?"}]
        workspace = normalize_workspace({
            "version": 3,
            "dashboards": [{"id": "default", "name": "Můj dashboard", "pages": []}],
            "saved_chats": [
                {"id": "chat-1", "title": "  Po splatnosti  ", "history": history},
                {"id": "broken", "title": "Broken", "history": "not a list"},
            ],
        })

        self.assertEqual(workspace["saved_chats"], [{
            "id": "chat-1", "title": "Po splatnosti", "history": history,
        }])
        self.assertIsNot(workspace["saved_chats"][0]["history"], history)

    def test_dashboards_have_independent_pages_cards_and_filters(self):
        workspace = normalize_workspace(None)
        original = workspace["dashboards"][0]
        finance = add_dashboard(workspace, "Finance")
        revenue = add_page(finance, "Tržby")
        add_card_to_page(finance, revenue["id"], {"title": "Revenue", "sql": "SELECT 1"})
        finance["pages"][0]["filters"]["cities"] = ["Brno"]
        self.assertEqual([page["name"] for page in original["pages"]], ["Přehled"])
        self.assertEqual(original["pages"][0]["cards"], [])
        self.assertEqual(original["pages"][0]["filters"]["cities"], [])
        self.assertEqual(finance["pages"][0]["cards"], [])
        self.assertEqual(len(revenue["cards"]), 1)
        self.assertIs(dashboard_by_id(workspace, finance["id"]), finance)
        with self.assertRaises(ValueError):
            add_card_to_page(original, revenue["id"], {"sql": "SELECT 1"})
        with self.assertRaises(ValueError):
            dashboard_by_id(workspace, "missing")

    def test_dashboard_names_are_validated_separately_from_page_names(self):
        workspace = normalize_workspace(None)
        add_page(workspace["dashboards"][0], "Finance")
        finance = add_dashboard(workspace, " Finance ")
        self.assertEqual(finance["name"], "Finance")
        self.assertTrue(dashboard_name_exists(workspace, " FINANCE "))
        self.assertFalse(page_name_exists(finance, "Finance"))
        with self.assertRaises(ValueError):
            add_dashboard(workspace, "finance")
        with self.assertRaises(ValueError):
            add_dashboard(workspace, " ")

    def test_editor_changes_only_selected_dashboard_pages(self):
        workspace = normalize_workspace(None)
        finance = add_dashboard(workspace, "Finance")
        edited, _ = parse_editor_command(finance, finance["pages"][0]["id"], "Přidej stránku Tržby")
        finance["pages"] = edited["pages"]
        restored = normalize_workspace(workspace)
        self.assertEqual([page["name"] for page in restored["dashboards"][0]["pages"]], ["Přehled"])
        self.assertEqual([page["name"] for page in restored["dashboards"][1]["pages"]], ["Přehled", "Tržby"])

    def test_weekly_granularity_rewrites_known_monthly_query(self):
        monthly = "SELECT strftime(CAST(i.invoice_date AS DATE), '%Y-%m') AS month FROM invoices i GROUP BY month ORDER BY month"
        weekly = apply_time_granularity(monthly, "weekly")
        self.assertIn("date_trunc('week'", weekly)
        self.assertIn("GROUP BY week", weekly)
        self.assertIn("ORDER BY week", weekly)


class DashboardSqlFilterTests(unittest.TestCase):
    def setUp(self):
        self.connection = duckdb.connect()
        self.addCleanup(self.connection.close)
        self.connection.execute("""
            CREATE TABLE companies AS
            SELECT * FROM (VALUES
                (1, 'Alpha', 'Enterprise', 'Praha'),
                (2, 'Beta', 'SMB', 'Brno'),
                (3, 'Gamma', 'Enterprise', 'Praha')
            ) AS t(company_id, company_name, segment, city);
            CREATE TABLE invoices AS
            SELECT * FROM (VALUES
                (1, 1, DATE '2025-12-01', 'Overdue'),
                (2, 1, DATE '2026-03-01', 'Overdue'),
                (3, 1, DATE '2026-04-01', 'Paid'),
                (4, 2, DATE '2026-05-01', 'Overdue'),
                (5, 2, DATE '2027-01-01', 'Overdue')
            ) AS t(invoice_id, company_id, invoice_date, payment_status);
            CREATE TABLE opportunities AS
            SELECT invoice_id AS opportunity_id, company_id, invoice_date AS created_date
            FROM invoices;
        """)
        self.filters = {"date_from": "2026-01-01", "date_to": "2026-10-31"}

    def execute_filtered(self, sql, filters=None):
        return self.connection.execute(
            apply_filters_to_sql(sql, self.filters if filters is None else filters),
        ).fetchall()

    def test_unaliased_overdue_metric_with_date_filters(self):
        sql = "SELECT COUNT(*) FROM invoices WHERE payment_status = 'Overdue'"
        self.assertEqual(self.execute_filtered(sql), [(2,)])

    def test_filters_apply_without_where_and_with_aliases_and_suffixes(self):
        for source in ("invoices", "opportunities"):
            for alias in ("", " i", " AS custom_source", ' AS "custom source"'):
                for suffix in ("", ";", " ORDER BY 1 LIMIT 10"):
                    with self.subTest(source=source, alias=alias, suffix=suffix):
                        sql = f"SELECT COUNT(*) FROM {source}{alias}{suffix}"
                        self.assertEqual(self.execute_filtered(sql), [(3,)])

    def test_company_filters_with_or_without_existing_join(self):
        filters = {**self.filters, "cities": ["Praha"], "segments": ["Enterprise", "Other"]}
        for source in (
            "invoices",
            "invoices i",
            "invoices AS inv JOIN companies AS customer USING (company_id)",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.execute_filtered(f"SELECT COUNT(*) FROM {source}", filters), [(2,)])

    def test_filters_reach_both_union_branches_inside_bounded_query(self):
        sql = """SELECT * FROM (
            SELECT 'Total' AS company_name, COUNT(*) AS invoice_count
            FROM invoices WHERE payment_status = 'Overdue'
            UNION ALL
            SELECT c.company_name, COUNT(i.invoice_id)
            FROM companies c LEFT JOIN invoices i
                ON c.company_id = i.company_id AND i.payment_status = 'Overdue'
            GROUP BY c.company_name
        ) AS _bounded_result ORDER BY company_name LIMIT 500"""
        self.assertEqual(
            self.execute_filtered(sql),
            [("Alpha", 1), ("Beta", 1), ("Gamma", 0), ("Total", 2)],
        )

    def test_cte_shadowing_source_name_is_not_filtered_as_base_table(self):
        sql = "WITH invoices AS (SELECT COUNT(*) AS total FROM invoices) SELECT * FROM invoices"
        self.assertEqual(self.execute_filtered(sql), [(3,)])

    def test_existing_or_predicate_stays_inside_filters(self):
        sql = "SELECT COUNT(*) FROM invoices WHERE payment_status = 'Paid' OR payment_status = 'Overdue'"
        self.assertEqual(self.execute_filtered(sql), [(3,)])

    def test_no_filters_preserves_original_sql(self):
        sql = "SELECT COUNT(*) FROM invoices;"
        self.assertEqual(apply_filters_to_sql(sql, {}), sql)

    def test_unrelated_source_and_literals_are_not_rewritten(self):
        sql = "SELECT 'FROM invoices' AS description FROM companies ORDER BY company_id"
        self.assertEqual(self.execute_filtered(sql), [("FROM invoices",)] * 3)


if __name__ == "__main__":
    unittest.main()