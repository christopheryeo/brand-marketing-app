# Campaign-Send Agent — Specification

**Status:** Decisions taken by Christopher on 15 Sep 2026 (Round 1–4) are recorded below. Action *behaviour* is confirmed by Christopher **subject to Jorge's review** (Jimmy chasing). Technical design lives in `campaign/DESIGN.md`.

**Sources:**
- Requirements — "Influential Brands Knowledge Requirements" Google Doc, section *Campaign-send agent behaviour (Jorge)*.
- Build plan — Google Doc `1s9Y36dA4NYHzdrHmQqfW4uTvYUXOsa1sXpzNR3ixm_Y` (Phases 0–5).

## Architecture at a glance (confirmed)

**Apollo.io is the sending platform.** Apollo runs the actual send, tracking, and the follow-up. **Our repo (the Knowledge Graph) owns**: recipient selection, campaign packs, and the response **Actions that update records** — driven by Apollo's reply/bounce/status events. So this is an **Apollo integration + Knowledge-Graph updater**, not an in-repo email sender.

---

## 1. What the agent does (high level)

1. Select the people to email (recipients) from the Knowledge Graph.
2. Select a **campaign pack** — email header, email body, attachment — where packs are editable, addable, and deletable.
3. **Create an Apollo sequence from the pack** (subject/body/attachment + the 1-week follow-up step) via the Apollo API, then **enroll** the selected recipients into it (Apollo sends + tracks + follows up).
4. **Consume Apollo's response events** and take one of six Actions.

---

## 2. The six Actions — CONFIRMED (subject to Jorge review)

| # | Trigger | Agent behaviour | Owner | Confirm |
|---|---|---|---|---|
| Action 1 | Recipient does **not** reply | Follow-up email **one week** later | **Apollo** (sequence step) | ✅ |
| Action 2 | Reply, **interested** | Arrange a call — **Google Meet** via Calendar | Repo | ✅ |
| Action 3 | Reply **adds colleagues** | Add the new **real people** to records (skip role mailboxes) | Repo (DB) | ✅ |
| Action 4 | Email **bounced** | Set `emailBounced: true` on the record | Repo (DB) | ✅ |
| Action 5 | Auto-reply — **left the company** | Set `departed: true` on the record | Repo (DB) | ✅ |
| Action 6 | Auto-reply — **on leave**, alternate contact given | **Auto-enroll the alternate contact** in Apollo | Repo → Apollo | ✅ |

**Action 7 — DROPPED (9 Sep 2026):** duplicated Action 3. Not built.

---

## 3. Resolved questions (Christopher, 15 Sep 2026)

- **Pack → sequence (creation):** the agent **creates the Apollo sequence from the pack** via the API (subject/body/attachment + the 1-week follow-up step), then enrolls recipients into it — packs are not pre-built in Apollo by hand.
- **Follow-up cadence (Action 1):** exactly **one** follow-up at 1 week — created as the sequence's second step.
- **"Interested" (Action 2):** classified by LLM (see §5) at **confidence ≥ 0.90 + evidence**; borderline cases go to **human review**, not auto-action.
- **Zoom/call (Action 2):** **Google Meet** via the native Calendar connector (not Zoom).
- **Colleague add (Action 3):** add **real individuals only**; skip generic role mailboxes (info@/sales@/support@), matching the vault ingestion rule.
- **Bounce / left-company (Actions 4/5):** two **separate booleans** — `emailBounced` and `departed` — with history kept in `entities/people/log.md`.
- **Alternate contact (Action 6):** **auto-enroll** in the Apollo sequence (no manual step).
- **Recipient eligibility:** a person **may be in multiple campaigns**, but recipient selection **always excludes a suppression / opt-out list**.
- **Suppression population:** the suppression list is **manual only** — entries are added by an authorised person. Bounces (Action 4) and left-company (Action 5) set their own record flags but do **not** auto-add to suppression.
- **Action 2 call host:** the Google Meet is hosted on a **shared team calendar** (not an individual's), so any campaign call lands on the same calendar.
- **Response signals:** read from **Apollo (API/webhook)**, not by monitoring a mailbox.
- **Timezone:** SGT.

---

## 4. Sending authority (CONFIRMED)

- **Sender identity:** **shared mailbox** (e.g. `campaigns@…`), connected to Apollo.
- **Who may launch** (enroll a recipient list into an Apollo sequence): **named authorised users only.** Composing packs and selecting recipients may be broader.

| Role / person | Compose pack | Select recipients | **Launch (enroll to Apollo)** |
|---|---|---|---|
| _(fill the authorised names)_ | ☐ | ☐ | ☐ |

**Standing guardrail:** launching a campaign is a deliberate, authorised action (named users only). The one place our repo composes a *new* outbound — Action 2's Google Meet proposal — is prepared for human confirmation where the invitee is unverified.

---

## 5. Integrations (CONFIRMED)

| Concern | Choice | Native? |
|---|---|---|
| **Send / track / follow-up** | **Apollo.io** (sequences) | Apollo API — key in `.env.local` (same pattern as enrichment) |
| **Response signals** (reply/bounce/auto-reply) | **Apollo API / webhook** → repo Actions | Apollo API |
| **Call (Action 2)** | **Google Meet** via **native Calendar** connector, hosted on a **shared team calendar** | ✅ Native |
| **Reply classification** | **LLM — OpenAI `gpt-4o-mini`** (existing app model path) | Native HTTP + `.env.local` key |
| **Record updates** (Actions 3/4/5) | Internal vault writeback (`record_enrichment` / `set_to_enhance` pattern) | ✅ Internal |

**Notes:**
- No Zapier is required; Apollo, OpenAI, and Google are reached via their own APIs / native connectors.
- Apollo API access needs an Apollo key in `.env.local` (gitignored) — to confirm the exact scope/plan supports sequence enrollment + event webhooks.

---

## 6. Build sequence (revised for Apollo)

Phase 1 foundations (packs, recipient picker + suppression, DB-agent wrapper, `create_person`) → Apollo integration (enroll a list into a sequence; consume events) → Actions 2–6 wired to Apollo events → hardening/reporting. **In-repo email send and inbound-mailbox monitoring are NOT built** (Apollo owns them). See `campaign/DESIGN.md` for the technical design.
