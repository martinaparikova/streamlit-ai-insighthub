import unittest
from copy import deepcopy

import duckdb
import pandas as pd

from ontology import default_semantic_model
from schema_diagram import build_schema_diagram_data


class SchemaDiagramTests(unittest.TestCase):
    def setUp(self):
        self.connection = duckdb.connect()
        self.addCleanup(self.connection.close)
        self.connection.register("companies", pd.DataFrame({
            "company_id": [1], "company_name": ["Example"], "city": ["Prague"],
        }))
        self.connection.execute("CREATE TABLE invoices (invoice_id INTEGER, company_id INTEGER, amount DECIMAL(12,2))")
        self.connection.execute("CREATE TABLE opportunities (opportunity_id INTEGER, company_id INTEGER, stage VARCHAR)")
        self.model = default_semantic_model()

    def test_reads_every_column_and_type_in_database_order(self):
        data = build_schema_diagram_data(self.model, self.connection)
        invoices = next(table for table in data["tables"] if table["id"] == "invoices")
        self.assertEqual(invoices["columns"], [
            {"name": "invoice_id", "type": "INTEGER"},
            {"name": "company_id", "type": "INTEGER"},
            {"name": "amount", "type": "DECIMAL(12,2)"},
        ])
        companies = next(table for table in data["tables"] if table["id"] == "companies")
        self.assertEqual([column["name"] for column in companies["columns"]], ["company_id", "company_name", "city"])
        self.assertEqual(companies["join_columns"], ["company_id"])
        self.assertEqual(data["hub"], "companies")
        self.assertEqual(len({table["id"] for table in data["tables"]}), 3)

    def test_preserves_relationship_direction_cardinality_and_model(self):
        self.model["relationships"][0]["from_table"] = "invoices"
        self.model["relationships"][0]["to_table"] = "companies"
        self.model["relationships"][0]["cardinality"] = "N:1"
        before = deepcopy(self.model)
        data = build_schema_diagram_data(self.model, self.connection)
        self.assertEqual(data["relationships"][0]["from_table"], "invoices")
        self.assertEqual(data["relationships"][0]["to_table"], "companies")
        self.assertEqual(data["relationships"][0]["cardinality"], "N:1")
        self.assertEqual(self.model, before)

    def test_disconnected_tables_are_included_and_hub_ties_are_stable(self):
        self.model["relationships"] = []
        data = build_schema_diagram_data(self.model, self.connection)
        self.assertEqual(len(data["tables"]), 3)
        self.assertEqual(data["relationships"], [])
        self.assertEqual(data["hub"], "companies")

    def test_added_cross_table_and_parallel_relationships_are_not_lost(self):
        self.model["relationships"].extend([
            {
                "from_table": "invoices", "from_column": "company_id",
                "to_table": "opportunities", "to_column": "company_id", "cardinality": "N:M",
            },
            {
                "from_table": "companies", "from_column": "company_id",
                "to_table": "invoices", "to_column": "company_id", "cardinality": "1:1",
            },
        ])
        data = build_schema_diagram_data(self.model, self.connection)
        self.assertEqual(len(data["relationships"]), 4)
        self.assertEqual(len(data["tables"]), 3)
        self.assertEqual(data["relationships"][2]["cardinality"], "N:M")
        self.assertEqual(data["relationships"][3]["cardinality"], "1:1")

    def test_unavailable_metadata_and_dangling_edges_are_explicit(self):
        self.connection.execute("DROP TABLE invoices")
        self.model["relationships"].append({
            "from_table": "missing", "to_table": "companies",
            "from_column": "id", "to_column": "company_id",
        })
        data = build_schema_diagram_data(self.model, self.connection, "cs")
        invoices = next(table for table in data["tables"] if table["id"] == "invoices")
        self.assertTrue(invoices["error"])
        self.assertEqual(invoices["columns"], [])
        self.assertEqual(len(data["relationships"]), 2)
        self.assertIn("missing", data["issues"][0])

    def test_table_names_are_bound_not_interpolated(self):
        self.connection.execute('CREATE TABLE "strange; name" ("a""b" VARCHAR)')
        self.model["tables"].append({
            "technical_name": "strange; name", "name": "<custom table>",
        })
        data = build_schema_diagram_data(self.model, self.connection)
        custom = data["tables"][-1]
        self.assertIsNone(custom["error"])
        self.assertEqual(custom["columns"], [{"name": 'a"b', "type": "VARCHAR"}])

    def test_empty_model(self):
        data = build_schema_diagram_data({"tables": [], "relationships": []}, self.connection)
        self.assertIsNone(data["hub"])
        self.assertEqual(data["tables"], [])


if __name__ == "__main__":
    unittest.main()
