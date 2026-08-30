import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import tempfile

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "wiki_pipeline.py"
SPEC = importlib.util.spec_from_file_location("wiki_pipeline", MODULE_PATH)
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class PipelineTests(unittest.TestCase):
    def test_normalize_email(self):
        self.assertEqual(PIPELINE.normalize_email(" MAILTO:Person@Example.COM; ")[0], "person@example.com")

    def test_invalid_email_is_not_invented(self):
        self.assertIsNone(PIPELINE.normalize_email("person at example dot com")[0])

    def test_stable_ids(self):
        self.assertEqual(PIPELINE.stable_id("person", "A@Example.com"), PIPELINE.stable_id("person", "a@example.COM"))

    def test_placeholders(self):
        self.assertIsNone(PIPELINE.null_if_placeholder("Not Applicable"))

    def test_role_mailbox(self):
        self.assertTrue(PIPELINE.is_role_mailbox("marketing@example.com"))
        self.assertFalse(PIPELINE.is_role_mailbox("christopher@example.com"))

    def test_clay_enhanced_date_validation(self):
        PIPELINE.validate_clay_enhanced_date(None)
        PIPELINE.validate_clay_enhanced_date("2026-08-27")
        for invalid in (False, "2026-8-27", "2026-02-30", "2026-08-27T12:00:00+08:00"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                PIPELINE.validate_clay_enhanced_date(invalid)

    def test_to_enhance_validation(self):
        PIPELINE.validate_to_enhance(None)
        PIPELINE.validate_to_enhance(True)
        PIPELINE.validate_to_enhance(False)
        for invalid in (0, 1, "true", "false", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                PIPELINE.validate_to_enhance(invalid)

    def test_person_rewrite_preserves_enrichment_fields(self):
        original_root = PIPELINE.ROOT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                PIPELINE.ROOT = Path(tmp)
                base = {
                    "entityType": "person", "personId": "person-test", "displayName": "Test Person",
                    "createdAt": "2026-08-27T00:00:00+08:00", "updatedAt": "2026-08-27T00:00:00+08:00",
                    "aliases": [], "tags": [], "confidence": 1.0, "sourceRefs": [],
                }
                PIPELINE.write_entity(
                    "person", base | {"clayEnhanced": "2026-08-27", "ToEnhance": True}
                )
                PIPELINE.write_entity("person", base | {"updatedAt": "2026-08-28T00:00:00+08:00"})
                stored = PIPELINE.frontmatter(PIPELINE.ROOT / "entities" / "people" / "person-test.md")
                self.assertEqual(stored["clayEnhanced"], "2026-08-27")
                self.assertIs(stored["ToEnhance"], True)

                new_person = base | {"personId": "person-new", "displayName": "New Person"}
                PIPELINE.write_entity("person", new_person)
                created = PIPELINE.frontmatter(
                    PIPELINE.ROOT / "entities" / "people" / "person-new.md"
                )
                self.assertIn("ToEnhance", created)
                self.assertIsNone(created["ToEnhance"])
                self.assertIn("clayEnhanced", created)
                self.assertIsNone(created["clayEnhanced"])
        finally:
            PIPELINE.ROOT = original_root

    def test_schema_regeneration_retains_clay_enhanced(self):
        original_root = PIPELINE.ROOT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                PIPELINE.ROOT = Path(tmp)
                domains = {directory for directory, _, _ in PIPELINE.ENTITY_CONFIG.values()} | {"decisions", "search"}
                for domain in domains:
                    directory = PIPELINE.ROOT / "entities" / domain
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "index.md").write_text(
                        "---\nlast_updated: 2026-08-07\n---\n\n## Production record requirements\n\nOld\n\n## System files\n",
                        encoding="utf-8",
                    )
                (PIPELINE.ROOT / "schemas").mkdir()
                PIPELINE.generate_schemas_and_indexes()
                schema = json.loads((PIPELINE.ROOT / "schemas" / "person.schema.json").read_text(encoding="utf-8"))
                self.assertEqual(schema["properties"]["clayEnhanced"]["format"], "date")
                self.assertEqual(schema["properties"]["clayEnhanced"]["type"], ["string", "null"])
                self.assertIn("clayEnhanced", schema["required"])
                self.assertEqual(schema["properties"]["ToEnhance"]["type"], ["boolean", "null"])
                self.assertIn("ToEnhance", schema["required"])
                person_index = (PIPELINE.ROOT / "entities" / "people" / "index.md").read_text(encoding="utf-8")
                self.assertIn("`clayEnhanced`", person_index)
                self.assertIn('"clayEnhanced":null', person_index)
                self.assertIn("`ToEnhance`", person_index)
                self.assertIn('"ToEnhance":null', person_index)
        finally:
            PIPELINE.ROOT = original_root

    def test_people_directory_exposes_enrichment_fields(self):
        root = Path(__file__).resolve().parents[1]
        builder = (root / "scripts" / "people-directory" / "build_people_directory.py").read_text(encoding="utf-8")
        template = (root / "scripts" / "people-directory" / "template.html").read_text(encoding="utf-8")
        self.assertIn("Path(__file__).resolve().parents[2]", builder)
        self.assertIn("os.makedirs(os.path.dirname(OUT), exist_ok=True)", builder)
        self.assertIn('"clayEnhanced": fm.get("clayEnhanced")', builder)
        self.assertIn('"ToEnhance": fm.get("ToEnhance")', builder)
        self.assertIn("field('Clay Enhanced', esc(fmtDate(p.clayEnhanced)))", template)
        self.assertIn("field('To Enhance', p.ToEnhance==null?'—':(p.ToEnhance?'Yes':'No'))", template)

    def test_static_app_builders_are_portable(self):
        root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "scripts/people-directory/build_people_directory.py",
            "scripts/wiki-browser/build_wiki.py",
        ):
            builder = (root / relative_path).read_text(encoding="utf-8")
            self.assertIn("Path(__file__).resolve().parents[2]", builder)
            self.assertIn("os.makedirs(os.path.dirname(OUT), exist_ok=True)", builder)
            self.assertNotIn("Customer Folders/influential-brands", builder)

    def test_message_folder_policy_and_addresses(self):
        xml = b"""<emails><email>
        <OPFMessageCopyMessageID>&lt;id@example.com&gt;</OPFMessageCopyMessageID>
        <OPFMessageCopySubject>Test</OPFMessageCopySubject>
        <OPFMessageCopyFromAddresses><emailAddress OPFContactEmailAddressAddress="sender@example.com" OPFContactEmailAddressName="Sender"/></OPFMessageCopyFromAddresses>
        <OPFMessageCopyToAddresses><emailAddress OPFContactEmailAddressAddress="receiver@example.com" OPFContactEmailAddressName="Receiver"/></OPFMessageCopyToAddresses>
        </email></emails>"""
        inbox = PIPELINE.parse_olm_message(xml, "Accounts/a@example.com/com.microsoft.__Messages/INBOX/message_00001.xml", "source")
        trash = PIPELINE.parse_olm_message(xml, "Accounts/a@example.com/com.microsoft.__Messages/INBOX/Trash/message_00001.xml", "source")
        self.assertTrue(inbox["eligible"])
        self.assertFalse(trash["eligible"])
        self.assertEqual(inbox["from"][0]["email"], "sender@example.com")

    def test_attachment_text_extraction(self):
        text, status, error = PIPELINE.safe_attachment_text("sample.txt", b"hello")
        self.assertEqual((text, status, error), ("hello", "extracted", None))

    def test_unsupported_attachment_is_quarantined(self):
        _, status, error = PIPELINE.safe_attachment_text("sample.bin", b"\x00\x01")
        self.assertEqual(status, "quarantined")
        self.assertTrue(error)

    def test_semantic_candidate_publishes_only_allowed_entity(self):
        original_root = PIPELINE.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            PIPELINE.ROOT = Path(tmp)
            for directory, _, _ in PIPELINE.ENTITY_CONFIG.values():
                (PIPELINE.ROOT / "entities" / directory).mkdir(parents=True, exist_ok=True)
            candidate = {
                "entityType": "topic", "name": "Responsible Leadership", "attributes": {"description": "Explicit topic"},
                "relationships": [], "outcomes": [], "confidence": 0.95,
                "sourceRef": PIPELINE.source_ref("source-id", "message.xml"), "evidenceHash": "abc",
                "provider": "test", "model": "test",
            }
            result = PIPELINE.publish_semantic_candidates("run", [candidate])
            self.assertEqual(result["publishedEntities"], 1)
            self.assertEqual(len(list((PIPELINE.ROOT / "entities" / "topics").glob("*.md"))), 1)
        PIPELINE.ROOT = original_root


if __name__ == "__main__":
    unittest.main()
