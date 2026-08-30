---
type: domain-index
domain: Search
subtype: query
status: active
last_updated: 2026-08-08
---

# Domain: Search

**Purpose:** Saved natural-language questions and answers for efficient, traceable query reuse.

**Domain type:** Operational
**Note subtype:** `query`

## Operating instructions

1. Read this file before creating or updating records in this domain.
2. Use a flat namespace unless a future accepted governance decision authorises dated subfolders.
3. Resolve aliases and existing identities before creating a new record.
4. Link every imported fact to its Source and retain the internal source locator.
5. Links to resolved entities and cited sources live in the body.

## Production record requirements

All canonical records must contain the approved type-specific ID and name fields plus `createdAt`, `updatedAt`, `status`, `aliases`, `tags`, `confidence`, and `sourceRefs`. Relationships are typed fields compiled into the generated query index. The machine-readable schema under `schemas/` is authoritative.

## Record template

```md
---
{"entityType":"query","queryId":"<stable-id>","query":"<name>","createdAt":"<SGT timestamp>","updatedAt":"<SGT timestamp>","status":"active","aliases":[],"tags":[],"confidence":1.0,"sourceRefs":[]}
---

## Summary

## Relationships

## Source Information

## AI Context
```

## System files

- `catalog.md` — generated complete listing; never hand-edit.
- `log.md` — append-only audit ledger.

