# Influential Brands Wiki Agent Instructions

## Mandatory startup

Read `README.md` before operating in this Wiki. Read `DEVELOPMENT.md` for Now, Next, and Done. Do not log Done in this file. Read the relevant domain's `entities/<domain>/index.md` before creating or updating an entity.

## Operating rules

1. Treat Markdown entity notes as the canonical Wiki records.
2. Never edit original uploads under `raw/`.
3. Keep catalogs and query indexes generated; do not hand-edit generated outputs.
4. Keep every domain's `log.md` append-only.
5. Record an accepted governance note under `entities/decisions/` before changing an approved schema or operating rule.
6. Resolve identities before creating entities; do not create one entity per source row when the person or organisation already exists.
7. Link derived information to a Source entity and retain the source locator, such as worksheet row or OLM message path.
8. Store campaign participation as a Person–Campaign relationship, not a duplicate Person or Campaign.
9. Store actions, commitments and business decisions as structured attributes on their originating activity; index them for fast retrieval.
10. Use Singapore Time (SGT, UTC+8) for operational timestamps.
11. Never commit credentials, extracted private data, dependency folders, caches or generated indexes.

## Learned Preferences

### Query Tooling — `query.py` First

For all future information queries about the Influential Brands Wiki, use
`scripts/query.py` as the first query interface. Use its deterministic Markdown
commands (`resolve`, `inspect`, `search`, `list`, `related`, `outcomes`, and
`cache`) to retrieve and verify answers from canonical entity records. Do not
bypass it with raw-file or `Inputs/` searches. If it cannot answer a query,
report the limitation and diagnose the query tooling before using a different
Wiki retrieval path.

**Why:** Christopher explicitly requested on 2026-08-11 that `query.py` be used
for all future Wiki information queries.

**How to apply:** This activates whenever Christopher asks for factual,
relationship, roster, activity, outcome, or source information held in this
Wiki. Autonomous external API mode remains subject to its explicit transfer
approval gate; deterministic local commands are the default.
