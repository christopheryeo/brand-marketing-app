# Campaign-Send Agent — Technical Design

**Companion to `campaign/SPEC.md`.** SPEC = *what/whether*; this = *how*. Updated 15 Sep 2026 for the confirmed **Apollo-centric** model. Grounded in the current repo (Python scripts + Markdown/JSON entity store; no backend; no in-repo email code).

**Confirmed model:** **Apollo.io sends, tracks, and follows up.** Our repo selects recipients, holds packs, **enrolls recipients into an Apollo sequence via the Apollo API**, and **consumes Apollo's response events** to update the Knowledge Graph and arrange Google Meet calls. We do **not** build an in-repo email sender or inbound-mailbox monitor.

---

## 1. Execution model (confirmed)

- The agent is a **Python module in this repo** that calls the **Apollo API** directly (key in `.env.local`, same pattern as the existing enrichment path and how `ask_server.py` calls OpenAI). No Zapier.
- **Outbound = Apollo.** We enroll a recipient list into an Apollo sequence; Apollo performs sends, tracking, and the 1-week follow-up (Action 1).
- **Inbound = Apollo events.** We consume Apollo reply/bounce/status events (webhook receiver or API poll) and fire Actions 2–6.
- Runs unattended (Apollo owns delivery timing); our side is event-driven + idempotent.

---

## 2. Repository layout

```
campaign/
  SPEC.md, DESIGN.md
  packs/<id>.json         # campaign packs (tracked; no recipient data)
  attachments/<id>/…      # pack attachments (GITIGNORED if customer content)
  lists/<id>.json         # recipient lists — personIds only (tracked)
  suppression.json        # opt-out / do-not-email list, by personId/email-hash (GITIGNORED)
  campaigns/<id>.json     # a launched campaign: packId + listId + apolloSequenceId + status (GITIGNORED — holds addresses)
  events/<campaignId>.jsonl # Apollo events + classification results (GITIGNORED — PII)
  apollo.py               # Apollo API client: enroll, fetch/receive events
  db_agent.py             # vault writeback wrapper (see §7)
  classify.py             # reply classification (see §6)
  meet.py                 # Google Meet via native Calendar (Action 2)
  agent.py                # orchestration: enroll → consume events → Actions
  tests/                  # fixtures + dry-run tests
```

---

## 3. Data model & PII rules

- **CampaignPack** `{id, subject, body, attachmentRef, createdAt, updatedAt, status}` — no recipient data → **tracked**.
- **RecipientList** `{id, name, personIds[], createdAt}` — people **by personId reference only** → **tracked**.
- **Campaign** `{id, packId, listId, apolloSequenceId, launchedBy, status, recipients:[{personId, email, apolloContactId, state}]}` — resolves addresses at enroll → **gitignored**.
- **Event** (JSONL) `{campaignId, personId, class, evidence, at}` from Apollo → **gitignored** (PII).
- **Suppression** list of personIds / email hashes → **gitignored**; recipient selection **always excludes it**.

**Gitignore additions:** `campaign/campaigns/`, `campaign/events/`, `campaign/attachments/`, `campaign/suppression.json`. Tracked files carry **no addresses or reply bodies**.

---

## 4. Apollo integration (replaces the old Gmail send/monitor)

- **Enroll:** `apollo.py` maps each recipient to an Apollo contact (by email; create in Apollo if absent) and adds them to the chosen **sequence**. Sender = the shared mailbox connected in Apollo. Launch is gated to **named authorised users** (§SPEC 4).
- **Events in:** prefer an **Apollo webhook** (a small receiver) for reply/bounce/auto-reply/status; fall back to periodic **API poll** if webhooks aren't on the plan. Each event carries the Apollo contact id → map back to `personId`.
- **DECISION to confirm:** Apollo plan/scope supports (a) sequence enrollment via API and (b) reply/bounce event delivery. If not, revisit.

---

## 5. Event → person correlation

Apollo events reference an **Apollo contact id** and the recipient email. Correlate to our `personId` via the `apolloContactId` stored on the Campaign at enroll time (primary), or by **normalized email** (fallback, using `wiki_pipeline.normalize_email`).

---

## 6. Reply classification (confirmed: OpenAI `gpt-4o-mini`)

- Deterministic signals first: **bounce** and **auto-reply** come from Apollo's own event types / headers — no model needed.
- For **interested** (Action 2), **left-company** vs **on-leave+alternate-contact** (Actions 5/6): classify the reply text with **OpenAI `gpt-4o-mini`** (key + `MODEL` from `.env.local`, exactly like `ask_server.py`).
- Apply the vault discipline: **confidence ≥ 0.90 + evidence text**; **borderline → human review**, never auto-act. On-leave parsing extracts the alternate contact's name + email.

---

## 7. Database-agent contract (Actions 3/4/5) — reuse existing writeback

`campaign/db_agent.py` wraps the proven pattern (`scripts/record_enrichment.py`, `scripts/mark_to_enhance.py`: atomic frontmatter rewrite + `entities/people/log.md` append):

- `set_email_bounced(personId)` → `emailBounced: true` (Action 4).
- `set_departed(personId)` → `departed: true` (Action 5).
- `add_person(email, displayName, orgId?)` → Action 3 (see §8).

Constraint (Codex lane): writes touch **gitignored person notes**, append **tracked `log.md`**; commit only `log.md`/scripts, never person notes or PII.

---

## 8. `create_person` (Action 3) — must be built

No programmatic create-person exists today (only `wiki_pipeline.py` ingestion). Build a helper that:
- uses `wiki_pipeline.normalize_email()` + `stable_id("person", email)` (= `person-<slug>-<sha10>`) — matching every existing personId;
- **dedupes** against the graph (via `query.py resolve`/catalog) — update, don't duplicate;
- links the originating `organisationId` where known; **skips role mailboxes** (info/sales/support), per the confirmed Action 3 rule.

---

## 9. Person-schema change (Actions 4/5) — confirmed shape

Add two **separate booleans** to the Person schema (nullable), like `ToEnhance`/`enrichment*` were added:
- `emailBounced`: `true | false | null`
- `departed`: `true | false | null`

Update `schemas/person.schema.json` + schema generation, and backfill existing records to `null` (mirror `backfill_to_enhance.py`).

---

## 10. Recipient picker (items 1–2)

- Source via `query.py` (`tool_list_domain("people")` / `parse_catalog("people")`).
- **Filters are relationships:** company = `organisationId`, industry = `industryId`, segment = `marketingSegmentId` — graph joins, not flat columns.
- **Always subtract the suppression list.** Multiple concurrent campaigns are allowed.

---

## 11. Secrets

`.env.local` (gitignored via `.env.*`) holds: **Apollo API key**, the OpenAI model key (already present), and Google OAuth for Calendar/Meet. Provide `.env.example` with key names only. Nothing committed.

---

## 12. Idempotency & state

- Keys: `campaignId`, `personId`, per-Action keys (e.g. `bounce:<campaignId>:<personId>`).
- Every Action is **at-most-once**: check state before acting; re-delivered Apollo events are no-ops. Matches the repo's idempotent-run ethos.

---

## 13. Testing

- `campaign/tests/fixtures/` with sample Apollo events (reply/interested, bounce, left-company, on-leave) — no live Apollo calls in CI.
- Enrollment tests run in **dry-run** (assert the payload; don't hit Apollo). Vault-write tests use a temp `root` (as `record_enrichment` tests do). Google Meet tested as a proposal, not a live booking.

---

## 14. Remaining decisions

1. **Apollo API capability** (§4): confirm the plan supports sequence enrollment + reply/bounce webhooks (or accept API polling).
2. Fill the **authorised-launcher names** (SPEC §4).

All other prior blockers are resolved: platform = Apollo, sender = shared mailbox, classification = gpt-4o-mini, call = Google Meet, field shape = `emailBounced`/`departed`, eligibility = multiple + suppression, signals = Apollo events.
