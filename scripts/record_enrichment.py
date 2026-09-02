#!/usr/bin/env python3
"""Record a verified Person enrichment from Clay or LinkedIn.

This is deliberately a writeback utility: provider connectors perform the
lookup, then call this script only after a verified successful result.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from wiki_pipeline import SGT, frontmatter, now_sgt, validate_to_enhance


ROOT = Path(__file__).resolve().parents[1]
PERSON_ID_RE = re.compile(r"person-[a-z0-9-]+")
FRONTMATTER_RE = re.compile(r"---\s*\n(.*?)\n---", flags=re.S)
PROVIDERS = {"clay", "linkedin"}


def _validate_date(value: str) -> None:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("enrichmentDate must use YYYY-MM-DD format") from error
    if parsed.isoformat() != value:
        raise ValueError("enrichmentDate must use YYYY-MM-DD format")


def _replace_frontmatter(path: Path, data: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"missing-frontmatter: {path}")
    updated = text[:match.start(1)] + json.dumps(data, ensure_ascii=False, indent=2) + text[match.end(1):]
    temp = path.with_suffix(".md.enrichment.tmp")
    temp.write_text(updated, encoding="utf-8")
    temp.replace(path)


def _minimum_profile(provider: str, data: dict[str, Any]) -> bool:
    """Return whether this result supplies the minimum useful profile."""
    if provider == "clay":
        return any(data.get(key) for key in ("primaryEmail", "phone", "mobilePhone", "linkedInUrl"))
    return bool(data.get("linkedInUrl")) and any(
        data.get(key) for key in ("jobTitle", "company", "organisation", "professionalHistory", "currentRole")
    )


def record_enrichment(
    person_id: str,
    provider: str,
    enrichment_date: str,
    profile: dict[str, Any] | None = None,
    *,
    root: Path = ROOT,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if not PERSON_ID_RE.fullmatch(person_id):
        raise ValueError("personId must be a canonical person-* identifier")
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError("provider must be clay or linkedin")
    _validate_date(enrichment_date)
    profile = profile or {}
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")

    path = root / "entities" / "people" / f"{person_id}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Person record not found: {person_id}")
    data = frontmatter(path)
    if data.get("entityType") != "person" or data.get("personId") != person_id:
        raise ValueError(f"Person identity mismatch: {path}")

    previous_provider = data.get("enrichmentProvider")
    previous_date = data.get("enrichmentDate")
    data.update(profile)
    data["enrichmentProvider"] = provider
    data["enrichmentDate"] = enrichment_date
    if provider == "clay":
        # Keep the legacy field for older consumers; the generic fields are canonical.
        data["clayEnhanced"] = enrichment_date
    complete = _minimum_profile(provider, data)
    previous_flag = data.get("ToEnhance")
    if complete:
        data["ToEnhance"] = False
    validate_to_enhance(data.get("ToEnhance"))

    changed_at = timestamp or now_sgt()
    data["updatedAt"] = changed_at
    _replace_frontmatter(path, data)
    log_path = root / "entities" / "people" / "log.md"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n- {changed_at} | action: recorded successful {provider} enrichment | "
            f"entity: [[{person_id}]] | enrichmentProvider: {provider} | "
            f"enrichmentDate: {enrichment_date} | minimumProfile: {str(complete).lower()}\n"
        )
    return {
        "personId": person_id,
        "enrichmentProvider": provider,
        "enrichmentDate": enrichment_date,
        "minimumProfile": complete,
        "previousToEnhance": previous_flag,
        "ToEnhance": data.get("ToEnhance"),
        "previousEnrichmentProvider": previous_provider,
        "previousEnrichmentDate": previous_date,
        "updatedAt": changed_at,
        "path": str(path.relative_to(root)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a verified Clay or LinkedIn Person enrichment.")
    parser.add_argument("person_id")
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--date", required=True, dest="enrichment_date")
    parser.add_argument("--field", action="append", default=[], metavar="NAME=VALUE",
                        help="Optional profile field; repeat for multiple fields")
    args = parser.parse_args()
    profile: dict[str, Any] = {}
    for item in args.field:
        if "=" not in item:
            parser.error("--field must be NAME=VALUE")
        key, value = item.split("=", 1)
        if not key:
            parser.error("--field name cannot be empty")
        try:
            profile[key] = json.loads(value)
        except json.JSONDecodeError:
            profile[key] = value
    try:
        print(json.dumps({"status": "ok", **record_enrichment(
            args.person_id, args.provider, args.enrichment_date, profile)}, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
