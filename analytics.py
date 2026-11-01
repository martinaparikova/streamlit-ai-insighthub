"""Safe analytics planning and SQL generation for Insight Hub.

The language model can select only a validated plan. It never supplies SQL that
the application executes.
"""

import json
import os
import sys


SEGMENTS = ("Enterprise", "Mid-market", "SMB")
CITIES = ("Praha", "Brno", "Ostrava", "Plzeň", "Liberec", "Olomouc")
INTENTS = (
    "overdue_invoice_count",
    "overdue_invoice_list",
    "overdue_amount_total",
    "revenue_by_product",
    "revenue_by_month",
    "pipeline_by_stage",
    "top_companies_by_revenue",
)
SORT_ORDERS = ("highest", "lowest")


ANALYTICS_PLAN_TOOL = {
    "type": "function",
    "name": "select_analytics_plan",
    "description": "Select the safe analytics plan that best answers the user's question.",
    "strict": True,
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {"type": "string", "enum": list(INTENTS)},
            "segment": {"anyOf": [{"type": "string", "enum": list(SEGMENTS)}, {"type": "null"}]},
            "city": {"anyOf": [{"type": "string", "enum": list(CITIES)}, {"type": "null"}]},
            "limit": {"anyOf": [{"type": "integer", "enum": [3, 5, 10, 100]}, {"type": "null"}]},
            "sort_order": {"type": "string", "enum": list(SORT_ORDERS)},
        },
        "required": ["intent", "segment", "city", "limit", "sort_order"],
    },
}


def get_openai_api_key():
    """Return the API key without exposing it, including Windows `setx` user scope.

    Processes started before `setx` do not inherit its new environment variable.
    Reading the user environment registry value makes a long-running local
    Streamlit process work after a browser refresh as well.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as environment_key:
                api_key, _ = winreg.QueryValueEx(environment_key, "OPENAI_API_KEY")
                return api_key or None
        except (FileNotFoundError, OSError):
            return None
    return None


def normalize_plan(plan):
    """Validate and normalize a plan received from an LLM or a test."""
    if not isinstance(plan, dict) or plan.get("intent") not in INTENTS:
        raise ValueError("The analytics plan contains an unsupported intent.")

    normalized = {
        "intent": plan["intent"],
        "segment": plan.get("segment"),
        "city": plan.get("city"),
        "limit": plan.get("limit"),
        "sort_order": plan.get("sort_order", "highest"),
    }
    if normalized["segment"] not in (*SEGMENTS, None):
        raise ValueError("The analytics plan contains an unsupported segment.")
    if normalized["city"] not in (*CITIES, None):
        raise ValueError("The analytics plan contains an unsupported city.")
    if normalized["limit"] not in (None, 3, 5, 10, 100):
        raise ValueError("The analytics plan contains an unsupported limit.")
    if normalized["sort_order"] not in SORT_ORDERS:
        raise ValueError("The analytics plan contains an unsupported sort order.")
    return normalized


def _company_filters(plan, table_alias):
    conditions = []
    if plan["segment"]:
        conditions.append(f"c.segment = '{plan['segment']}'")
    if plan["city"]:
        conditions.append(f"c.city = '{plan['city']}'")
    join = f" JOIN companies c USING (company_id)" if conditions else ""
    where = f" AND {' AND '.join(conditions)}" if conditions else ""
    return join, where


def build_analytics_result(plan):
    """Create an English presentation result and SQL from a whitelisted plan."""
    plan = normalize_plan(plan)
    intent = plan["intent"]
    invoice_join, invoice_filters = _company_filters(plan, "i")
    opportunity_join, opportunity_filters = _company_filters(plan, "o")
    limit = plan["limit"] or 10
    revenue_direction = "ASC" if plan["sort_order"] == "lowest" else "DESC"

    if intent == "overdue_invoice_count":
        return {
            "title": "Overdue invoice count",
            "kind": "metric",
            "metric_label": "Overdue invoices",
            "summary": "The number of invoices currently marked as overdue.",
            "sql": f"""SELECT COUNT(*) AS overdue_invoice_count
FROM invoices i{invoice_join}
WHERE i.payment_status = 'Overdue'{invoice_filters}""",
        }
    if intent == "overdue_amount_total":
        return {
            "title": "Total overdue amount",
            "kind": "metric",
            "metric_label": "Total overdue amount (CZK)",
            "summary": "The total net amount of invoices currently marked as overdue.",
            "sql": f"""SELECT COALESCE(SUM(i.net_amount_czk), 0) AS overdue_amount_czk
FROM invoices i{invoice_join}
WHERE i.payment_status = 'Overdue'{invoice_filters}""",
        }
    if intent == "overdue_invoice_list":
        return {
            "title": "Overdue invoices",
            "kind": "table",
            "summary": "Overdue invoices, ordered by net amount from highest to lowest.",
            "sql": f"""SELECT c.company_name AS company, c.segment, i.invoice_date, i.due_date,
       i.net_amount_czk AS amount_czk
FROM invoices i JOIN companies c USING (company_id)
WHERE i.payment_status = 'Overdue'{invoice_filters}
ORDER BY i.net_amount_czk DESC
LIMIT {plan['limit'] or 100}""",
        }
    if intent == "revenue_by_product":
        is_lowest = plan["sort_order"] == "lowest"
        return {
            "title": "Lowest-revenue products" if is_lowest else "Revenue by product",
            "kind": "bar",
            "summary": "Products with the lowest revenue in the available 2026 demo data." if is_lowest else "Revenue by product for the available 2026 demo data.",
            "sql": f"""SELECT i.product, SUM(i.net_amount_czk) AS revenue_czk,
       COUNT(*) AS invoice_count
FROM invoices i{invoice_join}
WHERE 1 = 1{invoice_filters}
GROUP BY i.product
ORDER BY revenue_czk {revenue_direction}
LIMIT {limit}""",
        }
    if intent == "revenue_by_month":
        return {
            "title": "Revenue by month",
            "kind": "bar",
            "summary": "Monthly revenue for the available 2026 demo data.",
            "sql": f"""SELECT strftime(CAST(i.invoice_date AS DATE), '%Y-%m') AS month,
       SUM(i.net_amount_czk) AS revenue_czk
FROM invoices i{invoice_join}
WHERE 1 = 1{invoice_filters}
GROUP BY month
ORDER BY month""",
        }
    if intent == "pipeline_by_stage":
        return {
            "title": "Pipeline by stage",
            "kind": "bar",
            "summary": "Opportunity value grouped by sales stage.",
            "sql": f"""SELECT o.stage, SUM(o.amount_czk) AS pipeline_value_czk,
       COUNT(*) AS opportunity_count
FROM opportunities o{opportunity_join}
WHERE 1 = 1{opportunity_filters}
GROUP BY o.stage
ORDER BY pipeline_value_czk DESC
LIMIT {limit}""",
        }
    return {
        "title": "Top companies by revenue",
        "kind": "table",
        "summary": "Companies with the highest invoiced revenue.",
        "sql": f"""SELECT c.company_name AS company, c.segment,
       SUM(i.net_amount_czk) AS revenue_czk, COUNT(i.invoice_id) AS invoice_count
FROM invoices i JOIN companies c USING (company_id)
WHERE 1 = 1{invoice_filters}
GROUP BY c.company_name, c.segment
ORDER BY revenue_czk DESC
LIMIT {limit}""",
    }


def get_local_plan(question, previous_plan=None):
    """Deterministic English/Czech fallback for the most important chat requests."""
    prompt = question.lower()
    segment = next((value for value in SEGMENTS if value.lower() in prompt), None)
    city = next((value for value in CITIES if value.lower() in prompt), None)
    limit = next((value for value in (3, 5, 10, 100) if f"top {value}" in prompt), None)
    if not limit:
        limit = next(
            (
                value
                for value in (3, 5, 10, 100)
                if any(phrase in prompt for phrase in (
                    f"{value} worst", f"{value} lowest", f"{value} least", f"{value} with the least",
                ))
            ),
            None,
        )
    sort_order = "lowest" if any(term in prompt for term in (
        "worst", "least", "lowest", "bottom", "smallest", "nejhor", "nejmén", "nejmen", "nejniž", "nejniz",
    )) else "highest"

    asks_for_count = any(term in prompt for term in (
        "how many", "count", "number", "one number", "kolik", "počet", "pocet", "jedno číslo", "jedno cislo",
    ))
    asks_for_total = any(term in prompt for term in (
        "total overdue", "total amount", "sum", "celkem", "součet", "soucet", "částka", "castka",
    ))
    mentions_overdue = any(term in prompt for term in ("overdue", "past due", "po splatnosti"))
    previous_intent = (previous_plan or {}).get("intent")

    if mentions_overdue or previous_intent and (asks_for_count or asks_for_total):
        if asks_for_count:
            intent = "overdue_invoice_count"
        elif asks_for_total:
            intent = "overdue_amount_total"
        else:
            intent = "overdue_invoice_list"
        return normalize_plan({"intent": intent, "segment": segment, "city": city, "limit": limit, "sort_order": sort_order})

    if any(term in prompt for term in ("product", "produkt", "produkty")):
        return normalize_plan({"intent": "revenue_by_product", "segment": segment, "city": city, "limit": limit, "sort_order": sort_order})
    if previous_intent == "revenue_by_product" and any(term in prompt for term in ("worst", "least", "lowest", "bottom", "highest", "best", "top")):
        return normalize_plan({"intent": "revenue_by_product", "segment": segment, "city": city, "limit": limit, "sort_order": sort_order})
    if any(term in prompt for term in ("pipeline", "stage", "fáze", "faze")):
        return normalize_plan({"intent": "pipeline_by_stage", "segment": segment, "city": city, "limit": limit, "sort_order": sort_order})
    if any(term in prompt for term in ("month", "měsíc", "mesic")):
        return normalize_plan({"intent": "revenue_by_month", "segment": segment, "city": city, "limit": limit, "sort_order": sort_order})
    return normalize_plan({"intent": "top_companies_by_revenue", "segment": segment, "city": city, "limit": limit, "sort_order": sort_order})


def get_llm_plan(question, previous_plan=None):
    """Ask OpenAI to select a safe plan. Returns None when no key is configured."""
    api_key = get_openai_api_key()
    if not api_key:
        return None

    from openai import OpenAI

    prior_context = "None."
    if previous_plan:
        safe_previous = normalize_plan(previous_plan)
        prior_context = json.dumps(safe_previous)
    instructions = """You are the intent planner for an English-language CRM/ERP analytics chat.
Choose exactly one function call. Never answer the question directly and never invent data.
Use overdue_invoice_count for how many/count/number requests; overdue_invoice_list for a detailed list;
and overdue_amount_total for total monetary value. Use sort_order=lowest for worst, least, bottom,
or lowest-revenue requests; use sort_order=highest otherwise. Interpret a follow-up in light of prior context.
The dataset covers companies, invoices, and opportunities. The only supported filters are segment,
city, and limit. If the question is ambiguous, use the closest supported intent instead of making up
an unsupported calculation."""
    response = OpenAI(api_key=api_key).responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=instructions,
        input=f"Previous plan: {prior_context}\nUser question: {question}",
        tools=[ANALYTICS_PLAN_TOOL],
        tool_choice={"type": "function", "name": "select_analytics_plan"},
    )
    for item in response.output:
        if item.type == "function_call" and item.name == "select_analytics_plan":
            return normalize_plan(json.loads(item.arguments))
    raise RuntimeError("The model did not return an analytics plan.")