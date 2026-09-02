# Log: People

Append-only audit ledger. Never edit or delete prior entries; correct forward with a new entry.

- 2026-08-07T19:49:24+08:00 | action: created domain scaffold | source: approved Influential Brands Wiki architecture | result: initialized `index.md`, `catalog.md`, and `log.md`


- 2026-08-08T14:20:33+08:00 | run `20260808T014-full-ingest` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}

- 2026-08-08T14:22:52+08:00 | run `20260808T017-idempotency-rerun` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}

- 2026-08-09T00:20:28+08:00 | run `20260809T024-clean-reingest` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}

- 2026-08-13T11:15:00+08:00 | run `20260813T-quality-check` | repair | normalised 14 malformed `linkedInUrl` values (added missing scheme, extracted embedded URL, nulled 7 non-URL placeholders) and corrected 2 malformed `primaryEmail` values; no identity merges performed

- 2026-08-27T19:12:16+08:00 | action: extended Person schema | source: [[decision-person-clay-enhanced-date-2026-08-27]] | result: added optional `clayEnhanced` ISO date for the latest successful Clay enhancement; existing records not backfilled

- 2026-08-27T19:29:30+08:00 | action: completed Clay Enhanced integration safeguards | source: [[decision-person-clay-enhanced-date-2026-08-27]] | result: schema regeneration and ingestion preserve `clayEnhanced`; ISO dates are enforced; safe connector-success writeback and People Directory display added

- 2026-08-28T21:01:19+08:00 | action: extended Person schema | source: [[decision-person-to-enhance-flag-2026-08-28]] | result: added optional Boolean `ToEnhance` for notes needing enhancement; existing records not backfilled

- 2026-08-28T21:05:43+08:00 | action: completed ToEnhance integration safeguards | source: [[decision-person-to-enhance-flag-2026-08-28]] | result: schema regeneration and ingestion preserve `ToEnhance`; non-Boolean values are rejected; exact `query.py` filtering avoids false positives; existing Person records remain unchanged

- 2026-08-28T21:16:15+08:00 | action: approved required nullable ToEnhance migration | source: [[decision-require-nullable-person-to-enhance-2026-08-28]] | result: require `ToEnhance` on every Person record; use null for unassessed existing records and preserve any valid values

- 2026-08-28T21:23:14+08:00 | action: completed required nullable ToEnhance migration | run: `20260828T211615-toenhance-nullable` | source: [[decision-require-nullable-person-to-enhance-2026-08-28]] | result: 2,666 of 2,666 Person records contain `ToEnhance`; true=0, false=0, null=2,666; all body hashes unchanged; idempotency re-run changed 0 records

- 2026-08-28T21:49:23+08:00 | action: approved required nullable clayEnhanced migration | source: [[decision-require-nullable-person-clay-enhanced-2026-08-28]] | result: require `clayEnhanced` on every Person record; use null when no verified Clay enhancement is recorded and preserve valid dates

- 2026-08-28T21:55:35+08:00 | action: completed required nullable clayEnhanced migration | run: `20260828T214923-clay-enhanced-nullable` | source: [[decision-require-nullable-person-clay-enhanced-2026-08-28]] | result: 2,666 of 2,666 Person records contain `clayEnhanced`; date=0, null=2,666; all `ToEnhance` values and body hashes unchanged; idempotency re-run changed 0 records

- 2026-09-02T12:05:31+08:00 | action: recorded successful linkedin enrichment | entity: [[person-agatha-pabloasia-com-121dbb64df]] | enrichmentProvider: linkedin | enrichmentDate: 2026-09-02 | minimumProfile: true

- 2026-09-02T16:42:35+08:00 | action: set ToEnhance | entity: [[person-allan-kwek-mynews-com-my-9c4dead19f]] | ToEnhance: true | source: People Directory checkbox

- 2026-09-02T16:42:43+08:00 | action: set ToEnhance | entity: [[person-alvin-bizlink-org-sg-ab93957289]] | ToEnhance: true | source: People Directory checkbox

- 2026-09-02T17:18:15+08:00 | action: recorded successful linkedin enrichment | entity: [[person-allan-kwek-mynews-com-my-9c4dead19f]] | enrichmentProvider: linkedin | enrichmentDate: 2026-09-02 | minimumProfile: true

- 2026-09-02T17:43:47+08:00 | action: recorded successful linkedin enrichment | entity: [[person-alvin-bizlink-org-sg-ab93957289]] | enrichmentProvider: linkedin | enrichmentDate: 2026-09-02 | minimumProfile: true

- 2026-09-02T18:51:54+08:00 | action: set ToEnhance | entity: [[person-kenneth-tang-kornworth-com-hk-881e4eb85d]] | ToEnhance: true | source: People Directory checkbox

- 2026-09-02T18:52:03+08:00 | action: set ToEnhance | entity: [[person-georgelim-shaw-com-sg-2980c0c947]] | ToEnhance: true | source: People Directory checkbox

- 2026-09-02T18:55:08+08:00 | action: recorded successful apollo enrichment | entity: [[person-georgelim-shaw-com-sg-2980c0c947]] | enrichmentProvider: apollo | enrichmentDate: 2026-09-02 | minimumProfile: true

- 2026-09-02T18:55:55+08:00 | action: enrichment found no minimum useful profile | entity: [[person-kenneth-tang-kornworth-com-hk-881e4eb85d]] | providers: apollo,clay,linkedin | enrichmentStatus: not_found | enrichmentFound: false
