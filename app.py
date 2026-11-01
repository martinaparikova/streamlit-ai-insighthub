import json
import os
from datetime import date
from io import BytesIO
from pathlib import Path

from analytics import build_analytics_result, get_llm_plan, get_local_plan, get_openai_api_key
from dashboard import (
    CHART_KINDS,
    CITIES,
    COLORS,
    SEGMENTS,
    add_page,
    apply_card_preferences,
    apply_filters_to_sql,
    apply_time_granularity,
    normalize_card,
    normalize_dashboard,
    normalize_filters,
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
NAVY, PAPER, PINK, BLUE, TEAL, SLATE = "#14213D", "#F7F5F2", "#EC4899", "#2563EB", "#0F766E", "#334155"

st.set_page_config(page_title="Insight Hub", page_icon="◒", layout="wide", initial_sidebar_state="expanded")


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
        csv_path = (DATA_DIR / f"{table_name}.csv").as_posix()
        connection.execute(f"CREATE VIEW {table_name} AS SELECT * FROM read_csv_auto('{csv_path}')")
    return connection


def run_sql(sql):
    return get_connection().execute(sql).df()


def sql_card(sql, row_count=None):
    with st.expander("SQL trace — zobrazit skutečně vykonaný dotaz"):
        st.code(sql, language="sql")
        if row_count is not None:
            st.caption(f"DuckDB · read-only SELECT · vráceno řádků: {row_count}")


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
            "color": PINK if "růž" in prompt or "ruz" in prompt else BLUE,
            "highlight": BLUE if (any(term in prompt for term in ["nejvyš", "maximum", " max"]) and ("modr" in prompt or "blue" in prompt)) else None,
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
    if result["kind"] == "table" or len(data.columns) < 2:
        return {"title": result["title"], "kind": "table", "sql": result["sql"], "x": data.columns[0], "y": data.columns[-1], "color": BLUE, "highlight": None, "font": "Arial", "title_size": 20, "position": "bottom"}
    design = parse_visual_prompt(prompt or result["title"])
    design.update({"title": result["title"], "kind": "bar", "sql": result["sql"], "x": data.columns[0], "y": data.columns[1]})
    return design


def chart_figure(spec, data):
    if spec["kind"] in ("table", "metric"):
        return None
    colors_for_bars = [spec["color"]] * len(data)
    if spec.get("highlight") and len(data):
        max_index = data[spec["y"]].astype(float).idxmax()
        colors_for_bars[data.index.get_loc(max_index)] = spec["highlight"]
    kind = spec.get("kind", "bar")
    if kind == "pie":
        figure = go.Figure(go.Pie(labels=data[spec["x"]], values=data[spec["y"]], marker_colors=colors_for_bars, hole=0.42))
    elif kind in ("line", "area"):
        figure = go.Figure(go.Scatter(x=data[spec["x"]], y=data[spec["y"]], mode="lines+markers", line={"color": spec["color"], "width": 3}, fill="tozeroy" if kind == "area" else None, fillcolor="rgba(37,99,235,.14)" if kind == "area" else None))
    else:
        figure = go.Figure(go.Bar(x=data[spec["x"]], y=data[spec["y"]], marker_color=colors_for_bars, text=[f"{value:,.0f}".replace(",", " ") for value in data[spec["y"]]], textposition="outside"))
    figure.update_layout(
        title={"text": spec["title"], "font": {"family": spec["font"], "size": spec["title_size"], "color": NAVY}},
        font={"family": spec["font"], "color": SLATE}, paper_bgcolor="white", plot_bgcolor="white",
        margin=dict(t=58, r=18, b=30, l=20), height=340, xaxis_title="", yaxis_title="Kč", yaxis_gridcolor="#E5E7EB",
    )
    return figure


def load_dashboard():
    if not STORE.exists():
        return normalize_dashboard(None)
    return normalize_dashboard(json.loads(STORE.read_text(encoding="utf-8")))


def save_dashboard(document):
    STORE.parent.mkdir(exist_ok=True)
    STORE.write_text(json.dumps(normalize_dashboard(document), ensure_ascii=False, indent=2), encoding="utf-8")


def pdf_report(page):
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.4 * cm, leftMargin=1.4 * cm, topMargin=1.3 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Insight Hub — {page['name']}", styles["Title"]),
        Paragraph(f"Vygenerováno lokálně: {date.today().strftime('%d.%m.%Y')}", styles["Normal"]),
        Spacer(1, 14),
    ]
    for number, spec in enumerate(page["cards"], 1):
        filtered_sql = apply_time_granularity(apply_filters_to_sql(spec["sql"], page["filters"]), page["filters"]["period"])
        data = apply_card_preferences(run_sql(filtered_sql), spec)
        story.extend([
            Paragraph(f"{number}. {spec['title']}", styles["Heading2"]),
            Paragraph(f"Typ: {spec['kind']} | Font: {spec['font']} | Barva: {spec['color']}", styles["Normal"]),
        ])
        preview = [list(data.columns)] + data.head(8).astype(str).values.tolist()
        table = Table(preview, repeatRows=1, colWidths=[(17.5 * cm) / max(1, len(data.columns))] * len(data.columns))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.extend([Spacer(1, 5), table, Spacer(1, 6), Paragraph("SQL: " + spec["sql"].replace("\n", " "), styles["Code"]), Spacer(1, 15)])
    document.build(story)
    return buffer.getvalue()


def style_app():
    st.markdown(
        f"""<style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono&family=DM+Sans:wght@400;500;600;700&family=Roboto:wght@400;500;700&display=swap');
        .stApp {{ background: {PAPER}; color: {NAVY}; font-family: 'DM Sans', sans-serif; }}
        h1,h2,h3 {{ color: {NAVY}; letter-spacing: -.035em; }}
        [data-testid='stSidebar'] {{ background: {NAVY}; }} [data-testid='stSidebar'] * {{ color: #F8FAFC; }}
        [data-testid='stTextArea'] textarea, [data-testid='stTextInput'] input,
        [data-testid='stSelectbox'] [data-baseweb='select'] > div {{
            background: #FFFFFF !important; color: {NAVY} !important; border-color: #94A3B8 !important;
        }}
        [data-testid='stTextArea'] textarea::placeholder, [data-testid='stTextInput'] input::placeholder {{ color: #64748B !important; opacity: 1 !important; }}
        [data-testid='stTextArea'] textarea {{ caret-color: {NAVY} !important; }}
        [data-testid='stSelectbox'] *, [data-testid='stTextArea'] textarea, [data-testid='stTextInput'] input {{ color: {NAVY} !important; }}
        label, [data-testid='stWidgetLabel'] p {{ color: {NAVY} !important; font-weight: 600 !important; }}
        .trace {{ border-left: 4px solid {PINK}; background: #FFF1F7; padding: .55rem .8rem; border-radius: 0 8px 8px 0; color: {SLATE}; margin: .25rem 0 .65rem; font-size: .9rem; }}
        [data-testid='stChatMessage'] {{ padding: .28rem 0 !important; gap: .55rem !important; }}
        [data-testid='stChatMessageContent'] {{ width: 100%; }}
        .chat-user, .chat-ai {{ border-radius: 10px; padding: .62rem .8rem .7rem; margin: 0 0 .18rem; }}
        .chat-user {{ background: #EAF2FF; border-left: 4px solid {BLUE}; }}
        .chat-ai {{ background: #FFFFFF; border-left: 4px solid {NAVY}; box-shadow: 0 1px 1px rgba(20,33,61,.05); }}
        .chat-label {{ color: {SLATE}; font-size: .67rem; font-weight: 700; letter-spacing: .08em; margin-bottom: .25rem; }}
        .chat-ai .chat-label {{ color: {NAVY}; }}
        .chat-summary {{ color: {SLATE}; margin: 0 0 .45rem; }}
        [data-testid='stChatMessage'] h2, [data-testid='stChatMessage'] h3 {{ margin: .25rem 0 .4rem !important; }}
        [data-testid='stChatMessage'] [data-testid='stPlotlyChart'] {{ margin-top: -.25rem; }}
        [data-testid='stChatMessage'] [data-testid='stDataFrame'] {{ margin-top: .25rem; }}
        .dashboard-filter-note {{ color: {SLATE}; font-size: .82rem; margin: -.25rem 0 .35rem; }}
        .stButton>button {{ border-radius: 8px; border: 1px solid {NAVY}; color: {NAVY}; font-weight: 600; }}
        .stButton>button[kind='primary'] {{ background: {NAVY}; color: white; }} code {{ font-family: 'DM Mono', monospace; }}
        .stButton>button {{ background: {NAVY} !important; border-color: {NAVY} !important; color: #FFFFFF !important; min-height: 44px !important; white-space: nowrap !important; }}
        .stButton>button *, .stButton>button p {{ color: #FFFFFF !important; white-space: nowrap !important; }}
        .stButton>button:hover {{ background: #243B64 !important; border-color: #243B64 !important; }}
        [data-testid='stFormSubmitButton'] > button {{ background: {NAVY} !important; border: 1px solid {NAVY} !important; border-radius: 8px !important; color: #FFFFFF !important; font-weight: 700 !important; min-height: 44px !important; }}
        [data-testid='stFormSubmitButton'] > button *, [data-testid='stFormSubmitButton'] > button p {{ color: #FFFFFF !important; }}
        [data-testid='stFormSubmitButton'] > button:hover {{ background: #243B64 !important; border-color: #243B64 !important; }}
        [data-testid='stDownloadButton'] > button {{ background: {NAVY} !important; border: 1px solid {NAVY} !important; border-radius: 8px !important; color: #FFFFFF !important; font-weight: 600 !important; }}
        [data-testid='stDownloadButton'] > button *, [data-testid='stDownloadButton'] > button p {{ color: #FFFFFF !important; }}
        [data-testid='stDownloadButton'] > button:hover {{ background: #243B64 !important; border-color: #243B64 !important; }}
        </style>""",
        unsafe_allow_html=True,
    )
def render_chat_item(item, index):
    with st.chat_message(item["role"]):
        if item["role"] == "user":
            st.markdown("<div class='chat-user'><div class='chat-label'>VY · DOTAZ</div>" + item["content"] + "</div>", unsafe_allow_html=True)
            return
        result = item["result"]
        data = run_sql(result["sql"])
        visual = item["mode"] == "visual"
        st.markdown("<div class='chat-ai'><div class='chat-label'>INSIGHT HUB · " + ("VIZUALIZACE" if visual else "VÝSLEDEK") + "</div>", unsafe_allow_html=True)
        if not visual:
            st.subheader(result["title"])
        st.markdown("<div class='chat-summary'>" + result["summary"] + "</div>", unsafe_allow_html=True)
        if result["kind"] == "metric":
            value = data.iloc[0, 0] if not data.empty else 0
            st.metric(result.get("metric_label", result["title"]), f"{float(value):,.0f}".replace(",", " "))
        elif visual:
            spec = normalize_card(item["spec"])
            st.caption(f"Graf · {spec['kind']} · {spec['color']} · {spec['font']} · zvýraznění: {spec.get('highlight') or 'žádné'}")
            if spec["kind"] == "table":
                st.dataframe(data, use_container_width=True, hide_index=True)
            else:
                st.plotly_chart(chart_figure(spec, data), use_container_width=True, key=f"chat-chart-{index}")
            if st.button("Přidat na dashboard", key=f"add-dashboard-{index}", type="primary"):
                document = load_dashboard()
                document["pages"][0]["cards"].append(spec)
                save_dashboard(document)
                st.success("Vizualizace byla přidána na stránku Přehled.")
        else:
            if result["kind"] == "bar":
                preview_spec = chart_spec_from_result(result)
                st.plotly_chart(chart_figure(preview_spec, data), use_container_width=True, key=f"answer-chart-{index}")
            st.dataframe(data, use_container_width=True, hide_index=True)
            st.download_button("Stáhnout výsledek CSV", data.to_csv(index=False).encode("utf-8-sig"), f"insight-{index}.csv", "text/csv", key=f"download-{index}")
        sql_card(result["sql"], len(data))
        st.markdown("</div>", unsafe_allow_html=True)


def render_analytics_chat():
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "analysis_context" not in st.session_state:
        st.session_state.analysis_context = None
    if "chat_notice" not in st.session_state:
        st.session_state.chat_notice = None
    if "chat_mode" not in st.session_state:
        st.session_state.chat_mode = "OpenAI AI mode — ready" if get_openai_api_key() else "Local demo mode — no OpenAI API key configured"

    title_column, reset_column = st.columns([4, 2])
    with title_column:
        st.title("Analytický chat")
        st.markdown("<div class='trace'><b>TRACE RAIL</b> &nbsp; Ptejte se, upřesňujte výsledek a pak z něj vytvořte vizualizaci. Každý krok ukazuje skutečné SQL.</div>", unsafe_allow_html=True)
        if st.session_state.chat_mode.startswith("OpenAI AI mode"):
            st.success(st.session_state.chat_mode)
        else:
            st.info(st.session_state.chat_mode)
    with reset_column:
        if st.button("↺ Nová konverzace", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.analysis_context = None
            st.rerun()

    for index, item in enumerate(st.session_state.chat_history):
        render_chat_item(item, index)

    if st.session_state.chat_notice:
        st.warning(st.session_state.chat_notice)
        st.session_state.chat_notice = None

    with st.form("analytics_chat_form", clear_on_submit=True):
        prompt = st.text_area(
            "Message",
            placeholder="For example: How many overdue invoices do we have?",
            help="Use Ctrl+Enter to submit the selected action.",
            height=68,
        )
        answer_column, visual_column = st.columns([1, 1], gap="small")
        answer = answer_column.form_submit_button("Answer", type="primary", use_container_width=True)
        visual = visual_column.form_submit_button("Create visual", type="primary", use_container_width=True)

    if not (answer or visual):
        return
    query = prompt.strip()
    if not query:
        st.warning("Please enter a question or instruction.")
        return

    st.session_state.chat_history.append({"role": "user", "content": query})
    previous_plan = (st.session_state.analysis_context or {}).get("plan")
    try:
        plan = get_llm_plan(query, previous_plan)
        if plan is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        result = build_analytics_result(plan)
        context = {"result": result, "plan": plan, "filters": {}, "limit": plan.get("limit")}
        st.session_state.chat_mode = "OpenAI AI mode — answer planned by OpenAI"
    except Exception as error:
        # A deterministic fallback preserves correct count/list/total semantics without the API.
        plan = get_local_plan(query, previous_plan)
        result = build_analytics_result(plan)
        context = {"result": result, "plan": plan, "filters": {}, "limit": plan.get("limit")}
        error_name = type(error).__name__
        st.session_state.chat_mode = f"Local demo mode — OpenAI planner unavailable ({error_name})"
        st.session_state.chat_notice = "The answer used local demo rules because OpenAI planning was unavailable."
    st.session_state.analysis_context = context

    if visual and result["kind"] == "metric":
        st.session_state.chat_notice = "A single-value answer cannot be added as a chart. Ask for a grouped result, such as revenue by product."
        visual = False
    if visual:
        spec = chart_spec_from_result(result, query)
        st.session_state.chat_history.append({"role": "assistant", "mode": "visual", "result": result, "spec": spec})
    else:
        st.session_state.chat_history.append({"role": "assistant", "mode": "answer", "result": result})
    st.rerun()


def render_dashboard():
    document = load_dashboard()
    page_ids = [page["id"] for page in document["pages"]]
    if "active_dashboard_page" not in st.session_state or st.session_state.active_dashboard_page not in page_ids:
        st.session_state.active_dashboard_page = page_ids[0]
    page = page_by_id(document, st.session_state.active_dashboard_page)

    title_column, action_column = st.columns([4, 2])
    with title_column:
        st.title(page["name"])
        st.caption("Stránkovaný dashboard · filtry platí pro všechny karty na této stránce")
    with action_column:
        st.download_button("Exportovat stránku do PDF", pdf_report(page), f"insight-hub-{page['id']}.pdf", "application/pdf", type="primary", use_container_width=True)

    with st.sidebar:
        st.divider()
        st.caption("STRÁNKY DASHBOARDU")
        selected_page_name = st.radio("Aktivní stránka", [item["name"] for item in document["pages"]], index=page_ids.index(page["id"]), label_visibility="collapsed")
        selected_page = next(item for item in document["pages"] if item["name"] == selected_page_name)
        if selected_page["id"] != page["id"]:
            st.session_state.active_dashboard_page = selected_page["id"]
            st.rerun()
        with st.form("new_dashboard_page", clear_on_submit=True):
            page_name = st.text_input("Nová stránka", placeholder="Např. Finance")
            if st.form_submit_button("+ Přidat stránku", use_container_width=True):
                new_page = add_page(document, page_name)
                save_dashboard(document)
                st.session_state.active_dashboard_page = new_page["id"]
                st.rerun()
        if len(document["pages"]) > 1 and st.button("Odstranit tuto stránku", use_container_width=True):
            remove_page(document, page["id"])
            save_dashboard(document)
            st.session_state.active_dashboard_page = document["pages"][0]["id"]
            st.rerun()

    with st.container(border=True):
        st.markdown("#### Filtry stránky")
        filter_one, filter_two, filter_three, filter_four = st.columns([1.25, 1.25, 1.5, 1])
        with filter_one:
            segments = st.multiselect("Segment", SEGMENTS, default=page["filters"]["segments"], key=f"segments-{page['id']}")
        with filter_two:
            cities = st.multiselect("Město", CITIES, default=page["filters"]["cities"], key=f"cities-{page['id']}")
        with filter_three:
            dates = st.date_input("Období", value=(pd.to_datetime(page["filters"]["date_from"]).date() if page["filters"]["date_from"] else date(2026, 1, 1), pd.to_datetime(page["filters"]["date_to"]).date() if page["filters"]["date_to"] else date(2026, 10, 31)), key=f"dates-{page['id']}")
        with filter_four:
            period_label = st.segmented_control("Granularita", ["Monthly", "Weekly"], default="Weekly" if page["filters"]["period"] == "weekly" else "Monthly", key=f"period-{page['id']}")
        updated_filters = normalize_filters({"segments": segments, "cities": cities, "date_from": dates[0].isoformat(), "date_to": dates[1].isoformat(), "period": (period_label or "Monthly").lower()})
        if updated_filters != page["filters"]:
            page["filters"] = updated_filters
            save_dashboard(document)
            st.rerun()
        st.markdown("<div class='dashboard-filter-note'>Weekly / monthly je uložené nastavení stránky; časové karty jej mohou používat při rozšíření datového dotazu.</div>", unsafe_allow_html=True)

    if not page["cards"]:
        st.info("Tato stránka je zatím prázdná. V Analytickém chatu vytvořte vizualizaci a přidejte ji na dashboard.")
    selected_card_id = st.session_state.get("selected_dashboard_card")
    for index, spec in enumerate(page["cards"]):
        spec = normalize_card(spec)
        page["cards"][index] = spec
        with st.container(border=True):
            content_column, control_column = st.columns([5, 1])
            with content_column:
                filtered_sql = apply_time_granularity(apply_filters_to_sql(spec["sql"], page["filters"]), page["filters"]["period"])
                data = apply_card_preferences(run_sql(filtered_sql), spec)
                if spec["kind"] == "table":
                    st.subheader(spec["title"])
                    st.dataframe(data, use_container_width=True, hide_index=True)
                elif spec["kind"] == "metric":
                    st.metric(spec["title"], f"{float(data.iloc[0, 0]):,.0f}".replace(",", " "))
                else:
                    st.plotly_chart(chart_figure(spec, data), use_container_width=True, key=f"chart-{page['id']}-{spec['id']}")
                sql_card(filtered_sql, len(data))
            with control_column:
                st.caption(f"Karta {index + 1}")
                if st.button("Upravit", key=f"select-{spec['id']}", use_container_width=True):
                    st.session_state.selected_dashboard_card = spec["id"]
                    st.rerun()
                if index > 0 and st.button("↑", key=f"up-{spec['id']}", use_container_width=True):
                    page["cards"][index - 1], page["cards"][index] = page["cards"][index], page["cards"][index - 1]
                    save_dashboard(document)
                    st.rerun()
                if index < len(page["cards"]) - 1 and st.button("↓", key=f"down-{spec['id']}", use_container_width=True):
                    page["cards"][index + 1], page["cards"][index] = page["cards"][index], page["cards"][index + 1]
                    save_dashboard(document)
                    st.rerun()
                if st.button("Odstranit", key=f"delete-{spec['id']}", use_container_width=True):
                    page["cards"].pop(index)
                    save_dashboard(document)
                    st.rerun()

    selected = next((card for card in page["cards"] if card["id"] == selected_card_id), None)
    st.divider()
    editor_column, chat_column = st.columns([1, 1], gap="large")
    with editor_column:
        st.markdown("### Upravit kartu")
        if not selected:
            st.caption("Vyberte u karty tlačítko „Upravit“.")
        else:
            with st.form(f"card-editor-{selected['id']}"):
                title = st.text_input("Název", selected["title"])
                kind = st.selectbox("Typ grafu", CHART_KINDS, index=CHART_KINDS.index(selected["kind"]))
                color = st.selectbox("Barva", COLORS, index=COLORS.index(selected["color"]) if selected["color"] in COLORS else 0)
                sort_order = st.selectbox("Řazení", ["original", "ascending", "descending"], index=["original", "ascending", "descending"].index(selected.get("sort_order", "original")))
                if st.form_submit_button("Uložit úpravy", type="primary", use_container_width=True):
                    selected.update({"title": title.strip() or selected["title"], "kind": kind, "color": color, "sort_order": sort_order})
                    save_dashboard(document)
                    st.success("Karta byla upravena.")
                    st.rerun()
    with chat_column:
        st.markdown("### Editor dashboardu")
        st.caption("Např. „Přidej stránku Finance“, „nastav weekly“, „změň graf na line“, „seřaď vzestupně“ nebo „nastav růžovou“.")
        with st.form(f"dashboard-editor-{page['id']}", clear_on_submit=True):
            command = st.text_input("Pokyn pro editor", placeholder="Uprav aktuálně vybranou kartu…")
            submitted = st.form_submit_button("Provést změnu", type="primary", use_container_width=True)
        if submitted:
            updated_document, notice = parse_editor_command(document, page["id"], command, selected_card_id)
            save_dashboard(updated_document)
            st.session_state.dashboard_editor_notice = notice
            if command.lower().strip().startswith(("přidej stránku", "pridej stranku", "new page")):
                st.session_state.active_dashboard_page = updated_document["pages"][-1]["id"]
            st.rerun()
        if st.session_state.get("dashboard_editor_notice"):
            st.success(st.session_state.dashboard_editor_notice)
            st.session_state.dashboard_editor_notice = None


style_app()
with st.sidebar:
    st.markdown("# ◒ Insight Hub")
    st.caption("ERP × CRM · local POC")
    page = st.radio("Pracovní plocha", ["Analytický chat", "Můj dashboard"])
    st.divider()
    st.caption("Lokální data · DuckDB · read-only SQL")
    st.caption("2026 demo dataset")

if page == "Analytický chat":
    render_analytics_chat()
else:
    render_dashboard()