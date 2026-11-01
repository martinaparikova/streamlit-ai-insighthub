"""Dashboard configuration, safe filter application, and local editor commands."""

from copy import deepcopy
import re
import uuid


SEGMENTS = ("Enterprise", "Mid-market", "SMB")
CITIES = ("Praha", "Brno", "Ostrava", "Plzeň", "Liberec", "Olomouc")
CHART_KINDS = ("bar", "line", "area", "pie", "table", "metric")
PERIODS = ("monthly", "weekly")
COLORS = ("#0B3B2E", "#C2185B", "#2F6B5A", "#7C3AED", "#EA580C")
LEGACY_COLOR_MAP = {"#2563EB": "#2F6B5A", "#EC4899": "#C2185B", "#0F766E": "#0B3B2E"}


def default_filters():
    return {"segments": [], "cities": [], "date_from": None, "date_to": None, "period": "monthly"}


def default_page(name="Přehled", cards=None):
    return {"id": uuid.uuid4().hex[:8], "name": name, "filters": default_filters(), "cards": cards or []}


def normalize_card(card):
    normalized = dict(card)
    normalized["color"] = LEGACY_COLOR_MAP.get(normalized.get("color"), normalized.get("color"))
    normalized.setdefault("id", uuid.uuid4().hex[:8])
    normalized.setdefault("kind", "bar")
    normalized.setdefault("color", COLORS[0])
    normalized.setdefault("highlight", None)
    normalized.setdefault("font", "Arial")
    normalized.setdefault("title_size", 20)
    normalized.setdefault("position", "bottom")
    normalized.setdefault("sort_order", "original")
    normalized.setdefault("show_table", False)
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


def normalize_dashboard(document):
    """Normalize v1 list storage or v2 object storage into the current document."""
    if isinstance(document, list):
        return {"version": 2, "pages": [default_page(cards=[normalize_card(card) for card in document])]}
    if not isinstance(document, dict):
        return {"version": 2, "pages": [default_page()]}
    pages = []
    for page in document.get("pages", []):
        if not isinstance(page, dict):
            continue
        cards = [normalize_card(card) for card in page.get("cards", []) if isinstance(card, dict)]
        normalized = default_page(page.get("name") or "Bez názvu", cards)
        normalized["id"] = page.get("id") or normalized["id"]
        normalized["filters"] = normalize_filters(page.get("filters"))
        pages.append(normalized)
    return {"version": 2, "pages": pages or [default_page()]}


def add_page(document, name):
    page = default_page((name or "Nová stránka").strip()[:60] or "Nová stránka")
    document["pages"].append(page)
    return page


def remove_page(document, page_id):
    if len(document["pages"]) <= 1:
        return False
    document["pages"] = [page for page in document["pages"] if page["id"] != page_id]
    return True


def page_by_id(document, page_id):
    return next((page for page in document["pages"] if page["id"] == page_id), document["pages"][0])


def _quote_values(values):
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def apply_filters_to_sql(sql, filters):
    """Add only whitelisted page filters to the application's known SELECT queries."""
    filters = normalize_filters(filters)
    if not any(filters[key] for key in ("segments", "cities", "date_from", "date_to")):
        return sql
    source = "invoices" if re.search(r"\bFROM\s+invoices\b", sql, flags=re.I) else "opportunities" if re.search(r"\bFROM\s+opportunities\b", sql, flags=re.I) else None
    if not source:
        return sql
    alias, date_column = ("i", "invoice_date") if source == "invoices" else ("o", "created_date")
    filtered_sql = sql
    needs_company = filters["segments"] or filters["cities"]
    if needs_company and not re.search(r"\bJOIN\s+companies\b", filtered_sql, flags=re.I):
        filtered_sql = re.sub(rf"\bFROM\s+{source}\s+{alias}\b", f"FROM {source} {alias} JOIN companies c USING (company_id)", filtered_sql, count=1, flags=re.I)
        filtered_sql = re.sub(rf"\bFROM\s+{source}\b", f"FROM {source} {alias} JOIN companies c USING (company_id)", filtered_sql, count=1, flags=re.I)
    conditions = []
    if filters["segments"]:
        conditions.append(f"c.segment IN ({_quote_values(filters['segments'])})")
    if filters["cities"]:
        conditions.append(f"c.city IN ({_quote_values(filters['cities'])})")
    if filters["date_from"]:
        conditions.append(f"CAST({alias}.{date_column} AS DATE) >= DATE '{filters['date_from']}'")
    if filters["date_to"]:
        conditions.append(f"CAST({alias}.{date_column} AS DATE) <= DATE '{filters['date_to']}'")
    condition_sql = " AND ".join(conditions)
    if re.search(r"\bWHERE\b", filtered_sql, flags=re.I):
        return re.sub(r"\bWHERE\b", f"WHERE {condition_sql} AND ", filtered_sql, count=1, flags=re.I)
    return re.sub(r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", f"WHERE {condition_sql}\n\\1", filtered_sql, count=1, flags=re.I)


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
    chart_terms = {"bar": ("bar", "sloupc"), "line": ("line", "spojnic"), "area": ("area", "plošn", "plosn"), "pie": ("pie", "koláč", "kolac"), "table": ("table", "tabulk")}
    for kind, terms in chart_terms.items():
        if any(term in prompt for term in terms):
            selected["kind"] = kind
            return document, f"Karta „{selected['title']}“ používá typ {kind}."
    if any(term in prompt for term in ("vzestup", "ascending", "nejniž", "nejniz")):
        selected["sort_order"] = "ascending"
        return document, f"Karta „{selected['title']}“ je seřazena vzestupně."
    if any(term in prompt for term in ("sestup", "descending", "nejvyš", "nejvyss")):
        selected["sort_order"] = "descending"
        return document, f"Karta „{selected['title']}“ je seřazena sestupně."
    color_terms = {"růž": "#C2185B", "ruz": "#C2185B", "pink": "#C2185B", "modr": "#2F6B5A", "blue": "#2F6B5A", "zelen": "#0B3B2E", "green": "#0B3B2E", "fial": "#7C3AED", "purple": "#7C3AED"}
    for term, color in color_terms.items():
        if term in prompt:
            selected["color"] = color
            return document, f"Barva karty „{selected['title']}“ byla změněna."
    if any(term in prompt for term in ("nahoru", "up", "první", "prvni")):
        index = page["cards"].index(selected)
        if index:
            page["cards"][index - 1], page["cards"][index] = page["cards"][index], page["cards"][index - 1]
        return document, f"Karta „{selected['title']}“ byla posunuta nahoru."
    return document, "Pokyn jsem nerozpoznal. Zkuste například „změň graf na line“, „seřaď vzestupně“ nebo „nastav růžovou“."