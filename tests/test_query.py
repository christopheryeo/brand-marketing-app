import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ib_query", ROOT / "scripts" / "query.py")
query = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(query)


class MarkdownQueryTests(unittest.TestCase):
    def test_catalog_parser_uses_generated_id_name_file_columns(self):
        columns, rows = query.parse_catalog("organisations")
        self.assertEqual(columns[:3], ["ID", "Name", "File"])
        ident, label, file = query._row_identity(rows[0])
        self.assertTrue(ident.startswith("organisation-"))
        self.assertTrue(label)
        self.assertTrue(file.endswith(".md"))

    def test_exact_resolution_distinguishes_brand_and_organisation(self):
        result = query.tool_resolve_entity("UOB", ["brands", "organisations"])
        identities = {(item["domain"], item["id"]) for item in result["matches"]}
        self.assertIn(("brands", "brand-uob-a508cdd695"), identities)
        self.assertIn(("organisations", "organisation-uob-a508cdd695"), identities)

    def test_relationships_are_derived_from_canonical_frontmatter(self):
        result = query.tool_related_entity("organisation-uob-a508cdd695")
        people = {
            item["fromId"] for item in result["relationships"]
            if item["direction"] == "inbound" and item["relatedDomain"] == "people"
        }
        self.assertIn("person-jeremy-leezh-uobgroup-com-ff4c5dd528", people)
        self.assertEqual(result["entityName"], "UOB")

    def test_search_is_scoped_to_canonical_domains(self):
        result = query.tool_search_entities(
            "Top Employer Award", ["sales-opportunities", "marketing-campaigns"], 10
        )
        self.assertGreater(result["match_count"], 0)
        self.assertTrue(all(item["domain"] in {
            "sales-opportunities", "marketing-campaigns"
        } for item in result["matches"]))

    def test_search_finds_people_flagged_to_enhance(self):
        original_root = query.ROOT
        original_entities = query.ENTITIES
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                people = root / "entities" / "people"
                people.mkdir(parents=True)
                data = {
                    "entityType": "person",
                    "personId": "person-needs-enhancement",
                    "displayName": "Needs Enhancement",
                    "ToEnhance": True,
                }
                (people / "person-needs-enhancement.md").write_text(
                    f"---\n{json.dumps(data)}\n---\n\n# Needs Enhancement\n",
                    encoding="utf-8",
                )
                false_positive = {
                    "entityType": "person",
                    "personId": "person-url-contains-true",
                    "displayName": "URL Contains True",
                    "linkedInUrl": "https://example.com/profile?skipRedirect=true",
                }
                (people / "person-url-contains-true.md").write_text(
                    f"---\n{json.dumps(false_positive)}\n---\n\n# URL Contains True\n",
                    encoding="utf-8",
                )
                for value, suffix in ((False, "false"), (None, "null")):
                    item = {
                        "entityType": "person",
                        "personId": f"person-to-enhance-{suffix}",
                        "displayName": f"ToEnhance {suffix}",
                        "ToEnhance": value,
                    }
                    (people / f"person-to-enhance-{suffix}.md").write_text(
                        f"---\n{json.dumps(item)}\n---\n\n# ToEnhance {suffix}\n",
                        encoding="utf-8",
                    )
                query.ROOT = root
                query.ENTITIES = root / "entities"
                query._RECORD_CACHE = None
                query._RECORD_BY_ID = None
                result = query.tool_search_entities("ToEnhance true", ["people"], 10)
                self.assertEqual(result["match_count"], 1)
                self.assertEqual(result["matches"][0]["id"], "person-needs-enhancement")
                false_result = query.tool_search_entities("ToEnhance false", ["people"], 10)
                self.assertEqual(false_result["match_count"], 1)
                self.assertEqual(false_result["matches"][0]["id"], "person-to-enhance-false")
                null_result = query.tool_search_entities("ToEnhance null", ["people"], 10)
                self.assertEqual(null_result["match_count"], 1)
                self.assertEqual(null_result["matches"][0]["id"], "person-to-enhance-null")
        finally:
            query.ROOT = original_root
            query.ENTITIES = original_entities
            query._RECORD_CACHE = None
            query._RECORD_BY_ID = None

    def test_search_filters_clay_enhanced_null_and_date_exactly(self):
        original_root = query.ROOT
        original_entities = query.ENTITIES
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                people = root / "entities" / "people"
                people.mkdir(parents=True)
                fixtures = [
                    ("person-clay-null", None, "No verified enhancement"),
                    ("person-clay-date", "2026-08-28", "Verified enhancement"),
                    ("person-unrelated-date", ..., "Mentioned 2026-08-28 elsewhere"),
                ]
                for person_id, value, body in fixtures:
                    data = {
                        "entityType": "person",
                        "personId": person_id,
                        "displayName": person_id,
                    }
                    if value is not ...:
                        data["clayEnhanced"] = value
                    (people / f"{person_id}.md").write_text(
                        f"---\n{json.dumps(data)}\n---\n\n# {person_id}\n\n{body}\n",
                        encoding="utf-8",
                    )
                query.ROOT = root
                query.ENTITIES = root / "entities"
                query._RECORD_CACHE = None
                query._RECORD_BY_ID = None

                null_result = query.tool_search_entities("clayEnhanced null", ["people"], 10)
                self.assertEqual(null_result["match_count"], 1)
                self.assertEqual(null_result["matches"][0]["id"], "person-clay-null")
                date_result = query.tool_search_entities(
                    "clayEnhanced 2026-08-28", ["people"], 10
                )
                self.assertEqual(date_result["match_count"], 1)
                self.assertEqual(date_result["matches"][0]["id"], "person-clay-date")
        finally:
            query.ROOT = original_root
            query.ENTITIES = original_entities
            query._RECORD_CACHE = None
            query._RECORD_BY_ID = None

    def test_structured_outcomes_are_queryable(self):
        result = query.tool_business_outcomes(text="follow", limit=10)
        self.assertGreater(result["total"], 0)
        self.assertTrue(all("outcome" in item for item in result["outcomes"]))

    def test_query_runtime_has_no_generated_database_dependency(self):
        source = (ROOT / "scripts" / "query.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("sqlite", source)
        self.assertNotIn("wiki.db", source)
        self.assertNotIn("wiki.sqlite", source)

    def test_decision_catalog_retains_canonical_identity(self):
        _, rows = query.parse_catalog("decisions")
        identities = {query._row_identity(row)[0] for row in rows}
        self.assertIn("decision-query-py-first-for-wiki-queries-2026-08-11", identities)


if __name__ == "__main__":
    unittest.main()
