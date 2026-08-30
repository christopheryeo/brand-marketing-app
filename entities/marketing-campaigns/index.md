---
type: domain-index
domain: Marketing Campaigns
subtype: marketing-campaign
status: active
last_updated: 2026-08-08
---

# Domain: Marketing Campaigns

**Purpose:** Coordinated, time-bound marketing activities with an audience, objective, content and results.

**Domain type:** Entity
**Note subtype:** `marketing-campaign`

## Operating instructions

1. Read this file before creating or updating records in this domain.
2. Use a flat namespace unless a future accepted governance decision authorises dated subfolders.
3. Resolve aliases and existing identities before creating a new record.
4. Link every imported fact to its Source and retain the internal source locator.
5. Multi-value relationships should be represented as explicit links or indexed relationship records, not duplicated embedded entities.
6. Actions, commitments and business decisions are structured attributes of this activity and are indexed for retrieval; they are not standalone entities.

## Production record requirements

All canonical records must contain the approved type-specific ID and name fields plus `createdAt`, `updatedAt`, `status`, `aliases`, `tags`, `confidence`, and `sourceRefs`. Relationships are typed fields compiled into the generated query index. The machine-readable schema under `schemas/` is authoritative.

## Record template

```md
---
{"entityType":"marketing-campaign","campaignId":"<stable-id>","name":"<name>","createdAt":"<SGT timestamp>","updatedAt":"<SGT timestamp>","status":"active","aliases":[],"tags":[],"confidence":1.0,"sourceRefs":[]}
---

## Summary

## Relationships

## Source Information

## AI Context
```

## System files

- `catalog.md` — generated complete listing; never hand-edit.
- `log.md` — append-only audit ledger.

