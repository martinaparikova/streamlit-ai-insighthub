import unittest

from ontology import answer_knowledge_question, default_semantic_model, draft_preview, normalize_semantic_model, upsert_item, validate_relationship


class OntologyTests(unittest.TestCase):
    def setUp(self):
        self.model = default_semantic_model()

    def test_answers_table_question_without_sql(self):
        answer = answer_knowledge_question("Jaké tabulky jsou v modelu?", self.model)

        self.assertEqual(answer["title"], "Tabulky v ontologii")
        self.assertIn("`companies`", answer["content"])
        self.assertIn("`invoices`", answer["content"])

    def test_english_knowledge_answer_uses_english_ui_copy(self):
        answer = answer_knowledge_question("What tables are in the model?", self.model, "en")

        self.assertEqual(answer["title"], "Tables in the ontology")
        self.assertIn("The model contains 3 tables", answer["content"])
        self.assertIn("**Companies**", answer["content"])
        self.assertNotIn("**Firmy**", answer["content"])

    def test_english_metric_definition_uses_english_default_content(self):
        answer = answer_knowledge_question("What is the pipeline value metric?", self.model, "en")

        self.assertEqual(answer["title"], "Metric definition: Pipeline value")
        self.assertIn("Sum of open sales-opportunity values by stage.", answer["content"])
        self.assertNotIn("Hodnota pipeline", answer["content"])

    def test_answers_revenue_definition(self):
        answer = answer_knowledge_question("Jak se počítá revenue?", self.model)

        self.assertEqual(answer["title"], "Definice metriky: Revenue")
        self.assertIn("SUM(invoices.net_amount_czk)", answer["content"])

    def test_answers_overdue_rule(self):
        answer = answer_knowledge_question("Jak se určuje faktura po splatnosti?", self.model)

        self.assertIn("payment_status = 'Overdue'", answer["content"])

    def test_draft_preview_uses_the_selected_language(self):
        self.assertIn("AI draft is available in phase 1", draft_preview(self.model, "en"))
        self.assertNotIn("AI draft je ve fázi 1", draft_preview(self.model, "en"))
        self.assertIn("AI draft je ve fázi 1", draft_preview(self.model, "cs"))

    def test_upsert_metric_creates_normalized_draft(self):
        updated = upsert_item(self.model, "metrics", {
            "name": "Average invoice", "description": "Průměrná netto hodnota faktury.",
            "formula": "AVG(invoices.net_amount_czk)", "entity": "invoices",
        })
        metric = next(item for item in updated["metrics"] if item["name"] == "Average invoice")

        self.assertEqual(metric["status"], "draft")
        self.assertEqual(normalize_semantic_model(updated), updated)

    def test_relationship_validation_requires_known_distinct_tables_and_columns(self):
        valid = {
            "from_table": "companies", "from_column": "company_id",
            "to_table": "invoices", "to_column": "company_id",
        }
        self.assertTrue(validate_relationship(self.model, valid))

        with self.assertRaises(ValueError):
            validate_relationship(self.model, {**valid, "to_table": "missing"})
        with self.assertRaises(ValueError):
            validate_relationship(self.model, {**valid, "to_table": "companies"})
        with self.assertRaises(ValueError):
            validate_relationship(self.model, {**valid, "to_column": ""})

    def test_upsert_relationship_preserves_a_new_draft(self):
        relationship = {
            "name": "Faktury → Příležitosti", "description": "Propojení přes firmu.",
            "from_table": "invoices", "from_column": "company_id",
            "to_table": "opportunities", "to_column": "company_id", "cardinality": "N:M", "status": "draft",
        }
        self.assertTrue(validate_relationship(self.model, relationship))
        updated = upsert_item(self.model, "relationships", relationship)
        stored = next(item for item in updated["relationships"] if item["name"] == relationship["name"])

        self.assertEqual(stored["status"], "draft")
        self.assertEqual(stored["from_table"], "invoices")


if __name__ == "__main__":
    unittest.main()