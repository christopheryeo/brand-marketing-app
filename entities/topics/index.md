---
type: domain-index
domain: Topics
subtype: topic
status: active
last_updated: 2026-08-08
---

# Domain: Topics

**Purpose:** Meaningful subjects connecting related people, organisations, communications and business activities.

**Domain type:** Entity
**Note subtype:** `topic`

## Operating instructions

1. Read this file before creating or updating records in this domain.
2. Use a flat namespace unless a future accepted governance decision authorises dated subfolders.
3. Resolve aliases and existing identities before creating a new record.
4. Link every imported fact to its Source and retain the internal source locator.
5. Multi-value relationships should be represented as explicit links or indexed relationship records, not duplicated embedded entities.

## Production record requirements

All canonical records must contain the approved type-specific ID and name fields plus `createdAt`, `updatedAt`, `status`, `aliases`, `tags`, `confidence`, and `sourceRefs`. Relationships are typed fields compiled into the generated query index. The machine-readable schema under `schemas/` is authoritative.

## Record template

```md
---
{"entityType":"topic","topicId":"<stable-id>","name":"<name>","createdAt":"<SGT timestamp>","updatedAt":"<SGT timestamp>","status":"active","aliases":[],"tags":[],"confidence":1.0,"sourceRefs":[]}
---

## Summary

## Relationships

## Source Information

## AI Context
```

## System files

- `catalog.md` — generated complete listing; never hand-edit.
- `log.md` — append-only audit ledger.
