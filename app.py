import json
import os
import re
import uuid
from copy import deepcopy
from datetime import date
from html import escape
from io import BytesIO
from pathlib import Path

from analytics import (
    LLMRequestError,
    build_analytics_result,
    build_bounded_select_sql,
    get_dashboard_editor_plan,
    get_llm_sql,
    get_local_plan,
    get_openai_api_key,
    validate_read_only_sql,
)
from dashboard import (
    CHART_KINDS,
    CITIES,
    COLORS,
    SEGMENTS,
    add_dashboard,
    add_page,
    add_card_to_page,
    apply_card_preferences,
    apply_filters_to_sql,
    apply_time_granularity,
    dashboard_by_id,
    dashboard_name_exists,
    normalize_card,
    normalize_workspace,
    normalize_filters,
    page_name_exists,
    page_by_id,
    parse_editor_command,
    previous_period_filters,
    rename_dashboard,
    remove_page,
    restore_latest_dashboard_snapshot,
    save_dashboard_snapshot,
)
from ontology import answer_knowledge_question, draft_preview, normalize_semantic_model, upsert_item
import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
STORE = ROOT / "storage" / "dashboard.json"
LOGO_PATH = ROOT / "assets" / "biizy_logo.png"
FOREST, PAPER, PINK, GREEN, SLATE = "#0B3B2E", "#F7F7F7", "#C2185B", "#2F6B5A", "#4B5563"
CREATE_NEW_DASHBOARD = "__create_new_dashboard__"
NEW_DASHBOARD_OVERVIEW = "__new_dashboard_overview__"
COLOR_OPTION_LABELS = {
    "#0B3B2E": "🟩 Forest green · #0B3B2E",
    "#C2185B": "🩷 Pink · #C2185B",
    "#4B5563": "⬛ Slate gray · #4B5563",
}

st.set_page_config(page_title="Biizy · BI easy", page_icon="✦", layout="wide", initial_sidebar_state="expanded")

TEXT = {
    "cs": {
        "language": "Jazyk rozhraní", "sidebar_subtitle": "BI easy · ERP × CRM přehled",
        "workspace": "Pracovní plocha", "analytics_chat": "Analytický chat", "dashboards": "Dashboardy", "saved_chats": "Uložené chaty",
        "dashboard_name": "Název nového dashboardu", "rename_dashboard_name": "Název dashboardu", "rename_dashboard": "Přejmenovat", "dashboard_renamed": "Dashboard byl přejmenován na „{dashboard}“.", "create_dashboard": "Vytvořit nový",
        "save_dashboard": "Uložit", "save_chat": "Uložit chat", "chat_saved": "Chat byl uložen.",
        "chat_name": "Název chatu", "rename_chat": "Uložit název", "chat_name_required": "Zadejte název chatu.",
        "overview": "Přehled", "target_page": "Stránka",
        "target_dashboard": "Dashboard",
        "new_dashboard_placeholder": "Nový dashboard",
        "save_destination": "Uloží se do dashboardu <strong>{dashboard}</strong> na stránku <strong>{page}</strong> s názvem <strong>{title}</strong>.",
        "local_data": "Lokální data · DuckDB · SQL pouze pro čtení", "demo_data": "Demo data 2026",
        "demo_project_title": "Biizy je work in progress",
        "demo_project_intro": "Pracovní demo pro rychlé zkoumání propojených ERP a CRM dat.",
        "demo_project_capabilities": "Co aplikace umí", "demo_project_capability_one": "Odpovídat na otázky nad ukázkovými daty přirozeným jazykem.", "demo_project_capability_two": "Zobrazit výsledek jako tabulku, metriku nebo graf.", "demo_project_capability_three": "Uložit výsledek na vlastní dashboard a dále jej upravovat.",
        "demo_project_how_to": "Jak na to", "demo_project_how_to_one": "Napište dotaz do Analytického chatu.", "demo_project_how_to_two": "Výsledek upřesněte nebo z něj vytvořte graf.", "demo_project_how_to_three": "Přidejte ho na vybranou stránku dashboardu.",
        "demo_project_roadmap": "Plány", "demo_project_roadmap_one": "Napojení na Microsoft Fabric Data včetně ontologie.", "demo_project_roadmap_two": "Tvorba ontologie přímo v aplikaci.", "demo_project_roadmap_three": "Další datové zdroje a analytické možnosti.",
        "demo_project_feedback": "Komentáře a nápady posílejte na {email}.",
        "hide_demo_project_notice": "Skrýt", "show_demo_project_notice": "Informace o projektu",
        "reset_demo": "Resetovat demo", "reset_demo_help": "Smaže všechny společně uložené dashboardy, změny i chaty a vrátí aplikaci do výchozího stavu.",
        "reset_demo_confirm": "Rozumím, že tím smažu společná demo data všech testerů.", "reset_demo_done": "Demo bylo resetováno do výchozího stavu.",
        "sql_trace": "SQL trace — zobrazit skutečně vykonaný dotaz", "sql_rows": "DuckDB · read-only SELECT · vráceno řádků: {rows}",
        "you_question": "VY · DOTAZ", "visualization": "VIZUALIZACE", "result": "VÝSLEDEK",
        "chart_details": "Graf · {kind} · {color} · {font} · zvýraznění: {highlight}", "no_highlight": "žádné",
        "add_dashboard": "Přidat do dashboardu", "add_to_dashboard_title": "Přidat vizuál do dashboardu",
        "visual_name": "Název",
        "visual_name_required": "Zadejte název vizuálu.",
        "create_new_dashboard": "Vytvořit nový",
        "dashboard_name_required": "Zadejte název dashboardu.",
        "dashboard_name_exists": "Dashboard s tímto názvem už existuje.",
        "confirm_add_dashboard": "Přidat", "cancel_add_dashboard": "Zrušit",
        "added_dashboard": "Výsledek byl přidán do dashboardu „{dashboard}“ na stránku „{page}“.",
        "download_csv": "Stáhnout výsledek CSV", "chat_title": "Analytický chat",
        "how_it_works": "<b>Jak to funguje</b><ol><li>Zeptejte se na data.</li><li>Výsledek případně upřesněte.</li><li>Přidejte výsledek nebo graf na vybraný dashboard.</li></ol>SQL je vždy viditelné.",
        "chat_guide": "Jak pracovat s chatem", "chat_empty": "Co chcete zjistit ze svých dat?",
        "chat_empty_hint": "Začněte otázkou. Výsledek můžete upřesnit, zobrazit v grafu a uložit na vybranou stránku dashboardu.",
        "new_conversation": "Nová konverzace", "question": "Váš dotaz", "question_placeholder": "Např. Kolik faktur je po splatnosti?",
        "question_help": "Napište otázku k datům nebo pokyn pro vytvoření grafu.", "show_answer": "Zobrazit odpověď", "create_chart": "Vytvořit graf", "previous_turn": "Předchozí dotaz · {question}",
        "missing_prompt": "Napište prosím dotaz nebo pokyn.", "local_fallback": "Odpověď vznikla podle lokálních demo pravidel, protože OpenAI plánování nebylo dostupné.",
        "query_result_summary": "Výsledek bezpečně spuštěného SQL dotazu pouze pro čtení.",
        "query_value": "Výsledek",
        "sql_diagnostics": "Diagnostika dotazu",
        "query_error": "Dotaz se nepodařilo bezpečně připravit nebo vykonat. Zkuste otázku upřesnit.",
        "metric_no_chart": "Jednu hodnotu nelze převést na graf. Zeptejte se například na revenue podle produktu.",
        "filters_apply": "Filtry níže platí pro všechny karty na této stránce.", "export_pdf": "Export PDF",
        "all_values": "Všechny hodnoty",
        "dashboard_pages": "STRÁNKY DASHBOARDU", "active_page": "Aktivní stránka", "new_page": "Název nové stránky", "new_page_placeholder": "Např. Finance",
        "page_name_required": "Zadejte název stránky.", "page_name_exists": "Stránka s tímto názvem už v dashboardu existuje.",
        "create_page": "Nová stránka", "add_page": "Přidat stránku", "delete_page": "Smazat stránku", "page_filters": "Filtry stránky", "city": "Město", "period": "Období",
        "granularity": "Granularita", "monthly": "Měsíčně", "weekly": "Týdně", "granularity_note": "Zvolená granularita se uloží pro tuto stránku a použije se u časových přehledů.",
        "empty_dashboard": "Tato stránka je zatím prázdná. V Analytickém chatu vytvořte výsledek nebo vizualizaci a přidejte ji na dashboard.", "card": "Karta {number}",
        "edit": "Upravit", "move_up": "Posunout výš", "move_down": "Posunout níž", "remove": "Odstranit", "edit_card": "Upravit kartu",
        "select_card": "Vyberte u karty tlačítko „Upravit“.", "name": "Název", "chart_type": "Typ grafu", "color": "Barva", "sort": "Řazení",
        "save_changes": "Uložit úpravy", "card_updated": "Karta byla upravena.", "dashboard_editor": "Editor dashboardu",
        "editor_example": "Např. „Přidej stránku Finance“, „nastav weekly“, „změň graf na line“, „seřaď vzestupně“ nebo „nastav růžovou“.",
        "editor_instruction": "Pokyn pro editor", "editor_placeholder": "Uprav aktuálně vybranou kartu…", "apply_change": "Provést změnu", "generated": "Vygenerováno lokálně",
        "editor_history": "Historie editoru: {count} uložených verzí (max. 30).", "undo_last_change": "Vrátit poslední změnu", "undo_completed": "Poslední potvrzená změna byla vrácena.",
        "block_width": "Šířka bloku", "layout_row": "Řádek rozvržení", "comment_text": "Text komentáře", "decimal_places": "Desetinná místa", "value_format": "Formát hodnoty", "trend_evaluation": "Vyhodnocení trendu",
        "selected_card": "Aktuálně vybraná karta: **{title}**", "select_card_for_editor": "Nejdřív u požadované karty klikněte na „Upravit“. Pokyny pro stránku a přidání bloků fungují i bez výběru.",
        "propose_change": "Navrhnout změnu", "editor_submit_hint": "Stiskněte Enter pro odeslání nebo použijte tlačítko níže.", "change_preview": "Náhled navržené změny", "change_preview_note": "Změna se uloží až po potvrzení. Před uložením vznikne verze pro Undo.", "confirm_change": "Potvrdit změnu", "discard_proposal": "Zahodit návrh",
        "editor_command_unrecognized": "Pokyn jsem nerozpoznal. Zkuste například „změň graf na line“, „seřaď vzestupně“ nebo „nastav růžovou“.", "editor_card_updated": "Karta „{title}“ byla upravena.",
        "card_editor_title": "Upravit kartu", "card_editor_settings": "Nastavení", "working_preview": "Pracovní náhled", "working_preview_note": "Změny se projeví na dashboardu až po uložení.", "discard_changes": "Zahodit změny", "selected_color": "Vybraná barva",
    },
    "en": {
        "language": "Interface language", "sidebar_subtitle": "BI easy · ERP × CRM overview",
        "workspace": "Workspace", "analytics_chat": "Analytics chat", "dashboards": "Dashboards", "saved_chats": "Saved chats",
        "dashboard_name": "New dashboard name", "rename_dashboard_name": "Dashboard name", "rename_dashboard": "Rename", "dashboard_renamed": "Dashboard renamed to “{dashboard}”.", "create_dashboard": "Create new",
        "save_dashboard": "Save", "save_chat": "Save chat", "chat_saved": "Chat saved.",
        "chat_name": "Chat name", "rename_chat": "Save name", "chat_name_required": "Enter a chat name.",
        "overview": "Overview", "target_page": "Page",
        "target_dashboard": "Dashboard",
        "new_dashboard_placeholder": "New dashboard",
        "save_destination": "This will be saved to dashboard <strong>{dashboard}</strong>, page <strong>{page}</strong>, as <strong>{title}</strong>.",
        "local_data": "Local data · DuckDB · read-only SQL", "demo_data": "2026 demo data",
        "demo_project_title": "Biizy is a work in progress",
        "demo_project_intro": "A working demo for exploring connected ERP and CRM data quickly.",
        "demo_project_capabilities": "What the app can do", "demo_project_capability_one": "Answer questions about the sample data in natural language.", "demo_project_capability_two": "Show results as a table, metric, or chart.", "demo_project_capability_three": "Save results to your dashboard and refine them later.",
        "demo_project_how_to": "How to use it", "demo_project_how_to_one": "Ask a question in Analytics chat.", "demo_project_how_to_two": "Refine the result or turn it into a chart.", "demo_project_how_to_three": "Add it to a selected dashboard page.",
        "demo_project_roadmap": "Plans", "demo_project_roadmap_one": "Microsoft Fabric Data connection, including ontology support.", "demo_project_roadmap_two": "Ontology creation directly in the app.", "demo_project_roadmap_three": "Additional data sources and analytical capabilities.",
        "demo_project_feedback": "Please send comments and ideas to {email}.",
        "hide_demo_project_notice": "Hide", "show_demo_project_notice": "Project information",
        "sql_trace": "SQL trace — show the executed query", "sql_rows": "DuckDB · read-only SELECT · rows returned: {rows}",
        "you_question": "YOU · QUESTION", "visualization": "VISUALIZATION", "result": "RESULT",
        "chart_details": "Chart · {kind} · {color} · {font} · highlight: {highlight}", "no_highlight": "none",
        "add_dashboard": "Add to dashboard", "add_to_dashboard_title": "Add visual to dashboard",
        "visual_name": "Name",
        "visual_name_required": "Enter a visual name.",
        "create_new_dashboard": "Create new",
        "dashboard_name_required": "Enter a dashboard name.",
        "dashboard_name_exists": "A dashboard with this name already exists.",
        "confirm_add_dashboard": "Add", "cancel_add_dashboard": "Cancel",
        "added_dashboard": "The result was added to dashboard “{dashboard}”, page “{page}”.",
        "download_csv": "Download result CSV", "chat_title": "Analytics chat",
        "how_it_works": "<b>How it works</b><ol><li>Ask about the data.</li><li>Refine the result if needed.</li><li>Add the result or chart to a selected dashboard.</li></ol>SQL is always visible.",
        "chat_guide": "How to use the chat", "chat_empty": "What would you like to learn from your data?",
        "chat_empty_hint": "Start with a question. Refine the result, view it as a chart and save it to a selected dashboard page.",
        "new_conversation": "New conversation", "question": "Your question", "question_placeholder": "For example: How many overdue invoices do we have?",
        "question_help": "Ask a question about the data or provide instructions for a chart.", "show_answer": "Show answer", "create_chart": "Create chart", "previous_turn": "Previous question · {question}",
        "missing_prompt": "Enter a question or an instruction.", "local_fallback": "This response uses local demo rules because OpenAI planning was unavailable.",
        "query_result_summary": "Result from a safely executed read-only SQL query.",
        "query_value": "Result",
        "sql_diagnostics": "Query diagnostics",
        "query_error": "The query could not be safely prepared or executed. Please clarify the question and try again.",
        "metric_no_chart": "A single value cannot be converted into a chart. Ask, for example, for revenue by product.",
        "filters_apply": "The filters below apply to every card on this page.", "export_pdf": "Export PDF",
        "all_values": "All values",
        "dashboard_pages": "DASHBOARD PAGES", "active_page": "Active page", "new_page": "New page name", "new_page_placeholder": "For example: Finance",
        "page_name_required": "Enter a page name.", "page_name_exists": "A page with this name already exists in this dashboard.",
        "create_page": "New page", "add_page": "Add page", "delete_page": "Delete page", "page_filters": "Page filters", "city": "City", "period": "Period",
        "granularity": "Granularity", "monthly": "Monthly", "weekly": "Weekly", "granularity_note": "The selected granularity is saved for this page and used by time-based reports.",
        "empty_dashboard": "This page is empty. Create a result or visualization in Analytics chat and add it to the dashboard.", "card": "Card {number}",
        "edit": "Edit", "move_up": "Move up", "move_down": "Move down", "remove": "Remove", "edit_card": "Edit card",
        "select_card": "Select a card using its Edit button.", "name": "Name", "chart_type": "Chart type", "color": "Color", "sort": "Sort order",
        "save_changes": "Save changes", "card_updated": "Card updated.", "dashboard_editor": "Dashboard editor",
        "editor_example": "For example: “Add page Finance”, “set weekly”, “change chart to line”, “sort ascending”, or “set pink”.",
        "editor_instruction": "Editor instruction", "editor_placeholder": "Update the currently selected card…", "apply_change": "Apply change", "generated": "Generated locally",
        "editor_history": "Editor history: {count} saved versions (max. 30).", "undo_last_change": "Undo last change", "undo_completed": "The last confirmed change was undone.",
        "block_width": "Block width", "layout_row": "Layout row", "comment_text": "Comment text", "decimal_places": "Decimal places", "value_format": "Value format", "trend_evaluation": "Trend evaluation",
        "selected_card": "Currently selected card: **{title}**", "select_card_for_editor": "Select a card with its Edit button first. Page instructions and adding blocks also work without a selection.",
        "propose_change": "Propose change", "editor_submit_hint": "Press Enter to submit, or use the button below.", "change_preview": "Proposed change preview", "change_preview_note": "The change is saved only after confirmation. A version for Undo is created first.", "confirm_change": "Confirm change", "discard_proposal": "Discard proposal",
        "editor_command_unrecognized": "I could not recognize that instruction. Try, for example, “change chart to line”, “sort ascending”, or “set pink”.", "editor_card_updated": "Card “{title}” was updated.",
        "card_editor_title": "Edit card", "card_editor_settings": "Settings", "working_preview": "Working preview", "working_preview_note": "Changes appear on the dashboard only after you save them.", "discard_changes": "Discard changes", "selected_color": "Selected color",
        "reset_demo": "Reset demo", "reset_demo_help": "Delete all shared dashboards, changes, and chats, then return the app to its default state.",
        "reset_demo_confirm": "I understand that this deletes the shared demo data for every tester.", "reset_demo_done": "The demo has been reset to its default state.",
    },
}


def t(key, **values):
    language = st.session_state.get("language", "en")
    return TEXT[language][key].format(**values)


def render_language_switcher():
    """Render compact flag controls and preserve the selected interface language."""
    with st.container(horizontal=True, vertical_alignment="center", key="language-switcher"):
        choose_czech = st.button("Čeština", key="language-cs", type="primary" if st.session_state.language == "cs" else "secondary")
        choose_english = st.button("English", key="language-en", type="primary" if st.session_state.language == "en" else "secondary")
    if choose_czech and st.session_state.language != "cs":
        st.session_state.language = "cs"
        st.rerun()
    if choose_english and st.session_state.language != "en":
        st.session_state.language = "en"
        st.rerun()


def render_sidebar_brand():
    """Render the supplied Biizy artwork when it is available locally."""
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width="stretch", alt="Biizy — BI easy")
        return
    st.markdown(
        """<div class='biizy-brand'>
        <svg class='biizy-mark' viewBox='0 0 48 48' aria-hidden='true'>
          <circle cx='24' cy='24' r='22' fill='#DDF5EE'/>
          <path d='M15 28 L23 18 L33 25' fill='none' stroke='#0B3B2E' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>
          <circle cx='15' cy='28' r='4' fill='#C2185B'/><circle cx='23' cy='18' r='4' fill='#0B3B2E'/><circle cx='33' cy='25' r='4' fill='#2F6B5A'/>
        </svg>
        <div><div class='biizy-name'>Biizy</div><div class='biizy-tagline'>BI easy</div></div>
        </div>""",
        unsafe_allow_html=True,
    )


def hide_demo_project_notice():
    """Collapse the work-in-progress notice for the active browser session."""
    st.session_state.demo_project_notice_hidden = True


def show_demo_project_notice():
    """Expand the work-in-progress notice for the active browser session."""
    st.session_state.demo_project_notice_hidden = False


def render_demo_project_notice():
    """Render the project notice with an in-place control to collapse or expand it."""
    with st.container(key="demo-project-notice"):
        if st.session_state.get("demo_project_notice_hidden", False):
            with st.container(horizontal=True, horizontal_alignment="left"):
                st.button(
                    t("show_demo_project_notice"), key="show-demo-project-notice",
                    icon=":material/info:", on_click=show_demo_project_notice, width="content",
                )
            return

        st.markdown(
            f"<div class='demo-project-notice__content'>"
            f"<h2>{escape(t('demo_project_title'))}</h2>"
            f"<p>{escape(t('demo_project_intro'))}</p>"
            f"<div class='demo-project-notice__sections'>"
            f"<section><h3>{escape(t('demo_project_capabilities'))}</h3><ul>"
            f"<li>{escape(t('demo_project_capability_one'))}</li>"
            f"<li>{escape(t('demo_project_capability_two'))}</li>"
            f"<li>{escape(t('demo_project_capability_three'))}</li></ul></section>"
            f"<section><h3>{escape(t('demo_project_how_to'))}</h3><ol>"
            f"<li>{escape(t('demo_project_how_to_one'))}</li>"
            f"<li>{escape(t('demo_project_how_to_two'))}</li>"
            f"<li>{escape(t('demo_project_how_to_three'))}</li></ol></section>"
            f"<section><h3>{escape(t('demo_project_roadmap'))}</h3><ul>"
            f"<li>{escape(t('demo_project_roadmap_one'))}</li>"
            f"<li>{escape(t('demo_project_roadmap_two'))}</li>"
            f"<li>{escape(t('demo_project_roadmap_three'))}</li></ul></section>"
            "</div>"
            f"<p>{t('demo_project_feedback', email='<a href=\"mailto:martina.parikova@gmail.com\">martina.parikova@gmail.com</a>')}</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        with st.container(horizontal=True, horizontal_alignment="right"):
            st.button(
                t("hide_demo_project_notice"), key="hide-demo-project-notice",
                on_click=hide_demo_project_notice, width="content",
            )


def make_fake_data():
    """Create reproducible, linked CRM/ERP sample CSV files once."""
    DATA_DIR.mkdir(exist_ok=True)
    needed = [DATA_DIR / file_name for file_name in ("companies.csv", "opportunities.csv", "invoices.csv")]
    invoice_path = DATA_DIR / "invoices.csv"
    if all(path.exists() for path in needed):
        # Versioned fake-data schema: add the product dimension required by the agent.
        if "product" in pd.read_csv(invoice_path, nrows=0).columns:
            return

    rng = np.random.default_rng(42)
    names = [
        "Asterion", "Boreal", "CleverFox", "DeltaWorks", "Evident", "Futura", "GreenPath",
        "Helios", "Inventa", "Juno", "Kinetiq", "Lumina", "Moneta", "Nordicore", "Orbis",
        "Penta", "Quantio", "Riverton", "Solventa", "TeraNova", "Umbra", "Vektor",
        "Westfield", "Xenon", "Ypsilon", "Zenith",
    ]
    companies = pd.DataFrame(
        {
            "company_id": range(1, len(names) + 1),
            "company_name": [f"{name} s.r.o." for name in names],
            "segment": rng.choice(["Enterprise", "Mid-market", "SMB"], len(names), p=[0.27, 0.43, 0.30]),
            "city": rng.choice(["Praha", "Brno", "Ostrava", "Plzeň", "Liberec", "Olomouc"], len(names)),
            "account_manager": rng.choice(["Anna Nováková", "Jan Dvořák", "Petra Svobodová", "Tomáš Král"], len(names)),
        }
    )
    companies.to_csv(DATA_DIR / "companies.csv", index=False)

    stages = ["Prospecting", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]
    opportunity_rows = []
    for opportunity_id in range(1, 151):
        created = pd.Timestamp("2026-01-01") + pd.Timedelta(days=int(rng.integers(0, 300)))
        opportunity_rows.append(
            [
                opportunity_id,
                int(rng.integers(1, 27)),
                f"Obchodní příležitost {opportunity_id:03d}",
                rng.choice(stages, p=[0.14, 0.20, 0.20, 0.16, 0.19, 0.11]),
                int(rng.integers(40_000, 1_600_000)),
                created.date(),
                (created + pd.Timedelta(days=int(rng.integers(30, 140)))).date(),
            ]
        )
    pd.DataFrame(
        opportunity_rows,
        columns=["opportunity_id", "company_id", "opportunity_name", "stage", "amount_czk", "created_date", "expected_close_date"],
    ).to_csv(DATA_DIR / "opportunities.csv", index=False)

    products = ["Insight Core", "Sales Flow", "Finance Pro", "Service Desk", "Data Connect"]
    invoice_rows, invoice_id = [], 1
    for company_id in companies.company_id:
        for month in pd.date_range("2026-01-01", "2026-10-01", freq="MS"):
            if rng.random() < 0.76:
                issue_date = month + pd.Timedelta(days=int(rng.integers(1, 24)))
                amount = int(max(15_000, rng.normal(225_000 if company_id % 4 else 480_000, 95_000)))
                due_date = issue_date + pd.Timedelta(days=30)
                paid = rng.random() > 0.17
                invoice_rows.append(
                    [
                        invoice_id, company_id, rng.choice(products, p=[0.28, 0.22, 0.18, 0.17, 0.15]),
                        issue_date.date(), due_date.date(), amount,
                        "Paid" if paid else "Overdue",
                        (due_date + pd.Timedelta(days=int(rng.integers(1, 35)))).date() if paid else None,
                    ]
                )
                invoice_id += 1
    pd.DataFrame(
        invoice_rows,
        columns=["invoice_id", "company_id", "product", "invoice_date", "due_date", "net_amount_czk", "payment_status", "paid_date"],
    ).to_csv(DATA_DIR / "invoices.csv", index=False)


@st.cache_resource
def get_connection():
    make_fake_data()
    connection = duckdb.connect(database=":memory:")
    for table_name in ["companies", "opportunities", "invoices"]:
        connection.register(table_name, pd.read_csv(DATA_DIR / f"{table_name}.csv"))
    connection.execute("SET enable_external_access = false")
    return connection


def run_sql(sql):
    connection = get_connection()
    query = validate_read_only_sql(sql, connection)
    return connection.execute(query).df()


def sql_card(sql, row_count=None):
    with st.expander(t("sql_trace")):
        st.code(sql, language="sql")
        if row_count is not None:
            st.caption(t("sql_rows", rows=row_count))


def parse_agent(text):
    prompt = text.lower()
    if any(term in prompt for term in ["produkt", "produkty", "product"]):
        return {
            "title": "Revenue podle produktu", "kind": "bar",
            "summary": "Dataset obsahuje období leden až říjen 2026; níže je revenue podle produktu za celé dostupné období.",
            "sql": """SELECT product AS produkt, SUM(net_amount_czk) AS revenue_czk,
       COUNT(*) AS pocet_faktur
FROM invoices
GROUP BY product
ORDER BY revenue_czk DESC""",
        }
    if any(term in prompt for term in ["po splatnosti", "overdue"]):
        return {
            "title": "Faktury po splatnosti", "kind": "table",
            "summary": "Níže jsou neuhrazené faktury, seřazené od nejvyšší hodnoty.",
            "sql": """SELECT c.company_name AS firma, c.segment, i.invoice_date AS datum_vystaveni,
       i.due_date AS splatnost, i.net_amount_czk AS castka_czk
FROM invoices i JOIN companies c USING (company_id)
WHERE i.payment_status = 'Overdue'
ORDER BY i.net_amount_czk DESC
LIMIT 100""",
        }
    if "pipeline" in prompt or "fáze" in prompt or "faze" in prompt:
        return {
            "title": "Pipeline podle fáze", "kind": "bar",
            "summary": "Hodnota aktivní i uzavřené pipeline je seskupená podle fáze obchodního procesu.",
            "sql": """SELECT stage AS faze, SUM(amount_czk) AS hodnota_czk, COUNT(*) AS pocet_prilezitosti
FROM opportunities
GROUP BY stage
ORDER BY hodnota_czk DESC""",
        }
    if any(term in prompt for term in ["měsíc", "mesic", "month"]):
        return {
            "title": "Revenue po měsících", "kind": "bar",
            "summary": "Revenue je počítané z faktur vystavených v jednotlivých měsících roku 2026.",
            "sql": """SELECT strftime(CAST(invoice_date AS DATE), '%Y-%m') AS mesic,
       SUM(net_amount_czk) AS revenue_czk
FROM invoices
GROUP BY mesic
ORDER BY mesic""",
        }
    return {
        "title": "Top firmy podle revenue", "kind": "table",
        "summary": "Zobrazuji deset firem s nejvyšším fakturovaným revenue.",
        "sql": """SELECT c.company_name AS firma, c.segment,
       SUM(i.net_amount_czk) AS revenue_czk, COUNT(i.invoice_id) AS pocet_faktur
FROM invoices i JOIN companies c USING (company_id)
GROUP BY c.company_name, c.segment
ORDER BY revenue_czk DESC
LIMIT 10""",
    }


def parse_visual_prompt(text):
    prompt = text.lower()
    if any(term in prompt for term in ["po splatnosti", "overdue"]):
        spec = {"title": "Faktury po splatnosti", "kind": "table", "sql": parse_agent("po splatnosti")["sql"], "x": "firma", "y": "castka_czk"}
    elif "pipeline" in prompt or "fáze" in prompt or "faze" in prompt:
        spec = {"title": "Pipeline podle fáze", "kind": "bar", "sql": parse_agent("pipeline")["sql"], "x": "faze", "y": "hodnota_czk"}
    elif any(term in prompt for term in ["produkt", "produkty", "product"]):
        spec = {"title": "Revenue podle produktu", "kind": "bar", "sql": parse_agent("produkt")["sql"], "x": "produkt", "y": "revenue_czk"}
    else:
        spec = {"title": "Revenue po měsících", "kind": "bar", "sql": parse_agent("měsíce")["sql"], "x": "mesic", "y": "revenue_czk"}

    spec.update(
        {
            "color": PINK if "růž" in prompt or "ruz" in prompt else GREEN,
            "highlight": GREEN if any(term in prompt for term in ["nejvyš", "maximum", " max"]) else None,
            "font": "Roboto" if "roboto" in prompt else "Arial",
            "title_size": 25 if any(term in prompt for term in ["větší", "vetsi", "larger"]) else 20,
            "position": "top" if any(term in prompt for term in ["nahoru", "top", "první", "prvni"]) else "bottom",
        }
    )
    if "histogram" in prompt:
        spec["kind"] = "bar"  # Monthly aggregates are correctly visualized as a bar chart, not a statistical histogram.
    return spec


def refine_context(context, text):
    """Apply a small, explicit set of follow-up filters to the previous query."""
    prompt = text.lower()
    filters = dict(context.get("filters", {}))
    for segment in ["Enterprise", "Mid-market", "SMB"]:
        if segment.lower() in prompt:
            filters["segment"] = segment
    for city in ["Praha", "Brno", "Ostrava", "Plzeň", "Liberec", "Olomouc"]:
        if city.lower() in prompt:
            filters["city"] = city

    limit = context.get("limit")
    for candidate in [3, 5, 10]:
        if f"top {candidate}" in prompt or f"top{candidate}" in prompt:
            limit = candidate

    result = dict(context["result"])
    conditions = []
    if filters.get("segment"):
        conditions.append(f"c.segment = '{filters['segment']}'")
    if filters.get("city"):
        conditions.append(f"c.city = '{filters['city']}'")
    if conditions:
        condition_sql = " AND ".join(conditions)
        sql = result["sql"]
        if "FROM invoices\n" in sql:
            sql = sql.replace("FROM invoices\n", "FROM invoices i JOIN companies c USING (company_id)\n")
        elif "FROM opportunities\n" in sql:
            sql = sql.replace("FROM opportunities\n", "FROM opportunities o JOIN companies c USING (company_id)\n")
        if "WHERE " in sql:
            sql = sql.replace("WHERE ", f"WHERE {condition_sql} AND ", 1)
        elif "GROUP BY" in sql:
            sql = sql.replace("GROUP BY", f"WHERE {condition_sql}\nGROUP BY", 1)
        result["sql"] = sql
        labels = []
        if filters.get("segment"):
            labels.append(f"segment {filters['segment']}")
        if filters.get("city"):
            labels.append(filters["city"])
        result["summary"] = f"Upřesněno na: {', '.join(labels)}. " + result["summary"]

    if limit and "LIMIT " in result["sql"]:
        import re
        result["sql"] = re.sub(r"LIMIT \d+", f"LIMIT {limit}", result["sql"])
    elif limit:
        result["sql"] += f"\nLIMIT {limit}"
    return {"result": result, "filters": filters, "limit": limit}


def chart_spec_from_result(result, prompt=""):
    data = run_sql(result["sql"])
    if result["kind"] == "query":
        numeric_columns = list(data.select_dtypes(include="number").columns)
        if len(data.columns) < 2 or not numeric_columns:
            return {"title": result["title"], "kind": "table", "sql": result["sql"], "x": data.columns[0], "y": data.columns[-1], "color": GREEN, "highlight": None, "font": "Arial", "title_size": 20, "position": "bottom"}
        y_column = numeric_columns[0]
        x_column = next((column for column in data.columns if column not in numeric_columns), None)
        if x_column is None:
            x_column = next((column for column in data.columns if column != y_column), None)
        if x_column is None:
            return {"title": result["title"], "kind": "table", "sql": result["sql"], "x": data.columns[0], "y": data.columns[-1], "color": GREEN, "highlight": None, "font": "Arial", "title_size": 20, "position": "bottom"}
        design = parse_visual_prompt(prompt or result["title"])
        design.update({"title": result["title"], "kind": "bar", "sql": result["sql"], "x": x_column, "y": y_column})
        return design
    if result["kind"] == "table" or len(data.columns) < 2:
        return {"title": result["title"], "kind": "table", "sql": result["sql"], "x": data.columns[0], "y": data.columns[-1], "color": GREEN, "highlight": None, "font": "Arial", "title_size": 20, "position": "bottom"}
    design = parse_visual_prompt(prompt or result["title"])
    design.update({"title": result["title"], "kind": "bar", "sql": result["sql"], "x": data.columns[0], "y": data.columns[1]})
    return design


def suggest_visual_title(spec):
    """Turn a chat instruction into a short, editable dashboard-card title."""
    title = re.sub(r"\s+", " ", str(spec.get("title") or "").strip())
    if not title:
        return ""
    title = re.sub(
        r"^(?:(?:please\s+)?(?:show|display|plot|chart|graph|visuali[sz]e|create)\s+(?:me\s+)?"
        r"(?:a\s+|an\s+|the\s+)?|(?:ukaž(?:te)?|zobraz(?:te)?|vykresli(?:te)?|"
        r"vytvoř(?:te)?|udělej(?:te)?)\s+(?:mi\s+)?)",
        "",
        title,
        flags=re.IGNORECASE,
    ).rstrip(" .!?")
    title = title or str(spec.get("title") or "").strip().rstrip(" .!?")
    return title[:1].upper() + title[1:]


def chart_figure(spec, data, show_title=True):
    if spec["kind"] in ("table", "metric"):
        return None
    font_family = "Plus Jakarta Sans" if spec["font"] == "Arial" else spec["font"]
    colors_for_bars = [spec["color"]] * len(data)
    if spec.get("highlight") and len(data):
        max_index = data[spec["y"]].astype(float).idxmax()
        colors_for_bars[data.index.get_loc(max_index)] = spec["highlight"]
    kind = spec.get("kind", "bar")
    if kind == "pie":
        figure = go.Figure(go.Pie(labels=data[spec["x"]], values=data[spec["y"]], marker_colors=colors_for_bars, hole=0.42))
    elif kind in ("line", "area"):
        figure = go.Figure(go.Scatter(x=data[spec["x"]], y=data[spec["y"]], mode="lines+markers", line={"color": spec["color"], "width": 3}, fill="tozeroy" if kind == "area" else None, fillcolor="rgba(11,59,46,.12)" if kind == "area" else None))
    else:
        figure = go.Figure(go.Bar(x=data[spec["x"]], y=data[spec["y"]], marker_color=colors_for_bars, text=[f"{value:,.0f}".replace(",", " ") for value in data[spec["y"]]], textposition="outside"))
    figure.update_layout(
        title={"text": spec["title"], "font": {"family": font_family, "size": spec["title_size"], "color": FOREST}} if show_title else None,
        font={"family": font_family, "color": SLATE}, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=58 if show_title else 24, r=18, b=30, l=20), height=340, xaxis_title="", yaxis_title="Kč", yaxis_gridcolor="#E5E7EB",
    )
    return figure


def format_card_value(value, spec):
    if pd.isna(value):
        return "—"
    if not isinstance(value, (int, float, np.number)):
        return str(value)
    decimals = min(4, max(0, int(spec.get("decimal_places", 0))))
    formatted = f"{float(value):,.{decimals}f}".replace(",", " ")
    if spec.get("value_format") == "currency_czk":
        return f"{formatted} Kč"
    if spec.get("value_format") == "percent":
        return f"{formatted} %"
    return formatted


def card_data(spec, page, filters=None):
    active_filters = filters if filters is not None else page["filters"]
    filtered_sql = apply_filters_to_sql(apply_time_granularity(spec["sql"], active_filters["period"]), active_filters)
    return filtered_sql, apply_card_preferences(run_sql(filtered_sql), spec)


def render_kpi(spec, page):
    _, current = card_data(spec, page)
    value = current.iloc[0, 0] if not current.empty and not current.columns.empty else None
    previous_filters = previous_period_filters(page["filters"])
    delta = None
    if previous_filters:
        _, previous = card_data(spec, page, previous_filters)
        if not previous.empty and not previous.columns.empty and isinstance(value, (int, float, np.number)):
            previous_value = previous.iloc[0, 0]
            if isinstance(previous_value, (int, float, np.number)):
                if previous_value == 0:
                    delta = None
                else:
                    delta = (float(value) - float(previous_value)) / abs(float(previous_value))
    if delta is None:
        st.metric(spec["title"], format_card_value(value, spec), help="Bez srovnatelných dat pro předchozí období.")
        return
    delta_text = f"{delta:+.1%}".replace(".", ",") + f" {spec.get('comparison_label', 'oproti předchozímu období')}"
    direction = spec.get("trend_direction", "higher_is_better")
    delta_color = "off" if direction == "neutral" else ("normal" if direction == "higher_is_better" else "inverse")
    st.metric(spec["title"], format_card_value(value, spec), delta=delta_text, delta_color=delta_color)


def render_card_content(spec, page, key_prefix, show_sql=True):
    """Render a card body without its dashboard management controls."""
    if spec["kind"] == "text":
        if spec.get("title") and spec["title"] != "Komentář":
            st.subheader(spec["title"])
        st.markdown(spec.get("text") or "")
        return
    if spec["kind"] == "kpi":
        render_kpi(spec, page)
        return
    filtered_sql, data = card_data(spec, page)
    if spec["kind"] == "table":
        st.subheader(spec["title"])
        st.dataframe(data, width="stretch", hide_index=True)
    elif spec["kind"] == "metric":
        value = data.iloc[0, 0] if not data.empty else None
        st.metric(spec["title"], format_card_value(value, spec))
    else:
        st.plotly_chart(chart_figure(spec, data), width="stretch", key=f"{key_prefix}-chart-{spec['id']}")
    if show_sql:
        sql_card(filtered_sql, len(data))


def render_dashboard_card(spec, page, document, index):
    with st.container(border=True, key=f"dashboard-card-{spec['id']}"):
        render_card_content(spec, page, f"dashboard-{page['id']}")
        controls = st.columns(4, gap="small")
        with controls[0]:
            if st.button(t("edit"), key=f"select-{spec['id']}", icon=":material/edit:", width="stretch"):
                st.session_state.selected_dashboard_card = spec["id"]
                st.session_state.dashboard_card_editor = spec["id"]
                st.rerun()
        with controls[1]:
            if st.button(t("move_up"), key=f"up-{spec['id']}", disabled=index == 0, icon=":material/arrow_upward:", width="stretch"):
                page["cards"][index - 1], page["cards"][index] = page["cards"][index], page["cards"][index - 1]
                save_dashboard(document)
                st.rerun()
        with controls[2]:
            if st.button(t("move_down"), key=f"down-{spec['id']}", disabled=index == len(page["cards"]) - 1, icon=":material/arrow_downward:", width="stretch"):
                page["cards"][index + 1], page["cards"][index] = page["cards"][index], page["cards"][index + 1]
                save_dashboard(document)
                st.rerun()
        with controls[3]:
            if st.button(t("remove"), key=f"delete-{spec['id']}", icon=":material/delete:", width="stretch"):
                page["cards"].pop(index)
                save_dashboard(document)
                st.rerun()


def render_dashboard_grid(page, document):
    grouped = {}
    for index, card in enumerate(page["cards"]):
        spec = normalize_card(card)
        page["cards"][index] = spec
        grouped.setdefault(spec["layout"]["row"], []).append((index, spec))
    for row in sorted(grouped):
        items = grouped[row]
        visual_rows, current, used = [], [], 0
        for item in items:
            width = item[1]["layout"]["width"]
            if current and used + width > 12:
                visual_rows.append(current)
                current, used = [], 0
            current.append(item)
            used += width
        if current:
            visual_rows.append(current)
        for visual_row in visual_rows:
            columns = st.columns([spec["layout"]["width"] for _, spec in visual_row], gap="medium")
            for column, (index, spec) in zip(columns, visual_row):
                with column:
                    render_dashboard_card(spec, page, document, index)


def create_kpi_from_instruction(instruction, page):
    """Create a one-value KPI query through the same safe path as Analytics chat."""
    question = re.sub(r"^(?:přidej|pridej|add)\s+(?:kpi|metriku|metric)\s*", "", instruction, flags=re.I).strip(" .:")
    if not question:
        return None, "Upřesněte, jakou KPI metriku chcete přidat."
    try:
        if get_openai_api_key():
            generated = get_llm_sql(question, [])
            if not generated or generated.get("clarification"):
                return None, generated.get("clarification") if generated else "KPI dotaz se nepodařilo připravit."
            sql = build_bounded_select_sql(generated["sql"], get_connection(), row_limit=1)
        else:
            plan = get_local_plan(question)
            if not plan:
                return None, "Tuto KPI v lokálním režimu neznám. Zkuste ji vytvořit s nastaveným OpenAI API klíčem."
            sql = build_analytics_result(plan)["sql"]
        data = run_sql(sql)
    except (LLMRequestError, ValueError, duckdb.Error) as error:
        return None, f"KPI dotaz se nepodařilo bezpečně vytvořit: {error}"
    if data.shape != (1, 1) or not pd.api.types.is_numeric_dtype(data.iloc[:, 0]):
        return None, "KPI musí vrátit právě jednu číselnou hodnotu. Zkuste zadání upřesnit."
    return normalize_card({
        "title": question[:1].upper() + question[1:], "kind": "kpi", "sql": sql,
        "x": data.columns[0], "y": data.columns[0],
        "layout": {"row": next((card["layout"]["row"] for card in reversed(page["cards"]) if "layout" in card), -1) + 1, "width": 4},
        "value_format": "currency_czk" if any(term in question.lower() for term in ("tržb", "trzb", "revenue", "částk", "castk", "amount", "marž", "marz")) else "number",
    }), None


def local_editor_plan(command, dashboard, page, selected_card_id):
    """Keep a small deterministic fallback when no API key is configured."""
    updated, notice = parse_editor_command(dashboard, page["id"], command, selected_card_id)
    if notice.startswith("Pokyn jsem nerozpoznal"):
        return None, t("editor_command_unrecognized")
    candidate = deepcopy(dashboard)
    candidate["pages"] = updated["pages"]
    if selected_card_id and st.session_state.get("language") == "en":
        selected = next((card for card in page_by_id(candidate, page["id"])["cards"] if card["id"] == selected_card_id), None)
        if selected:
            notice = t("editor_card_updated", title=selected["title"])
    return {"mode": "local", "command": command, "dashboard": candidate, "summary": notice}, None


def dashboard_editor_context(page, selected):
    return {
        "page": {"id": page["id"], "name": page["name"]},
        "selected_card": {"id": selected["id"], "title": selected["title"], "kind": selected["kind"]} if selected else None,
        "cards": [{"id": card["id"], "title": card["title"], "kind": card["kind"]} for card in page["cards"]],
    }


def plan_ai_dashboard_edit(command, dashboard, page, selected):
    """Turn a safe AI plan into a pending, reviewable dashboard mutation."""
    plan = get_dashboard_editor_plan(command, dashboard_editor_context(page, selected))
    if plan is None:
        return local_editor_plan(command, dashboard, page, selected["id"] if selected else None)
    if plan["action"] == "clarify":
        return None, plan.get("clarification") or "Upřesněte prosím požadovanou změnu."

    candidate = deepcopy(dashboard)
    target_page = page_by_id(candidate, page["id"])
    target = next((card for card in target_page["cards"] if selected and card["id"] == selected["id"]), None)
    if plan["action"] == "update_selected":
        if not target:
            return None, "Nejdřív vyberte kartu tlačítkem „Upravit“."
        changes = []
        if plan.get("title"):
            target["title"] = plan["title"].strip()[:120]
            changes.append("název")
        if plan.get("chart_kind"):
            target["kind"] = plan["chart_kind"]
            changes.append(f"typ grafu: {plan['chart_kind']}")
        if plan.get("color"):
            target["color"] = plan["color"]
            changes.append("barva")
        if plan.get("layout_width"):
            target["layout"]["width"] = plan["layout_width"]
            changes.append("šířka")
        if not changes:
            return None, "AI nenašla žádnou bezpečnou změnu k provedení."
        summary = f"Upravím kartu „{target['title']}“: {', '.join(changes)}."
    elif plan["action"] == "add_text":
        text = (plan.get("text") or "").strip()
        if not text:
            return None, "Chybí text komentáře."
        target_page["cards"].append(normalize_card({"title": plan.get("title") or "Komentář", "kind": "text", "text": text}))
        summary = "Přidám textový komentář na dashboard."
    elif plan["action"] == "add_page":
        name = (plan.get("title") or "").strip()
        if not name:
            return None, "Chybí název nové stránky."
        add_page(candidate, name)
        summary = f"Přidám stránku „{name}“."
    elif plan["action"] == "add_kpi":
        request = (plan.get("query_request") or command).strip()
        kpi, error = create_kpi_from_instruction(f"Přidej KPI {request}", target_page)
        if error:
            return None, error
        if plan.get("title"):
            kpi["title"] = plan["title"].strip()[:120]
        if plan.get("layout_width"):
            kpi["layout"]["width"] = plan["layout_width"]
        target_page["cards"].append(kpi)
        summary = f"Přidám KPI „{kpi['title']}“ s porovnáním předchozího období."
    else:
        return None, "AI navrhla nepodporovanou změnu."
    return {"mode": "ai", "command": command, "dashboard": candidate, "summary": summary}, None


def plan_dashboard_editor_command(command, dashboard, page, selected):
    if re.match(r"^(?:přidej|pridej|add)\s+(?:kpi|metriku|metric)\b", command.strip(), flags=re.I) and not get_openai_api_key():
        candidate = deepcopy(dashboard)
        target_page = page_by_id(candidate, page["id"])
        kpi, error = create_kpi_from_instruction(command, target_page)
        if error:
            return None, error
        target_page["cards"].append(kpi)
        return {"mode": "local", "command": command, "dashboard": candidate, "summary": f"Přidám KPI „{kpi['title']}“ s porovnáním předchozího období."}, None
    return plan_ai_dashboard_edit(command, dashboard, page, selected)


def load_dashboard():
    if not STORE.exists():
        document = normalize_workspace(None)
        save_dashboard(document)
        return document
    stored = json.loads(STORE.read_text(encoding="utf-8"))
    document = normalize_workspace(stored)
    if document != stored:
        save_dashboard(document)
    return document


def save_dashboard(document):
    STORE.parent.mkdir(exist_ok=True)
    STORE.write_text(json.dumps(normalize_workspace(document), ensure_ascii=False, indent=2), encoding="utf-8")


def chat_title_from_history(history):
    first_question = next((item.get("content", "") for item in history if item.get("role") == "user"), "")
    title = re.sub(r"\s+", " ", str(first_question)).strip()
    if not title:
        return "Uložený chat"
    return title[:57].rstrip() + "..." if len(title) > 60 else title


def saved_chat_by_id(document, chat_id):
    return next((chat for chat in document["saved_chats"] if chat["id"] == chat_id), None)


def save_current_chat(document):
    history = deepcopy(st.session_state.get("chat_history", []))
    chat_id = st.session_state.get("active_saved_chat_id")
    saved_chat = saved_chat_by_id(document, chat_id) if chat_id else None
    if saved_chat is None:
        saved_chat = {"id": uuid.uuid4().hex[:8], "title": chat_title_from_history(history), "history": history}
        document["saved_chats"].append(saved_chat)
        st.session_state.active_saved_chat_id = saved_chat["id"]
    else:
        saved_chat["history"] = history
    save_dashboard(document)


def reset_current_chat():
    st.session_state.chat_history = []
    st.session_state.analysis_context = None
    st.session_state.chat_notice = None
    st.session_state.dashboard_add_notice = None
    st.session_state.dashboard_add_item_index = None
    st.session_state.active_saved_chat_id = None


def reset_demo():
    """Restore the shared demo workspace and clear transient session state."""
    save_dashboard(normalize_workspace(None))
    reset_current_chat()
    st.session_state.workspace_view = "chat"
    st.session_state.active_dashboard_id = None
    st.session_state.active_dashboard_page = None
    st.session_state.selected_dashboard_card = None
    st.session_state.pending_dashboard_edit = None
    st.session_state.dashboard_editor_notice = None
    st.session_state.dashboard_menu_open = False
    st.session_state.dashboard_create_open = False
    st.session_state.saved_chat_menu_open = False
    st.session_state.demo_reset_notice = t("reset_demo_done")


def pdf_report(page):
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.4 * cm, leftMargin=1.4 * cm, topMargin=1.3 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Biizy — {page['name']}", styles["Title"]),
        Paragraph(f"{t('generated')}: {date.today().strftime('%d.%m.%Y')}", styles["Normal"]),
        Spacer(1, 14),
    ]
    for number, spec in enumerate(page["cards"], 1):
        spec = normalize_card(spec)
        if spec["kind"] == "text":
            story.extend([
                Paragraph(f"{number}. {spec['title']}", styles["Heading2"]),
                Paragraph(escape(spec.get("text") or "").replace("\n", "<br/>"), styles["Normal"]),
                Spacer(1, 12),
            ])
            continue
        filtered_sql = apply_filters_to_sql(apply_time_granularity(spec["sql"], page["filters"]["period"]), page["filters"])
        data = apply_card_preferences(run_sql(filtered_sql), spec)
        if spec["kind"] == "kpi":
            value = data.iloc[0, 0] if not data.empty else None
            story.extend([
                Paragraph(f"{number}. {spec['title']}", styles["Heading2"]),
                Paragraph(format_card_value(value, spec), styles["Title"]),
                Paragraph(spec.get("comparison_label", "oproti předchozímu období"), styles["Normal"]),
                Spacer(1, 6), Paragraph("SQL: " + spec["sql"].replace("\n", " "), styles["Code"]), Spacer(1, 15),
            ])
            continue
        story.extend([
            Paragraph(f"{number}. {spec['title']}", styles["Heading2"]),
            Paragraph(f"Typ: {spec['kind']} | Font: {spec['font']} | Barva: {spec['color']}", styles["Normal"]),
        ])
        preview = [list(data.columns)] + data.head(8).astype(str).values.tolist()
        table = Table(preview, repeatRows=1, colWidths=[(17.5 * cm) / max(1, len(data.columns))] * len(data.columns))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(FOREST)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.extend([Spacer(1, 5), table, Spacer(1, 6), Paragraph("SQL: " + spec["sql"].replace("\n", " "), styles["Code"]), Spacer(1, 15)])
    document.build(story)
    return buffer.getvalue()


def style_app():
    st.markdown(
        f"""<style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
        .stApp {{
            --ink: {FOREST}; --muted: {SLATE}; --accent: {PINK}; --accent-hover: #A8144D;
            --rose: #F9EDF2; --sage: #EAF3EE; --line: #DCE4DF; --surface: #FFFFFF;
            background: {PAPER}; color: var(--ink); font-family: 'Plus Jakarta Sans', sans-serif;
        }}
        .stApp :is(p, label, input, textarea, button) {{ font-family: 'Plus Jakarta Sans', sans-serif; }}
        .block-container {{ max-width: 1180px; padding-top: 1rem; padding-bottom: 3rem; }}
        h1,h2,h3,h4 {{ color: var(--ink); font-family: 'Plus Jakarta Sans', sans-serif; letter-spacing: -.035em; }}
        h1 {{ font-size: clamp(1.85rem, 4vw, 2.4rem) !important; font-weight: 600 !important; }}
        h2,h3 {{ font-weight: 600 !important; }}
        [data-testid='stCaptionContainer'], [data-testid='stCaptionContainer'] p {{ color: var(--muted); line-height: 1.6; opacity: 1; }}
        [data-testid='stSidebar'] {{ background: var(--ink); border-right: 0; }}
        [data-testid='stSidebar'] [data-testid='stMarkdownContainer'],
        [data-testid='stSidebar'] [data-testid='stWidgetLabel'] {{ color: white; }}
        [data-testid='stSidebar'] [data-testid='stCaptionContainer'],
        [data-testid='stSidebar'] [data-testid='stCaptionContainer'] p {{ color: #C8DBD2; }}
        [data-testid='stSidebar'] h1 {{ color: white; font-size: 1.65rem !important; }}
        .biizy-brand {{ display: flex; align-items: center; gap: 1.2rem; margin: .35rem 0 1.25rem; }}
        .biizy-mark {{ width: 4rem; height: 4rem; flex: 0 0 auto; filter: drop-shadow(0 5px 10px rgba(0,0,0,.2)); }}
        .biizy-name {{ color: white; font-size: 2.95rem; font-weight: 800; letter-spacing: -.095em; line-height: .84; text-shadow: 0 2px 12px rgba(0,0,0,.16); }}
        .biizy-tagline {{ color: #9FE2CF; font-size: .78rem; font-weight: 800; letter-spacing: .25em; line-height: 1.4; margin-top: .72rem; text-transform: uppercase; }}
        .st-key-language-switcher {{
            position: fixed; top: .48rem; right: 13.6rem; z-index: 1000001;
            display: flex; flex-wrap: nowrap; justify-content: flex-end; gap: .2rem; align-items: center; margin: 0;
        }}
        .st-key-language-cs, .st-key-language-en {{ margin: 0; }}
        .st-key-language-cs button, .st-key-language-en button {{
            position: relative; box-sizing: border-box; display: block; width: 2.1rem !important; min-width: 2.1rem !important;
            min-height: 1.4rem !important; height: 1.4rem !important; padding: 0 !important; line-height: 0 !important;
            border: 1px solid #B6C6D1 !important; border-radius: 2px !important; background-color: transparent !important;
            background-position: center !important; background-repeat: no-repeat !important; background-size: 100% 100% !important;
            overflow: visible;
        }}
        .st-key-language-cs button {{
            background-image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAzIDIiPjxwYXRoIGZpbGw9IiNmZmYiIGQ9Ik0wIDBoM3YySDB6Ii8+PHBhdGggZmlsbD0iI2Q3MTQxYSIgZD0iTTAgMWgzdjFIMHoiLz48cGF0aCBmaWxsPSIjMTE0NTdlIiBkPSJNMCAwdjJsMS41LTF6Ii8+PC9zdmc+") !important;
        }}
        .st-key-language-en button {{
            background-image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2MCAzMCI+PHJlY3Qgd2lkdGg9IjYwIiBoZWlnaHQ9IjMwIiBmaWxsPSIjMDEyMTY5Ii8+PHBhdGggZD0iTTAgMCA2MCAzME02MCAwIDAgMzAiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSI2Ii8+PHBhdGggZD0iTTAgMCA2MCAzME02MCAwIDAgMzAiIHN0cm9rZT0iI2M4MTAyZSIgc3Ryb2tlLXdpZHRoPSIyLjUiLz48cGF0aCBkPSJNMzAgMHYzME0wIDE1aDYwIiBzdHJva2U9IiNmZmYiIHN0cm9rZS13aWR0aD0iMTAiLz48cGF0aCBkPSJNMzAgMHYzME0wIDE1aDYwIiBzdHJva2U9IiNjODEwMmUiIHN0cm9rZS13aWR0aD0iNiIvPjwvc3ZnPg==") !important;
        }}
        .st-key-language-cs button p, .st-key-language-en button p {{ font-size: 0 !important; }}
        .st-key-language-cs button:hover::after, .st-key-language-en button:hover::after {{
            position: absolute; z-index: 1000; top: calc(100% + .45rem); left: 50%; transform: translateX(-50%);
            padding: .32rem .5rem; border-radius: 5px; color: white; background: #102A43; font-size: .72rem; font-weight: 700;
            line-height: 1; white-space: nowrap; box-shadow: 0 4px 12px rgba(0,0,0,.24); pointer-events: none;
        }}
        .st-key-language-cs button:hover::after {{ content: 'Čeština'; }}
        .st-key-language-en button:hover::after {{ content: 'English'; }}
        .st-key-language-cs button[kind^='primary'], .st-key-language-en button[kind^='primary'] {{
            border-color: var(--ink) !important; box-shadow: inset 0 0 0 1px #9FE2CF !important;
        }}
        @media (max-width: 700px) {{
            .st-key-language-switcher {{ right: 10.5rem; }}
        }}
        [data-testid='stSidebar'] [role='radiogroup'] {{ gap: .4rem; }}
        [data-testid='stSidebar'] [role='radiogroup'] label {{ border-radius: 10px; padding: .65rem .75rem; color: white; }}
        [data-testid='stSidebar'] [role='radiogroup'] label p {{ color: white; }}
        [data-testid='stSidebar'] [role='radiogroup'] label:has(input:checked) {{ background: var(--rose); color: var(--ink); }}
        [data-testid='stSidebar'] [role='radiogroup'] label:has(input:checked) p {{ color: var(--ink); }}
        [data-testid='stSidebar'] hr {{ border-color: rgba(255,255,255,.16); }}
        [data-testid='stSidebar'] button[kind='headerNoPadding'] {{ color: white; }}
        [data-testid='stTextArea'] textarea, [data-testid='stTextInput'] input,
        [data-baseweb='select'] > div, [data-baseweb='input'] {{
            background: var(--surface) !important; color: var(--ink) !important; border-radius: 10px !important;
        }}
        [data-testid='stTextArea'] textarea, [data-testid='stTextInput'] input {{ caret-color: var(--accent); }}
        textarea::placeholder, input::placeholder {{ color: #66746D !important; opacity: 1; }}
        [data-testid='stWidgetLabel'] p {{ font-weight: 500; }}
        [class*='st-key-dashboard-editor-'] [data-testid='stTextInput'] small {{ display: none !important; }}
        .editor-submit-hint {{ margin: -.35rem 0 .8rem; color: #54756A; font-size: .82rem; line-height: 1.35; }}
        [data-testid='stDialog'] [role='dialog'] {{
            width: min(960px, calc(100vw - 2rem)) !important;
            max-width: 960px !important;
            border-radius: 20px; border: 1px solid var(--line);
        }}
        [data-testid='stDialog'] [data-testid='stDialogContent'] {{ padding: .4rem .5rem .75rem; }}
        [data-baseweb='select'] {{ color: var(--ink); }}
        .stApp :is(button, input, textarea, [role='combobox']):focus-visible {{
            outline: 3px solid var(--accent) !important; outline-offset: 3px !important;
        }}
        [data-testid='stChatMessage'] {{
            background: var(--sage); border: 1px solid var(--line); border-radius: 16px;
            padding: 1.25rem !important; gap: .85rem !important; margin-bottom: .5rem;
        }}
        [data-testid='stChatMessage']:has([data-testid='stChatMessageAvatarUser']) {{
            background: var(--rose); border-color: #EDD4DF;
        }}
        [data-testid='stChatMessageAvatarUser'] {{ background: var(--rose) !important; color: var(--accent) !important; }}
        [data-testid='stChatMessageAvatarAssistant'] {{ background: var(--sage) !important; color: var(--ink) !important; }}
        [data-testid='stChatMessageContent'] {{ width: 100%; min-width: 0; overflow-wrap: anywhere; }}
        [data-testid='stChatMessage'] h3 {{ font-size: 1.35rem; padding-top: 0; }}
        [data-testid='stChatMessage'] [data-testid='stMetric'] {{ background: rgba(255,255,255,.65); }}
        [data-testid='stChatMessage'] [data-testid='stExpander'] {{ background: rgba(255,255,255,.5); }}
        .st-key-demo-project-notice {{
            margin: 0 0 1.25rem; padding: 1.4rem 1.45rem 1rem; background: #FCE4EC; border: 1px solid #EC407A;
            border-radius: 16px; box-shadow: 0 10px 28px rgba(194,24,91,.16);
        }}
        .st-key-demo-project-notice:has(.st-key-show-demo-project-notice) {{
            position: relative; z-index: 1000002; top: -3.45rem; left: -4.625rem;
            margin: 0 0 -0.75rem; padding: 0; background: transparent; border: 0; box-shadow: none;
        }}
        .st-key-demo-project-notice:has(.st-key-show-demo-project-notice) [data-testid='stButton'] > button {{
            min-height: 2.7rem; padding: .55rem 1rem; background: #C2185B !important;
            color: #FFFFFF !important; border: 1px solid #AD1457 !important; font-weight: 700;
            box-shadow: 0 4px 12px rgba(194,24,91,.24);
        }}
        .st-key-demo-project-notice:has(.st-key-show-demo-project-notice) button p,
        .st-key-demo-project-notice:has(.st-key-show-demo-project-notice) button [data-testid='stMarkdownContainer'] {{ color: #FFFFFF !important; }}
        .demo-project-notice__content {{ color: #880E4F; font-size: 1rem; font-weight: 500; line-height: 1.6; }}
        .demo-project-notice__content h2 {{ margin: .1rem 0 .65rem; color: #AD1457; font-size: 1.3rem !important; }}
        .demo-project-notice__content p {{ margin: .55rem 0; color: #880E4F; }}
        .demo-project-notice__sections {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .65rem; margin: .95rem 0; }}
        .demo-project-notice__sections section {{ padding: .7rem .8rem; background: rgba(255,255,255,.48); border: 1px solid rgba(194,24,91,.18); border-radius: 10px; }}
        .demo-project-notice__sections h3 {{ margin: 0 0 .35rem; color: #AD1457; font-size: .91rem !important; font-weight: 800; letter-spacing: .01em; }}
        .demo-project-notice__sections ul, .demo-project-notice__sections ol {{ margin: 0; padding-left: 1.1rem; }}
        .demo-project-notice__sections li {{ margin: .22rem 0; font-size: .9rem; }}
        .demo-project-notice__content a {{ color: #C2185B; font-weight: 800; }}
        #stDeployButton, [data-testid='stDeployButton'] {{ display: none !important; }}
        .st-key-demo-project-notice [data-testid='stButton'] > button {{
            min-height: 2.4rem; padding: .5rem .85rem; border-color: #EC407A; color: #AD1457; font-weight: 700;
        }}
        @media (max-width: 700px) {{
            .st-key-demo-project-notice:has(.st-key-show-demo-project-notice) {{
                top: 0; left: 0; margin-bottom: .75rem;
            }}
            .demo-project-notice__sections {{ grid-template-columns: 1fr; }}
        }}
        .dashboard-filter-note {{ color: var(--muted); font-size: .85rem; margin-top: .25rem; }}
        .st-key-dashboard-filters [data-testid='stHorizontalBlock'] {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr));
            gap: 1rem 1.5rem;
        }}
        .st-key-dashboard-filters [data-testid='stColumn'] {{
            width: 100%; min-width: 0;
        }}
        .st-key-dashboard-filters {{ border-top: 3px solid var(--accent); }}
        .st-key-dashboard-filters h4 {{ color: var(--accent); }}
        code, pre, [data-testid='stMetricValue'] {{ font-family: 'Plus Jakarta Sans', sans-serif; }}
        [data-testid='stButton'] > button, [data-testid='stFormSubmitButton'] > button,
        [data-testid='stDownloadButton'] > button {{
            background: var(--surface); color: var(--ink); border: 1px solid var(--line);
            border-radius: 10px; min-height: 44px; height: auto; padding: .65rem .9rem;
            max-width: 100%; white-space: normal; transition: background-color .15s, border-color .15s;
        }}
        [data-testid='stButton'] > button p, [data-testid='stFormSubmitButton'] > button p,
        [data-testid='stDownloadButton'] > button p {{
            color: inherit; white-space: normal; overflow-wrap: anywhere; font-weight: 500; line-height: 1.4;
        }}
        [data-testid='stButton'] > button:hover, [data-testid='stFormSubmitButton'] > button:hover,
        [data-testid='stDownloadButton'] > button:hover {{ background: var(--rose); border-color: var(--accent); color: var(--accent); }}
        .stApp button[kind^='primary'] {{ background: var(--accent); border-color: var(--accent); color: white; }}
        .stApp button[kind^='primary']:hover {{ background: var(--accent-hover); border-color: var(--accent-hover); color: white; }}
        .stApp button:disabled {{ opacity: .45; cursor: not-allowed; }}
        [data-testid='stSidebar'] [data-testid='stButton'] > button p,
        [data-testid='stSidebar'] [data-testid='stFormSubmitButton'] > button p {{ color: inherit; }}
        [data-testid='stSidebar'] button [data-testid='stMarkdownContainer'] {{ color: inherit; }}
        [data-testid='stSidebar'] .st-key-dashboard-submenu,
        [data-testid='stSidebar'] .st-key-saved-chat-submenu {{
            margin-left: .75rem; width: calc(100% - .75rem);
            padding-left: 1rem; border-left: 2px solid #8EAEA0;
        }}
        [data-testid='stSidebar'] .st-key-dashboard-submenu button[kind='primary'],
        [data-testid='stSidebar'] .st-key-dashboard-submenu button[kind='primary']:hover,
        [data-testid='stSidebar'] .st-key-saved-chat-submenu button[kind='primary'],
        [data-testid='stSidebar'] .st-key-saved-chat-submenu button[kind='primary']:hover {{
            background: var(--accent); border-color: var(--accent); color: white;
        }}
        .st-key-dashboard-page-navigation [role='tablist'] {{
            gap: .35rem; border-bottom: 1px solid var(--line);
        }}
        .st-key-dashboard-page-navigation [role='tab'] {{
            min-height: 44px; padding: .65rem 1rem;
            border: 1px solid var(--line); border-bottom: 0;
            border-radius: 10px 10px 0 0; background: var(--sage); color: var(--ink);
        }}
        .st-key-dashboard-page-navigation [role='tab'][aria-selected='true'] {{
            background: var(--accent); color: white; font-weight: 600;
        }}
        .st-key-dashboard-page-navigation [role='tab'][aria-selected='true'] p {{ font-weight: 600; }}
        .st-key-dashboard-page-navigation [data-baseweb='tab-highlight'] {{ background: var(--accent); }}
        .st-key-dashboard-page-navigation [data-testid='stPopover'] > button {{
            min-height: 44px; color: var(--accent); background: var(--rose); border-color: #EDD4DF;
        }}
        [class*='st-key-delete-'] button {{ color: var(--accent); }}
        [class*='st-key-delete-'] button:hover {{ background: var(--rose); border-color: var(--accent); color: var(--accent); }}
        [data-testid='stForm'], [data-testid='stVerticalBlockBorderWrapper'] > div {{
            border-color: var(--line); border-radius: 14px;
        }}
        [data-testid='stForm'] {{ background: var(--surface); padding: 1.25rem; }}
        [class*='st-key-dashboard-card-'] {{ background: var(--surface); border-radius: 14px; }}
        [class*='st-key-card-editor-preview-'], [class*='st-key-dashboard-proposal-card-preview'] {{
            background: #FCF8FA; border-color: #E8BED1; border-radius: 14px;
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) [role='dialog'] {{
            width: min(94vw, 1320px) !important; max-width: calc(100vw - 1.5rem) !important; min-height: min(88vh, 980px);
            overflow-x: hidden;
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) [data-testid='stDialogContent'] {{
            box-sizing: border-box; width: 100%; min-width: 0; padding: 1.4rem 1.65rem 1.65rem; overflow-x: hidden;
        }}
        .card-editor-dialog {{ display: none; }}
        [data-testid='stDialog']:has(.card-editor-dialog) [data-testid='stHorizontalBlock'] {{ align-items: stretch; min-width: 0; }}
        [data-testid='stDialog']:has(.card-editor-dialog) [data-testid='stColumn'] {{ min-width: 0; }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel,
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-preview-panel {{
            box-sizing: border-box; min-height: 24rem; height: 100%; border-radius: 16px; overflow: hidden;
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel {{
            background: linear-gradient(145deg, #0B3B2E 0%, #164D3B 100%); border-color: #0B3B2E; padding: 1.25rem;
            box-shadow: inset 0 1px 0 rgba(255,255,255,.1);
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel h4,
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stCaptionContainer'],
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stCaptionContainer'] p,
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stWidgetLabel'] p {{ color: #FFFFFF !important; }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stForm'] {{
            min-height: 14rem; background: #FFFFFF; border-color: #B7CEC4; padding: 1.1rem;
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stForm'] [data-testid='stWidgetLabel'] p,
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stForm'] .editor-submit-hint {{ color: #0B3B2E !important; }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stForm'] [data-baseweb='input'] {{
            background: #FFFFFF; border-color: #B7CEC4;
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stForm'] input {{ color: #0B3B2E !important; }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stForm'] input::placeholder {{ color: #6E827A !important; opacity: 1; }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stFormSubmitButton'] > button {{
            background: #F2F8F5; border-color: #B7CEC4; color: #0B3B2E;
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-ai-panel [data-testid='stFormSubmitButton'] > button:hover {{
            background: #DDF5EE; border-color: #0B3B2E; color: #0B3B2E;
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-preview-panel,
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-manual-panel {{
            box-sizing: border-box; width: 100%; min-width: 0; background: #FFFFFF; border-color: #DCE4DF; border-radius: 16px; padding: 1.25rem;
        }}
        [data-testid='stDialog']:has(.card-editor-dialog) .st-key-card-editor-preview-panel {{ min-height: 24rem; }}
        [data-testid='stDialog']:has(.card-editor-dialog) [class*='st-key-card-editor-preview-'] {{
            box-sizing: border-box; width: 100%; min-width: 0; min-height: 18.4rem; background: #FCF8FA; border-color: #E8BED1;
        }}
        .color-swatch {{ display: flex; align-items: center; gap: .65rem; margin: -.35rem 0 .85rem; color: var(--muted); font-size: .82rem; font-weight: 700; }}
        .color-swatch__chip {{ width: 1.5rem; height: 1.5rem; border: 2px solid white; border-radius: 50%; box-shadow: 0 0 0 1px var(--line); flex: 0 0 auto; }}
        .color-swatch code {{ color: var(--ink); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem; }}
        [data-testid='stSidebar'] [data-testid='stForm'] {{ background: transparent; border-color: rgba(255,255,255,.2); }}
        [data-testid='stDataFrame'] {{ border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }}
        [data-testid='stMetric'] {{ background: var(--surface); border-radius: 12px; padding: 1rem 1.2rem; }}
        [data-testid='stExpander'] {{ border-color: var(--line); border-radius: 10px; }}
        .block-container:has(.chat-heading) {{ padding-top: 3rem; padding-bottom: 1rem; }}
        .chat-heading {{ display: flex; align-items: center; gap: .5rem; position: relative; }}
        .chat-heading h1 {{ padding: 0; margin: 0; }}
        .chat-info {{ display: inline-flex; }}
        .chat-info > button {{
            border: 1px solid var(--muted); border-radius: 50%; width: 22px; height: 22px;
            padding: 0; background: transparent; color: var(--accent); font: 600 14px 'Plus Jakarta Sans', sans-serif;
            cursor: help;
        }}
        .chat-tooltip {{
            display: none; position: absolute; top: 100%; left: 0; z-index: 1000;
            width: min(28rem, calc(100vw - 3rem)); padding: 1rem;
            background: var(--surface); color: var(--ink); border: 1px solid var(--line);
            border-radius: 12px; box-shadow: 0 8px 28px rgba(11,59,46,.14);
            font-size: .9rem; line-height: 1.6; font-weight: 400;
        }}
        .chat-tooltip p {{ margin: 0 0 .65rem; font-size: inherit; }}
        .chat-tooltip p:last-child {{ margin: 0; color: var(--muted); }}
        .chat-info:hover .chat-tooltip, .chat-info:focus-within .chat-tooltip {{ display: block; }}
        .st-key-analytics_chat_form {{ padding: .8rem 1rem; }}
        @media (max-width: 700px) {{
            .block-container {{ padding: 1.25rem 1rem 2rem; }}
            [data-testid='stChatMessage'] {{ padding: .85rem !important; gap: .5rem !important; }}
            [data-testid='stForm'] {{ padding: 1rem; }}
        }}
        @media (prefers-reduced-motion: reduce) {{ .stApp button {{ transition: none !important; }} }}
        </style>""",
        unsafe_allow_html=True,
    )
@st.dialog(t("add_to_dashboard_title"), width="large")
def render_add_to_dashboard_dialog(document, spec, index):
    """Save a chat result to a selected dashboard and page."""
    dashboard_ids = [item["id"] for item in document["dashboards"]]
    dashboard_names = {item["id"]: item["name"] for item in document["dashboards"]}
    active_dashboard_id = st.session_state.get("active_dashboard_id")
    selected_index = dashboard_ids.index(active_dashboard_id) if active_dashboard_id in dashboard_ids else 0
    target_dashboard = None
    selected_page_id = None
    new_dashboard_name = None

    dashboard_column, page_column = st.columns(2)
    with dashboard_column:
        selected_dashboard_id = st.selectbox(
            t("target_dashboard"),
            dashboard_ids + [CREATE_NEW_DASHBOARD],
            index=selected_index,
            format_func=lambda value: (
                t("create_new_dashboard") if value == CREATE_NEW_DASHBOARD else dashboard_names[value]
            ),
            key=f"dashboard-target-{index}",
        )
    is_new_dashboard = selected_dashboard_id == CREATE_NEW_DASHBOARD
    page_ids = (
        [NEW_DASHBOARD_OVERVIEW]
        if is_new_dashboard
        else [page["id"] for page in dashboard_by_id(document, selected_dashboard_id)["pages"]]
    )
    page_names = (
        {NEW_DASHBOARD_OVERVIEW: t("overview")}
        if is_new_dashboard
        else {
            page["id"]: page["name"]
            for page in dashboard_by_id(document, selected_dashboard_id)["pages"]
        }
    )
    active_page_id = st.session_state.get("active_dashboard_page")
    page_index = page_ids.index(active_page_id) if active_page_id in page_ids else 0
    with page_column:
        selected_page_id = st.selectbox(
            t("target_page"),
            page_ids,
            index=page_index,
            format_func=page_names.__getitem__,
            key=f"dashboard-target-page-{index}-{selected_dashboard_id}",
            disabled=is_new_dashboard,
        )

    if is_new_dashboard:
        new_dashboard_name = st.text_input(
            t("dashboard_name"), placeholder=t("new_page_placeholder"), max_chars=60,
            key=f"dashboard-new-name-{index}",
        )
        destination_dashboard = new_dashboard_name.strip() or t("new_dashboard_placeholder")
    else:
        target_dashboard = dashboard_by_id(document, selected_dashboard_id)
        destination_dashboard = target_dashboard["name"]

    visual_title = st.text_input(
        t("visual_name"), value=suggest_visual_title(spec), max_chars=120,
        key=f"dashboard-visual-title-{index}",
    )
    st.markdown(t(
        "save_destination",
        dashboard=escape(destination_dashboard),
        page=escape(page_names[selected_page_id]),
        title=escape(visual_title.strip() or "…"),
    ), unsafe_allow_html=True)

    confirm_column, cancel_column = st.columns([1, 1], gap="small")
    with confirm_column:
        confirm = st.button(
            t("confirm_add_dashboard"), key=f"confirm-add-dashboard-{index}",
            type="primary", icon=":material/add:", use_container_width=True,
        )
    with cancel_column:
        cancel = st.button(t("cancel_add_dashboard"), key=f"cancel-add-dashboard-{index}", use_container_width=True)

    if cancel:
        st.session_state.dashboard_add_item_index = None
        st.rerun()
    if not confirm:
        return
    if new_dashboard_name is not None and not new_dashboard_name.strip():
        st.error(t("dashboard_name_required"))
        return
    if new_dashboard_name is not None and dashboard_name_exists(document, new_dashboard_name):
        st.error(t("dashboard_name_exists"))
        return
    if not visual_title.strip():
        st.error(t("visual_name_required"))
        return
    if new_dashboard_name is not None:
        target_dashboard = add_dashboard(document, new_dashboard_name, t("overview"))
        selected_page_id = target_dashboard["pages"][0]["id"]
    saved_spec = {**spec, "title": visual_title.strip()[:120]}
    added_page = add_card_to_page(target_dashboard, selected_page_id, saved_spec)
    save_dashboard(document)
    st.session_state.active_dashboard_id = target_dashboard["id"]
    st.session_state.active_dashboard_page = added_page["id"]
    st.session_state.dashboard_add_item_index = None
    st.session_state.dashboard_add_notice = t(
        "added_dashboard", dashboard=target_dashboard["name"], page=added_page["name"],
    )
    st.rerun()


def _card_editor_draft(card_id, selected):
    """Keep one isolated editable card draft while the dialog is open."""
    draft_key = "dashboard_card_editor_draft"
    current = st.session_state.get(draft_key)
    if not current or current.get("id") != card_id:
        st.session_state[draft_key] = {
            "id": card_id, "title": selected["title"], "kind": selected["kind"], "color": selected["color"],
            "sort_order": selected.get("sort_order", "original"), "text": selected.get("text", ""),
            "decimal_places": int(selected.get("decimal_places", 0)), "value_format": selected.get("value_format", "number"),
            "trend_direction": selected.get("trend_direction", "higher_is_better"), "layout": deepcopy(selected["layout"]),
        }
    return st.session_state[draft_key]


@st.dialog(t("card_editor_title"), width="large")
def render_card_editor_dialog(document, dashboard, page, card_id):
    """Edit one card beside a live, unsaved rendering of that card."""
    st.markdown("<div class='card-editor-dialog'></div>", unsafe_allow_html=True)
    selected_index = next((index for index, card in enumerate(page["cards"]) if card["id"] == card_id), None)
    if selected_index is None:
        st.session_state.dashboard_card_editor = None
        st.session_state.pop("dashboard_card_editor_draft", None)
        st.rerun()
    selected = normalize_card(page["cards"][selected_index])
    draft = _card_editor_draft(card_id, selected)
    ai_column, preview_column = st.columns([.9, 1.7], gap="large")
    with ai_column:
        with st.container(border=True, key="card-editor-ai-panel"):
            st.markdown("#### " + t("dashboard_editor"))
            st.caption(t("editor_example"))
            with st.form(f"card-editor-command-{card_id}", clear_on_submit=True):
                command = st.text_input(t("editor_instruction"), placeholder=t("editor_placeholder"), key=f"editor-command-{card_id}")
                st.markdown("<div class='editor-submit-hint'>" + t("editor_submit_hint") + "</div>", unsafe_allow_html=True)
                proposed = st.form_submit_button(t("propose_change"), type="primary", icon=":material/auto_awesome:", width="stretch")
            if proposed:
                pending, error = plan_dashboard_editor_command(command, dashboard, page, selected)
                if error:
                    st.error(error)
                else:
                    st.session_state.pending_dashboard_edit = pending
                    st.rerun()
            pending = st.session_state.get("pending_dashboard_edit")
            if pending:
                with st.container(border=True, key="card-editor-command-preview"):
                    st.markdown("#### " + t("change_preview"))
                    st.write(pending["summary"])
                    st.caption(t("change_preview_note"))
                    confirm_column, cancel_column = st.columns(2, gap="small")
                    with confirm_column:
                        if st.button(t("confirm_change"), type="primary", icon=":material/check:", width="stretch", key=f"confirm-card-command-{card_id}"):
                            save_dashboard_snapshot(document, dashboard, pending["summary"])
                            replacement = pending["dashboard"]
                            dashboard["name"] = replacement["name"]
                            dashboard["pages"] = replacement["pages"]
                            save_dashboard(document)
                            st.session_state.pending_dashboard_edit = None
                            st.session_state.dashboard_card_editor = None
                            st.session_state.pop("dashboard_card_editor_draft", None)
                            st.session_state.dashboard_editor_notice = pending["summary"]
                            st.rerun()
                    with cancel_column:
                        if st.button(t("discard_proposal"), icon=":material/close:", width="stretch", key=f"discard-card-command-{card_id}"):
                            st.session_state.pending_dashboard_edit = None
                            st.rerun()
    with preview_column:
        with st.container(border=True, key="card-editor-preview-panel"):
            st.markdown("#### " + t("working_preview"))
            st.caption(t("working_preview_note"))
            preview = normalize_card({**selected, **draft, "layout": dict(draft["layout"])})
            with st.container(border=True, key=f"card-editor-preview-{card_id}"):
                render_card_content(preview, page, f"editor-preview-{card_id}", show_sql=False)
            pending = st.session_state.get("pending_dashboard_edit")
            if pending:
                preview_dashboard = pending["dashboard"]
                preview_page = page_by_id(preview_dashboard, page["id"])
                preview_card = next((card for card in preview_page["cards"] if card["id"] == card_id), None) if preview_page else None
                if preview_card:
                    st.caption(t("change_preview"))
                    with st.container(border=True, key="card-editor-ai-preview"):
                        render_card_content(normalize_card(preview_card), preview_page, "card-command-preview", show_sql=False)
    st.divider()
    with st.container(border=True, key="card-editor-manual-panel"):
        st.markdown("#### " + t("card_editor_settings"))
        manual_row_one = st.columns([1.8, 1.15, 1.35], gap="medium")
        with manual_row_one[0]:
            draft["title"] = st.text_input(t("name"), value=draft["title"], key=f"editor-title-{card_id}")
        with manual_row_one[1]:
            draft["kind"] = st.selectbox(t("chart_type"), CHART_KINDS, index=CHART_KINDS.index(draft["kind"]), key=f"editor-kind-{card_id}")
        with manual_row_one[2]:
            draft["color"] = st.selectbox(
                t("color"), COLORS, index=COLORS.index(draft["color"]),
                format_func=lambda color: COLOR_OPTION_LABELS[color], key=f"editor-color-{card_id}",
            )
            st.markdown(
                f"<div class='color-swatch'><span class='color-swatch__chip' style='background:{draft['color']}'></span>"
                f"{t('selected_color')}: <code>{draft['color']}</code></div>", unsafe_allow_html=True,
            )
        manual_row_two = st.columns(4, gap="medium")
        with manual_row_two[0]:
            draft["sort_order"] = st.selectbox(t("sort"), ["original", "ascending", "descending"], index=["original", "ascending", "descending"].index(draft["sort_order"]), key=f"editor-sort-{card_id}")
        with manual_row_two[1]:
            draft["layout"]["width"] = st.selectbox(t("block_width"), [12, 6, 4, 3], index=[12, 6, 4, 3].index(draft["layout"]["width"]), key=f"editor-width-{card_id}")
        with manual_row_two[2]:
            draft["decimal_places"] = int(st.number_input(t("decimal_places"), min_value=0, max_value=4, value=draft["decimal_places"], step=1, key=f"editor-decimals-{card_id}"))
        with manual_row_two[3]:
            draft["value_format"] = st.selectbox(t("value_format"), ["number", "currency_czk", "percent"], index=["number", "currency_czk", "percent"].index(draft["value_format"]), key=f"editor-format-{card_id}")
        manual_row_three = st.columns([1, 1, 2], gap="medium")
        with manual_row_three[0]:
            draft["layout"]["row"] = int(st.number_input(t("layout_row"), min_value=0, value=draft["layout"]["row"], step=1, key=f"editor-row-{card_id}"))
        with manual_row_three[1]:
            draft["trend_direction"] = st.selectbox(t("trend_evaluation"), ["higher_is_better", "lower_is_better", "neutral"], index=["higher_is_better", "lower_is_better", "neutral"].index(draft["trend_direction"]), key=f"editor-trend-{card_id}")
        with manual_row_three[2]:
            if draft["kind"] == "text":
                draft["text"] = st.text_area(t("comment_text"), value=draft["text"], key=f"editor-text-{card_id}")
        save_column, discard_column = st.columns(2, gap="small")
        with save_column:
            if st.button(t("save_changes"), type="primary", icon=":material/save:", width="stretch"):
                saved_draft = {
                    **draft,
                    "title": st.session_state[f"editor-title-{card_id}"],
                    "kind": st.session_state[f"editor-kind-{card_id}"],
                    "color": st.session_state[f"editor-color-{card_id}"],
                    "sort_order": st.session_state[f"editor-sort-{card_id}"],
                    "decimal_places": st.session_state[f"editor-decimals-{card_id}"],
                    "value_format": st.session_state[f"editor-format-{card_id}"],
                    "trend_direction": st.session_state[f"editor-trend-{card_id}"],
                    "layout": {
                        "row": st.session_state[f"editor-row-{card_id}"],
                        "width": st.session_state[f"editor-width-{card_id}"],
                    },
                }
                if saved_draft["kind"] == "text":
                    saved_draft["text"] = st.session_state[f"editor-text-{card_id}"]
                save_dashboard_snapshot(document, dashboard, f"Ruční úprava karty „{selected['title']}“")
                page["cards"][selected_index] = normalize_card({**selected, **saved_draft, "layout": dict(saved_draft["layout"])})
                save_dashboard(document)
                st.session_state.dashboard_card_editor = None
                st.session_state.pop("dashboard_card_editor_draft", None)
                st.session_state.dashboard_editor_notice = t("card_updated")
                st.rerun()
        with discard_column:
            if st.button(t("discard_changes"), icon=":material/close:", width="stretch"):
                st.session_state.dashboard_card_editor = None
                st.session_state.pop("dashboard_card_editor_draft", None)
                st.rerun()


def render_chat_item(item, index):
    with st.chat_message(item["role"]):
        if item["role"] == "user":
            st.caption(t("you_question"))
            st.markdown(item["content"])
            return
        if item.get("mode") in ("clarification", "error"):
            if item["mode"] == "error":
                st.error(item["content"])
                if item.get("sql") or item.get("details"):
                    with st.expander(t("sql_diagnostics")):
                        if item.get("sql"):
                            st.code(item["sql"], language="sql")
                        if item.get("details"):
                            st.code(item["details"])
            else:
                st.info(item["content"])
            return
        if item.get("mode") == "knowledge":
            st.subheader(item["title"])
            st.markdown(item["content"])
            st.caption("Zdroj: semantický model · bez spuštění SQL" if st.session_state.get("language") == "cs" else "Source: semantic model · no SQL executed")
            return
        result = item["result"]
        data = run_sql(result["sql"])
        visual = item["mode"] == "visual"
        if visual:
            spec = normalize_card(item["spec"])
        elif result["kind"] == "query" and data.shape == (1, 1):
            spec = {
                "title": result["title"], "kind": "metric", "sql": result["sql"],
                "x": data.columns[0], "y": data.columns[0],
            }
        elif result["kind"] in ("query", "table"):
            spec = {
                "title": result["title"], "kind": "table", "sql": result["sql"],
                "x": data.columns[0], "y": data.columns[-1],
            }
        elif result["kind"] == "metric":
            spec = {
                "title": result["title"], "kind": "metric", "sql": result["sql"],
                "x": data.columns[0], "y": data.columns[0],
            }
        else:
            spec = chart_spec_from_result(result)
        st.subheader(result["title"])
        if result["kind"] != "query":
            st.write(result["summary"])
        if result["kind"] == "metric":
            value = data.iloc[0, 0] if not data.empty else 0
            st.metric(result.get("metric_label", result["title"]), f"{float(value):,.0f}".replace(",", " "))
        elif result["kind"] == "query" and data.shape == (1, 1):
            value = data.iloc[0, 0]
            if isinstance(value, (int, float, np.number)):
                numeric_value = float(value)
                formatted_value = f"{numeric_value:,.0f}" if numeric_value.is_integer() else f"{numeric_value:,.2f}"
                st.metric(t("query_value"), formatted_value.replace(",", " "))
            else:
                st.metric(t("query_value"), str(value))
        elif visual:
            st.caption(t("chart_details", kind=spec["kind"], color=spec["color"], font=spec["font"], highlight=spec.get("highlight") or t("no_highlight")))
            if spec["kind"] == "table":
                st.dataframe(data, use_container_width=True, hide_index=True)
            else:
                st.plotly_chart(chart_figure(spec, data, show_title=False), use_container_width=True, key=f"chat-chart-{index}")
        else:
            if result["kind"] == "bar":
                st.plotly_chart(chart_figure(spec, data, show_title=False), use_container_width=True, key=f"answer-chart-{index}")
            st.dataframe(data, use_container_width=True, hide_index=True)
            st.download_button(t("download_csv"), data.to_csv(index=False).encode("utf-8-sig"), f"biizy-{index}.csv", "text/csv", key=f"download-{index}", icon=":material/download:")

        add_open_key = "dashboard_add_item_index"
        if st.button(t("add_dashboard"), key=f"add-dashboard-{index}", type="primary", icon=":material/dashboard_customize:"):
            st.session_state[add_open_key] = index
            render_add_to_dashboard_dialog(load_dashboard(), spec, index)
        elif st.session_state.get(add_open_key) == index:
            render_add_to_dashboard_dialog(load_dashboard(), spec, index)
        sql_card(result["sql"], len(data))


def render_analytics_chat_form():
    with st.form("analytics_chat_form", clear_on_submit=True, enter_to_submit=True):
        prompt = st.text_input(
            t("question"),
            placeholder=t("question_placeholder"),
            help=t("question_help"),
        )
        answer_column, visual_column = st.columns([1, 1], gap="small")
        answer = answer_column.form_submit_button(
            t("show_answer"), type="primary", icon=":material/send:", use_container_width=True,
        )
        visual = visual_column.form_submit_button(
            t("create_chart"), icon=":material/bar_chart:", use_container_width=True,
        )
    return prompt, answer, visual


def render_analytics_chat(document):
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "analysis_context" not in st.session_state:
        st.session_state.analysis_context = None
    if "chat_notice" not in st.session_state:
        st.session_state.chat_notice = None
    if "dashboard_add_notice" not in st.session_state:
        st.session_state.dashboard_add_notice = None
    if "chat_mode" not in st.session_state:
        st.session_state.chat_mode = "OpenAI AI mode — ready" if get_openai_api_key() else "Local demo mode — no OpenAI API key configured"
    if "active_saved_chat_id" not in st.session_state:
        st.session_state.active_saved_chat_id = None

    title_column, save_column, reset_column = st.columns([3, 1, 1], vertical_alignment="center")
    with title_column:
        st.markdown(
            f"<div class='chat-heading'><h1>{escape(t('chat_title'))}</h1>"
            f"<span class='chat-info'><button type='button' aria-label='{escape(t('chat_guide'), quote=True)}' "
            "aria-describedby='chat-help'>i</button>"
            f"<span class='chat-tooltip' role='tooltip' id='chat-help'>"
            f"<p><b>{escape(t('chat_empty'))}</b><br>{escape(t('chat_empty_hint'))}</p>"
            f"<p>{t('how_it_works')}</p>"
            f"<p>{escape(t('local_data'))}</p>"
            "</span></span></div>",
            unsafe_allow_html=True,
        )
    with save_column:
        if st.button(
            t("save_chat"), key="save-chat", icon=":material/save:",
            disabled=not st.session_state.chat_history, use_container_width=True,
        ):
            save_current_chat(document)
            st.session_state.chat_notice = t("chat_saved")
            st.rerun()
    with reset_column:
        if st.button(t("new_conversation"), icon=":material/add:", use_container_width=True):
            reset_current_chat()
            st.rerun()

    active_saved_chat = saved_chat_by_id(document, st.session_state.active_saved_chat_id)
    if active_saved_chat:
        with st.form(f"rename-chat-{active_saved_chat['id']}"):
            chat_name = st.text_input(t("chat_name"), value=active_saved_chat["title"], max_chars=60)
            if st.form_submit_button(t("rename_chat"), icon=":material/edit:"):
                if not chat_name.strip():
                    st.error(t("chat_name_required"))
                else:
                    active_saved_chat["title"] = chat_name.strip()[:60]
                    save_dashboard(document)
                    st.rerun()

    if st.session_state.dashboard_add_notice:
        st.success(st.session_state.dashboard_add_notice)
        st.session_state.dashboard_add_notice = None

    history = st.session_state.chat_history
    latest_assistant_index = max((index for index, item in enumerate(history) if item["role"] == "assistant"), default=-1)
    index = 0
    while index < len(history):
        item = history[index]
        next_item = history[index + 1] if index + 1 < len(history) else None
        is_turn = item["role"] == "user" and next_item and next_item["role"] == "assistant"
        if is_turn:
            is_previous_turn = index + 1 != latest_assistant_index
            if is_previous_turn:
                with st.expander(t("previous_turn", question=item["content"]), expanded=False):
                    render_chat_item(item, index)
                    render_chat_item(next_item, index + 1)
            else:
                render_chat_item(item, index)
                render_chat_item(next_item, index + 1)
            index += 2
            continue
        render_chat_item(item, index)
        index += 1

    if st.session_state.chat_notice:
        st.warning(st.session_state.chat_notice)
        st.session_state.chat_notice = None

    prompt, answer, visual = render_analytics_chat_form()

    if not (answer or visual):
        return
    query = prompt.strip()
    if not query:
        st.warning(t("missing_prompt"))
        return

    st.session_state.chat_history.append({"role": "user", "content": query})
    # A long-running Streamlit session can still hold a legacy workspace loaded
    # before the v5 migration. Normalize here as a safe final guard.
    semantic_model = normalize_semantic_model(document.get("semantic_model"))
    if document.get("semantic_model") != semantic_model:
        document["semantic_model"] = semantic_model
        save_dashboard(document)
    knowledge_answer = answer_knowledge_question(query, semantic_model)
    if knowledge_answer and not visual:
        st.session_state.analysis_context = None
        st.session_state.chat_history.append({"role": "assistant", "mode": "knowledge", **knowledge_answer})
        st.session_state.chat_mode = "Semantic model knowledge answer" if st.session_state.get("language") == "en" else "Odpověď ze semantického modelu"
        st.rerun()
        return
    failed_sql = None
    try:
        generated = get_llm_sql(query, st.session_state.chat_history[:-1])
        if generated is None:
            plan = get_local_plan(query, (st.session_state.analysis_context or {}).get("plan"))
            result = build_analytics_result(plan)
            context = {"result": result, "plan": plan, "query": query, "filters": {}, "limit": plan.get("limit")}
            st.session_state.chat_mode = "Local demo mode — no OpenAI API key configured"
            st.session_state.chat_notice = t("local_fallback")
        elif generated["clarification"] is not None:
            st.session_state.chat_history.append({
                "role": "assistant",
                "mode": "clarification",
                "content": generated["clarification"],
            })
            st.session_state.chat_mode = "OpenAI AI mode — clarification needed"
            st.rerun()
            return
        else:
            sql = build_bounded_select_sql(generated["sql"], get_connection())
            failed_sql = sql
            try:
                run_sql(sql)
            except duckdb.Error as first_error:
                repaired = get_llm_sql(
                    query,
                    st.session_state.chat_history[:-1],
                    execution_feedback={"sql": sql, "error": str(first_error)},
                )
                if repaired is None:
                    raise
                if repaired["clarification"] is not None:
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "mode": "clarification",
                        "content": repaired["clarification"],
                    })
                    st.session_state.chat_mode = "OpenAI AI mode — clarification needed"
                    st.rerun()
                    return
                sql = build_bounded_select_sql(repaired["sql"], get_connection())
                failed_sql = sql
                run_sql(sql)
            result = {
                "title": query,
                "kind": "query",
                "summary": t("query_result_summary"),
                "sql": sql,
            }
            context = {"result": result, "query": query, "filters": {}, "limit": None}
            st.session_state.chat_mode = "OpenAI AI mode — read-only SQL generated by OpenAI"
    except (LLMRequestError, ValueError, duckdb.Error) as error:
        st.session_state.chat_history.append({
            "role": "assistant",
            "mode": "error",
            "content": f"{t('query_error')} ({type(error).__name__})",
            "sql": failed_sql,
            "details": str(error),
        })
        if get_openai_api_key():
            st.session_state.chat_mode = "OpenAI AI mode — query failed safely"
        else:
            st.session_state.chat_mode = "Local demo mode — question is not supported"
        st.rerun()
        return
    st.session_state.analysis_context = context

    if visual and result["kind"] == "metric":
        st.session_state.chat_notice = t("metric_no_chart")
        visual = False
    if visual:
        spec = chart_spec_from_result(result, query)
        st.session_state.chat_history.append({"role": "assistant", "mode": "visual", "result": result, "spec": spec})
    else:
        st.session_state.chat_history.append({"role": "assistant", "mode": "answer", "result": result})
    st.rerun()


def _semantic_status_options():
    return ["approved", "draft"]


def _semantic_status_label(status):
    return "Schváleno" if status == "approved" and st.session_state.get("language") == "cs" else status


def render_semantic_model(document):
    """Render the editable first-stage semantic model for the built-in demo source."""
    model = normalize_semantic_model(document.get("semantic_model"))
    document["semantic_model"] = model
    cs = st.session_state.get("language") == "cs"
    st.title("Semantický model" if cs else "Semantic model")
    st.caption(
        "Editovatelný zdroj pravdy pro tabulky, vztahy, metriky a business pravidla. Analytický chat z něj odpovídá bez SQL."
        if cs else "Editable source of truth for tables, relationships, metrics, and business rules. Analytics chat answers from it without SQL."
    )
    summary = st.columns(4)
    summary[0].metric("Tabulky" if cs else "Tables", len(model["tables"]))
    summary[1].metric("Vztahy" if cs else "Relationships", len(model["relationships"]))
    summary[2].metric("Metriky" if cs else "Metrics", len(model["metrics"]))
    summary[3].metric("Pravidla" if cs else "Rules", len(model["rules"]))
    with st.container(border=True):
        st.subheader("AI draft" if cs else "AI draft")
        st.write(draft_preview(model))
        st.button("Vytvořit AI draft (brzy)" if cs else "Create AI draft (coming soon)", disabled=True, icon=":material/auto_awesome:")

    tables_tab, relations_tab, metrics_tab, knowledge_tab = st.tabs(
        ["Tabulky" if cs else "Tables", "Vztahy" if cs else "Relationships", "Metriky" if cs else "Metrics", "Business znalosti" if cs else "Business knowledge"]
    )
    with tables_tab:
        for item in model["tables"]:
            with st.expander(f"{item['name']} · `{item['technical_name']}`", expanded=False):
                with st.form(f"semantic-table-{item['id']}"):
                    name = st.text_input("Business název" if cs else "Business name", value=item["name"])
                    technical_name = st.text_input("Technický název" if cs else "Technical name", value=item["technical_name"])
                    description = st.text_area("Popis" if cs else "Description", value=item["description"])
                    grain = st.text_input("Granularita" if cs else "Grain", value=item.get("grain", ""))
                    status = st.selectbox("Stav" if cs else "Status", _semantic_status_options(), index=_semantic_status_options().index(item["status"]), format_func=_semantic_status_label)
                    if st.form_submit_button("Uložit" if cs else "Save", icon=":material/save:"):
                        document["semantic_model"] = upsert_item(model, "tables", {**item, "name": name, "technical_name": technical_name, "description": description, "grain": grain, "status": status})
                        save_dashboard(document)
                        st.rerun()
    with relations_tab:
        for item in model["relationships"]:
            with st.expander(item["name"], expanded=False):
                with st.form(f"semantic-relation-{item['id']}"):
                    name = st.text_input("Název" if cs else "Name", value=item["name"])
                    description = st.text_area("Popis" if cs else "Description", value=item["description"])
                    left, right = st.columns(2)
                    from_table = left.text_input("Zdrojová tabulka" if cs else "From table", value=item["from_table"])
                    from_column = left.text_input("Zdrojový sloupec" if cs else "From column", value=item["from_column"])
                    to_table = right.text_input("Cílová tabulka" if cs else "To table", value=item["to_table"])
                    to_column = right.text_input("Cílový sloupec" if cs else "To column", value=item["to_column"])
                    cardinality = st.selectbox("Kardinalita" if cs else "Cardinality", ["1:1", "1:N", "N:1", "N:M"], index=["1:1", "1:N", "N:1", "N:M"].index(item.get("cardinality", "1:N")))
                    if st.form_submit_button("Uložit" if cs else "Save", icon=":material/save:"):
                        document["semantic_model"] = upsert_item(model, "relationships", {**item, "name": name, "description": description, "from_table": from_table, "from_column": from_column, "to_table": to_table, "to_column": to_column, "cardinality": cardinality})
                        save_dashboard(document)
                        st.rerun()
    with metrics_tab:
        for item in model["metrics"]:
            with st.expander(item["name"], expanded=False):
                with st.form(f"semantic-metric-{item['id']}"):
                    name = st.text_input("Název metriky" if cs else "Metric name", value=item["name"])
                    synonyms = st.text_input("Synonyma (oddělená čárkou)" if cs else "Synonyms (comma separated)", value=", ".join(item.get("synonyms", [])))
                    description = st.text_area("Business definice" if cs else "Business definition", value=item["description"])
                    formula = st.text_area("Formula / SQL výraz" if cs else "Formula / SQL expression", value=item["formula"])
                    entity = st.text_input("Zdrojová entita" if cs else "Source entity", value=item["entity"])
                    time_dimension = st.text_input("Časová dimenze" if cs else "Time dimension", value=item.get("time_dimension", ""))
                    rules = st.text_area("Pravidla a výjimky" if cs else "Rules and exceptions", value=item.get("rules", ""))
                    status = st.selectbox("Stav" if cs else "Status", _semantic_status_options(), index=_semantic_status_options().index(item["status"]), key=f"metric-status-{item['id']}", format_func=_semantic_status_label)
                    if st.form_submit_button("Uložit" if cs else "Save", icon=":material/save:"):
                        document["semantic_model"] = upsert_item(model, "metrics", {**item, "name": name, "synonyms": [value.strip() for value in synonyms.split(",") if value.strip()], "description": description, "formula": formula, "entity": entity, "time_dimension": time_dimension, "rules": rules, "status": status})
                        save_dashboard(document)
                        st.rerun()
        with st.expander("Přidat metriku" if cs else "Add metric"):
            with st.form("semantic-add-metric", clear_on_submit=True):
                name = st.text_input("Název metriky" if cs else "Metric name")
                formula = st.text_input("Formula / SQL výraz" if cs else "Formula / SQL expression")
                entity = st.text_input("Zdrojová entita" if cs else "Source entity")
                description = st.text_area("Business definice" if cs else "Business definition")
                if st.form_submit_button("Přidat metriku" if cs else "Add metric", icon=":material/add:"):
                    document["semantic_model"] = upsert_item(model, "metrics", {"name": name, "formula": formula, "entity": entity, "description": description, "status": "draft"})
                    save_dashboard(document)
                    st.rerun()
    with knowledge_tab:
        for collection, heading in (("terms", "Slovník pojmů" if cs else "Business glossary"), ("rules", "Business pravidla" if cs else "Business rules")):
            st.subheader(heading)
            for item in model[collection]:
                with st.expander(item["name"], expanded=False):
                    with st.form(f"semantic-{collection}-{item['id']}"):
                        name = st.text_input("Název" if cs else "Name", value=item["name"])
                        description = st.text_area("Popis" if cs else "Description", value=item["description"])
                        if st.form_submit_button("Uložit" if cs else "Save", icon=":material/save:"):
                            document["semantic_model"] = upsert_item(model, collection, {**item, "name": name, "description": description})
                            save_dashboard(document)
                            st.rerun()


def render_dashboard(document, dashboard):
    page_ids = [page["id"] for page in dashboard["pages"]]
    if "active_dashboard_page" not in st.session_state or st.session_state.active_dashboard_page not in page_ids:
        st.session_state.active_dashboard_page = page_ids[0]
    page = page_by_id(dashboard, st.session_state.active_dashboard_page)

    dashboard_title_column, dashboard_rename_column = st.columns([6, 1], gap="small", vertical_alignment="center")
    with dashboard_title_column:
        st.title(dashboard["name"])
    with dashboard_rename_column:
        with st.popover(t("rename_dashboard"), icon=":material/edit:"):
            with st.form(f"rename-dashboard-{dashboard['id']}", enter_to_submit=False):
                dashboard_name = st.text_input(
                    t("rename_dashboard_name"), value=dashboard["name"], max_chars=60,
                    key=f"rename-dashboard-name-{dashboard['id']}",
                )
                if st.form_submit_button(t("rename_dashboard"), type="primary", icon=":material/check:", width="stretch"):
                    try:
                        candidate = deepcopy(document)
                        renamed_dashboard = rename_dashboard(candidate, dashboard["id"], dashboard_name)
                    except ValueError:
                        st.error(
                            t("dashboard_name_required")
                            if not dashboard_name.strip()
                            else t("dashboard_name_exists")
                        )
                    else:
                        save_dashboard_snapshot(document, dashboard, t("rename_dashboard"))
                        dashboard["name"] = renamed_dashboard["name"]
                        save_dashboard(document)
                        st.session_state.dashboard_editor_notice = t("dashboard_renamed", dashboard=renamed_dashboard["name"])
                        st.rerun()
    with st.container(horizontal=True, vertical_alignment="top", key="dashboard-page-navigation"):
        page_tabs = st.tabs(
            [item["name"] for item in dashboard["pages"]],
            default=page["name"],
            key=f"dashboard-page-tabs-{dashboard['id']}-{page['id']}",
            on_change="rerun",
        )
        for tab, item in zip(page_tabs, dashboard["pages"]):
            if tab.open and item["id"] != page["id"]:
                st.session_state.active_dashboard_page = item["id"]
                st.session_state.selected_dashboard_card = None
                st.rerun()
        with st.popover(t("create_page"), icon=":material/add:"):
            with st.form(f"new_dashboard_page-{dashboard['id']}"):
                page_name = st.text_input(t("new_page"), placeholder=t("new_page_placeholder"), max_chars=60)
                if st.form_submit_button(t("add_page"), icon=":material/add:", width="stretch"):
                    if not page_name.strip():
                        st.error(t("page_name_required"))
                    elif page_name_exists(dashboard, page_name):
                        st.error(t("page_name_exists"))
                    else:
                        new_page = add_page(dashboard, page_name)
                        save_dashboard(document)
                        st.session_state.active_dashboard_page = new_page["id"]
                        st.session_state.selected_dashboard_card = None
                        st.rerun()

    title_column, action_column = st.columns([3, 2], gap="large", vertical_alignment="center")
    with title_column:
        st.header(page["name"])
        st.caption(t("filters_apply"))
    with action_column:
        st.download_button(t("export_pdf"), pdf_report(page), f"biizy-{page['id']}.pdf", "application/pdf", type="primary", icon=":material/picture_as_pdf:", width="stretch")
        if len(dashboard["pages"]) > 1 and st.button(t("delete_page"), icon=":material/delete:", width="stretch"):
            remove_page(dashboard, page["id"])
            save_dashboard(document)
            st.session_state.active_dashboard_page = dashboard["pages"][0]["id"]
            st.session_state.selected_dashboard_card = None
            st.rerun()

    with st.container(border=True, key="dashboard-filters"):
        st.markdown("#### " + t("page_filters"))
        filter_one, filter_two, filter_three, filter_four = st.columns(4, gap="medium")
        with filter_one:
            segments = st.multiselect("Segment", SEGMENTS, default=page["filters"]["segments"], placeholder=t("all_values"), key=f"segments-{page['id']}")
        with filter_two:
            cities = st.multiselect(t("city"), CITIES, default=page["filters"]["cities"], placeholder=t("all_values"), key=f"cities-{page['id']}")
        with filter_three:
            dates = st.date_input(t("period"), value=(pd.to_datetime(page["filters"]["date_from"]).date() if page["filters"]["date_from"] else date(2026, 1, 1), pd.to_datetime(page["filters"]["date_to"]).date() if page["filters"]["date_to"] else date(2026, 10, 31)), key=f"dates-{page['id']}")
        with filter_four:
            period_label = st.selectbox(t("granularity"), [t("monthly"), t("weekly")], index=1 if page["filters"]["period"] == "weekly" else 0, key=f"period-{page['id']}")
        updated_filters = normalize_filters({"segments": segments, "cities": cities, "date_from": dates[0].isoformat(), "date_to": dates[1].isoformat(), "period": "weekly" if period_label == t("weekly") else "monthly"})
        if updated_filters != page["filters"]:
            page["filters"] = updated_filters
            save_dashboard(document)
            st.rerun()
        st.markdown("<div class='dashboard-filter-note'>" + t("granularity_note") + "</div>", unsafe_allow_html=True)

    if not page["cards"]:
        st.info(t("empty_dashboard"))
    else:
        render_dashboard_grid(page, document)
    selected_card_id = st.session_state.get("selected_dashboard_card")

    selected = next((card for card in page["cards"] if card["id"] == selected_card_id), None)
    st.divider()
    history_column, undo_column = st.columns([4, 1], vertical_alignment="center")
    with history_column:
        versions = [item for item in document.get("dashboard_history", []) if item.get("dashboard", {}).get("id") == dashboard["id"]]
        st.caption(t("editor_history", count=len(versions)))
    with undo_column:
        if st.button(t("undo_last_change"), icon=":material/undo:", disabled=not versions, width="stretch"):
            restored = restore_latest_dashboard_snapshot(document, dashboard["id"])
            if restored:
                st.session_state.selected_dashboard_card = None
                st.session_state.dashboard_editor_notice = t("undo_completed")
                save_dashboard(document)
                st.rerun()
    st.markdown("### " + t("dashboard_editor"))
    with st.container(border=True, key="dashboard-ai-editor"):
        st.caption(t("editor_example"))
        if selected:
            st.info(t("selected_card", title=selected["title"]))
        else:
            st.warning(t("select_card_for_editor"))
        with st.form(f"dashboard-editor-{page['id']}", clear_on_submit=True):
            command = st.text_input(t("editor_instruction"), placeholder=t("editor_placeholder"))
            st.markdown("<div class='editor-submit-hint'>" + t("editor_submit_hint") + "</div>", unsafe_allow_html=True)
            submitted = st.form_submit_button(t("propose_change"), type="primary", icon=":material/auto_awesome:", use_container_width=True)
        if submitted:
            pending, error = plan_dashboard_editor_command(command, dashboard, page, selected)
            if error:
                st.error(error)
            else:
                st.session_state.pending_dashboard_edit = pending
                st.rerun()
        pending = st.session_state.get("pending_dashboard_edit")
        if pending:
            with st.container(border=True, key="dashboard-edit-preview"):
                st.markdown("#### " + t("change_preview"))
                st.write(pending["summary"])
                st.caption(t("change_preview_note"))
                preview_dashboard = pending["dashboard"]
                preview_page = page_by_id(preview_dashboard, page["id"])
                preview_card = next((card for card in preview_page["cards"] if card["id"] == selected_card_id), None) if preview_page and selected_card_id else None
                if preview_card:
                    with st.container(border=True, key="dashboard-proposal-card-preview"):
                        render_card_content(normalize_card(preview_card), preview_page, "proposal-preview", show_sql=False)
                confirm_column, cancel_column = st.columns(2, gap="small")
                with confirm_column:
                    if st.button(t("confirm_change"), type="primary", icon=":material/check:", width="stretch"):
                        save_dashboard_snapshot(document, dashboard, pending["summary"])
                        replacement = pending["dashboard"]
                        dashboard["name"] = replacement["name"]
                        dashboard["pages"] = replacement["pages"]
                        if re.match(r"^(?:přidej|pridej|add)\s+(?:stránku|stranku|page)\b", pending["command"].strip(), flags=re.I):
                            st.session_state.active_dashboard_page = dashboard["pages"][-1]["id"]
                        save_dashboard(document)
                        st.session_state.pending_dashboard_edit = None
                        st.session_state.dashboard_editor_notice = pending["summary"]
                        st.rerun()
                with cancel_column:
                    if st.button(t("discard_proposal"), icon=":material/close:", width="stretch"):
                        st.session_state.pending_dashboard_edit = None
                        st.rerun()
        if st.session_state.get("dashboard_editor_notice"):
            st.success(st.session_state.dashboard_editor_notice)
            st.session_state.dashboard_editor_notice = None
    editor_card_id = st.session_state.get("dashboard_card_editor")
    if editor_card_id:
        render_card_editor_dialog(document, dashboard, page, editor_card_id)


style_app()
if "language" not in st.session_state:
    st.session_state.language = "en"
st.session_state.setdefault("demo_project_notice_hidden", False)
document = load_dashboard()
with st.sidebar:
    render_sidebar_brand()
    if st.button(t("analytics_chat"), icon=":material/chat:", use_container_width=True):
        st.session_state.workspace_view = "chat"
        st.session_state.dashboard_menu_open = False
        st.session_state.dashboard_create_open = False
        st.session_state.saved_chat_menu_open = False
        st.rerun()
    if st.button("Semantický model" if st.session_state.get("language") == "cs" else "Semantic model", icon=":material/account_tree:", use_container_width=True):
        st.session_state.workspace_view = "semantic_model"
        st.session_state.dashboard_menu_open = False
        st.session_state.dashboard_create_open = False
        st.session_state.saved_chat_menu_open = False
        st.rerun()
    if st.button(t("dashboards"), icon=":material/dashboard:", use_container_width=True):
        st.session_state.dashboard_menu_open = not st.session_state.get("dashboard_menu_open", False)
        st.session_state.saved_chat_menu_open = False
        if not st.session_state.dashboard_menu_open:
            st.session_state.dashboard_create_open = False
        st.rerun()
    if st.session_state.get("dashboard_menu_open", False):
        with st.container(key="dashboard-submenu"):
            for dashboard in document["dashboards"]:
                is_active = (
                    st.session_state.get("workspace_view") == "dashboard"
                    and st.session_state.get("active_dashboard_id") == dashboard["id"]
                )
                if st.button(
                    dashboard["name"], key=f"open-dashboard-{dashboard['id']}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                ):
                    st.session_state.workspace_view = "dashboard"
                    st.session_state.active_dashboard_id = dashboard["id"]
                    st.session_state.active_dashboard_page = dashboard["pages"][0]["id"]
                    st.session_state.selected_dashboard_card = None
                    st.session_state.dashboard_create_open = False
                    st.rerun()
            if st.button(t("create_dashboard"), icon=":material/add:", use_container_width=True):
                st.session_state.dashboard_create_open = True
                st.rerun()
            if st.session_state.get("dashboard_create_open", False):
                with st.form("new_dashboard"):
                    dashboard_name = st.text_input(
                        t("dashboard_name"), placeholder=t("new_page_placeholder"), max_chars=60,
                    )
                    if st.form_submit_button(t("save_dashboard"), icon=":material/save:", use_container_width=True):
                        if not dashboard_name.strip():
                            st.error(t("dashboard_name_required"))
                        elif dashboard_name_exists(document, dashboard_name):
                            st.error(t("dashboard_name_exists"))
                        else:
                            dashboard = add_dashboard(document, dashboard_name, t("overview"))
                            save_dashboard(document)
                            st.session_state.workspace_view = "dashboard"
                            st.session_state.active_dashboard_id = dashboard["id"]
                            st.session_state.active_dashboard_page = dashboard["pages"][0]["id"]
                            st.session_state.selected_dashboard_card = None
                            st.session_state.dashboard_create_open = False
                            st.rerun()
    if st.button(t("saved_chats"), icon=":material/bookmarks:", use_container_width=True):
        st.session_state.saved_chat_menu_open = not st.session_state.get("saved_chat_menu_open", False)
        st.session_state.dashboard_menu_open = False
        st.session_state.dashboard_create_open = False
        st.rerun()
    if st.session_state.get("saved_chat_menu_open", False):
        with st.container(key="saved-chat-submenu"):
            for saved_chat in document["saved_chats"]:
                is_active = (
                    st.session_state.get("workspace_view") == "chat"
                    and st.session_state.get("active_saved_chat_id") == saved_chat["id"]
                )
                if st.button(
                    saved_chat["title"], key=f"open-saved-chat-{saved_chat['id']}",
                    type="primary" if is_active else "secondary", use_container_width=True,
                ):
                    st.session_state.workspace_view = "chat"
                    st.session_state.chat_history = deepcopy(saved_chat["history"])
                    st.session_state.analysis_context = None
                    st.session_state.chat_notice = None
                    st.session_state.dashboard_add_notice = None
                    st.session_state.dashboard_add_item_index = None
                    st.session_state.active_saved_chat_id = saved_chat["id"]
                    st.rerun()
    st.divider()
    with st.expander(t("reset_demo"), icon=":material/restart_alt:"):
        st.warning(t("reset_demo_help"))
        confirmed = st.checkbox(t("reset_demo_confirm"), key="confirm-demo-reset")
        if st.button(t("reset_demo"), key="reset-demo", type="primary", icon=":material/delete_forever:", disabled=not confirmed, width="stretch"):
            reset_demo()
            st.rerun()
    st.caption(t("local_data"))
    st.caption(t("demo_data"))

if st.session_state.pop("demo_reset_notice", None):
    st.success(t("reset_demo_done"))

render_language_switcher()
render_demo_project_notice()

if st.session_state.get("workspace_view") == "semantic_model":
    render_semantic_model(document)
elif st.session_state.get("workspace_view") == "dashboard":
    active_dashboard_id = st.session_state.get("active_dashboard_id")
    active_dashboard = next((item for item in document["dashboards"] if item["id"] == active_dashboard_id), None)
    if active_dashboard is None:
        st.session_state.workspace_view = "chat"
        st.rerun()
    render_dashboard(document, active_dashboard)
else:
    render_analytics_chat(document)