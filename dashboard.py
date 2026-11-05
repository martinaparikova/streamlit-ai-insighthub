"""Dashboard configuration, safe filter application, and local editor commands."""

from copy import deepcopy
from datetime import date, timedelta
import re
import uuid

from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import traverse_scope


SEGMENTS = ("Enterprise", "Mid-market", "SMB")
CITIES = ("Praha", "Brno", "Ostrava", "Plzeň", "Liberec", "Olomouc")
CHART_KINDS = ("bar", "line", "area", "pie", "table", "metric", "text", "kpi")
PERIODS = ("monthly", "weekly")
COLORS = ("#0B3B2E", "#C2185B", "#4B5563")


def default_filters():
    return {"segments": [], "cities": [], "date_from": None, "date_to": None, "period": "monthly"}


def default_page(name="Přehled", cards=None):
    return {"id": uuid.uuid4().hex[:8], "name": name, "filters": default_filters(), "cards": cards or []}


def normalize_card(card):
    normalized = dict(card)
    if normalized.get("color") not in COLORS:
        normalized["color"] = COLORS[0]
    normalized.setdefault("id", uuid.uuid4().hex[:8])
    normalized.setdefault("kind", "bar")
    normalized.setdefault("color", COLORS[0])
    normalized.setdefault("highlight", None)
    normalized.setdefault("font", "Arial")
    normalized.setdefault("title_size", 20)
    normalized.setdefault("position", "bottom")
    normalized.setdefault("sort_order", "original")
    normalized.setdefault("show_table", False)
    layout = normalized.get("layout") if isinstance(normalized.get("layout"), dict) else {}
    normalized["layout"] = {
        "row": max(0, int(layout.get("row", 0))),
        "width": min(12, max(1, int(layout.get("width", 12)))),
    }
    normalized.setdefault("text", "")
    normalized.setdefault("text_style", "note")
    normalized.setdefault("decimal_places", 0)
    normalized.setdefault("value_format", "number")
    normalized.setdefault("trend_direction", "higher_is_better")
    normalized.setdefault("comparison_label", "oproti předchozímu období")
    if normalized["kind"] not in CHART_KINDS:
        normalized["kind"] = "bar"
    return normalized


def normalize_filters(filters):
    filters = filters or {}
    segments = [value for value in filters.get("segments", []) if value in SEGMENTS]
    cities = [value for value in filters.get("cities", []) if value in CITIES]
    period = filters.get("period", "monthly")
    return {
        "segments": segments,
        "cities": cities,
        "date_from": filters.get("date_from") or None,
        "date_to": filters.get("date_to") or None,
        "period": period if period in PERIODS else "monthly",
    }


def previous_period_filters(filters):
    """Return the immediately preceding period with the same inclusive length."""
    normalized = normalize_filters(filters)
    if not normalized["date_from"] or not normalized["date_to"]:
        return None
    start = date.fromisoformat(normalized["date_from"])
    end = date.fromisoformat(normalized["date_to"])
    if end < start:
        return None
    length = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    return {**normalized, "date_from": previous_start.isoformat(), "date_to": previous_end.isoformat()}


def next_layout_row(page):
    return max((normalize_card(card)["layout"]["row"] for card in page.get("cards", [])), default=-1) + 1


def normalize_dashboard(document):
    """Normalize v1 list storage or v2 object storage into the current document."""
    if isinstance(document, list):
        cards = []
        for index, card in enumerate(document):
            if not isinstance(card, dict):
                continue
            normalized_card = normalize_card(card)
            if "layout" not in card:
                normalized_card["layout"] = {"row": index, "width": 12}
            cards.append(normalized_card)
        return {"version": 2, "pages": [default_page(cards=cards)]}
    if not isinstance(document, dict):
        return {"version": 2, "pages": [default_page()]}
    pages = []
    for page in document.get("pages", []):
        if not isinstance(page, dict):
            continue
        cards = []
        for index, card in enumerate(page.get("cards", [])):
            if not isinstance(card, dict):
                continue
            normalized_card = normalize_card(card)
            if "layout" not in card:
                normalized_card["layout"] = {"row": index, "width": 12}
            cards.append(normalized_card)
        normalized = default_page(page.get("name") or "Bez názvu", cards)
        normalized["id"] = page.get("id") or normalized["id"]
        normalized["filters"] = normalize_filters(page.get("filters"))
        pages.append(normalized)
    return {"version": 2, "pages": pages or [default_page()]}


def normalize_workspace(document):
    """Keep legacy pages together in one dashboard and normalize saved chats."""
    if not isinstance(document, dict) or "dashboards" not in document:
        dashboards = [{
            "id": "default", "name": "Můj dashboard",
            "pages": normalize_dashboard(document)["pages"],
        }]
    else:
        dashboards = []
        for item in document["dashboards"]:
            if not isinstance(item, dict):
                continue
            dashboards.append({
                "id": item.get("id") or uuid.uuid4().hex[:8],
                "name": item.get("name") or "Bez názvu",
                "pages": normalize_dashboard(item)["pages"],
            })
        if not dashboards:
            return normalize_workspace(None)
    saved_chats = []
    if isinstance(document, dict):
        for chat in document.get("saved_chats", []):
            if not isinstance(chat, dict) or not isinstance(chat.get("history"), list):
                continue
            saved_chats.append({
                "id": chat.get("id") or uuid.uuid4().hex[:8],
                "title": str(chat.get("title") or "Uložený chat").strip()[:60] or "Uložený chat",
                "history": deepcopy(chat["history"]),
            })
    dashboard_history = []
    if isinstance(document, dict):
        for item in document.get("dashboard_history", [])[-30:]:
            if not isinstance(item, dict) or not isinstance(item.get("dashboard"), dict):
                continue
            try:
                snapshot = {
                    "id": item.get("id") or uuid.uuid4().hex[:8],
                    "label": str(item.get("label") or "Úprava dashboardu")[:160],
                    "dashboard": normalize_dashboard(item["dashboard"]),
                }
                snapshot["dashboard"]["id"] = item["dashboard"].get("id") or snapshot["dashboard"].get("id")
                snapshot["dashboard"]["name"] = item["dashboard"].get("name") or "Bez názvu"
                dashboard_history.append(snapshot)
            except (AttributeError, TypeError):
                continue
    return {"version": 4, "dashboards": dashboards, "saved_chats": saved_chats, "dashboard_history": dashboard_history}


def save_dashboard_snapshot(document, dashboard, label):
    """Store the pre-change state for Undo and version history."""
    document.setdefault("dashboard_history", []).append({
        "id": uuid.uuid4().hex[:8], "label": str(label or "Úprava dashboardu")[:160],
        "dashboard": deepcopy(dashboard),
    })
    document["dashboard_history"] = document["dashboard_history"][-30:]


def restore_latest_dashboard_snapshot(document, dashboard_id):
    """Restore and consume the latest history item for one dashboard."""
    history = document.get("dashboard_history", [])
    for index in range(len(history) - 1, -1, -1):
        snapshot = history[index].get("dashboard", {})
        if snapshot.get("id") != dashboard_id:
            continue
        restored = deepcopy(snapshot)
        target_index = next((i for i, item in enumerate(document["dashboards"]) if item["id"] == dashboard_id), None)
        if target_index is None:
            return None
        document["dashboards"][target_index] = restored
        history.pop(index)
        return restored
    return None


def add_dashboard(document, name, overview_name="Přehled"):
    name = name.strip()[:60].strip()
    if not name:
        raise ValueError("Enter a dashboard name.")
    if dashboard_name_exists(document, name):
        raise ValueError("A dashboard with this name already exists.")
    dashboard = {
        "id": uuid.uuid4().hex[:8], "name": name,
        "pages": [default_page(overview_name)],
    }
    document["dashboards"].append(dashboard)
    return dashboard


def rename_dashboard(document, dashboard_id, name):
    """Rename one dashboard while keeping names unique across the workspace."""
    dashboard = dashboard_by_id(document, dashboard_id)
    normalized_name = (name or "").strip()[:60].strip()
    if not normalized_name:
        raise ValueError("Enter a dashboard name.")
    if any(
        item["id"] != dashboard_id and item["name"].strip().casefold() == normalized_name.casefold()
        for item in document["dashboards"]
    ):
        raise ValueError("A dashboard with this name already exists.")
    dashboard["name"] = normalized_name
    return dashboard


def dashboard_by_id(document, dashboard_id):
    dashboard = next((item for item in document["dashboards"] if item["id"] == dashboard_id), None)
    if dashboard is None:
        raise ValueError("The selected dashboard does not exist.")
    return dashboard


def dashboard_name_exists(document, name):
    return _name_exists(document["dashboards"], name)


def add_page(document, name):
    page = default_page((name or "Nová stránka").strip()[:60] or "Nová stránka")
    document["pages"].append(page)
    return page


def page_name_exists(document, name):
    return _name_exists(document["pages"], name)


def _name_exists(items, name):
    normalized_name = (name or "").strip()[:60].strip().casefold()
    return bool(normalized_name) and any(
        item["name"].strip()[:60].strip().casefold() == normalized_name
        for item in items
    )


def remove_page(document, page_id):
    if len(document["pages"]) <= 1:
        return False
    document["pages"] = [page for page in document["pages"] if page["id"] != page_id]
    return True


def page_by_id(document, page_id):
    return next((page for page in document["pages"] if page["id"] == page_id), document["pages"][0])


def add_card_to_page(document, page_id, card):
    """Append a normalized card to the explicitly selected dashboard page."""
    page = next((item for item in document["pages"] if item["id"] == page_id), None)
    if page is None:
        raise ValueError("The selected dashboard page does not exist.")
    page["cards"].append(normalize_card(card))
    return page


def apply_filters_to_sql(sql, filters):
    """Filter base sources before aggregation, preserving aliases and query scopes."""
    filters = normalize_filters(filters)
    if not any(filters[key] for key in ("segments", "cities", "date_from", "date_to")):
        return sql
    query = parse_one(sql, read="duckdb")
    changed = False
    for scope in traverse_scope(query):
        for _, source in scope.selected_sources.values():
            if not isinstance(source, exp.Table):
                continue
            date_column = {"invoices": "invoice_date", "opportunities": "created_date"}.get(source.name.lower())
            if date_column is None:
                continue
            conditions = []
            for key, comparison in (("date_from", exp.GTE), ("date_to", exp.LTE)):
                if filters[key]:
                    conditions.append(comparison(
                        this=exp.cast(exp.column(date_column), "DATE"),
                        expression=exp.cast(exp.Literal.string(filters[key]), "DATE"),
                    ))
            company_conditions = [
                exp.column(column).isin(*(exp.Literal.string(value) for value in filters[key]))
                for key, column in (("segments", "segment"), ("cities", "city"))
                if filters[key]
            ]
            if company_conditions:
                companies = exp.select("company_id").from_("companies").where(*company_conditions)
                conditions.append(exp.In(this=exp.column("company_id"), query=companies.subquery()))
            base_table = source.copy()
            base_table.set("alias", None)
            filtered_source = exp.select("*").from_(base_table).where(*conditions).subquery()
            alias = source.args.get("alias")
            filtered_source.set("alias", alias.copy() if alias else exp.TableAlias(this=source.this.copy()))
            source.replace(filtered_source)
            changed = True
    return query.sql(dialect="duckdb") if changed else sql


def apply_time_granularity(sql, period):
    """Switch the application's known monthly revenue query to weekly buckets."""
    if period != "weekly" or "strftime(CAST(i.invoice_date AS DATE), '%Y-%m') AS month" not in sql:
        return sql
    weekly = sql.replace(
        "strftime(CAST(i.invoice_date AS DATE), '%Y-%m') AS month",
        "strftime(date_trunc('week', CAST(i.invoice_date AS DATE)), '%Y-%m-%d') AS week",
    )
    return weekly.replace("GROUP BY month", "GROUP BY week").replace("ORDER BY month", "ORDER BY week")


def apply_card_preferences(data, card):
    """Keep ordering in the display layer, never alter the stored safe SQL."""
    if data.empty or card.get("sort_order") not in ("ascending", "descending") or card.get("y") not in data.columns:
        return data
    return data.sort_values(card["y"], ascending=card["sort_order"] == "ascending", kind="stable")


def parse_editor_command(document, page_id, command, selected_card_id=None):
    """Apply a constrained Czech/English command and return a visible change summary."""
    document = deepcopy(normalize_dashboard(document))
    page = page_by_id(document, page_id)
    prompt = command.lower().strip()
    selected = next((card for card in page["cards"] if card["id"] == selected_card_id), None)
    if not prompt:
        return document, "Zadejte prosím pokyn pro editor."

    match = re.search(r"(?:přidej|pridej|add)\s+(?:komentář|komentar|text|comment)\s*:\s*(.+)", command, flags=re.I)
    if match:
        content = match.group(1).strip()
        if not content:
            return document, "Text komentáře nesmí být prázdný."
        page["cards"].append(normalize_card({
            "title": "Komentář", "kind": "text", "text": content,
            "layout": {"row": next_layout_row(page), "width": 12},
        }))
        return document, "Textový komentář byl přidán na dashboard."

    match = re.search(r"(?:přidej|pridej|nová|nova|new)\s+(?:stránku|stranku|page)\s+(.+)", command, flags=re.I)
    if match:
        new_page = add_page(document, match.group(1).strip(" ."))
        return document, f"Přidána stránka „{new_page['name']}“."
    match = re.search(r"(?:přejmenuj|prejmenuj|rename).+?(?:na|to)\s+(.+)", command, flags=re.I)
    if match and any(term in prompt for term in ("strán", "stran", "page")):
        page["name"] = match.group(1).strip(" .")[:60] or page["name"]
        return document, f"Stránka přejmenována na „{page['name']}“."

    for segment in SEGMENTS:
        if segment.lower() in prompt:
            page["filters"]["segments"] = [segment]
            return document, f"Filtr stránky: segment {segment}."
    for city in CITIES:
        if city.lower() in prompt:
            page["filters"]["cities"] = [city]
            return document, f"Filtr stránky: město {city}."
    if any(term in prompt for term in ("weekly", "týden", "tyden")):
        page["filters"]["period"] = "weekly"
        return document, "Časová granularita nastavena na weekly."
    if any(term in prompt for term in ("monthly", "měsíc", "mesic")):
        page["filters"]["period"] = "monthly"
        return document, "Časová granularita nastavena na monthly."

    if not selected:
        return document, "Vyberte kartu, kterou chcete upravit, nebo přidejte či přejmenujte stránku."
    changes = []

    rename_match = re.search(
        r"(?:uprav|změň|zmen|nastav|přejmenuj|prejmenuj|rename|set|change)\s+"
        r"(?:it\s+)?(?:název|nazev|jméno|jmeno|title)?\s*(?:grafu|tabulky|karty|chart|table|card)?\s*"
        r"(?:na|to)\s+(.+)",
        command,
        flags=re.I,
    )
    if rename_match:
        title = rename_match.group(1).strip(" .")[:120]
        if title:
            selected["title"] = title
            changes.append("název")

    # Change a chart type only after an explicit "change chart to …" phrase.
    # Do not infer it from nouns such as "tabulky" in "uprav název tabulky".
    chart_match = re.search(
        r"(?:změň|zmen|nastav|přepni|prepni|change|set|switch)\s+(?:typ\s+)?"
        r"(?:graf(?:u)?|chart)\s+(?:na|to)\s+"
        r"(bar|line|area|pie|table|sloupc\w*|spojnic\w*|plošn\w*|plosn\w*|koláč\w*|kolac\w*|tabulk\w*)\b",
        prompt,
    )
    if chart_match:
        target = chart_match.group(1)
        chart_kind = next((kind for kind, terms in {
            "bar": ("bar", "sloupc"), "line": ("line", "spojnic"),
            "area": ("area", "plošn", "plosn"), "pie": ("pie", "koláč", "kolac"),
            "table": ("table", "tabulk"),
        }.items() if any(target.startswith(term) for term in terms)), None)
        if chart_kind:
            selected["kind"] = chart_kind
            changes.append(f"typ grafu: {chart_kind}")

    color_terms = {
        "růž": "#C2185B", "ruz": "#C2185B", "pink": "#C2185B",
        "zelen": "#0B3B2E", "green": "#0B3B2E",
        "šed": "#4B5563", "sed": "#4B5563", "gray": "#4B5563", "grey": "#4B5563",
    }
    for term, color in color_terms.items():
        if term in prompt:
            selected["color"] = color
            changes.append("barva")
            break

    if any(term in prompt for term in ("vzestup", "ascending", "nejniž", "nejniz")):
        selected["sort_order"] = "ascending"
        changes.append("řazení vzestupně")
    elif any(term in prompt for term in ("sestup", "descending", "nejvyš", "nejvyss")):
        selected["sort_order"] = "descending"
        changes.append("řazení sestupně")
    if any(term in prompt for term in ("nahoru", "up", "první", "prvni")):
        index = page["cards"].index(selected)
        if index:
            page["cards"][index - 1], page["cards"][index] = page["cards"][index], page["cards"][index - 1]
            changes.append("pozice karty")
    if any(term in prompt for term in ("vedle", "polovinu", "half", "half-width")):
        selected["layout"]["width"] = 6
        changes.append("šířka poloviny řádku")
    elif any(term in prompt for term in ("třetinu", "tretinu", "third")):
        selected["layout"]["width"] = 4
        changes.append("šířka třetiny řádku")
    elif any(term in prompt for term in ("celou šířku", "celou sirku", "full width", "full-width")):
        selected["layout"]["width"] = 12
        changes.append("šířka celého řádku")
    if changes:
        return document, f"Karta „{selected['title']}“ byla upravena: {', '.join(changes)}."
    return document, "Pokyn jsem nerozpoznal. Zkuste například „změň graf na line“, „seřaď vzestupně“ nebo „nastav růžovou“."