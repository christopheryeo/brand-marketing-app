#!/usr/bin/env python3
"""Set the ToEnhance flag on one canonical Person record.

Mirrors mark_clay_enhanced.py's safe-writeback pattern: validates the value,
rewrites only the frontmatter (temp file + atomic replace), bumps updatedAt, and
appends an audit line to entities/people/log.md. Importable by the People
Directory server so the "To Enhance" checkbox can persist to the vault.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from wiki_pipeline import frontmatter, now_sgt, validate_to_enhance


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


def _person_path(person_id: str, root: Path) -> Path:
    if not PERSON_ID_RE.fullmatch(person_id):
        raise ValueError("personId must be a canonical person-* identifier")
    path = root / "entities" / "people" / f"{person_id}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Person record not found: {person_id}")
    return path


def read_to_enhance(person_id: str, *, root: Path = ROOT) -> Any:
    """Return the current ToEnhance value (True / False / None) for one Person."""
    return frontmatter(_person_path(person_id, root)).get("ToEnhance")


def set_to_enhance(
    person_id: str,
    value: Any,
    *,
    root: Path = ROOT,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Set ToEnhance (True/False/None) on one canonical Person record."""
    validate_to_enhance(value)
    path = _person_path(person_id, root)
    data = frontmatter(path)
    if data.get("entityType") != "person" or data.get("personId") != person_id:
        raise ValueError(f"Person identity mismatch: {path}")

    previous = data.get("ToEnhance")
    if previous == value and "ToEnhance" in data:
        return {
            "personId": person_id,
            "ToEnhance": value,
            "changed": False,
            "path": str(path.relative_to(root)),
        }

    changed_at = timestamp or now_sgt()
    data["ToEnhance"] = value
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
            f"\n- {changed_at} | action: set ToEnhance | entity: [[{person_id}]] | "
            f"ToEnhance: {json.dumps(value)} | source: People Directory checkbox\n"
        )

    return {
        "personId": person_id,
        "previousToEnhance": previous,
        "ToEnhance": value,
        "changed": True,
        "updatedAt": changed_at,
        "path": str(path.relative_to(root)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the ToEnhance flag on one canonical Person record.")
    parser.add_argument("person_id", help="Canonical Person ID, e.g. person-name-example-com-abc123")
    parser.add_argument("--value", required=True, choices=["true", "false", "null"],
                        help="true = needs enhancement, false = assessed and clear, null = not assessed")
    args = parser.parse_args()
    value = {"true": True, "false": False, "null": None}[args.value]
    try:
        result = set_to_enhance(args.person_id, value)
    except Exception as error:
        print(json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 1
    print(json.dumps({"status": "ok", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
