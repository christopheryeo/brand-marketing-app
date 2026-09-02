#!/usr/bin/env python3
"""Record a verified successful Clay enhancement on one canonical Person."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from wiki_pipeline import SGT, frontmatter, now_sgt, validate_clay_enhanced_date


ROOT = Path(__file__).resolve().parents[1]
PERSON_ID_RE = re.compile(r"person-[a-z0-9-]+")
FRONTMATTER_RE = re.compile(r"---\s*\n(.*?)\n---", flags=re.S)


def _replace_frontmatter(path: Path, data: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"missing-frontmatter: {path}")
    updated = text[:match.start(1)] + json.dumps(data, ensure_ascii=False, indent=2) + text[match.end(1):]
    temp = path.with_suffix(".md.tmp")
    temp.write_text(updated, encoding="utf-8")
    temp.replace(path)


def record_clay_enhancement(
    person_id: str,
    enhanced_date: str | None = None,
    *,
    root: Path = ROOT,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if not PERSON_ID_RE.fullmatch(person_id):
        raise ValueError("personId must be a canonical person-* identifier")
    date_value = enhanced_date or dt.datetime.now(SGT).date().isoformat()
    validate_clay_enhanced_date(date_value)

    path = root / "entities" / "people" / f"{person_id}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Person record not found: {person_id}")
    data = frontmatter(path)
    if data.get("entityType") != "person" or data.get("personId") != person_id:
        raise ValueError(f"Person identity mismatch: {path}")

    previous = data.get("clayEnhanced")
    if previous == date_value:
        return {
            "personId": person_id,
            "clayEnhanced": date_value,
            "changed": False,
            "path": str(path.relative_to(root)),
        }

    changed_at = timestamp or now_sgt()
    data["clayEnhanced"] = date_value
    # Generic fields are canonical; clayEnhanced remains for older consumers.
    data["enrichmentProvider"] = "clay"
    data["enrichmentDate"] = date_value
    data["updatedAt"] = changed_at
    _replace_frontmatter(path, data)

    log_path = root / "entities" / "people" / "log.md"
    if not log_path.exists():
        log_path.write_text(
            "# Log: People\n\nAppend-only audit ledger. Never edit or delete prior entries; correct forward with a new entry.\n",
            encoding="utf-8",
        )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n- {changed_at} | action: recorded successful Clay enhancement | "
            f"entity: [[{person_id}]] | clayEnhanced: {date_value} | "
            f"enrichmentProvider: clay | enrichmentDate: {date_value} | source: Clay connector\n"
        )

    return {
        "personId": person_id,
        "previousClayEnhanced": previous,
        "clayEnhanced": date_value,
        "changed": True,
        "updatedAt": changed_at,
        "path": str(path.relative_to(root)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record the date of a verified successful Clay connector enhancement."
    )
    parser.add_argument("person_id", help="Canonical Person ID, for example person-name-example-com-abc123")
    parser.add_argument("--date", dest="enhanced_date", help="Verified enhancement date in YYYY-MM-DD; defaults to today in SGT")
    args = parser.parse_args()
    try:
        result = record_clay_enhancement(args.person_id, args.enhanced_date)
    except Exception as error:
        print(json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 1
    print(json.dumps({"status": "ok", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
