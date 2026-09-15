# Campaign-Send Agent — Technical Design

**Companion to `campaign/SPEC.md`.** SPEC.md captures *what/whether* (for Jorge). This doc captures *how* — the engineering decisions a developer needs before Phase 1 code. Grounded in the current repo (Python scripts + Markdown/JSON entity store; no backend service; no existing email code).

**Status:** DRAFT for review. Items marked **DECISION** must be settled before the dependent build item is promoted.

---

## 1. Execution model (DECISION — this gates everything)

The repo is plain Python scripts. `ask_server.py` already calls an external HTTP API (OpenAI) **directly via `urllib` with a key from `.env.local`** — no MCP, no framework. The campaign agent should follow the same shape.

**Recommended:** the agent is a **Python module in this repo** that talks to Google directly via the **Gmail API (OAuth), not the MCP connector.** The MCP Gmail connector is for the *assistant's* ad-hoc use and is not callable from repo Python or an unattended run; the first-party Gmail API is the "native" equivalent for automated code and keeps the agent runnable like every other script here.

- Outbound send, draft creation, and inbound reads all use the Gmail API.
- Secrets (OAuth client + refresh token) live in `.env.local` (already gitignored), exactly like `OPENAI_API_KEY`.
- Alternatives to weigh: (b) an assistant/MCP-driven workflow (no unattended runs; Zapier for Gmail needs approval), (c) Zapier (prohibited without Christopher's approval per CLAUDE.md). **Recommend (a).**

Everything below assumes (a).

---

## 2. Repository layout

```
campaign/
  SPEC.md              # behaviour + decisions (Jorge)
  DESIGN.md            # this file
  packs/<id>.json      # campaign packs (tracked; no recipient data)
  attachments/<id>/…   # pack attachments (GITIGNORED if customer content)
  lists/<id>.json      # recipient lists — personIds only (tracked)
  sends/<id>.json      # a send: packId + listId + status (GITIGNORED — holds addresses at dispatch)
  events/<sendId>.jsonl# classified inbound events + reply text (GITIGNORED — PII)
  db_agent.py          # thin wrapper over the vault writeback (see §7)
  gmail.py             # Gmail API client (send/draft/read); key from .env.local
  classify.py          # reply classification (see §6)
  agent.py             # orchestration (send → monitor → Actions)
  tests/               # fixtures + dry-run tests
```

**`scripts/` stays for vault/build tooling; `campaign/` is the new agent module.**

---

## 3. Data model & PII rules

- **CampaignPack** `{id, subject, body, attachmentRef, createdAt, updatedAt, status}` — no recipient data → **tracked**.
- **RecipientList** `{id, name, personIds[], createdAt}` — people by **`personId` reference only, never copied** → **tracked**.
- **Send** `{id, packId, listId, createdAt, recipients: [{personId, email, state, timestamp, gmailThreadId, gmailMessageId}]}` — resolves emails at dispatch → **gitignored** (holds addresses).
- **Event** (one JSONL line per inbound) `{sendId, personId, class, evidence, threadId, at}` — holds reply text → **gitignored**.

**Gitignore additions:** `campaign/sends/`, `campaign/events/`, `campaign/attachments/` (mirroring how `Apps/wiki-data.js` is excluded because it embeds contact data). Tracked artifacts must contain **no email addresses or reply bodies**.

---

## 4. Email integration (§1 = Gmail API)

- **Send / draft:** `gmail.py` assembles MIME (subject + body + attachment) and creates a **draft by default**; an authorised trigger promotes draft→send (SPEC §4 guardrail). Dry-run mode writes the MIME to disk and never calls Gmail.
- **Monitor:** poll Gmail (`users.history.list` / `messages.list` with a saved `historyId` cursor) for replies to the campaign threads. Read-only.
- **Bounce / auto-reply:** detected from monitored messages — bounces via the `mailer-daemon` / `Auto-Submitted`/`Delivery Status Notification` signals; auto-replies via `Auto-Submitted: auto-replied` / vacation headers.

---

## 5. Inbound correlation (DECISION — blocks Phase 3)

Every inbound must map to a `(sendId, personId)`. Design: **capture `gmailThreadId` + `gmailMessageId` on each recipient at send time** (§3 Send). Replies are matched by `threadId`; bounces/auto-replies by `In-Reply-To`/`References` back to the sent `messageId`. If threading proves unreliable, fall back to a per-recipient token embedded in the send (e.g. a hidden `+campaign-<sendId>-<personId>` sub-address or a body marker). **Pick one before building the monitor.**

---

## 6. Reply classification (DECISION — for Actions 1/2/5/6)

Classification decides interested / left-company / on-leave+alt-contact. Reuse the repo's existing model path:

- **LLM via the existing pattern** — `.env.local` key + a `MODEL` constant (as `ask_server.py` does), or the local **`ollama_semantic_adapter`** for an offline option.
- Apply the vault's existing discipline: **confidence threshold (≥ 0.90) + evidence text**, and **route borderline cases to human review** rather than acting. Deterministic rules handle the unambiguous classes (bounce, auto-reply headers) with no model.
- **DECISION:** which model, and the exact thresholds per Action.

---

## 7. Database-agent contract (Actions 3/4/5) — reuse what exists

The "database agent" is **not new infrastructure** — it's the existing vault-writeback pattern:

- `scripts/record_enrichment.py` → `record_enrichment(person_id, provider, date, profile, *, root)` and `scripts/mark_to_enhance.py` → `set_to_enhance(person_id, value, *, root)` already do atomic frontmatter rewrite + append to `entities/people/log.md`.
- **`campaign/db_agent.py` wraps the same helpers** to expose:
  - `update_person(personId, changes, reason)` — Actions 4 (`emailStatus: bounced`) and 5 (mark departed) → one atomic frontmatter write + a `log.md` line (identical mechanism to `record_enrichment`).
  - `add_person(email, displayName, orgId?)` — Action 3 (see §8).
- **Constraint (Codex lane):** these writes touch **gitignored person notes** and append **tracked `log.md`**; commit only `log.md`/scripts, never person notes or PII.

---

## 8. `create_person` (Action 3) — currently missing, must be built

There is **no programmatic create-person today** — people are created only by `wiki_pipeline.py` ingestion. Build a canonical helper reusing the pipeline's identity logic:

- Use `wiki_pipeline.normalize_email()` and `stable_id("person", email)` (= `person-<slug>-<sha10>`) for the id — matching every existing personId.
- **Dedupe:** if the normalized email already resolves (via `query.py resolve`/catalog), update that person, don't create a duplicate.
- Link to the originating `organisationId` where known; write the note + `log.md` line; skip generic role mailboxes (info/sales/support), consistent with the ingestion rule.

---

## 9. Person-schema changes (Actions 4/5)

New Person fields require a schema update + migration, exactly as `ToEnhance` / `enrichment*` were added:

- `emailStatus`: `active | bounced | departed | null` (or split into `emailBounced` / `departed` booleans — **DECISION**).
- Update `schemas/person.schema.json` + the schema generation, and backfill existing records to the default (nullable), mirroring the `backfill_to_enhance.py` migration pattern.

---

## 10. Recipient picker (items 1–2)

- Source people via `query.py` (`tool_list_domain("people", …)` / `parse_catalog("people")`) — reuse, don't re-read files.
- **Filters are relationships, not flat columns:** company = `organisationId`, industry = `industryId`, segment = `marketingSegmentId` on the Person. Filtering needs a graph join (resolve the taxonomy id → filter people whose relationship matches), which `query.py related`/the catalog already supports.

---

## 11. Secrets

All credentials (Gmail OAuth, model key, Zoom if used) live in **`.env.local`** (already gitignored via `.env.*`). Nothing committed; provide a `.env.example` with key names only.

---

## 12. Idempotency & state

- Identity keys: `sendId`, `personId`, and per-Action keys (e.g. `followup:<sendId>:<personId>`).
- Every Action is **at-most-once**: check state before send/write; re-processing the same event is a no-op. This matches the repo's "idempotent, repeatable run" ethos.

---

## 13. Testing

- `campaign/tests/fixtures/` with sample **bounce, auto-reply (left / on-leave), interested, and neutral** emails.
- **All send/dispatch tests run in draft/dry-run only** — never a real Gmail send in CI. Vault-write tests use a temp `root` (as `record_enrichment`'s tests do).

---

## 14. Blocking decisions (summary)

1. **Execution model** (§1) — recommend Gmail-API-in-Python.
2. **Inbound correlation key** (§5) — thread/message id vs embedded token.
3. **Classification model + thresholds** (§6).
4. **`emailStatus` field shape** (§9).
5. Plus the SPEC.md §4/§5 decisions (sending authority, Zoom method).

Once 1–4 here and SPEC's §4/§5 are settled, Phase 1 items are ready to promote — the foundations (writeback, identity, secrets, query layer, model path) already exist in the repo.
