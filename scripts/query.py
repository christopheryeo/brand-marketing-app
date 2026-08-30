#!/usr/bin/env python3
"""Query the Influential Brands Wiki using canonical Markdown records only.

The script never reads raw uploads, normalised inputs, or generated databases.
Catalogs provide index-first navigation; canonical entity-note frontmatter and
bodies provide facts, relationships, outcomes, and source traceability.

Autonomous mode requires ``OPENAI_API_KEY``:

    python3 scripts/query.py ask "Who at UOB is in the wiki?"
    python3 scripts/query.py serve --port 8080

The deterministic commands require no API key and are suitable for an agent-led
query session:

    python3 scripts/query.py resolve "UOB"
    python3 scripts/query.py inspect organisation-uob-a508cdd695
    python3 scripts/query.py search "Top Employer Award"
    python3 scripts/query.py related organisation-uob-a508cdd695
    python3 scripts/query.py outcomes --text "follow up"
    python3 scripts/query.py list organisations --limit 100
    python3 scripts/query.py cache "Who at UOB is in the wiki?"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from local_env import load_local_env  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    print("This script requires PyYAML. Install it with: pip3 install pyyaml", file=sys.stderr)
    raise SystemExit(2)


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ENTITIES = ROOT / "entities"
SEARCH_DIR = ENTITIES / "search"
PROCEDURE_PATH = SCRIPTS / "query_procedure.md"
API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6"
MAX_TOOL_TURNS = 24
API_TIMEOUT = 120
NOTE_CHAR_CAP = 24_000
ROSTER_ROW_CAP = 500
RESULT_CAP = 50
SGT = ZoneInfo("Asia/Singapore")

SYSTEM_FILES = {"index.md", "catalog.md", "log.md", "_template.md"}
OPERATIONAL_DOMAINS = {"search", "decisions"}
ACTIVITY_DOMAINS = {
    "email-messages", "meetings-events", "marketing-campaigns",
    "projects-initiatives", "sales-opportunities",
}
DOMAIN_ALIASES = {
    "appointment": "appointments", "appointments": "appointments",
    "brand": "brands", "brands": "brands",
    "campaign": "marketing-campaigns", "campaigns": "marketing-campaigns",
    "marketing-campaign": "marketing-campaigns", "marketing-campaigns": "marketing-campaigns",
    "decision": "decisions", "decisions": "decisions",
    "email": "email-messages", "emails": "email-messages",
    "email-message": "email-messages", "email-messages": "email-messages",
    "industry": "industries", "industries": "industries",
    "location": "locations", "locations": "locations",
    "meeting": "meetings-events", "meetings": "meetings-events",
    "event": "meetings-events", "events": "meetings-events",
    "meeting-event": "meetings-events", "meetings-events": "meetings-events",
    "marketing-segment": "marketing-segments", "marketing-segments": "marketing-segments",
    "function": "organisational-functions", "functions": "organisational-functions",
    "organisational-function": "organisational-functions",
    "organisational-functions": "organisational-functions",
    "organization": "organisations", "organizations": "organisations",
    "organisation": "organisations", "organisations": "organisations",
    "person": "people", "people": "people",
    "product": "products-services", "products": "products-services",
    "service": "products-services", "services": "products-services",
    "product-service": "products-services", "products-services": "products-services",
    "project": "projects-initiatives", "projects": "projects-initiatives",
    "initiative": "projects-initiatives", "initiatives": "projects-initiatives",
    "project-initiative": "projects-initiatives", "projects-initiatives": "projects-initiatives",
    "opportunity": "sales-opportunities", "opportunities": "sales-opportunities",
    "sales-opportunity": "sales-opportunities", "sales-opportunities": "sales-opportunities",
    "source": "sources", "sources": "sources",
    "topic": "topics", "topics": "topics",
    "search": "search",
}
ID_FIELDS = (
    "appointmentId", "brandId", "campaignId", "decisionId", "emailMessageId",
    "industryId", "locationId", "meetingEventId", "marketingSegmentId",
    "organisationalFunctionId", "organisationId", "personId", "productServiceId",
    "projectInitiativeId", "opportunityId", "queryId", "sourceId", "topicId",
)
ENTITY_TYPE_ID_FIELD = {
    "appointment": "appointmentId", "brand": "brandId",
    "marketing-campaign": "campaignId", "governance-decision": "decisionId",
    "email-message": "emailMessageId", "industry": "industryId",
    "location": "locationId", "meeting-event": "meetingEventId",
    "marketing-segment": "marketingSegmentId",
    "organisational-function": "organisationalFunctionId",
    "organisation": "organisationId", "person": "personId",
    "product-service": "productServiceId",
    "project-initiative": "projectInitiativeId",
    "sales-opportunity": "opportunityId", "query": "queryId",
    "source": "sourceId", "topic": "topicId",
}
NAME_FIELDS = ("displayName", "name", "title", "subject", "query")
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "about", "all", "an", "and", "are", "as", "at", "be", "been", "by",
    "did", "do", "does", "for", "from", "give", "has", "have", "how", "i", "in",
    "is", "it", "list", "me", "of", "on", "or", "show", "tell", "the", "there",
    "to", "was", "were", "what", "when", "where", "which", "who", "why", "with",
}


class QueryError(RuntimeError):
    """Raised when an autonomous query cannot be completed."""


_CATALOG_CACHE: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
_RECORD_CACHE: list[dict[str, Any]] | None = None
_RECORD_BY_ID: dict[str, dict[str, Any]] | None = None


def _now_sgt() -> datetime:
    return datetime.now(SGT)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_flags(cache_read: bool | None, cache_write: bool | None) -> tuple[bool, bool]:
    read = cache_read if cache_read is not None else _env_flag("QUERY_CACHE_READ", True)
    write = cache_write if cache_write is not None else _env_flag("QUERY_CACHE_WRITE", True)
    return read, write


def _domains() -> list[str]:
    return sorted(path.parent.name for path in ENTITIES.glob("*/catalog.md"))


def _domain(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    return DOMAIN_ALIASES.get(key, key)


def _requested_domains(values: list[str] | None) -> list[str]:
    if not values:
        return _domains()
    return sorted({_domain(value) for value in values})


def _strip_file_link(cell: str) -> str:
    match = re.search(r"\(([^)]+)\)", cell or "")
    return (match.group(1) if match else cell or "").strip().removeprefix("./")


def _row_get(row: dict[str, str], *names: str) -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        if lowered.get(name.lower()):
            return lowered[name.lower()]
    return ""


def parse_catalog(domain: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse one generated catalog table without assuming its frontmatter shape."""
    domain = _domain(domain)
    if domain in _CATALOG_CACHE:
        return _CATALOG_CACHE[domain]
    path = ENTITIES / domain / "catalog.md"
    columns: list[str] = []
    rows: list[dict[str, str]] = []
    if path.exists():
        table = [line for line in path.read_text(encoding="utf-8").splitlines()
                 if line.lstrip().startswith("|")]
        if len(table) >= 2:
            columns = [cell.strip() for cell in table[0].strip().strip("|").split("|")]
            for line in table[2:]:
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                if len(cells) == len(columns):
                    rows.append(dict(zip(columns, cells)))
    _CATALOG_CACHE[domain] = (columns, rows)
    return columns, rows


def _row_identity(row: dict[str, str]) -> tuple[str, str, str]:
    ident = _row_get(row, "ID", *ID_FIELDS, "slug")
    label = _row_get(row, "Name", *NAME_FIELDS) or ident
    file = _strip_file_link(_row_get(row, "File"))
    if not ident and file:
        ident = Path(file).stem
    return ident, label, file


def _parse_markdown(path: Path) -> tuple[dict[str, Any], str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    data: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                loaded = json.loads(parts[1])
            except json.JSONDecodeError:
                try:
                    loaded = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    loaded = {}
            data = loaded if isinstance(loaded, dict) else {}
            body = parts[2]
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", body, re.MULTILINE))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1).strip().lower()] = body[match.end():end].strip()
    return data, body.strip(), sections


def _record_id(data: dict[str, Any], fallback: str = "") -> str:
    own_field = ENTITY_TYPE_ID_FIELD.get(str(data.get("entityType", "")))
    if own_field and data.get(own_field):
        return str(data[own_field])
    for field in ID_FIELDS:
        if data.get(field):
            return str(data[field])
    return fallback


def _record_name(data: dict[str, Any], fallback: str = "") -> str:
    for field in NAME_FIELDS:
        if data.get(field):
            return str(data[field])
    return fallback


def _load_records() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load canonical entity notes; generated system notes are excluded."""
    global _RECORD_CACHE, _RECORD_BY_ID
    if _RECORD_CACHE is not None and _RECORD_BY_ID is not None:
        return _RECORD_CACHE, _RECORD_BY_ID
    records: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for domain_dir in sorted(path for path in ENTITIES.iterdir() if path.is_dir()):
        domain = domain_dir.name
        for path in sorted(domain_dir.rglob("*.md")):
            if path.name in SYSTEM_FILES:
                continue
            data, body, sections = _parse_markdown(path)
            ident = _record_id(data, path.stem)
            record = {
                "id": ident,
                "name": _record_name(data, ident),
                "domain": domain,
                "path": str(path.relative_to(ROOT)),
                "data": data,
                "body": body,
                "sections": sections,
            }
            records.append(record)
            by_id[ident] = record
    _RECORD_CACHE, _RECORD_BY_ID = records, by_id
    return records, by_id


def _score_name(needle: str, candidate: str) -> int:
    needle_n = " ".join(TOKEN_RE.findall(needle.lower()))
    candidate_n = " ".join(TOKEN_RE.findall(candidate.lower()))
    if not needle_n or not candidate_n:
        return 0
    if needle_n == candidate_n:
        return 1000
    if candidate_n.startswith(needle_n) or needle_n.startswith(candidate_n):
        return 700
    if re.search(rf"\b{re.escape(needle_n)}\b", candidate_n):
        return 550
    needle_tokens = set(needle_n.split())
    candidate_tokens = set(candidate_n.split())
    overlap = len(needle_tokens & candidate_tokens)
    if overlap:
        return 100 + 30 * overlap
    if len(needle_n) >= 4 and needle_n in candidate_n:
        return 80
    return 0


def tool_resolve_entity(name: str, domains: list[str] | None = None,
                        limit: int = RESULT_CAP) -> dict[str, Any]:
    """Resolve an identity from catalogs, then aliases/emails in canonical notes."""
    allowed = set(_requested_domains(domains))
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for domain in allowed:
        _, rows = parse_catalog(domain)
        for row in rows:
            ident, label, file = _row_identity(row)
            score = max(_score_name(name, ident), _score_name(name, label))
            if score:
                found[(domain, ident)] = {
                    "domain": domain, "id": ident, "displayName": label,
                    "file": file or f"{ident}.md", "score": score,
                    "matchedBy": "catalog",
                }
    exact_catalog = [item for item in found.values() if item["score"] >= 1000]
    if exact_catalog:
        exact_catalog.sort(key=lambda item: (item["domain"], item["id"]))
        cap = max(1, min(limit, RESULT_CAP))
        return {"query": name, "match_count": len(exact_catalog),
                "matches": exact_catalog[:cap],
                "truncated": len(exact_catalog) > cap}
    records, _ = _load_records()
    needle = name.strip().lower()
    for record in records:
        if record["domain"] not in allowed:
            continue
        data = record["data"]
        candidates = [(record["name"], "name"), (record["id"], "id")]
        candidates.extend((str(value), "alias") for value in data.get("aliases", []) or [])
        for field in ("primaryEmail", "email", "acronym"):
            if data.get(field):
                candidates.append((str(data[field]), field))
        best = max(((_score_name(name, value), kind, value) for value, kind in candidates),
                   default=(0, "", ""))
        if needle and "@" in needle:
            for value, kind in candidates:
                if value.lower() == needle:
                    best = max(best, (1100, kind, value))
        if best[0]:
            key = (record["domain"], record["id"])
            prior = found.get(key, {})
            if best[0] >= prior.get("score", -1):
                found[key] = {
                    "domain": record["domain"], "id": record["id"],
                    "displayName": record["name"], "file": Path(record["path"]).name,
                    "score": best[0], "matchedBy": best[1], "matchedValue": best[2],
                }
    matches = sorted(found.values(), key=lambda item: (-item["score"], item["domain"], item["id"]))
    top = matches[:max(1, min(limit, RESULT_CAP))]
    return {"query": name, "match_count": len(matches), "matches": top,
            "truncated": len(matches) > len(top)}


def tool_read_note(domain: str, note: str) -> dict[str, Any]:
    domain = _domain(domain)
    base = ENTITIES / domain
    candidate = base / note
    if not candidate.exists() and not note.endswith(".md"):
        candidate = base / f"{note}.md"
    if not candidate.exists():
        hits = sorted(base.rglob(Path(note).name if note.endswith(".md") else f"{Path(note).name}.md"))
        candidate = hits[0] if hits else candidate
    if not candidate.exists() or candidate.name in SYSTEM_FILES:
        return {"domain": domain, "note": note, "found": False, "text": ""}
    text = candidate.read_text(encoding="utf-8")
    return {"domain": domain, "note": note, "found": True,
            "path": str(candidate.relative_to(ROOT)),
            "truncated": len(text) > NOTE_CHAR_CAP, "text": text[:NOTE_CHAR_CAP]}


def tool_list_domain(domain: str, limit: int = ROSTER_ROW_CAP) -> dict[str, Any]:
    domain = _domain(domain)
    columns, rows = parse_catalog(domain)
    cap = max(1, min(int(limit), ROSTER_ROW_CAP))
    return {"domain": domain, "total": len(rows), "returned": min(len(rows), cap),
            "columns": columns, "rows": rows[:cap]}


def _query_tokens(text: str) -> list[str]:
    return [token for token in TOKEN_RE.findall(text.lower())
            if token not in STOP_WORDS and len(token) > 1]


def _snippet(text: str, tokens: list[str], size: int = 420) -> str:
    lowered = text.lower()
    positions = [lowered.find(token) for token in tokens if lowered.find(token) >= 0]
    start = max(0, (min(positions) if positions else 0) - size // 3)
    value = re.sub(r"\s+", " ", text[start:start + size]).strip()
    return ("…" if start else "") + value + ("…" if start + size < len(text) else "")


def tool_search_entities(text: str, domains: list[str] | None = None,
                         limit: int = 20) -> dict[str, Any]:
    """Rank canonical notes by token occurrence; raw and input files are never searched."""
    allowed = set(_requested_domains(domains))
    tokens = _query_tokens(text)
    if not tokens:
        return {"query": text, "match_count": 0, "matches": []}
    no_to_enhance_filter = object()
    to_enhance_filter: bool | None | object = no_to_enhance_filter
    token_set = set(tokens)
    if "toenhance" in token_set:
        if "true" in token_set:
            to_enhance_filter = True
        elif "false" in token_set:
            to_enhance_filter = False
        elif "null" in token_set:
            to_enhance_filter = None
    no_clay_enhanced_filter = object()
    clay_enhanced_filter: str | None | object = no_clay_enhanced_filter
    if "clayenhanced" in token_set:
        date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
        if date_match:
            clay_enhanced_filter = date_match.group(0)
        elif "null" in token_set:
            clay_enhanced_filter = None
    records, _ = _load_records()
    ranked: list[tuple[int, dict[str, Any]]] = []
    phrase = " ".join(TOKEN_RE.findall(text.lower()))
    for record in records:
        if record["domain"] not in allowed or record["domain"] == "search":
            continue
        if (to_enhance_filter is not no_to_enhance_filter
                and ("ToEnhance" not in record["data"]
                     or record["data"]["ToEnhance"] is not to_enhance_filter)):
            continue
        if (clay_enhanced_filter is not no_clay_enhanced_filter
                and ("clayEnhanced" not in record["data"]
                     or record["data"]["clayEnhanced"] != clay_enhanced_filter)):
            continue
        name = record["name"].lower()
        searchable = (
            json.dumps(record["data"], ensure_ascii=False)
            + "\n" + record["body"]
        )
        haystack = f"{record['name']}\n{searchable}".lower()
        present = [token for token in tokens if token in haystack]
        if not present:
            continue
        score = 20 * len(set(present))
        score += sum(min(haystack.count(token), 8) for token in set(present))
        score += 60 * sum(token in name for token in set(present))
        if phrase and phrase in haystack:
            score += 120
        ranked.append((score, {
            "domain": record["domain"], "id": record["id"],
            "displayName": record["name"], "file": Path(record["path"]).name,
            "matchedTokens": sorted(set(present)),
            "snippet": _snippet(searchable, present),
        }))
    ranked.sort(key=lambda item: (-item[0], item[1]["domain"], item[1]["id"]))
    cap = max(1, min(int(limit), RESULT_CAP))
    matches = [dict(item, score=score) for score, item in ranked[:cap]]
    return {"query": text, "match_count": len(ranked), "matches": matches,
            "truncated": len(ranked) > len(matches)}


def _relations_from(record: dict[str, Any]) -> list[dict[str, Any]]:
    data = record["data"]
    own_id = record["id"]
    relations: list[dict[str, Any]] = []
    for key, value in data.items():
        if key == "sourceRefs":
            continue
        if key.endswith("Id") and isinstance(value, str) and value:
            if value == own_id:
                continue
            relations.append({"fromId": own_id, "type": key[:-2], "toId": value})
        elif key.endswith("Ids") and isinstance(value, list):
            relations.extend({"fromId": own_id, "type": key[:-3], "toId": str(item)}
                             for item in value if item)
    for participant in data.get("participants", []) or []:
        if not isinstance(participant, dict):
            continue
        for key in ("personId", "organisationId"):
            if participant.get(key):
                relations.append({"fromId": own_id, "type": "participant",
                                  "toId": str(participant[key]),
                                  "role": participant.get("role")})
    for relationship in data.get("relationships", []) or []:
        if isinstance(relationship, dict) and relationship.get("toId"):
            relations.append({"fromId": own_id,
                              "type": relationship.get("relationshipType") or relationship.get("type") or "related",
                              "toId": str(relationship["toId"]),
                              "role": relationship.get("role"),
                              "status": relationship.get("status")})
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for relation in relations:
        unique[(relation["fromId"], relation["type"], relation["toId"])] = relation
    return list(unique.values())


def tool_related_entity(entity_id: str, direction: str = "both", limit: int = 100) -> dict[str, Any]:
    records, by_id = _load_records()
    if entity_id not in by_id:
        return {"entity_id": entity_id, "found": False, "relationships": []}
    relationships: list[dict[str, Any]] = []
    if direction in {"outbound", "both"}:
        for relation in _relations_from(by_id[entity_id]):
            target = by_id.get(relation["toId"])
            relationships.append(dict(relation, direction="outbound",
                                      relatedName=target["name"] if target else None,
                                      relatedDomain=target["domain"] if target else None))
    if direction in {"inbound", "both"}:
        for record in records:
            if record["id"] == entity_id:
                continue
            for relation in _relations_from(record):
                if relation["toId"] == entity_id:
                    relationships.append(dict(relation, direction="inbound",
                                              relatedName=record["name"],
                                              relatedDomain=record["domain"]))
    cap = max(1, min(int(limit), ROSTER_ROW_CAP))
    return {"entity_id": entity_id, "found": True, "entityName": by_id[entity_id]["name"],
            "total": len(relationships), "relationships": relationships[:cap],
            "truncated": len(relationships) > cap}


def tool_business_outcomes(entity_id: str | None = None, text: str | None = None,
                           status: str | None = None, limit: int = 100) -> dict[str, Any]:
    records, _ = _load_records()
    tokens = _query_tokens(text or "")
    matches: list[dict[str, Any]] = []
    for record in records:
        if record["domain"] not in ACTIVITY_DOMAINS:
            continue
        if entity_id and record["id"] != entity_id:
            relation_ids = {relation["toId"] for relation in _relations_from(record)}
            if entity_id not in relation_ids:
                continue
        for outcome in record["data"].get("outcomes", []) or []:
            if not isinstance(outcome, dict):
                continue
            if status and str(outcome.get("status", "")).lower() != status.lower():
                continue
            searchable = json.dumps(outcome, ensure_ascii=False).lower()
            if tokens and not all(token in searchable for token in tokens):
                continue
            matches.append({"activityId": record["id"], "activityName": record["name"],
                            "domain": record["domain"], "outcome": outcome})
    cap = max(1, min(int(limit), ROSTER_ROW_CAP))
    return {"entity_id": entity_id, "query": text, "status": status,
            "total": len(matches), "outcomes": matches[:cap], "truncated": len(matches) > cap}


def tool_inspect_entity(entity_id: str, relation_limit: int = 100) -> dict[str, Any]:
    _, by_id = _load_records()
    record = by_id.get(entity_id)
    if not record:
        return {"entity_id": entity_id, "found": False}
    text = (ENTITIES.parent / record["path"]).read_text(encoding="utf-8")
    return {
        "entity_id": entity_id, "found": True, "domain": record["domain"],
        "displayName": record["name"], "path": record["path"],
        "frontmatter": record["data"], "sections": record["sections"],
        "relationships": tool_related_entity(entity_id, limit=relation_limit),
        "outcomes": tool_business_outcomes(entity_id=entity_id, limit=100),
        "text_truncated": len(text) > NOTE_CHAR_CAP,
    }


def tool_search_cache(question: str, limit: int = 8) -> dict[str, Any]:
    tokens = set(_query_tokens(question))
    candidates: list[tuple[int, dict[str, Any]]] = []
    if SEARCH_DIR.exists():
        for path in SEARCH_DIR.glob("*.md"):
            if path.name in SYSTEM_FILES:
                continue
            data, _, sections = _parse_markdown(path)
            prior = str(data.get("query") or sections.get("question") or "")
            overlap = len(tokens & set(_query_tokens(prior)))
            if overlap:
                candidates.append((overlap, {
                    "queryId": data.get("queryId") or path.stem, "query": prior,
                    "status": data.get("status", ""), "updatedAt": data.get("updatedAt", ""),
                    "reuseCount": data.get("reuseCount", 0), "file": path.name,
                    "answer": sections.get("answer") or sections.get("summary", ""),
                }))
    candidates.sort(key=lambda item: (-item[0], str(item[1]["queryId"])))
    return {"question": question, "candidates": [item for _, item in candidates[:limit]]}


def _slugify(text: str, max_words: int = 7) -> str:
    return "-".join(TOKEN_RE.findall(text.lower())[:max_words]) or "query"


def _procedure_version() -> str:
    if not PROCEDURE_PATH.exists():
        return ""
    match = re.search(r"^last_updated:\s*(.+?)\s*$", PROCEDURE_PATH.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else ""


def _wikilinks(items: list[Any]) -> str:
    lines = []
    for item in items or []:
        if isinstance(item, dict):
            ident = str(item.get("id") or item.get("sourceId") or "")
            label = item.get("displayName") or item.get("label")
        else:
            ident, label = str(item).split("/")[-1], None
        if ident:
            lines.append(f"- [[{ident}|{label}]]" if label else f"- [[{ident}]]")
    return "\n".join(lines) if lines else "<!-- none -->"


def _regenerate_search_catalog() -> str | None:
    try:
        subprocess.run([sys.executable, str(SCRIPTS / "generate_catalog.py"), "search"],
                       cwd=ROOT, check=True, capture_output=True, timeout=90)
        _CATALOG_CACHE.pop("search", None)
        return None
    except Exception as exc:  # pragma: no cover
        return f"catalog regeneration failed: {exc}"


def persist_answer(question: str, final: dict[str, Any]) -> dict[str, Any]:
    """Write a schema-compatible query note and append the search audit log."""
    now = _now_sgt()
    stamp = now.isoformat(timespec="seconds")
    query_id = f"query-{_slugify(question)}-{hashlib.sha1(question.strip().encode()).hexdigest()[:8]}"
    status = final.get("status", "answered")
    frontmatter = {
        "entityType": "query", "queryId": query_id, "query": question,
        "createdAt": stamp, "updatedAt": stamp, "status": status,
        "aliases": [], "tags": ["time-sensitive"] if final.get("time_sensitive") else [],
        "confidence": 1.0 if status == "answered" else 0.0, "sourceRefs": [],
        "reuseCount": 0, "timeSensitive": bool(final.get("time_sensitive")),
        "procedureVersion": _procedure_version(),
    }
    note = (
        "---\n" + json.dumps(frontmatter, ensure_ascii=False, indent=2) + "\n---\n\n"
        f"# {question}\n\n## Summary\n\n{str(final.get('answer', '')).strip()}\n\n"
        f"## Question\n\n{question}\n\n## Answer\n\n{str(final.get('answer', '')).strip()}\n\n"
        f"## Relationships\n\n### Entities Resolved\n\n{_wikilinks(final.get('entities_resolved', []))}\n\n"
        f"### Sources Cited\n\n{_wikilinks(final.get('sources_cited', []))}\n\n"
        "## Source Information\n\nSee the resolved entities and their `sourceRefs`.\n\n"
        "## AI Context\n\nFiled by `scripts/query.py` using the canonical Markdown query procedure.\n"
    )
    SEARCH_DIR.mkdir(parents=True, exist_ok=True)
    path = SEARCH_DIR / f"{query_id}.md"
    path.write_text(note, encoding="utf-8")
    with (SEARCH_DIR / "log.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- {stamp} | query: {json.dumps(question, ensure_ascii=False)} | entity: [[{query_id}]] | action: created\n")
    warning = _regenerate_search_catalog()
    return {"query_id": query_id, "path": str(path.relative_to(ROOT)), "warning": warning}


def register_reuse(query_id: str, question: str) -> dict[str, Any]:
    path = SEARCH_DIR / f"{query_id}.md"
    if not path.exists():
        raise QueryError(f"cached query not found: {query_id}")
    data, body, _ = _parse_markdown(path)
    data["reuseCount"] = int(data.get("reuseCount", 0)) + 1
    data["updatedAt"] = _now_sgt().isoformat(timespec="seconds")
    path.write_text("---\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n---\n\n" + body + "\n", encoding="utf-8")
    with (SEARCH_DIR / "log.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- {data['updatedAt']} | query: {json.dumps(question, ensure_ascii=False)} | entity: [[{query_id}]] | action: reused\n")
    warning = _regenerate_search_catalog()
    return {"query_id": query_id, "reuseCount": data["reuseCount"], "warning": warning}


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}


def build_tools(cache_read: bool) -> list[dict[str, Any]]:
    tools = [
        _fn("resolve_entity", "Resolve a person, organisation, activity, or other identity using catalogs and canonical-note aliases.",
            {"name": {"type": "string"}, "domains": {"type": "array", "items": {"type": "string"}},
             "limit": {"type": "integer"}}, ["name"]),
        _fn("inspect_entity", "Read one canonical entity with frontmatter, sections, inbound/outbound relationships, outcomes, and sourceRefs.",
            {"entity_id": {"type": "string"}, "relation_limit": {"type": "integer"}}, ["entity_id"]),
        _fn("search_entities", "Search only canonical Markdown entity notes. Use for topics, activity history, commitments, or when a named entity is not enough.",
            {"text": {"type": "string"}, "domains": {"type": "array", "items": {"type": "string"}},
             "limit": {"type": "integer"}}, ["text"]),
        _fn("list_domain", "Return one domain's generated catalog rows for complete roster questions.",
            {"domain": {"type": "string"}, "limit": {"type": "integer"}}, ["domain"]),
        _fn("related_entity", "Return typed inbound and outbound relationships for one entity.",
            {"entity_id": {"type": "string"}, "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]},
             "limit": {"type": "integer"}}, ["entity_id"]),
        _fn("business_outcomes", "Find structured actions, commitments, and business decisions on activity records.",
            {"entity_id": {"type": "string"}, "text": {"type": "string"},
             "status": {"type": "string"}, "limit": {"type": "integer"}}, []),
        _fn("submit_answer", "Return the grounded answer. Keep citations in sources_cited unless the question explicitly asks for sources.",
            {"answer": {"type": "string"},
             "entities_resolved": {"type": "array", "items": {"type": "string"}},
             "sources_cited": {"type": "array", "items": {"type": "string"}},
             "status": {"type": "string", "enum": ["answered", "unresolved"]},
             "time_sensitive": {"type": "boolean"},
             "reused_query_id": {"type": ["string", "null"]}},
            ["answer", "entities_resolved", "sources_cited", "status", "time_sensitive"]),
    ]
    if cache_read:
        tools.insert(0, _fn("search_cache", "Find similar previously answered questions before running a new query.",
                            {"question": {"type": "string"}, "limit": {"type": "integer"}}, ["question"]))
    return tools


def dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "resolve_entity":
        return tool_resolve_entity(args["name"], args.get("domains"), args.get("limit", RESULT_CAP))
    if name == "inspect_entity":
        return tool_inspect_entity(args["entity_id"], args.get("relation_limit", 100))
    if name == "search_entities":
        return tool_search_entities(args["text"], args.get("domains"), args.get("limit", 20))
    if name == "list_domain":
        return tool_list_domain(args["domain"], args.get("limit", ROSTER_ROW_CAP))
    if name == "related_entity":
        return tool_related_entity(args["entity_id"], args.get("direction", "both"), args.get("limit", 100))
    if name == "business_outcomes":
        return tool_business_outcomes(args.get("entity_id"), args.get("text"), args.get("status"), args.get("limit", 100))
    if name == "search_cache":
        return tool_search_cache(args["question"], args.get("limit", 8))
    return {"error": f"unknown tool: {name}"}


def _instructions(cache_read: bool, cache_write: bool) -> str:
    return (
        f"Today is {_now_sgt().date().isoformat()} in Singapore. "
        "Use only the provided tools and canonical Markdown evidence. Never use outside knowledge. "
        f"Cache read is {'enabled' if cache_read else 'disabled'}; cache write is {'enabled' if cache_write else 'disabled'}. "
        "Finish by calling submit_answer exactly once.\n\n" + PROCEDURE_PATH.read_text(encoding="utf-8")
    )


def _call_responses(api_key: str, model: str, instructions: str,
                    input_items: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"model": model, "instructions": instructions, "input": input_items,
               "tools": tools, "store": False}
    request = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Authorization": f"Bearer {api_key}",
                                              "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise QueryError(f"OpenAI API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise QueryError(f"OpenAI API request failed: {exc}") from exc


def _message_text(output: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in output:
        if item.get("type") == "message":
            for chunk in item.get("content", []):
                if chunk.get("type") in {"output_text", "text"}:
                    parts.append(chunk.get("text", ""))
    return "\n".join(parts).strip()


def run_query(question: str, cache_read: bool | None = None,
              cache_write: bool | None = None, model: str | None = None) -> dict[str, Any]:
    load_local_env()
    if not PROCEDURE_PATH.exists():
        raise QueryError(f"missing procedure: {PROCEDURE_PATH}")
    if not _env_flag("QUERY_ALLOW_EXTERNAL", False):
        raise QueryError(
            "autonomous API mode is disabled; set QUERY_ALLOW_EXTERNAL=true only "
            "after approving transfer of the selected canonical evidence"
        )
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise QueryError("OPENAI_API_KEY is not set (checked environment and .env.local).")
    read, write = resolve_flags(cache_read, cache_write)
    selected_model = model or os.environ.get("QUERY_MODEL", DEFAULT_MODEL)
    tools = build_tools(read)
    inputs: list[dict[str, Any]] = [{"role": "user", "content": question}]
    final: dict[str, Any] | None = None
    for _ in range(MAX_TOOL_TURNS):
        response = _call_responses(api_key, selected_model, _instructions(read, write), inputs, tools)
        output = response.get("output", [])
        calls = [item for item in output if item.get("type") == "function_call"]
        if not calls:
            text = _message_text(output)
            if text:
                final = {"answer": text, "entities_resolved": [], "sources_cited": [],
                         "status": "answered", "time_sensitive": False,
                         "reused_query_id": None}
                break
            continue
        for call in calls:
            try:
                args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            inputs.append({"type": "function_call", "call_id": call["call_id"],
                           "name": call["name"], "arguments": call.get("arguments", "{}")})
            if call["name"] == "submit_answer":
                final = args
                inputs.append({"type": "function_call_output", "call_id": call["call_id"],
                               "output": json.dumps({"received": True})})
            else:
                result = dispatch_tool(call["name"], args)
                inputs.append({"type": "function_call_output", "call_id": call["call_id"],
                               "output": json.dumps(result, ensure_ascii=False)})
        if final is not None:
            break
    if final is None:
        raise QueryError(f"no answer after {MAX_TOOL_TURNS} tool turns")
    result = {
        "question": question, "answer": str(final.get("answer", "")).strip(),
        "status": final.get("status", "answered"),
        "entities_resolved": final.get("entities_resolved", []),
        "sources_cited": final.get("sources_cited", []),
        "time_sensitive": bool(final.get("time_sensitive")),
        "cache_read": read, "cache_write": write,
        "cache_hit": bool(final.get("reused_query_id")),
        "reused_query_id": final.get("reused_query_id"),
        "query_id": None, "cache_written": False,
    }
    if write:
        info = (register_reuse(result["reused_query_id"], question)
                if result["cache_hit"] else persist_answer(question, final))
        result["query_id"] = info["query_id"]
        result["cache_written"] = True
    return result


def serve(port: int = 8080) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, code: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            self.send_json(200, {"ok": True}) if self.path.rstrip("/") == "/health" else self.send_json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/query":
                self.send_json(404, {"error": "not found"})
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                question = str(body.get("question", "")).strip()
                if not question:
                    self.send_json(400, {"error": "missing question"})
                    return
                self.send_json(200, run_query(question, body.get("cache_read"),
                                               body.get("cache_write"), body.get("model")))
            except QueryError as exc:
                self.send_json(502, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover
                self.send_json(500, {"error": f"internal error: {exc}"})

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving POST /query and GET /health on port {port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query the Influential Brands Wiki's canonical Markdown entities.")
    sub = parser.add_subparsers(dest="cmd")
    ask = sub.add_parser("ask", help="answer autonomously using the model")
    ask.add_argument("question")
    ask.add_argument("--model")
    ask.add_argument("--no-cache-read", dest="cache_read", action="store_false", default=None)
    ask.add_argument("--no-cache-write", dest="cache_write", action="store_false", default=None)
    ask.add_argument("--json", action="store_true")
    server = sub.add_parser("serve", help="serve the HTTP query endpoint")
    server.add_argument("--port", type=int, default=int(os.environ.get("QUERY_PORT", "8080")))
    resolve = sub.add_parser("resolve", help="resolve an entity identity")
    resolve.add_argument("name")
    resolve.add_argument("--domains", nargs="*")
    resolve.add_argument("--limit", type=int, default=RESULT_CAP)
    inspect = sub.add_parser("inspect", help="inspect an entity and its graph context")
    inspect.add_argument("entity_id")
    inspect.add_argument("--relation-limit", type=int, default=100)
    read = sub.add_parser("read", help="read one canonical entity note")
    read.add_argument("domain")
    read.add_argument("note")
    search = sub.add_parser("search", help="search canonical entity notes")
    search.add_argument("text")
    search.add_argument("--domains", nargs="*")
    search.add_argument("--limit", type=int, default=20)
    listing = sub.add_parser("list", help="list a domain catalog")
    listing.add_argument("domain")
    listing.add_argument("--limit", type=int, default=ROSTER_ROW_CAP)
    related = sub.add_parser("related", help="show typed relationships")
    related.add_argument("entity_id")
    related.add_argument("--direction", choices=["inbound", "outbound", "both"], default="both")
    related.add_argument("--limit", type=int, default=100)
    outcomes = sub.add_parser("outcomes", help="find structured business outcomes")
    outcomes.add_argument("--entity")
    outcomes.add_argument("--text")
    outcomes.add_argument("--status")
    outcomes.add_argument("--limit", type=int, default=100)
    cache = sub.add_parser("cache", help="search prior query answers")
    cache.add_argument("question")
    submit = sub.add_parser("submit", help="file an agent-composed answer")
    submit.add_argument("--question", required=True)
    submit.add_argument("--answer", default="")
    submit.add_argument("--entities", nargs="*", default=[])
    submit.add_argument("--sources", nargs="*", default=[])
    submit.add_argument("--status", choices=["answered", "unresolved"], default="answered")
    submit.add_argument("--time-sensitive", action="store_true")
    submit.add_argument("--reuse")

    commands = {"ask", "serve", "resolve", "inspect", "read", "search", "list", "related", "outcomes", "cache", "submit"}
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and not raw[0].startswith("-") and raw[0] not in commands:
        raw.insert(0, "ask")
    args = parser.parse_args(raw)
    if args.cmd == "serve":
        serve(args.port)
    elif args.cmd == "resolve":
        _print(tool_resolve_entity(args.name, args.domains, args.limit))
    elif args.cmd == "inspect":
        _print(tool_inspect_entity(args.entity_id, args.relation_limit))
    elif args.cmd == "read":
        _print(tool_read_note(args.domain, args.note))
    elif args.cmd == "search":
        _print(tool_search_entities(args.text, args.domains, args.limit))
    elif args.cmd == "list":
        _print(tool_list_domain(args.domain, args.limit))
    elif args.cmd == "related":
        _print(tool_related_entity(args.entity_id, args.direction, args.limit))
    elif args.cmd == "outcomes":
        _print(tool_business_outcomes(args.entity, args.text, args.status, args.limit))
    elif args.cmd == "cache":
        _print(tool_search_cache(args.question))
    elif args.cmd == "submit":
        final = {"answer": args.answer, "entities_resolved": args.entities,
                 "sources_cited": args.sources, "status": args.status,
                 "time_sensitive": args.time_sensitive}
        _print(register_reuse(args.reuse, args.question) if args.reuse else persist_answer(args.question, final))
    elif args.cmd == "ask":
        try:
            result = run_query(args.question, args.cache_read, args.cache_write, args.model)
        except QueryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _print(result) if args.json else print(result["answer"])
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
