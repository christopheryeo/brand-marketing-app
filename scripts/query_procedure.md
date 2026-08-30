---
type: procedure
name: influential-brands-entity-query
status: active
last_updated: 2026-08-11
---

# Influential Brands Wiki Query Procedure

Answer natural-language questions from the canonical Markdown entity records in
`entities/`. Catalogs are the navigation layer. Entity-note frontmatter and body
sections are the factual layer. `sourceRefs` provide traceability.

Do not read or search original uploads under `raw/`, normalised material under
`Inputs/`, temporary files, run artifacts, or any generated database. If a fact
has not reached a canonical entity note, it is not queryable yet and must not be
inferred from an unprocessed source.

## Query shapes

Choose the smallest workflow that answers the question:

1. **Identity/profile** — resolve and inspect a person, organisation, brand,
   appointment, product/service, location, industry, function, segment, or topic.
2. **Roster** — list a complete domain from its `catalog.md`; do not open every
   entity merely to construct the roster.
3. **Relationship** — resolve the anchor entity, inspect its typed inbound and
   outbound relationships, then inspect only the relevant linked records.
4. **Activity/history** — search canonical email, meeting/event, campaign,
   project/initiative, and sales-opportunity notes; inspect the highest-ranked
   relevant records and order dated facts chronologically when appropriate.
5. **Actions, commitments, or decisions** — query structured business outcomes
   on their originating activity records. Governance decisions under
   `entities/decisions/` are separate and concern Wiki operating rules.
6. **Cross-cutting/topic** — search canonical notes across relevant domains,
   inspect the strongest matches, and follow typed relationships only where they
   materially answer the question.

## Step 0 — Check the saved-query cache

When cache reading is enabled, call `search_cache` before doing new work.

- A wording overlap is only a candidate. Reuse an answer only if it answers the
  same question and its resolved entities have not been updated since the cached
  answer's `updatedAt`.
- Treat relative questions such as “current”, “latest”, “recent”, “this week”,
  and “now” as time-sensitive. Do not reuse them when their time frame has moved.
- Do not reuse an answer produced under an older `procedureVersion` when the
  changed procedure could alter the result.
- On a valid reuse, return the saved answer and set `reused_query_id`. Otherwise
  continue with a new query.

## Step 1 — Resolve identities and scope

Extract all named entities and determine the likely domains. Call
`resolve_entity` for each name. Resolution uses catalog names and IDs plus aliases,
emails, and acronyms stored in canonical frontmatter.

- Prefer exact name, ID, email, or alias matches.
- A person and a brand or organisation can legitimately share a name; select the
  domain implied by the question.
- When multiple candidates remain plausible, state the ambiguity. In a headless
  run, answer only the unambiguous portion rather than guessing.
- For “all/every/list” questions, use `list_domain` and report whether the result
  was truncated.

## Step 2 — Inspect the canonical records

Call `inspect_entity` for each resolved anchor. Use:

- typed frontmatter for names, dates, statuses, emails, classifications,
  participants, appointments, and source references;
- `## Summary` for the compiled description;
- structured `outcomes` for actions, commitments, and business decisions;
- typed relationships for connected people, organisations, brands, campaigns,
  topics, and activities.

Generic summary wording such as “Canonical person record for…” does not establish
business history. Use the actual structured fields and connected activity records.

## Step 3 — Search canonical activity when needed

Use `search_entities` when the question concerns communications, events, history,
workstreams, opportunities, campaigns, or a topic that cannot be answered from one
entity. Restrict domains when the question clearly identifies the activity type.

Search results are candidates, not evidence by themselves. Inspect the relevant
records before asserting a fact. Prefer records where the query term appears in a
specific field, outcome, participant, title, or substantive summary. Do not treat
a shared keyword as proof of a relationship.

For action-oriented questions, call `business_outcomes`. Actions, commitments,
and business decisions remain attributes of the originating email, meeting,
campaign, project, or opportunity; do not convert them into standalone entities.

## Step 4 — Traverse relationships deliberately

Use `related_entity` for questions such as:

- who belongs to or communicated with an organisation;
- which organisation, brand, industry, location, or function is linked to a person;
- who participated in a meeting or email;
- which activities concern a campaign, project, opportunity, or topic.

Inspect only links needed to answer the question. Distinguish a direct typed
relationship from two entities merely appearing in separate records with similar
language.

## Step 5 — Ground and answer

Compose the answer solely from records actually inspected.

- Every factual claim must be traceable to a canonical entity and, where present,
  its `sourceRefs` locator.
- Preserve uncertainty, nulls, status, and confidence. Absence of a canonical
  record means “not found in the canonical Wiki”, not proof that the underlying
  real-world fact does not exist.
- Use Singapore Time (SGT, UTC+8) for operational dates and relative-time framing.
- Do not use live web results or model background knowledge.
- Answer directly and naturally. Do not narrate catalogs, tools, caches, files, or
  this procedure unless the user asks how the answer was produced.
- Do not append a source list unless the user asks for sources. Always populate
  `entities_resolved` and `sources_cited` internally. `sources_cited` should contain
  the canonical Source IDs found in the supporting records' `sourceRefs`.
- Set status to `unresolved` when the canonical records cannot support an answer.

## Step 6 — Save the query answer

When cache writing is enabled and the answer was not reused, the runtime writes a
schema-compatible query entity under `entities/search/`, appends the domain log,
and regenerates the search catalog. This records the question, answer, resolved
entities, cited Source IDs, time sensitivity, and procedure version.

Saving a query answer does not author or modify facts in any business entity.
Permanent factual changes must go through the Wiki's normal governed ingestion or
entity-update workflow.
