---
type: domain-index
domain: People
subtype: person
status: active
last_updated: 2026-08-27
---

# Domain: People

**Purpose:** Canonical records for identifiable individuals, contacts, employees, prospects and stakeholders.

**Domain type:** Entity
**Note subtype:** `person`

## Operating instructions

1. Read this file before creating or updating records in this domain.
2. Use a flat namespace unless a future accepted governance decision authorises dated subfolders.
3. Resolve aliases and existing identities before creating a new record.
4. Link every imported fact to its Source and retain the internal source locator.
5. Multi-value relationships should be represented as explicit links or indexed relationship records, not duplicated embedded entities.
6. After a successful Clay connector enhancement, run `python3 scripts/mark_clay_enhanced.py <personId>` to record the SGT date. Do not record a queued, failed or unverified enrichment.

## Production record requirements

All canonical records must contain the approved type-specific ID and name fields plus `createdAt`, `updatedAt`, `status`, `aliases`, `tags`, `confidence`, and `sourceRefs`. Every Person record must contain `clayEnhanced`: use the latest verified successful Clay enhancement date in `YYYY-MM-DD` format, or `null` when no verified enhancement is recorded. Every Person record must also contain `ToEnhance`: use `true` when its notes require enhancement, `false` when assessed and clear, and `null` when not yet assessed. `ToEnhance` and `clayEnhanced` are independent. Relationships are typed fields compiled into the generated query index. The machine-readable schema under `schemas/` is authoritative.

## Record template

```md
---
{"entityType":"person","personId":"<stable-id>","displayName":"<name>","createdAt":"<SGT timestamp>","updatedAt":"<SGT timestamp>","clayEnhanced":null,"ToEnhance":null,"status":"active","aliases":[],"tags":[],"confidence":1.0,"sourceRefs":[]}
---

## Summary

## Relationships

## Source Information

## AI Context
```

## System files

- `catalog.md` — generated complete listing; never hand-edit.
- `log.md` — append-only audit ledger.
