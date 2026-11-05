import unittest
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from dashboard import add_dashboard, add_page, normalize_workspace


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.key_patch = patch("analytics.get_openai_api_key", return_value=None)
        self.sql_patch = patch("analytics.get_llm_sql", return_value=None)
        self.key_patch.start()
        self.sql_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.addCleanup(self.sql_patch.stop)
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.store = Path(temporary_directory.name) / "dashboard.json"
        self.source = Path(__file__).with_name("app.py").read_text(encoding="utf-8").replace(
            "ROOT = Path(__file__).parent", f"ROOT = Path({str(Path(__file__).parent)!r})",
        ).replace(
            'STORE = ROOT / "storage" / "dashboard.json"', f"STORE = Path({str(self.store)!r})",
        ).replace(
            'if "language" not in st.session_state:\n    st.session_state.language = "en"',
            'if "language" not in st.session_state:\n    st.session_state.language = "cs"',
        ).replace(
            'st.session_state.get("language", "en")', 'st.session_state.get("language", "cs")',
        )
        self.app = AppTest.from_string(self.source, default_timeout=15).run()

    def assert_no_errors(self):
        self.assertEqual(list(self.app.exception), [])

    def open_dashboard_menu(self):
        if not any(item.label == "Vytvořit nový" for item in self.app.button):
            next(item for item in self.app.button if item.label == "Dashboardy").click().run()
        self.assert_no_errors()

    def start_dashboard_creation(self):
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Vytvořit nový").click().run()
        self.assert_no_errors()

    def select_dashboard_page(self, name):
        dashboard_id = self.app.session_state["active_dashboard_id"]
        page_id = self.app.session_state["active_dashboard_page"]
        self.app.session_state[f"dashboard-page-tabs-{dashboard_id}-{page_id}"] = name
        self.app.run()
        self.assert_no_errors()

    def ask(self, prompt, button="Zobrazit odpověď"):
        next(item for item in self.app.text_input if item.label == "Váš dotaz").input(prompt)
        next(item for item in self.app.button if item.label == button).click().run()
        self.assert_no_errors()

    def test_empty_chat_and_secondary_chart_action(self):
        self.assert_no_errors()
        heading = next(item.value for item in self.app.markdown if "chat-heading" in item.value and "<h1>" in item.value)
        self.assertIn("Co chcete zjistit ze svých dat?", heading)
        self.assertIn("Lokální data", heading)
        self.assertNotIn("AI je připravena", heading)
        self.assertIn("role='tooltip'", heading)
        self.assertIn("aria-describedby='chat-help'", heading)
        self.assertEqual(len(self.app.subheader), 0)
        self.assertEqual(len(self.app.expander), 1)
        self.assertEqual(self.app.expander[0].label, "Resetovat demo")
        self.assertTrue(any(item.label == "Dashboardy" for item in self.app.button))
        self.assertFalse(any(item.label == "Můj dashboard" for item in self.app.button))
        self.assertFalse(any(item.label == "Název nového dashboardu" for item in self.app.text_input))
        self.assertFalse(any(item.label == "Aktivní stránka" for item in self.app.radio))
        self.assertEqual(len(self.app.text_area), 0)
        buttons = {item.label: item.proto.type for item in self.app.button}
        self.assertEqual(buttons["Zobrazit odpověď"], "primary")
        self.assertEqual(buttons["Vytvořit graf"], "secondary")

    def test_work_in_progress_notice_is_visible_by_default_and_can_be_hidden(self):
        self.assert_no_errors()
        notice = next(
            item.value for item in self.app.markdown
            if "demo-project-notice__content" in item.value and "<h2>" in item.value
        )
        self.assertIn("Biizy je work in progress", notice)
        self.assertIn("Co aplikace umí", notice)
        self.assertIn("Jak na to", notice)
        self.assertIn("Plány", notice)
        self.assertIn("Přidejte ho na vybranou stránku dashboardu", notice)
        self.assertIn("martina.parikova@gmail.com", notice)
        self.assertNotIn(":material/construction:", notice)
        with Image.open(Path(__file__).parent / "assets" / "biizy_logo.png") as logo:
            self.assertEqual(logo.mode, "RGBA")
            self.assertLess(logo.getchannel("A").getextrema()[0], 255)
        self.assertTrue(any(item.label == "Skrýt" for item in self.app.button))

        next(item for item in self.app.button if item.label == "Skrýt").click().run()

        self.assert_no_errors()
        self.assertFalse(any(
            "demo-project-notice__content" in item.value and "<h2>" in item.value
            for item in self.app.markdown
        ))
        self.assertTrue(any(item.label == "Informace o projektu" for item in self.app.button))

        next(item for item in self.app.button if item.label == "Informace o projektu").click().run()

        self.assert_no_errors()
        self.assertTrue(any(
            "demo-project-notice__content" in item.value and "<h2>" in item.value
            for item in self.app.markdown
        ))

    def test_answer_preserves_native_chat_roles(self):
        self.ask("How many overdue invoices do we have?")
        self.assertEqual([item.name for item in self.app.chat_message], ["user", "assistant"])
        self.assertEqual(len(self.app.metric), 1)
        self.assertTrue(any("SQL" in item.label for item in self.app.expander))

    def test_catalog_error_retries_with_database_feedback(self):
        with patch(
            "analytics.get_llm_sql",
            side_effect=[
                {
                    "sql": """SELECT invoice_id, julianday(paid_date) - julianday(due_date) AS days_overdue
FROM invoices
WHERE payment_status = 'Overdue'
ORDER BY days_overdue DESC
LIMIT 5""",
                    "clarification": None,
                },
                {
                    "sql": """SELECT invoice_id,
       date_diff('day', CAST(due_date AS DATE), CURRENT_DATE) AS days_overdue
FROM invoices
WHERE payment_status = 'Overdue'
ORDER BY days_overdue DESC
LIMIT 5""",
                    "clarification": None,
                },
            ],
        ) as planner:
            self.ask("Chci 5 faktur, které mají nejdelší prodlení")

        self.assertEqual(planner.call_count, 2)
        repair_feedback = planner.call_args_list[1].kwargs["execution_feedback"]
        self.assertIn("julianday", repair_feedback["sql"])
        self.assertIn("julianday", repair_feedback["error"])
        self.assertTrue(any(item.label == "SQL trace — zobrazit skutečně vykonaný dotaz" for item in self.app.expander))
        self.assertFalse(any(item.value == "Dotaz se nepodařilo bezpečně připravit nebo vykonat. Zkuste otázku upřesnit. (CatalogException)" for item in self.app.error))

    def test_visualization_remains_available(self):
        self.ask("Show revenue by product.", button="Vytvořit graf")
        self.assertTrue(any(item.label == "Přidat do dashboardu" for item in self.app.button))
        self.assertEqual(len(self.app.get("plotly_chart")), 1)
        chart = json.loads(self.app.get("plotly_chart")[0].proto.spec)
        self.assertEqual(chart["layout"]["font"]["family"], "Plus Jakarta Sans")

    def test_chart_preserves_explicit_font_preference(self):
        self.ask("Show revenue by product, font Roboto.", button="Vytvořit graf")
        chart = json.loads(self.app.get("plotly_chart")[0].proto.spec)
        self.assertEqual(chart["layout"]["font"]["family"], "Roboto")

    def test_table_answer_can_choose_dashboard(self):
        with patch(
            "analytics.get_llm_sql",
            return_value={
                "sql": "SELECT 'Enterprise' AS segment, 42 AS invoice_count",
                "clarification": None,
            },
        ):
            self.ask("Show overdue invoices by segment.")

        add_button = next(item for item in self.app.button if item.label == "Přidat do dashboardu")
        add_button.click().run()

        self.assert_no_errors()
        dashboard_select = next(item for item in self.app.selectbox if item.label == "Dashboard")
        self.assertIn("Vytvořit nový", dashboard_select.options)
        self.assertTrue(any(item.label == "Stránka" for item in self.app.selectbox))
        self.assertTrue(any(item.label == "Přidat" for item in self.app.button))
        next(item for item in self.app.button if item.label == "Zrušit").click().run()
        self.assert_no_errors()
        self.assertFalse(any(item.label == "Dashboard" for item in self.app.selectbox))

    def test_chat_can_create_dashboard_and_add_result_to_it(self):
        self.ask("Show revenue by product.", button="Vytvořit graf")
        next(item for item in self.app.button if item.label == "Přidat do dashboardu").click().run()
        self.app.selectbox(key="dashboard-target-1").select("Vytvořit nový").run()
        self.app.text_input(key="dashboard-new-name-1").input("Finance")
        next(item for item in self.app.button if item.label == "Přidat").click().run()
        self.assert_no_errors()
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        finance = next(item for item in saved["dashboards"] if item["name"] == "Finance")
        self.assertEqual(len(finance["pages"]), 1)
        self.assertEqual(finance["pages"][0]["name"], "Přehled")
        self.assertEqual(len(finance["pages"][0]["cards"]), 1)
        self.assertEqual(self.app.session_state["active_dashboard_id"], finance["id"])
        self.assertEqual(self.app.session_state["active_dashboard_page"], finance["pages"][0]["id"])
        self.assertEqual(saved["dashboards"][0]["pages"][0]["cards"], [])
        self.assertTrue(any("„Finance“ na stránku „Přehled“" in item.value for item in self.app.success))

    def test_sql_answer_omits_redundant_labels_and_summary(self):
        self.app.session_state["chat_history"] = [{
            "role": "assistant", "mode": "answer",
            "result": {
                "kind": "query", "title": "Počet faktur", "sql": "SELECT 39 AS count",
                "summary": "Výsledek bezpečně spuštěného SQL dotazu pouze pro čtení.",
            },
        }]
        self.app.run()
        self.assert_no_errors()
        self.assertEqual(self.app.subheader[0].value, "Počet faktur")
        self.assertEqual(self.app.metric[0].value, "39")
        self.assertFalse(any("INSIGHT HUB" in item.value for item in self.app.caption))
        self.assertFalse(any("Výsledek bezpečně" in item.value for item in self.app.markdown))

    def test_new_conversation_clears_history_and_context(self):
        self.ask("How many overdue invoices do we have?")
        self.app.session_state["chat_notice"] = "Old notice"
        next(item for item in self.app.button if item.label == "Nová konverzace").click().run()
        self.assert_no_errors()
        self.assertEqual(len(self.app.chat_message), 0)
        self.assertIsNone(self.app.session_state["analysis_context"])
        self.assertIsNone(self.app.session_state["chat_notice"])

    def test_chat_can_be_saved_opened_renamed_and_updated(self):
        question = "How many overdue invoices do we have?"
        self.ask(question)
        next(item for item in self.app.button if item.label == "Uložit chat").click().run()
        self.assert_no_errors()

        saved = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["saved_chats"]), 1)
        saved_chat = saved["saved_chats"][0]
        self.assertEqual(saved_chat["title"], question)
        self.assertEqual(saved_chat["history"], self.app.session_state["chat_history"])

        next(item for item in self.app.button if item.label == "Nová konverzace").click().run()
        next(item for item in self.app.button if item.label == "Uložené chaty").click().run()
        next(item for item in self.app.button if item.label == question).click().run()
        self.assert_no_errors()
        self.assertEqual(self.app.session_state["chat_history"], saved_chat["history"])
        self.assertTrue(any(item.label == "Název chatu" for item in self.app.text_input))

        next(item for item in self.app.text_input if item.label == "Název chatu").input("Pohledávky po splatnosti")
        next(item for item in self.app.button if item.label == "Uložit název").click().run()
        self.assert_no_errors()
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(saved["saved_chats"][0]["title"], "Pohledávky po splatnosti")

        next(item for item in self.app.button if item.label == "Uložit chat").click().run()
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["saved_chats"]), 1)

    def test_english_labels_and_status(self):
        self.app.button(key="language-en").click().run()
        self.assert_no_errors()
        heading = next(item.value for item in self.app.markdown if "chat-heading" in item.value and "<h1>" in item.value)
        self.assertIn("Local data", heading)
        self.assertNotIn("AI is ready", heading)
        self.assertTrue(any(item.label == "New conversation" for item in self.app.button))

    def test_dashboard_can_be_created_from_dashboard_navigation(self):
        self.start_dashboard_creation()
        next(item for item in self.app.text_input if item.label == "Název nového dashboardu").input("Finance")
        next(item for item in self.app.button if item.label == "Uložit").click().run()
        self.assert_no_errors()
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        finance = next(item for item in saved["dashboards"] if item["name"] == "Finance")
        self.assertEqual(len(finance["pages"]), 1)
        self.assertEqual(finance["pages"][0]["name"], "Přehled")
        self.assertEqual(self.app.session_state["active_dashboard_id"], finance["id"])
        self.assertEqual(self.app.session_state["active_dashboard_page"], finance["pages"][0]["id"])
        self.assertEqual(self.app.title[0].value, "Finance")
        self.assertEqual([tab.label for tab in self.app.tabs], ["Přehled"])
        self.assertEqual(len(self.app.sidebar.tabs), 0)
        self.assertFalse(any(item.label == "Název nové stránky" for item in self.app.sidebar.text_input))
        self.assertTrue(any(item.proto.popover.label == "Nová stránka" for item in self.app.get("popover")))
        active_button = next(item for item in self.app.sidebar.button if item.label == "Finance")
        self.assertEqual(active_button.proto.type, "primary")

        self.assertTrue(any(item.proto.popover.label == "Přejmenovat" for item in self.app.get("popover")))
        next(item for item in self.app.text_input if item.label == "Název dashboardu").input("Finance 2026")
        next(item for item in self.app.button if item.label == "Přejmenovat").click().run()
        self.assert_no_errors()
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        finance = next(item for item in saved["dashboards"] if item["id"] == finance["id"])
        self.assertEqual(finance["name"], "Finance 2026")
        self.assertEqual(self.app.title[0].value, "Finance 2026")

        next(item for item in self.app.text_input if item.label == "Název nové stránky").input("Tržby")
        next(item for item in self.app.button if item.label == "Přidat stránku").click().run()
        self.assert_no_errors()
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        finance = next(item for item in saved["dashboards"] if item["name"] == "Finance 2026")
        self.assertEqual([page["name"] for page in finance["pages"]], ["Přehled", "Tržby"])
        self.assertEqual([page["name"] for page in saved["dashboards"][0]["pages"]], ["Přehled"])
        self.assertEqual(self.app.header[0].value, "Tržby")
        self.assertEqual([tab.label for tab in self.app.tabs], ["Přehled", "Tržby"])
        self.select_dashboard_page("Přehled")
        self.assertEqual(self.app.header[0].value, "Přehled")
        self.assertEqual(self.app.session_state["active_dashboard_page"], finance["pages"][0]["id"])
        self.select_dashboard_page("Tržby")
        self.assertEqual(self.app.header[0].value, "Tržby")

        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        self.assert_no_errors()
        self.assertEqual(self.app.title[0].value, "Můj dashboard")
        self.assertEqual([tab.label for tab in self.app.tabs], ["Přehled"])
        next(item for item in self.app.button if item.label == "Analytický chat").click().run()
        self.assert_no_errors()
        self.assertEqual(len(self.app.tabs), 0)

    def test_dashboard_menu_reveals_creation_form_only_on_request(self):
        buttons = {item.label: item.proto.type for item in self.app.button}
        self.assertEqual(buttons["Dashboardy"], buttons["Analytický chat"])
        self.open_dashboard_menu()
        button_labels = [item.label for item in self.app.button]
        self.assertLess(button_labels.index("Dashboardy"), button_labels.index("Můj dashboard"))
        self.assertLess(button_labels.index("Můj dashboard"), button_labels.index("Uložené chaty"))
        self.assertTrue(any(item.label == "Můj dashboard" for item in self.app.button))
        self.assertTrue(any(item.label == "Vytvořit nový" for item in self.app.button))
        self.assertFalse(any(item.label == "Název nového dashboardu" for item in self.app.text_input))
        self.assertFalse(any(item.label == "Uložit" for item in self.app.button))
        next(item for item in self.app.button if item.label == "Vytvořit nový").click().run()
        self.assert_no_errors()
        self.assertTrue(any(item.label == "Název nového dashboardu" for item in self.app.text_input))
        self.assertTrue(any(item.label == "Uložit" for item in self.app.button))
        next(item for item in self.app.button if item.label == "Dashboardy").click().run()
        self.assert_no_errors()
        self.assertFalse(any(item.label == "Můj dashboard" for item in self.app.button))
        self.open_dashboard_menu()
        self.assertFalse(any(item.label == "Název nového dashboardu" for item in self.app.text_input))
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        self.assert_no_errors()
        self.assertEqual(self.app.title[0].value, "Můj dashboard")
        self.assertFalse(any(item.label == "Uložit" for item in self.app.button))

    def test_dashboard_rename_uses_the_rename_label(self):
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()

        self.assert_no_errors()
        self.assertTrue(any(item.proto.popover.label == "Přejmenovat" for item in self.app.get("popover")))
        self.assertFalse(any(item.label == "Uložit název" for item in self.app.button))

    def test_chat_adds_chart_to_selected_dashboard_and_page(self):
        document = normalize_workspace(None)
        finance = add_dashboard(document, "Finance")
        revenue = add_page(finance, "Tržby")
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()
        self.ask("Show revenue by product.", button="Vytvořit graf")
        next(item for item in self.app.button if item.label == "Přidat do dashboardu").click().run()
        visual_name = next(item for item in self.app.text_input if item.label == "Název")
        self.assertEqual(visual_name.value, "Revenue by product")
        visual_name.input("Výnos podle produktů")
        self.app.selectbox(key="dashboard-target-1").select(finance["id"]).run()
        self.app.selectbox(key=f"dashboard-target-page-1-{finance['id']}").select(revenue["id"]).run()
        next(item for item in self.app.button if item.label == "Přidat").click().run()
        self.assert_no_errors()
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        finance = next(item for item in saved["dashboards"] if item["name"] == "Finance")
        self.assertEqual(finance["pages"][0]["cards"], [])
        self.assertEqual(len(finance["pages"][1]["cards"]), 1)
        self.assertEqual(saved["dashboards"][0]["pages"][0]["cards"], [])
        self.assertEqual(finance["pages"][1]["cards"][0]["kind"], "bar")
        self.assertEqual(finance["pages"][1]["cards"][0]["title"], "Výnos podle produktů")
        self.assertEqual(self.app.session_state["active_dashboard_id"], finance["id"])
        self.assertEqual(self.app.session_state["active_dashboard_page"], revenue["id"])

    def test_dashboard_dialog_suggests_short_visual_title(self):
        with patch(
            "analytics.get_llm_sql",
            return_value={
                "sql": "SELECT 'Enterprise' AS segment, 42 AS revenue",
                "clarification": None,
            },
        ):
            self.ask("Create a histogram with segments and their revenue.", button="Vytvořit graf")

        next(item for item in self.app.button if item.label == "Přidat do dashboardu").click().run()
        visual_name = next(item for item in self.app.text_input if item.label == "Název")
        self.assertEqual(visual_name.value, "Histogram with segments and their revenue")
        destination = next(item.value for item in self.app.markdown if "Uloží se do dashboardu" in item.value)
        self.assertIn("<strong>Můj dashboard</strong>", destination)
        self.assertIn("<strong>Přehled</strong>", destination)
        self.assertIn("<strong>Histogram with segments and their revenue</strong>", destination)

    def test_dashboard_creation_validates_name_without_saving(self):
        self.start_dashboard_creation()
        next(item for item in self.app.button if item.label == "Uložit").click().run()
        self.assert_no_errors()
        self.assertTrue(any(item.value == "Zadejte název dashboardu." for item in self.app.error))
        next(item for item in self.app.text_input if item.label == "Název nového dashboardu").input(" MŮJ DASHBOARD ")
        next(item for item in self.app.button if item.label == "Uložit").click().run()
        self.assert_no_errors()
        self.assertTrue(any("už existuje" in item.value for item in self.app.error))
        self.assertEqual(len(json.loads(self.store.read_text(encoding="utf-8"))["dashboards"]), 1)

    def test_dashboard_pages_survive_reload_and_delete_is_scoped(self):
        document = normalize_workspace(None)
        first = document["dashboards"][0]
        add_page(first, "Detail")
        second = add_dashboard(document, "Finance")
        add_page(second, "Detail")
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Finance").click().run()
        self.select_dashboard_page("Detail")
        self.assert_no_errors()
        self.assertEqual(self.app.header[0].value, "Detail")
        next(item for item in self.app.button if item.label == "Smazat stránku").click().run()
        self.assert_no_errors()
        self.assertEqual(self.app.header[0].value, "Přehled")
        restored = AppTest.from_string(self.source, default_timeout=15).run()
        self.assertEqual(list(restored.exception), [])
        next(item for item in restored.button if item.label == "Dashboardy").click().run()
        next(item for item in restored.button if item.label == "Finance").click().run()
        self.assertEqual([tab.label for tab in restored.tabs], ["Přehled"])
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual([page["name"] for page in saved["dashboards"][0]["pages"]], ["Přehled", "Detail"])

    def test_new_page_validates_name_and_preserves_current_selection(self):
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        original_page = self.app.session_state["active_dashboard_page"]
        for name, message in [("", "Zadejte název stránky."), (" PŘEHLED ", "Stránka s tímto názvem už v dashboardu existuje.")]:
            next(item for item in self.app.text_input if item.label == "Název nové stránky").input(name)
            next(item for item in self.app.button if item.label == "Přidat stránku").click().run()
            self.assert_no_errors()
            self.assertTrue(any(item.value == message for item in self.app.error))
            self.assertEqual(self.app.session_state["active_dashboard_page"], original_page)
            self.assertEqual([tab.label for tab in self.app.tabs], ["Přehled"])
        self.assertFalse(any(item.label == "Smazat stránku" for item in self.app.button))

    def test_dashboard_page_tabs_have_english_creation_label(self):
        self.app.button(key="language-en").click().run()
        next(item for item in self.app.button if item.label == "Dashboards").click().run()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        self.assert_no_errors()
        self.assertTrue(any(item.proto.popover.label == "New page" for item in self.app.get("popover")))
        self.assertEqual(len(self.app.sidebar.tabs), 0)

    def test_dashboard_editor_selected_card_status_is_english(self):
        document = normalize_workspace(None)
        page = document["dashboards"][0]["pages"][0]
        page["cards"] = [{
            "id": "revenue-chart", "title": "Revenue by segment", "kind": "bar",
            "sql": "SELECT 1 AS value", "x": "value", "y": "value",
        }]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()

        self.app.button(key="language-en").click().run()
        next(item for item in self.app.button if item.label == "Dashboards").click().run()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        next(item for item in self.app.button if item.label == "Edit").click().run()
        self.assert_no_errors()
        self.assertTrue(any("Currently selected card: **Revenue by segment**" in item.value for item in self.app.info))
        self.assertFalse(any("Aktuálně vybraná karta" in item.value for item in self.app.info))

    def test_english_dashboard_editor_renames_selected_card_with_local_fallback(self):
        document = normalize_workspace(None)
        page = document["dashboards"][0]["pages"][0]
        page["cards"] = [{
            "id": "revenue-chart", "title": "Revenue", "kind": "bar",
            "sql": "SELECT 1 AS value", "x": "value", "y": "value",
        }]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()

        self.app.button(key="language-en").click().run()
        next(item for item in self.app.button if item.label == "Dashboards").click().run()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        next(item for item in self.app.button if item.label == "Edit").click().run()
        next(item for item in self.app.text_input if item.label == "Editor instruction").input("Rename it to Segments by Revenue")
        next(item for item in self.app.button if item.label == "Propose change").click().run()
        self.assert_no_errors()
        self.assertTrue(any(item.label == "Confirm change" for item in self.app.button))
        self.assertTrue(any("Card “Segments by Revenue” was updated." in item.value for item in self.app.markdown))

    def test_editor_adds_page_without_modifying_other_dashboards(self):
        document = normalize_workspace(None)
        add_dashboard(document, "Finance")
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Finance").click().run()
        next(item for item in self.app.text_input if item.label == "Pokyn pro editor").input("Přidej stránku Tržby")
        next(item for item in self.app.button if item.label == "Navrhnout změnu").click().run()
        self.assertTrue(any(item.label == "Potvrdit změnu" for item in self.app.button))
        next(item for item in self.app.button if item.label == "Potvrdit změnu").click().run()
        self.assert_no_errors()
        self.assertEqual(self.app.header[0].value, "Tržby")
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual([page["name"] for page in saved["dashboards"][0]["pages"]], ["Přehled"])
        self.assertEqual([page["name"] for page in saved["dashboards"][1]["pages"]], ["Přehled", "Tržby"])

    def test_dashboard_editor_changes_selected_pie_color(self):
        document = normalize_workspace(None)
        page = document["dashboards"][0]["pages"][0]
        page["cards"] = [{
            "id": "segment-pie", "title": "Tržby podle segmentu", "kind": "pie",
            "sql": "SELECT segment, SUM(net_amount_czk) AS revenue FROM companies c JOIN invoices i ON c.company_id = i.company_id GROUP BY segment",
            "x": "segment", "y": "revenue", "color": "#C2185B",
        }]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()

        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        next(item for item in self.app.button if item.label == "Upravit").click().run()
        next(item for item in self.app.text_input if item.label == "Pokyn pro editor").input("Změň barvy v koláči na zelené")
        next(item for item in self.app.button if item.label == "Navrhnout změnu").click().run()
        next(item for item in self.app.button if item.label == "Potvrdit změnu").click().run()
        self.assert_no_errors()

        card = json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["cards"][0]
        self.assertEqual(card["kind"], "pie")
        self.assertEqual(card["color"], "#0B3B2E")

    def test_dashboard_editor_renames_the_selected_card_without_changing_chart_type(self):
        document = normalize_workspace(None)
        page = document["dashboards"][0]["pages"][0]
        page["cards"] = [{
            "id": "revenue-chart", "title": "Lowest-revenue products", "kind": "bar",
            "sql": "SELECT product, SUM(net_amount_czk) AS revenue FROM invoices GROUP BY product",
            "x": "product", "y": "revenue",
        }]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()

        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        next(item for item in self.app.button if item.label == "Upravit").click().run()
        next(item for item in self.app.text_input if item.label == "Pokyn pro editor").input("Uprav název tabulky na Number of invoices overdue")
        next(item for item in self.app.button if item.label == "Navrhnout změnu").click().run()
        next(item for item in self.app.button if item.label == "Potvrdit změnu").click().run()
        self.assert_no_errors()

        card = json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["cards"][0]
        self.assertEqual(card["title"], "Number of invoices overdue")
        self.assertEqual(card["kind"], "bar")

    def test_card_editor_dialog_previews_and_saves_only_after_confirmation(self):
        document = normalize_workspace(None)
        page = document["dashboards"][0]["pages"][0]
        page["cards"] = [{
            "id": "revenue-chart", "title": "Revenue", "kind": "bar",
            "sql": "SELECT 1 AS value", "x": "value", "y": "value",
        }]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()

        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        next(item for item in self.app.button if item.label == "Upravit").click().run()
        self.assert_no_errors()
        self.assertTrue(any(item.label == "Uložit úpravy" for item in self.app.button))
        next(item for item in self.app.text_input if item.label == "Název").input("Nové tržby").run()
        self.assertEqual(json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["cards"][0]["title"], "Revenue")
        next(item for item in self.app.button if item.label == "Uložit úpravy").click().run()
        self.assert_no_errors()
        self.assertEqual(json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["cards"][0]["title"], "Nové tržby")

    def test_dashboard_editor_cancel_and_undo_keep_history_safe(self):
        document = normalize_workspace(None)
        page = document["dashboards"][0]["pages"][0]
        page["cards"] = [{
            "id": "revenue-chart", "title": "Revenue", "kind": "bar", "sql": "SELECT 1 AS value", "x": "value", "y": "value",
        }]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        next(item for item in self.app.button if item.label == "Upravit").click().run()
        next(item for item in self.app.text_input if item.label == "Pokyn pro editor").input("Uprav název grafu na Nové tržby")
        next(item for item in self.app.button if item.label == "Navrhnout změnu").click().run()
        next(item for item in self.app.button if item.label == "Zahodit návrh").click().run()
        self.assertEqual(json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["cards"][0]["title"], "Revenue")

        next(item for item in self.app.text_input if item.label == "Pokyn pro editor").input("Uprav název grafu na Nové tržby")
        next(item for item in self.app.button if item.label == "Navrhnout změnu").click().run()
        next(item for item in self.app.button if item.label == "Potvrdit změnu").click().run()
        self.assertEqual(json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["cards"][0]["title"], "Nové tržby")
        next(item for item in self.app.button if item.label == "Vrátit poslední změnu").click().run()
        self.assertEqual(json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["cards"][0]["title"], "Revenue")

    def test_dashboard_renders_text_and_kpi_blocks_in_a_row(self):
        document = normalize_workspace(None)
        page = document["dashboards"][0]["pages"][0]
        page["filters"] = {"date_from": "2026-02-01", "date_to": "2026-04-30"}
        page["cards"] = [
            {"id": "note", "title": "Komentář", "kind": "text", "text": "Tržby rostou díky Enterprise.", "layout": {"row": 0, "width": 12}},
            {"id": "revenue-kpi", "title": "Tržby", "kind": "kpi", "sql": "SELECT SUM(net_amount_czk) AS revenue FROM invoices", "layout": {"row": 1, "width": 6}, "value_format": "currency_czk"},
            {"id": "overdue-kpi", "title": "Po splatnosti", "kind": "kpi", "sql": "SELECT COUNT(*) AS overdue FROM invoices WHERE payment_status = 'Overdue'", "layout": {"row": 1, "width": 6}, "trend_direction": "lower_is_better"},
        ]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        self.assert_no_errors()
        self.assertTrue(any("Tržby rostou díky Enterprise." in item.value for item in self.app.markdown))
        self.assertEqual(len(self.app.metric), 2)

    def test_dashboard_editor_creates_local_kpi(self):
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        next(item for item in self.app.text_input if item.label == "Pokyn pro editor").input("Přidej KPI kolik faktur je po splatnosti")
        next(item for item in self.app.button if item.label == "Navrhnout změnu").click().run()
        next(item for item in self.app.button if item.label == "Potvrdit změnu").click().run()
        self.assert_no_errors()
        cards = json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["cards"]
        self.assertEqual(cards[-1]["kind"], "kpi")
        self.assertEqual(cards[-1]["layout"]["width"], 4)

    def test_legacy_pages_migrate_once_without_becoming_dashboards(self):
        legacy = {
            "version": 2, "pages": [{
                "id": "overview", "name": "Přehled", "filters": {"cities": ["Praha"]},
                "cards": [{"id": "old-card", "title": "Count", "kind": "metric", "sql": "SELECT 2 AS count"}],
            }, {
                "id": "finance-page", "name": "Finance", "filters": {}, "cards": [],
            }],
        }
        self.store.write_text(json.dumps(legacy), encoding="utf-8")
        self.app.run()
        self.assert_no_errors()
        self.open_dashboard_menu()
        self.assertTrue(any(item.label == "Můj dashboard" for item in self.app.button))
        self.assertFalse(any(item.label == "Finance" for item in self.app.button))
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], 4)
        self.assertEqual(len(saved["dashboards"]), 1)
        pages = saved["dashboards"][0]["pages"]
        self.assertEqual([page["id"] for page in pages], ["overview", "finance-page"])
        self.assertEqual(pages[0]["cards"][0]["id"], "old-card")
        self.assertEqual(pages[0]["filters"]["cities"], ["Praha"])

    def test_dashboard_filter_values_remain_selected_after_rerun(self):
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        self.assert_no_errors()
        next(item for item in self.app.multiselect if item.label == "Segment").select("Enterprise")
        next(item for item in self.app.multiselect if item.label == "Město").select("Praha").select("Brno")
        self.app.run()
        self.assert_no_errors()
        self.assertEqual(next(item.value for item in self.app.multiselect if item.label == "Město"), ["Praha", "Brno"])
        self.assertEqual(next(item.value for item in self.app.multiselect if item.label == "Segment"), ["Enterprise"])
        filters = json.loads(self.store.read_text(encoding="utf-8"))["dashboards"][0]["pages"][0]["filters"]
        self.assertEqual(filters["cities"], ["Praha", "Brno"])
        self.assertEqual(filters["segments"], ["Enterprise"])
        self.assertEqual(filters["date_from"], "2026-01-01")
        self.assertEqual(filters["date_to"], "2026-10-31")

    def test_reset_demo_restores_the_shared_default_workspace(self):
        document = normalize_workspace(None)
        dashboard = add_dashboard(document, "Finance")
        dashboard["pages"][0]["cards"] = [{"id": "revenue", "title": "Revenue", "kind": "metric", "sql": "SELECT 1"}]
        document["saved_chats"] = [{"id": "chat", "title": "Saved", "history": [{"role": "user", "content": "Test"}]}]
        document["dashboard_history"] = [{"id": "history", "label": "Change", "dashboard": dashboard}]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()

        self.app.checkbox(key="confirm-demo-reset").check().run()
        next(item for item in self.app.button if item.label == "Resetovat demo").click().run()

        self.assert_no_errors()
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], 4)
        self.assertEqual(len(saved["dashboards"]), 1)
        self.assertEqual(saved["dashboards"][0]["name"], "Můj dashboard")
        self.assertEqual(saved["dashboards"][0]["pages"][0]["cards"], [])
        self.assertEqual(saved["saved_chats"], [])
        self.assertEqual(saved["dashboard_history"], [])
        self.assertEqual(self.app.session_state["workspace_view"], "chat")
        self.assertTrue(any(item.value == "Demo bylo resetováno do výchozího stavu." for item in self.app.success))

    def test_dashboard_renders_filtered_metric_union_and_pdf(self):
        document = normalize_workspace(None)
        page = document["dashboards"][0]["pages"][0]
        page["filters"] = {"date_from": "2026-02-01", "date_to": "2026-04-30"}
        page["cards"] = [
            {
                "title": "Overdue count", "kind": "metric",
                "sql": "SELECT COUNT(*) AS overdue_invoices_count FROM invoices WHERE payment_status = 'Overdue'",
            },
            {
                "title": "Overdue by company", "kind": "table",
                "sql": """SELECT * FROM (
                    SELECT 'Total' AS company_name, COUNT(*) AS overdue_invoices_count
                    FROM invoices WHERE payment_status = 'Overdue'
                    UNION ALL
                    SELECT c.company_name, COUNT(i.invoice_id)
                    FROM companies c LEFT JOIN invoices i
                        ON c.company_id = i.company_id AND i.payment_status = 'Overdue'
                    GROUP BY c.company_name
                ) AS _bounded_result LIMIT 500""",
            },
        ]
        self.store.write_text(json.dumps(document), encoding="utf-8")
        self.app.run()
        self.open_dashboard_menu()
        next(item for item in self.app.button if item.label == "Můj dashboard").click().run()
        self.assert_no_errors()
        with Path(__file__).with_name("data").joinpath("invoices.csv").open(encoding="utf-8", newline="") as invoices:
            expected = sum(
                row["payment_status"] == "Overdue" and "2026-02-01" <= row["invoice_date"] <= "2026-04-30"
                for row in csv.DictReader(invoices)
            )
        self.assertEqual(self.app.metric[0].value, f"{expected:,}".replace(",", " "))
        table = self.app.dataframe[0].value
        self.assertEqual(int(table.loc[table["company_name"] == "Total", "overdue_invoices_count"].iloc[0]), expected)
        self.assertEqual(len(self.app.get("download_button")), 1)


if __name__ == "__main__":
    unittest.main()
