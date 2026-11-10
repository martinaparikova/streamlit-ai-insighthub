"""Interactive table graph backed by the connected database's column metadata."""

from pathlib import Path

import duckdb
import streamlit as st


_ASSETS = Path(__file__).parent / "assets"
_SCHEMA_DIAGRAM = st.components.v2.component(
    "semantic_schema_graph",
    html="<div class='schema-root'></div>",
    css=(_ASSETS / "schema_diagram.css").read_text(encoding="utf-8"),
    js=(_ASSETS / "schema_diagram.js").read_text(encoding="utf-8"),
)


def build_schema_diagram_data(model, connection, language="en"):
    """Read every column without querying table rows or interpolating identifiers."""
    names = [table["technical_name"] for table in model["tables"]]
    keys = {name: set() for name in names}
    degrees = {name: 0 for name in names}
    relationships = []
    issues = []
    for relationship in model["relationships"]:
        source, target = relationship["from_table"], relationship["to_table"]
        if source not in names or target not in names:
            issues.append(
                f"Vztah odkazuje na neznámou tabulku: {source} → {target}."
                if language == "cs"
                else f"A relationship references an unknown table: {source} → {target}."
            )
            continue
        keys[source].add(relationship["from_column"])
        keys[target].add(relationship["to_column"])
        degrees[source] += 1
        degrees[target] += 1
        relationships.append({
            "from_table": source,
            "from_column": relationship["from_column"],
            "to_table": target,
            "to_column": relationship["to_column"],
            "cardinality": relationship.get("cardinality", "n/a"),
        })

    tables = []
    for table in model["tables"]:
        name = table["technical_name"]
        columns = []
        error = None
        try:
            metadata = connection.execute(
                "DESCRIBE SELECT * FROM query_table(?)", [name],
            ).fetchall()
        except duckdb.CatalogException as exception:
            error = str(exception)
        else:
            columns = [{"name": column[0], "type": column[1]} for column in metadata]
        tables.append({
            "id": name,
            "name": table["name"],
            "description": table.get("grain") or table.get("description") or "",
            "columns": columns,
            "join_columns": sorted(keys[name]),
            "error": error,
        })
    hub = max(degrees, key=lambda name: degrees[name]) if degrees else None
    return {
        "tables": tables,
        "relationships": relationships,
        "hub": hub,
        "language": language,
        "issues": issues,
    }


def render_schema_diagram(model, connection, language="en"):
    data = build_schema_diagram_data(model, connection, language)
    if not data["tables"]:
        st.info("Model zatím neobsahuje tabulky." if language == "cs" else "The model has no tables yet.")
        return
    for issue in data["issues"]:
        st.warning(issue)
    for table in data["tables"]:
        if table["error"]:
            st.warning(
                f"Sloupce tabulky {table['id']} nejsou dostupné v připojeném zdroji."
                if language == "cs"
                else f"Columns for {table['id']} are unavailable in the connected source."
            )
    _SCHEMA_DIAGRAM(data=data, key="semantic-schema-graph", height="content")
