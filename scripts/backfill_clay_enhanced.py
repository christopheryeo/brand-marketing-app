#!/usr/bin/env python3
"""Add a nullable clayEnhanced field to every canonical Person record."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from wiki_pipeline import now_sgt, validate_clay_enhanced_date


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_FILES = {"index.md", "catalog.md", "log.md"}
FRONTMATTER_RE = re.compile(r"---\s*\n(.*?)\n---", flags=re.S)


def _parse(text: str, path: Path) -> tuple[dict[str, Any], str, re.Match[str]]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"missing-frontmatter: {path}")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid-json-frontmatter: {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"frontmatter-not-object: {path}")
    return data, text[match.end():], match


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def backfill_clay_enhanced(
    *,
    root: Path = ROOT,
    run_id: str,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    people_dir = root / "entities" / "people"
    paths = sorted(
        path for path in people_dir.glob("*.md")
        if path.name not in SYSTEM_FILES
    )
    if not paths:
        raise ValueError("no-person-records")

    prepared: list[dict[str, Any]] = []
    for path in paths:
        original = path.read_text(encoding="utf-8")
        data, body, match = _parse(original, path)
        if data.get("entityType") != "person":
            raise ValueError(f"entity-type-mismatch: {path}")
        if data.get("personId") != path.stem:
            raise ValueError(f"person-identity-mismatch: {path}")
        changed = "clayEnhanced" not in data
        if changed:
            updated_data = dict(data)
            updated_data["clayEnhanced"] = None
            updated = (
                original[:match.start(1)]
                + json.dumps(updated_data, ensure_ascii=False, indent=2)
                + original[match.end(1):]
            )
        else:
            updated_data = data
            updated = original
        validate_clay_enhanced_date(updated_data["clayEnhanced"])
        if {key: value for key, value in updated_data.items() if key != "clayEnhanced"} != {
            key: value for key, value in data.items() if key != "clayEnhanced"
        }:
            raise ValueError(f"unrelated-frontmatter-change: {path}")
        _, updated_body, _ = _parse(updated, path)
        if updated_body != body:
            raise ValueError(f"body-change-detected: {path}")
        prepared.append({
            "path": path,
            "original": original,
            "updated": updated,
            "changed": changed,
            "bodyHash": _sha256(body),
            "toEnhance": data.get("ToEnhance", object()),
        })

    changed_items = [item for item in prepared if item["changed"]]
    backup = backup_dir or root / "tmp" / f"clay-enhanced-backup-{run_id}"
    staged: list[Path] = []
    replaced: list[dict[str, Any]] = []
    try:
        if changed_items:
            if backup.exists():
                raise FileExistsError(f"backup-already-exists: {backup}")
            backup.mkdir(parents=True)
            for item in changed_items:
                path = item["path"]
                shutil.copy2(path, backup / path.name)
                stage = path.with_suffix(".md.clay-enhanced.tmp")
                stage.write_text(item["updated"], encoding="utf-8")
                staged.append(stage)

            for item, stage in zip(changed_items, staged):
                path = item["path"]
                if path.read_text(encoding="utf-8") != item["original"]:
                    raise RuntimeError(f"concurrent-change-detected: {path}")
                staged_data, staged_body, _ = _parse(stage.read_text(encoding="utf-8"), stage)
                if staged_data.get("clayEnhanced", object()) is not None:
                    raise ValueError(f"staged-value-not-null: {stage}")
                if staged_data.get("ToEnhance", object()) != item["toEnhance"]:
                    raise ValueError(f"staged-ToEnhance-change: {stage}")
                if _sha256(staged_body) != item["bodyHash"]:
                    raise ValueError(f"staged-body-change: {stage}")

            for item, stage in zip(changed_items, staged):
                stage.replace(item["path"])
                replaced.append(item)
    except Exception:
        for item in replaced:
            restore = item["path"].with_suffix(".md.restore.tmp")
            restore.write_text(item["original"], encoding="utf-8")
            restore.replace(item["path"])
        for stage in staged:
            if stage.exists():
                stage.unlink()
        raise

    values = {"date": 0, "null": 0}
    for item in prepared:
        path = item["path"]
        data, body, _ = _parse(path.read_text(encoding="utf-8"), path)
        if "clayEnhanced" not in data:
            raise ValueError(f"missing-clayEnhanced-after-migration: {path}")
        validate_clay_enhanced_date(data["clayEnhanced"])
        values["null" if data["clayEnhanced"] is None else "date"] += 1
        if data.get("ToEnhance", object()) != item["toEnhance"]:
            raise ValueError(f"ToEnhance-change-after-migration: {path}")
        if _sha256(body) != item["bodyHash"]:
            raise ValueError(f"body-change-after-migration: {path}")

    return {
        "runId": run_id,
        "completedAt": now_sgt(),
        "personCount": len(prepared),
        "recordsChanged": len(changed_items),
        "recordsPreserved": len(prepared) - len(changed_items),
        "values": values,
        "toEnhanceValuesUnchanged": len(prepared),
        "bodyHashesUnchanged": len(prepared),
        "backupDirectory": str(backup.relative_to(root)) if changed_items else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Require nullable clayEnhanced across canonical Person records."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    run_dir = ROOT / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    receipt = run_dir / "clay-enhanced-migration-receipt.json"
    failure = run_dir / "clay-enhanced-migration-failure.json"
    try:
        result = backfill_clay_enhanced(
            root=ROOT,
            run_id=args.run_id,
            backup_dir=args.backup_dir,
        )
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        result = {
            "runId": args.run_id,
            "failedAt": now_sgt(),
            "error": f"{type(error).__name__}: {error}",
        }
        failure.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
