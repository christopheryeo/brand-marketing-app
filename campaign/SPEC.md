# Campaign-Send Agent — Specification (draft for confirmation)

**Status:** DRAFT — captured, not locked. Every behaviour below is Jorge's stated intent (captured 4 Sep 2026) and must be **confirmed or corrected by Jorge** (weekend review, via Comments / Suggested edits) before any Action is implemented. No Action code is written until its checklist line is confirmed.

**Sources:**
- Requirements — "Influential Brands Knowledge Requirements" Google Doc, section *Campaign-send agent behaviour (Jorge)*.
- Build plan — Google Doc `1s9Y36dA4NYHzdrHmQqfW4uTvYUXOsa1sXpzNR3ixm_Y` (Phases 0–5).

**Scope of this doc:** capture the agent's behaviour, open questions, sending-authority options, and integration choices. It does **not** implement anything.

---

## 1. What the agent does (high level)

1. Select the people to email (recipients) from the Knowledge Graph.
2. Select a **campaign pack** — email header, email body, and attachment — where packs are editable, addable (as many as needed), and deletable.
3. Send the pack to the selected recipients.
4. Watch each recipient's response and take one of six Actions.

---

## 2. The six Actions — confirmation checklist

Mark each line ✅ (confirmed) or ✍️ (corrected) — the correction goes in the Notes column.

| # | Trigger | Agent behaviour | Confirm | Notes |
|---|---|---|---|---|
| Action 1 | Recipient does **not** reply | Plan a follow-up email **one week** later | ☐ | |
| Action 2 | Recipient replies, **interested** to find out more | **Arrange a Zoom call** | ☐ | |
| Action 3 | Recipient replies and **adds colleagues** to the thread | Tell the **database agent** to add the new people to records | ☐ | |
| Action 4 | Email **bounced** | Tell the **database agent** to update the record | ☐ | |
| Action 5 | **Auto-reply** — person has **left the company** | Tell the **database agent** to update the record | ☐ | |
| Action 6 | **Auto-reply** — person **on leave**, suggests an alternate contact | **Send the email to the alternate contact** named in the auto-reply | ☐ | |

**Action 7 — DROPPED (9 Sep 2026, per Jorge):** it duplicated Action 3. Not to be built.

---

## 3. Open questions (confirmation checklist)

Resolve each before the relevant build item starts.

- ☐ **Follow-up cadence (Action 1):** exactly one follow-up at 1 week, or a further sequence after that? Stop condition?
- ☐ **"Interested" definition (Action 2):** what signals count as interested vs neutral vs negative? Who confirms borderline cases?
- ☐ **Zoom arrangement (Action 2):** does the agent propose times, or auto-book? (Default assumption: propose/draft for human confirmation — see §4.)
- ☐ **Colleague add (Action 3):** add every new address, or only non–role mailboxes? What org do they inherit?
- ☐ **Bounce handling (Action 4):** hard bounce only, or soft bounces after N tries? What flag is written?
- ☐ **Left-company (Action 5):** mark inactive vs departed vs delete? Keep for history?
- ☐ **Alternate contact (Action 6):** send immediately, or create a draft for review first? Same pack, or a tweaker intro?
- ☐ **Recipient eligibility:** may the same person be emailed by more than one campaign? Any suppression/opt-out list?
- ☐ **Campaign pack ownership:** who may create/edit/delete packs?
- ☐ **Timezone for the 1-week timer and sends:** SGT assumed unless corrected.

---

## 4. Sending authority (decision pending — leave blank for Christopher / Jorge)

Which identity sends, and who may trigger a send. (Planning refs A2–A3.)

| Option | What it means | Pros | Cons | Chosen? |
|---|---|---|---|---|
| **Named-user mailbox** | Sends come from a specific person's account (e.g. a salesperson) | Personal, higher reply rates; replies land in that person's inbox | Ties campaign to one person; access/rotation issues; per-user auth | ☐ |
| **Shared mailbox** | Sends come from a team/shared address (e.g. campaigns@…) | Team-owned, survives staff change; central monitoring | Less personal; shared-mailbox send/monitor permissions needed | ☐ |

**Who may trigger a send** (fill in):

| Role / person | May compose pack | May select recipients | May trigger the actual send |
|---|---|---|---|
| _(to fill)_ | ☐ | ☐ | ☐ |

**Standing guardrail (applies regardless of choice):** every outbound send **defaults to a draft for human review and is not auto-sent** unless an authorised person explicitly triggers it. This mirrors the organisation's email-review rule and is the safety gate for Actions 1, 2 (proposal), and 6.

---

## 5. Integrations (choose the channel; note native vs approval-needed)

"Native" = a first-party MCP connector is available (preferred, per policy). "Needs approval" = only a Zapier-routed option is known, which requires Christopher's explicit approval before use.

| Concern | Purpose | Candidate | Native? | Decision |
|---|---|---|---|---|
| **Outbound email** | Send the pack (drafts-first) | **Gmail** native connector | ✅ Native (supports drafts) | ☐ |
| **Inbound monitor** | Read/classify replies, bounces, auto-replies | **Gmail** native connector (thread/search reads) | ✅ Native (a polling/watch loop still to design) | ☐ |
| **Zoom** (Action 2) | Arrange the call | Zoom API | ⚠️ No native connector known → **needs approval** (Zapier), **or** substitute Google Calendar/Meet (native) | ☐ |
| **Database-agent handoff** (Actions 3/4/5) | Add/update Knowledge Graph records | Internal — the vault write path (Codex side, `entities/people` + `log.md`) | ✅ Internal, no external connector | ☐ |

**Notes:**
- Outbound + inbound both map cleanly onto the **native Gmail** connector; no Zapier needed for the core send/monitor loop.
- **Zoom is the one likely approval item.** If a native Zoom path isn't available, the fallback is either (a) Christopher approves the Zapier Zoom action, or (b) the agent proposes a **Google Meet** event via the native Calendar connector instead. Decision needed before Action 2.
- The **database agent** is a separate component (the vault-write side). This spec assumes it exists / will be built; the campaign agent only calls a defined interface (`add_person`, `update_person`) — see build-plan item 27.

---

## 6. Build sequence (reference)

Implementation follows the build plan's phases: Phase 0 (this spec + decisions) → Phase 1 foundations (packs, recipients, db-agent interface) → Phase 2 sending (drafts-first) → Phase 3 response monitoring → Phase 4 the six Actions → Phase 5 hardening/reporting. No Action is started until §2 and its §3 questions are confirmed.
