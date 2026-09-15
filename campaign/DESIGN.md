# Campaign-Send Agent — Technical Design

**Companion to `campaign/SPEC.md`.** SPEC = *what/whether*; this = *how*. Updated 15 Sep 2026 for the confirmed **Apollo-centric** model. Grounded in the current repo (Python scripts + Markdown/JSON entity store; no backend; no in-repo email code).

**Confirmed model:** **Apollo.io sends, tracks, and follows up.** Our repo selects recipients, holds packs, **enrolls recipients into an Apollo sequence via the Apollo API**, and **consumes Apollo's response events** to update the Knowledge Graph and arrange Google Meet calls. We do **not** build an in-repo email sender or inbound-mailbox monitor.

---

## 1. Execution model (confirmed)

- The agent is a **Python module in this repo** that calls the **Apollo API** directly. **`apollo.py` is greenfield** — there is *no* existing in-repo Apollo client to reuse: `run_person_enrichment.py` shells out to external provider **adapter commands**, it does not call Apollo's HTTP API. The real direct-API precedent to mirror is **`ask_server.py`** (OpenAI via `urllib` + key from `.env.local`). Add a new **`APOLLO_API_KEY`** to `.env.local`. No Zapier.
- **Outbound = Apollo.** We **create the Apollo sequence from the pack** (subject/body/attachment + a 1-week follow-up step) via the API, then enroll the recipient list into it; Apollo performs sends, tracking, and the follow-up (Action 1).
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
  runs/<id>.json          # a launch's transient Apollo state: packId + listId + campaignId + apolloSequenceId + per-recipient contactId/state (GITIGNORED — holds addresses). Participation itself is a graph relationship, not this file.
  events/<runId>.jsonl    # Apollo events + classification results (GITIGNORED — PII)
  apollo.py               # Apollo API client: enroll, fetch/receive events
  db_agent.py             # vault writeback wrapper (see §7)
  classify.py             # reply classification (see §6)
  meet.py                 # Google Meet via native Calendar, shared team calendar (Action 2)
  agent.py                # orchestration: enroll → consume events → Actions
```

Tests live in the repo's existing **top-level `tests/`** (e.g. `tests/test_record_enrichment.py`, `tests/test_query.py`), not under `campaign/` — new suites go there as `tests/test_campaign_*.py`, with fixtures under `tests/fixtures/`.

---

## 3. Data model & PII rules

**Graph-native participation (AGENTS rule 8).** A **marketing-campaign** is an existing entity (`schemas/marketing-campaign.schema.json`: `campaignId`, `name`, …) and enrollment is a **Person↔Campaign relationship** (`schemas/relationship.schema.json`: `fromId`/`toId`/`relationshipType`), **not** a duplicate store. So:

- A launched campaign is a **marketing-campaign entity** (create via the vault, reuse `campaignId`).
- Each enrolled recipient is a **relationship** `{fromId: personId, toId: campaignId, relationshipType: "enrolledInCampaign", sourceRefs}` — the canonical record of who was in what. Written on the **Codex/wiki lane** (§7), committed as tracked entity + `log.md`.
- The loose `campaign/` JSON below holds **only transient Apollo runtime state** (contact/sequence ids, per-recipient send state) — never the system of record for participation.

- **CampaignPack** `{id, subject, body, attachmentRef, createdAt, updatedAt, status}` — no recipient data → **tracked**.
- **RecipientList** `{id, name, personIds[], createdAt}` — people **by personId reference only** → **tracked**.
- **CampaignRun** (transient) `{id, packId, listId, campaignId, apolloSequenceId, launchedBy, status, recipients:[{personId, apolloContactId, state}]}` — Apollo runtime mapping; addresses resolved at enroll → **gitignored**. Participation itself lives in the graph (above), not here.
- **Event** (JSONL) `{runId, personId, class, evidence, at}` from Apollo → **gitignored** (PII).
- **Suppression** list of personIds / email hashes → **gitignored**; recipient selection **always excludes it**. **Populated manually only** — `db_agent` exposes an `add_suppression(personId, reason)` helper for an authorised person; Actions 4/5 do **not** write to it.

**Gitignore additions:** `campaign/runs/`, `campaign/events/`, `campaign/attachments/`, `campaign/suppression.json`. Tracked files carry **no addresses or reply bodies**.

---

## 4. Apollo integration (replaces the old Gmail send/monitor)

- **Create sequence:** `apollo.py` builds an Apollo sequence from the pack — step 1 = the pack's subject/body/attachment, step 2 = the 1-week follow-up — and returns its `apolloSequenceId`. Created once per launch (or reused if the pack already maps to a live sequence).
- **Enroll:** `apollo.py` maps each recipient to an Apollo contact (by email; create in Apollo if absent) and adds them to that sequence. Sender = the shared mailbox connected in Apollo. Launch is gated to **named authorised users** (§SPEC 4).
- **Events in:** prefer an **Apollo webhook** (a small receiver) for reply/bounce/auto-reply/status; fall back to periodic **API poll** if webhooks aren't on the plan. Each event carries the Apollo contact id → map back to `personId`.
- **DECISION to confirm:** Apollo plan/scope supports (a) **sequence creation** + enrollment via API and (b) reply/bounce event delivery. If sequence-create isn't on the API, fall back to referencing a pre-built sequence per pack.

---

## 5. Event → person correlation

Apollo events reference an **Apollo contact id** and the recipient email. Correlate to our `personId` via the `apolloContactId` stored on the **CampaignRun** at enroll time (primary), or by **normalized email** (fallback, using `wiki_pipeline.normalize_email`).

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
- `add_suppression(personId, reason)` → append to `suppression.json` (manual only; not called by any Action).

**Lane (DEVELOPMENT.md).** Everything in §7–§9 — `db_agent.py`, `create_person`, the schema change, and the **Person↔Campaign enrollment relationship** (§3) — is the **ChatGPT Codex / wiki** lane (writes entity records, `schemas/`, `log.md`). The `campaign/` picker, `apollo.py`, `meet.py`, `agent.py` are the **Claude Code / implement** lane. They ship as **separate Now prompts / PRs** (SPEC §6).

Constraint (Codex lane): writes touch **gitignored person notes**, append **tracked `log.md`**; commit only `log.md`/scripts/schemas, never person notes or PII.

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

**Hand-edit** `schemas/person.schema.json` (it is maintained by hand — there is no schema generator; `generate_catalog.py` builds catalogs, not schemas), then backfill existing records to `null` with a new script mirroring `backfill_to_enhance.py`.

---

## 10. Recipient picker (items 1–2)

- Source via `query.py` (`tool_list_domain("people")` / `parse_catalog("people")`).
- **Filters are relationships:** company = `organisationId`, industry = `industryId`, segment = `marketingSegmentId` — graph joins, not flat columns.
- **Always subtract the suppression list** (manually maintained; see §3/§7). Multiple concurrent campaigns are allowed.

---

## 11. Secrets

`.env.local` (gitignored via `.env.*`) holds: **`APOLLO_API_KEY`** (new — no Apollo key exists in-repo today), the OpenAI model key (already present, read by `ask_server.py`), and Google OAuth for Calendar/Meet. Provide a new `.env.example` (does not exist yet) with key names only. Nothing committed.

---

## 12. Idempotency & state

- Keys: `campaignId`, `personId`, per-Action keys (e.g. `bounce:<campaignId>:<personId>`).
- Every Action is **at-most-once**: check state before acting; re-delivered Apollo events are no-ops. Matches the repo's idempotent-run ethos.

---

## 13. Testing

- `tests/fixtures/` (repo top-level `tests/`, alongside `test_record_enrichment.py`) with sample Apollo events (reply/interested, bounce, left-company, on-leave) — no live Apollo calls in CI.
- Enrollment tests run in **dry-run** (assert the payload; don't hit Apollo). Vault-write tests use a temp `root` (as `record_enrichment` tests do). Google Meet tested as a proposal, not a live booking.

---

## 14. Remaining decisions

1. **Apollo API capability** (§4): confirm the plan supports **sequence creation** + enrollment + reply/bounce webhooks (or accept the fallbacks: pre-built sequence per pack; API polling).
2. Fill the **authorised-launcher names** (SPEC §4).
3. Name the **shared team calendar** that hosts Action 2 Meet calls (calendar id for `meet.py`).

All other prior blockers are resolved: platform = Apollo, pack→sequence = agent-created via API, sender = shared mailbox, classification = gpt-4o-mini, call = Google Meet on a shared team calendar, field shape = `emailBounced`/`departed`, eligibility = multiple + manual suppression, signals = Apollo events.
