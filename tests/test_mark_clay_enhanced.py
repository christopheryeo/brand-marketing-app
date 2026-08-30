import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("mark_clay_enhanced", SCRIPTS / "mark_clay_enhanced.py")
MARKER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MARKER)


class MarkClayEnhancedTests(unittest.TestCase):
    def test_records_date_preserves_body_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            people = root / "entities" / "people"
            people.mkdir(parents=True)
            person_id = "person-test-example-com-abc123"
            data = {
                "entityType": "person", "personId": person_id, "displayName": "Test Person",
                "createdAt": "2026-08-20T00:00:00+08:00", "updatedAt": "2026-08-20T00:00:00+08:00",
                "clayEnhanced": None, "ToEnhance": None,
                "aliases": [], "tags": [], "confidence": 1.0, "sourceRefs": [],
            }
            path = people / f"{person_id}.md"
            path.write_text(
                "---\n" + json.dumps(data, indent=2) + "\n---\n\n# Test Person\n\n## Summary\n\nKeep this body.\n",
                encoding="utf-8",
            )

            first = MARKER.record_clay_enhancement(
                person_id, "2026-08-27", root=root, timestamp="2026-08-27T20:00:00+08:00"
            )
            second = MARKER.record_clay_enhancement(
                person_id, "2026-08-27", root=root, timestamp="2026-08-27T20:01:00+08:00"
            )

            stored = MARKER.frontmatter(path)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(stored["clayEnhanced"], "2026-08-27")
            self.assertEqual(stored["updatedAt"], "2026-08-27T20:00:00+08:00")
            self.assertIsNone(stored["ToEnhance"])
            self.assertIn("Keep this body.", path.read_text(encoding="utf-8"))
            log = (people / "log.md").read_text(encoding="utf-8")
            self.assertEqual(log.count("recorded successful Clay enhancement"), 1)

    def test_rejects_invalid_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                MARKER.record_clay_enhancement("person-test-example-com-abc123", "2026-02-30", root=Path(tmp))


if __name__ == "__main__":
    unittest.main()
