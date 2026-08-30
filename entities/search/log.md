# Log: Search

Append-only audit ledger. Never edit or delete prior entries; correct forward with a new entry.

- 2026-08-07T19:49:24+08:00 | action: created domain scaffold | source: approved Influential Brands Wiki architecture | result: initialized `index.md`, `catalog.md`, and `log.md`


- 2026-08-08T14:20:33+08:00 | run `20260808T014-full-ingest` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}

- 2026-08-08T14:22:52+08:00 | run `20260808T017-idempotency-rerun` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}

- 2026-08-09T00:20:28+08:00 | run `20260809T024-clean-reingest` | full-ingest | {"appointment": 1666, "brand": 145, "email-message": 4712, "industry": 237, "location": 6, "marketing-segment": 13, "meeting-event": 12, "organisation": 1431, "organisational-function": 4, "person": 2666, "source": 2}
- 2026-08-11T18:05:43+08:00 | query: "Which companies won the Top Influential Brands campaign in 2025?" | entity: [[query-which-companies-won-the-top-influential-brands-faecb7b5]] | action: created
- 2026-08-26T23:09:34+08:00 | query: "Find Ivan Hoe as part of the people entity" | entity: [[query-find-ivan-hoe-as-part-of-the-045bc435]] | action: created
