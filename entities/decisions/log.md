# Log: Decisions

Append-only audit ledger. Never edit or delete prior entries; correct forward with a new entry.

- 2026-08-07T19:49:24+08:00 | action: created domain scaffold | source: approved Influential Brands Wiki architecture | result: initialized `index.md`, `catalog.md`, and `log.md`


- 2026-08-08T14:20:33+08:00 | run `20260808T014-full-ingest` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}

- 2026-08-08T14:22:52+08:00 | run `20260808T017-idempotency-rerun` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}

- 2026-08-09T00:20:28+08:00 | run `20260809T024-clean-reingest` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}

- 2026-08-11T15:29:27+08:00 | action: accepted MySQL query replica governance | source: explicit data-owner approval | result: approved transactional one-way Wiki-to-MySQL sync

- 2026-08-11T17:42:32+08:00 | action: accepted query.py-first governance | source: Christopher's explicit instruction | entity: [[decision-query-py-first-for-wiki-queries-2026-08-11]] | result: use `scripts/query.py` first for all future Influential Brands Wiki information queries

- 2026-08-27T19:12:16+08:00 | action: accepted Person Clay Enhanced date governance | source: Christopher's explicit instruction | entity: [[decision-person-clay-enhanced-date-2026-08-27]] | result: approve optional `clayEnhanced` ISO date on Person records after successful Clay enhancement

- 2026-08-27T19:29:30+08:00 | action: implemented Person Clay Enhanced governance | entity: [[decision-person-clay-enhanced-date-2026-08-27]] | result: completed durable schema generation, ingestion preservation, date validation, connector-success writeback, downstream display and regression coverage

- 2026-08-28T21:01:19+08:00 | action: accepted Person ToEnhance governance | source: Christopher's Approval Gate 1 instruction | entity: [[decision-person-to-enhance-flag-2026-08-28]] | result: approve optional Boolean `ToEnhance` on Person records to flag notes needing enhancement without backfilling existing records

- 2026-08-28T21:05:43+08:00 | action: implemented Person ToEnhance governance | entity: [[decision-person-to-enhance-flag-2026-08-28]] | result: completed durable schema generation, rewrite preservation, Boolean validation, exact query filtering, generated-index rebuild and regression coverage

- 2026-08-28T21:16:15+08:00 | action: accepted required nullable Person ToEnhance governance | source: Christopher's revised Approval Gate 1 instruction | entity: [[decision-require-nullable-person-to-enhance-2026-08-28]] | result: supersede the optional-field decision; require `ToEnhance` on every Person record with Boolean or null values and migrate existing records

- 2026-08-28T21:23:14+08:00 | action: implemented required nullable Person ToEnhance governance | entity: [[decision-require-nullable-person-to-enhance-2026-08-28]] | result: migrated all 2,666 Person records to include `ToEnhance`; schema now requires Boolean or null; future writes default null; exact true, false and null queries verified

- 2026-08-28T21:49:23+08:00 | action: accepted required nullable Person clayEnhanced governance | source: Christopher's Approval Gate 1 instruction | entity: [[decision-require-nullable-person-clay-enhanced-2026-08-28]] | result: supersede the optional-field decision; require `clayEnhanced` on every Person record with null or valid date values and migrate existing records

- 2026-08-28T21:55:35+08:00 | action: implemented required nullable Person clayEnhanced governance | entity: [[decision-require-nullable-person-clay-enhanced-2026-08-28]] | result: migrated all 2,666 Person records to include `clayEnhanced`; schema now requires null or a valid date; future writes default null; controlled date writeback and exact null/date queries verified
