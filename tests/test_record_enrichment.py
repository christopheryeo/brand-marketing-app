import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("record_enrichment", ROOT / "scripts" / "record_enrichment.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RecordEnrichmentTests(unittest.TestCase):
    def _person(self, root: Path, flag=True):
        people = root / "entities" / "people"
        people.mkdir(parents=True)
        person_id = "person-test-example-com-abc123"
        data = {
            "entityType": "person", "personId": person_id, "displayName": "Test Person",
            "createdAt": "2026-08-20T00:00:00+08:00", "updatedAt": "2026-08-20T00:00:00+08:00",
            "ToEnhance": flag, "clayEnhanced": None, "aliases": [], "tags": [],
            "confidence": 1.0, "sourceRefs": [],
        }
        (people / f"{person_id}.md").write_text(
            "---\n" + json.dumps(data, indent=2) + "\n---\n\n# Test Person\n\n## Summary\n",
            encoding="utf-8",
        )
        (people / "log.md").write_text("# Log: People\n", encoding="utf-8")
        return person_id, people / f"{person_id}.md"

    def test_linkedin_records_provider_date_and_clears_only_complete_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            person_id, path = self._person(Path(tmp))
            result = MODULE.record_enrichment(
                person_id, "linkedin", "2026-09-02",
                {"linkedInUrl": "https://linkedin.com/in/test", "jobTitle": "Director"},
                root=Path(tmp), timestamp="2026-09-02T10:00:00+08:00",
            )
            stored = MODULE.frontmatter(path)
            self.assertTrue(result["minimumProfile"])
            self.assertFalse(stored["ToEnhance"])
            self.assertEqual(stored["enrichmentProvider"], "linkedin")
            self.assertEqual(stored["enrichmentDate"], "2026-09-02")
            self.assertIsNone(stored["clayEnhanced"])

    def test_incomplete_linkedin_result_does_not_clear_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            person_id, path = self._person(Path(tmp))
            result = MODULE.record_enrichment(
                person_id, "linkedin", "2026-09-02", {"linkedInUrl": "https://linkedin.com/in/test"}, root=Path(tmp)
            )
            self.assertFalse(result["minimumProfile"])
            self.assertTrue(MODULE.frontmatter(path)["ToEnhance"])


if __name__ == "__main__":
    unittest.main()
