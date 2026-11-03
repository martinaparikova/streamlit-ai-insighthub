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
    remove_page,
)
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
FOREST, PAPER, PINK, GREEN, SLATE = "#0B3B2E", "#F7F7F7", "#C2185B", "#2F6B5A", "#4B5563"
CREATE_NEW_DASHBOARD = "__create_new_dashboard__"
NEW_DASHBOARD_OVERVIEW = "__new_dashboard_overview__"

st.set_page_config(page_title="Insight Hub", page_icon="◒", layout="wide", initial_sidebar_state="expanded")

TEXT = {
    "cs": {
        "language": "Jazyk rozhraní", "sidebar_subtitle": "ERP × CRM · lokální přehled dat",
        "workspace": "Pracovní plocha", "analytics_chat": "Analytický chat", "dashboards": "Dashboardy", "saved_chats": "Uložené chaty",
        "dashboard_name": "Název nového dashboardu", "create_dashboard": "Vytvořit nový",
        "save_dashboard": "Uložit", "save_chat": "Uložit chat", "chat_saved": "Chat byl uložen.",
        "chat_name": "Název chatu", "rename_chat": "Uložit název", "chat_name_required": "Zadejte název chatu.",
        "overview": "Přehled", "target_page": "Stránka",
        "target_dashboard": "Dashboard",
        "new_dashboard_placeholder": "Nový dashboard",
        "save_destination": "Uloží se do dashboardu <strong>{dashboard}</strong> na stránku <strong>{page}</strong> s názvem <strong>{title}</strong>.",
        "local_data": "Lokální data · DuckDB · SQL pouze pro čtení", "demo_data": "Demo data 2026",
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
    },
    "en": {
        "language": "Interface language", "sidebar_subtitle": "ERP × CRM · local data overview",
        "workspace": "Workspace", "analytics_chat": "Analytics chat", "dashboards": "Dashboards", "saved_chats": "Saved chats",
        "dashboard_name": "New dashboard name", "create_dashboard": "Create new",
        "save_dashboard": "Save", "save_chat": "Save chat", "chat_saved": "Chat saved.",
        "chat_name": "Chat name", "rename_chat": "Save name", "chat_name_required": "Enter a chat name.",
        "overview": "Overview", "target_page": "Page",
        "target_dashboard": "Dashboard",
        "new_dashboard_placeholder": "New dashboard",
        "save_destination": "This will be saved to dashboard <strong>{dashboard}</strong>, page <strong>{page}</strong>, as <strong>{title}</strong>.",
        "local_data": "Local data · DuckDB · read-only SQL", "demo_data": "2026 demo data",
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
    },
}


def t(key, **values):
    language = st.session_state.get("language", "cs")
    return TEXT[language][key].format(**values)


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


def pdf_report(page):
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.4 * cm, leftMargin=1.4 * cm, topMargin=1.3 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Insight Hub — {page['name']}", styles["Title"]),
        Paragraph(f"{t('generated')}: {date.today().strftime('%d.%m.%Y')}", styles["Normal"]),
        Spacer(1, 14),
    ]
    for number, spec in enumerate(page["cards"], 1):
        filtered_sql = apply_filters_to_sql(apply_time_granularity(spec["sql"], page["filters"]["period"]), page["filters"])
        data = apply_card_preferences(run_sql(filtered_sql), spec)
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
        .block-container {{ max-width: 1180px; padding-top: 2.5rem; padding-bottom: 3rem; }}
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
            st.download_button(t("download_csv"), data.to_csv(index=False).encode("utf-8-sig"), f"insight-{index}.csv", "text/csv", key=f"download-{index}", icon=":material/download:")

        add_open_key = "dashboard_add_item_index"
        if st.button(t("add_dashboard"), key=f"add-dashboard-{index}", type="primary", icon=":material/dashboard_customize:"):
            st.session_state[add_open_key] = index
            render_add_to_dashboard_dialog(load_dashboard(), spec, index)
        elif st.session_state.get(add_open_key) == index:
            render_add_to_dashboard_dialog(load_dashboard(), spec, index)
        sql_card(result["sql"], len(data))


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

    with st.form("analytics_chat_form", clear_on_submit=True, enter_to_submit=True):
        prompt = st.text_input(
            t("question"),
            placeholder=t("question_placeholder"),
            help=t("question_help"),
        )
        answer_column, visual_column = st.columns([1, 1], gap="small")
        answer = answer_column.form_submit_button(t("show_answer"), type="primary", icon=":material/send:", use_container_width=True)
        visual = visual_column.form_submit_button(t("create_chart"), icon=":material/bar_chart:", use_container_width=True)

    if not (answer or visual):
        return
    query = prompt.strip()
    if not query:
        st.warning(t("missing_prompt"))
        return

    st.session_state.chat_history.append({"role": "user", "content": query})
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


def render_dashboard(document, dashboard):
    page_ids = [page["id"] for page in dashboard["pages"]]
    if "active_dashboard_page" not in st.session_state or st.session_state.active_dashboard_page not in page_ids:
        st.session_state.active_dashboard_page = page_ids[0]
    page = page_by_id(dashboard, st.session_state.active_dashboard_page)

    st.title(dashboard["name"])
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
        st.download_button(t("export_pdf"), pdf_report(page), f"insight-hub-{page['id']}.pdf", "application/pdf", type="primary", icon=":material/picture_as_pdf:", width="stretch")
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
    selected_card_id = st.session_state.get("selected_dashboard_card")
    for index, spec in enumerate(page["cards"]):
        spec = normalize_card(spec)
        page["cards"][index] = spec
        with st.container(border=True, key=f"dashboard-card-{spec['id']}"):
            st.caption(t("card", number=index + 1))
            filtered_sql = apply_filters_to_sql(apply_time_granularity(spec["sql"], page["filters"]["period"]), page["filters"])
            data = apply_card_preferences(run_sql(filtered_sql), spec)
            if spec["kind"] == "table":
                st.subheader(spec["title"])
                st.dataframe(data, use_container_width=True, hide_index=True)
            elif spec["kind"] == "metric":
                st.metric(spec["title"], f"{float(data.iloc[0, 0]):,.0f}".replace(",", " "))
            else:
                st.plotly_chart(chart_figure(spec, data), use_container_width=True, key=f"chart-{page['id']}-{spec['id']}")
            sql_card(filtered_sql, len(data))
            edit_column, up_column, down_column, remove_column = st.columns(4, gap="small")
            with edit_column:
                if st.button(t("edit"), key=f"select-{spec['id']}", icon=":material/edit:", use_container_width=True):
                    st.session_state.selected_dashboard_card = spec["id"]
                    st.rerun()
            with up_column:
                if st.button(t("move_up"), key=f"up-{spec['id']}", disabled=index == 0, icon=":material/arrow_upward:", use_container_width=True):
                    page["cards"][index - 1], page["cards"][index] = page["cards"][index], page["cards"][index - 1]
                    save_dashboard(document)
                    st.rerun()
            with down_column:
                if st.button(t("move_down"), key=f"down-{spec['id']}", disabled=index == len(page["cards"]) - 1, icon=":material/arrow_downward:", use_container_width=True):
                    page["cards"][index + 1], page["cards"][index] = page["cards"][index], page["cards"][index + 1]
                    save_dashboard(document)
                    st.rerun()
            with remove_column:
                if st.button(t("remove"), key=f"delete-{spec['id']}", icon=":material/delete:", use_container_width=True):
                    page["cards"].pop(index)
                    save_dashboard(document)
                    st.rerun()

    selected = next((card for card in page["cards"] if card["id"] == selected_card_id), None)
    st.divider()
    editor_column, chat_column = st.columns([1, 1], gap="large")
    with editor_column:
        st.markdown("### " + t("edit_card"))
        if not selected:
            st.caption(t("select_card"))
        else:
            with st.form(f"card-editor-{selected['id']}"):
                title = st.text_input(t("name"), selected["title"])
                kind = st.selectbox(t("chart_type"), CHART_KINDS, index=CHART_KINDS.index(selected["kind"]))
                color = st.selectbox(t("color"), COLORS, index=COLORS.index(selected["color"]) if selected["color"] in COLORS else 0)
                sort_order = st.selectbox(t("sort"), ["original", "ascending", "descending"], index=["original", "ascending", "descending"].index(selected.get("sort_order", "original")))
                if st.form_submit_button(t("save_changes"), type="primary", icon=":material/save:", use_container_width=True):
                    selected.update({"title": title.strip() or selected["title"], "kind": kind, "color": color, "sort_order": sort_order})
                    save_dashboard(document)
                    st.success(t("card_updated"))
                    st.rerun()
    with chat_column:
        st.markdown("### " + t("dashboard_editor"))
        st.caption(t("editor_example"))
        with st.form(f"dashboard-editor-{page['id']}", clear_on_submit=True):
            command = st.text_input(t("editor_instruction"), placeholder=t("editor_placeholder"))
            submitted = st.form_submit_button(t("apply_change"), type="primary", icon=":material/check:", use_container_width=True)
        if submitted:
            updated_dashboard, notice = parse_editor_command(dashboard, page["id"], command, selected_card_id)
            dashboard["pages"] = updated_dashboard["pages"]
            save_dashboard(document)
            st.session_state.dashboard_editor_notice = notice
            if command.lower().strip().startswith(("přidej stránku", "pridej stranku", "new page")):
                st.session_state.active_dashboard_page = dashboard["pages"][-1]["id"]
            st.rerun()
        if st.session_state.get("dashboard_editor_notice"):
            st.success(st.session_state.dashboard_editor_notice)
            st.session_state.dashboard_editor_notice = None


style_app()
document = load_dashboard()
with st.sidebar:
    st.markdown("# ◒ Insight Hub")
    st.caption(t("sidebar_subtitle"))
    language_label = st.selectbox(
        t("language"),
        ["Čeština", "English"],
        index=0 if st.session_state.get("language", "cs") == "cs" else 1,
        key="language_selector",
    )
    st.session_state.language = "cs" if language_label == "Čeština" else "en"
    st.caption(t("workspace"))
    if st.button(t("analytics_chat"), icon=":material/chat:", use_container_width=True):
        st.session_state.workspace_view = "chat"
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
    st.caption(t("local_data"))
    st.caption(t("demo_data"))

if st.session_state.get("workspace_view") == "dashboard":
    active_dashboard_id = st.session_state.get("active_dashboard_id")
    active_dashboard = next((item for item in document["dashboards"] if item["id"] == active_dashboard_id), None)
    if active_dashboard is None:
        st.session_state.workspace_view = "chat"
        st.rerun()
    render_dashboard(document, active_dashboard)
else:
    render_analytics_chat(document)