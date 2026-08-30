import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "backfill_to_enhance", SCRIPTS / "backfill_to_enhance.py"
)
MIGRATION = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MIGRATION)


class BackfillToEnhanceTests(unittest.TestCase):
    def _write_person(self, people: Path, person_id: str, value=...):
        data = {
            "entityType": "person",
            "personId": person_id,
            "displayName": person_id,
            "createdAt": "2026-08-28T00:00:00+08:00",
            "updatedAt": "2026-08-28T00:00:00+08:00",
            "aliases": [],
            "tags": [],
            "confidence": 1.0,
            "sourceRefs": [],
        }
        if value is not ...:
            data["ToEnhance"] = value
        path = people / f"{person_id}.md"
        path.write_text(
            "---\n" + json.dumps(data, indent=2) + "\n---\n\n# Person\n\nKeep body.\n",
            encoding="utf-8",
        )
        return path

    def test_backfills_missing_preserves_existing_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            people = root / "entities" / "people"
            people.mkdir(parents=True)
            missing = self._write_person(people, "person-missing")
            existing = self._write_person(people, "person-existing", True)
            missing_body = MIGRATION._parse(missing.read_text(), missing)[1]
            existing_body = MIGRATION._parse(existing.read_text(), existing)[1]

            first = MIGRATION.backfill_to_enhance(
                root=root,
                run_id="first",
                backup_dir=root / "tmp" / "backup-first",
            )
            second = MIGRATION.backfill_to_enhance(
                root=root,
                run_id="second",
                backup_dir=root / "tmp" / "backup-second",
            )

            self.assertEqual(first["personCount"], 2)
            self.assertEqual(first["recordsChanged"], 1)
            self.assertEqual(first["values"], {"true": 1, "false": 0, "null": 1})
            self.assertEqual(second["recordsChanged"], 0)
            self.assertIsNone(MIGRATION._parse(missing.read_text(), missing)[0]["ToEnhance"])
            self.assertIs(MIGRATION._parse(existing.read_text(), existing)[0]["ToEnhance"], True)
            self.assertEqual(MIGRATION._parse(missing.read_text(), missing)[1], missing_body)
            self.assertEqual(MIGRATION._parse(existing.read_text(), existing)[1], existing_body)

    def test_invalid_existing_value_stops_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            people = root / "entities" / "people"
            people.mkdir(parents=True)
            missing = self._write_person(people, "person-missing")
            invalid = self._write_person(people, "person-invalid", "yes")
            before = missing.read_text(encoding="utf-8")
            with self.assertRaises(ValueError):
                MIGRATION.backfill_to_enhance(
                    root=root,
                    run_id="invalid",
                    backup_dir=root / "tmp" / "backup-invalid",
                )
            self.assertEqual(missing.read_text(encoding="utf-8"), before)
            self.assertFalse((root / "tmp" / "backup-invalid").exists())
            self.assertIn('"ToEnhance": "yes"', invalid.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
