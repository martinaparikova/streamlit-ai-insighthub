"""Editable semantic model and deterministic knowledge answers for the demo workspace."""

from copy import deepcopy
import re
import uuid


STATUSES = ("draft", "approved")


def _item(identifier, name, description, **values):
    return {"id": identifier, "name": name, "description": description, "status": "approved", **values}


def default_semantic_model():
    """Return the approved starter model for the built-in CRM/ERP demo source."""
    return {
        "version": 1,
        "source": {"name": "Demo CRM / ERP", "engine": "DuckDB", "status": "connected"},
        "tables": [
            _item("companies", "Firmy", "Kmen zákazníků a základní obchodní atributy.", technical_name="companies", grain="Jeden řádek představuje jednu firmu."),
            _item("invoices", "Faktury", "Vystavené faktury včetně netto hodnoty, data a stavu úhrady.", technical_name="invoices", grain="Jeden řádek představuje jednu fakturu."),
            _item("opportunities", "Obchodní příležitosti", "CRM pipeline obchodních příležitostí a očekávané hodnoty.", technical_name="opportunities", grain="Jeden řádek představuje jednu obchodní příležitost."),
        ],
        "relationships": [
            _item("companies-invoices", "Firma → Faktury", "Jedna firma může mít více faktur.", from_table="companies", from_column="company_id", to_table="invoices", to_column="company_id", cardinality="1:N"),
            _item("companies-opportunities", "Firma → Obchodní příležitosti", "Jedna firma může mít více obchodních příležitostí.", from_table="companies", from_column="company_id", to_table="opportunities", to_column="company_id", cardinality="1:N"),
        ],
        "metrics": [
            _item("revenue", "Revenue", "Součet netto hodnot vystavených faktur podle data vystavení.", synonyms=["tržby", "obrat"], formula="SUM(invoices.net_amount_czk)", entity="invoices", time_dimension="invoices.invoice_date", format="CZK", rules="Nezahrnuje DPH. Storna a dobropisy v demo zdroji nejsou samostatně modelovány."),
            _item("overdue-amount", "Objem po splatnosti", "Součet netto hodnot faktur se stavem Overdue.", synonyms=["overdue amount", "pohledávky po splatnosti"], formula="SUM(invoices.net_amount_czk) WHERE invoices.payment_status = 'Overdue'", entity="invoices", time_dimension="invoices.due_date", format="CZK", rules="Stav po splatnosti se určuje výhradně přes payment_status = 'Overdue'."),
            _item("overdue-invoice-count", "Počet faktur po splatnosti", "Počet faktur se stavem Overdue.", synonyms=["overdue invoices", "počet overdue faktur"], formula="COUNT(invoices.invoice_id) WHERE invoices.payment_status = 'Overdue'", entity="invoices", time_dimension="invoices.due_date", format="number", rules="Samotné datum splatnosti pro určení stavu nestačí."),
            _item("pipeline-value", "Hodnota pipeline", "Součet hodnot otevřených obchodních příležitostí podle jejich fáze.", synonyms=["pipeline", "hodnota příležitostí"], formula="SUM(opportunities.amount_czk)", entity="opportunities", time_dimension="opportunities.created_date", format="CZK", rules="Význam jednotlivých fází je dán hodnotou opportunities.stage."),
        ],
        "terms": [
            _item("company", "Firma", "Zákazník evidovaný v tabulce companies.", synonyms=["společnost", "customer", "account"]),
            _item("invoice", "Faktura", "Doklad vystavený zákazníkovi evidovaný v tabulce invoices.", synonyms=["invoice"]),
            _item("pipeline", "Pipeline", "Souhrn obchodních příležitostí v jednotlivých obchodních fázích.", synonyms=["obchodní pipeline"]),
        ],
        "rules": [
            _item("overdue-definition", "Určení faktury po splatnosti", "Faktura po splatnosti má payment_status = 'Overdue'. Datum due_date se nepoužívá jako samostatné kritérium, protože i zaplacená faktura může mít datum splatnosti v minulosti.", related_to=["invoices", "overdue-amount", "overdue-invoice-count"]),
            _item("revenue-definition", "Význam Revenue", "Revenue je v demo modelu součet netto hodnot vystavených faktur podle invoice_date.", related_to=["invoices", "revenue"]),
        ],
    }


def _normalize_collection(values, required):
    normalized = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        item = dict(value)
        if not all(str(item.get(field, "")).strip() for field in required):
            continue
        item["id"] = str(item.get("id") or uuid.uuid4().hex[:8])
        item["name"] = str(item["name"]).strip()[:120]
        item["description"] = str(item.get("description") or "").strip()[:2000]
        item["status"] = item.get("status") if item.get("status") in STATUSES else "draft"
        normalized.append(item)
    return normalized


def normalize_semantic_model(model):
    """Preserve valid user edits and backfill fields added in the first model version."""
    defaults = default_semantic_model()
    if not isinstance(model, dict):
        return defaults
    normalized = {
        "version": 1,
        "source": model.get("source") if isinstance(model.get("source"), dict) else defaults["source"],
        "tables": _normalize_collection(model.get("tables"), ("name", "technical_name")),
        "relationships": _normalize_collection(model.get("relationships"), ("name", "from_table", "from_column", "to_table", "to_column")),
        "metrics": _normalize_collection(model.get("metrics"), ("name", "formula", "entity")),
        "terms": _normalize_collection(model.get("terms"), ("name",)),
        "rules": _normalize_collection(model.get("rules"), ("name",)),
    }
    for item in normalized["metrics"]:
        item["synonyms"] = [str(value).strip() for value in item.get("synonyms", []) if str(value).strip()]
        item["time_dimension"] = str(item.get("time_dimension") or "").strip()
        item["format"] = str(item.get("format") or "number").strip()
        item["rules"] = str(item.get("rules") or "").strip()
    for item in normalized["terms"]:
        item["synonyms"] = [str(value).strip() for value in item.get("synonyms", []) if str(value).strip()]
    for item in normalized["rules"]:
        item["related_to"] = [str(value).strip() for value in item.get("related_to", []) if str(value).strip()]
    return normalized


def upsert_item(model, collection, item):
    """Store a validated model item and return the updated model."""
    updated = normalize_semantic_model(model)
    values = dict(item)
    values["id"] = values.get("id") or uuid.uuid4().hex[:8]
    values["status"] = values.get("status") if values.get("status") in STATUSES else "draft"
    target = updated[collection]
    index = next((index for index, value in enumerate(target) if value["id"] == values["id"]), None)
    if index is None:
        target.append(values)
    else:
        target[index] = values
    return normalize_semantic_model(updated)


def validate_relationship(model, relationship):
    """Ensure a relationship references two distinct tables from the current model."""
    normalized = normalize_semantic_model(model)
    table_names = {item["technical_name"] for item in normalized["tables"]}
    from_table = str(relationship.get("from_table") or "").strip()
    to_table = str(relationship.get("to_table") or "").strip()
    if from_table not in table_names or to_table not in table_names:
        raise ValueError("The relationship must reference tables in the semantic model.")
    if from_table == to_table:
        raise ValueError("The relationship must connect two different tables.")
    if not str(relationship.get("from_column") or "").strip() or not str(relationship.get("to_column") or "").strip():
        raise ValueError("The relationship must include both join columns.")
    return True


def delete_item(model, collection, identifier):
    updated = normalize_semantic_model(model)
    updated[collection] = [item for item in updated[collection] if item["id"] != identifier]
    return updated


def _matches(question, value):
    prompt = question.casefold()
    return any(token and token.casefold() in prompt for token in value)


def answer_knowledge_question(question, model, language="cs"):
    """Answer deterministic Czech/English model questions without SQL or an LLM call."""
    model = normalize_semantic_model(model)
    prompt = re.sub(r"\s+", " ", question.casefold()).strip()
    cs = language == "cs"
    analytical_words = ("show", "zobraz", "kolik", "how many", "count", "sum", "total", "by ", "podle", "za ", "v roce", "month", "měs", "mes", "segment")
    table_words = ("tabulk", "table", "schema", "schém", "modelu", "model")
    metric_words = ("metrik", "metric", "kpi", "jak se počít", "jak se pocit", "how is", "how do", "definition", "definic")
    relation_words = ("vztah", "relationship", "join", "propojen")
    rule_words = ("pravidl", "rule", "po splatnosti", "overdue")

    if _matches(prompt, table_words) and not _matches(prompt, metric_words):
        tables = "; ".join(f"**{item['name']}** (`{item['technical_name']}`) – {item['description']}" for item in model["tables"])
        return {
            "title": "Tabulky v semantickém modelu" if cs else "Tables in the semantic model",
            "content": f"Model obsahuje {len(model['tables'])} tabulky: {tables}" if cs else f"The model contains {len(model['tables'])} tables: {tables}",
        }
    if _matches(prompt, relation_words):
        relations = "; ".join(f"**{item['name']}**: `{item['from_table']}.{item['from_column']}` → `{item['to_table']}.{item['to_column']}` ({item.get('cardinality', 'n/a')}). {item['description']}" for item in model["relationships"])
        return {"title": "Vztahy v modelu" if cs else "Relationships in the model", "content": relations}
    if _matches(prompt, rule_words) and not _matches(prompt, analytical_words):
        rule = next((item for item in model["rules"] if "overdue" in item["id"]), None)
        if rule:
            return {"title": rule["name"], "content": rule["description"]}
    metric = next((item for item in model["metrics"] if _matches(prompt, [item["name"], *item.get("synonyms", [])])), None)
    if metric and not _matches(prompt, analytical_words) and (_matches(prompt, metric_words) or len(prompt.split()) <= 6):
        content = f"**{metric['name']}**: {metric['description']}\n\nFormula: `{metric['formula']}`"
        if metric.get("time_dimension"):
            content += f"\n\n{'Časová dimenze' if cs else 'Time dimension'}: `{metric['time_dimension']}`."
        if metric.get("rules"):
            content += f"\n\n{'Pravidla' if cs else 'Rules'}: {metric['rules']}"
        return {"title": f"{'Definice metriky' if cs else 'Metric definition'}: {metric['name']}", "content": content}
    if _matches(prompt, metric_words) and _matches(prompt, ("dostup", "available", "seznam", "list", "kter")):
        metrics = "; ".join(f"**{item['name']}** – {item['description']}" for item in model["metrics"])
        return {"title": "Dostupné metriky" if cs else "Available metrics", "content": metrics}
    term = next((item for item in model["terms"] if _matches(prompt, [item["name"], *item.get("synonyms", [])])), None)
    if term and not _matches(prompt, analytical_words) and (_matches(prompt, ("co je", "co znamen", "what is", "meaning", "vysvětli", "vysvetli")) or len(prompt.split()) <= 5):
        return {"title": term["name"], "content": term["description"]}
    return None


def draft_preview(model, language="en"):
    """Explain the future AI draft flow in the selected interface language."""
    model = normalize_semantic_model(model)
    if language == "cs":
        return (
            f"AI draft je ve fázi 1 připraven jako workflow placeholder. Aktuální demo model už obsahuje "
            f"{len(model['tables'])} tabulky, {len(model['relationships'])} vztahy a {len(model['metrics'])} metriky. "
            "Ve fázi 2 bude AI vytvářet návrh z metadat připojeného zdroje; každá změna se nejdříve ukáže jako návrh k potvrzení."
        )
    return (
        f"AI draft is available in phase 1 as a workflow placeholder. The current demo model already contains "
        f"{len(model['tables'])} tables, {len(model['relationships'])} relationships, and {len(model['metrics'])} metrics. "
        "In phase 2, AI will create a proposal from the connected source metadata; every change will first be shown as a proposal for confirmation."
    )