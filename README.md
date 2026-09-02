# Influential Brands Wiki

A file-based knowledge vault for Influential Brands contacts, organisations, campaigns, communications and commercial activity — plus self-contained browser apps for exploring and enriching it.

## Source of truth

- Entity notes under `entities/` are the canonical Wiki records.
- Original uploads under `raw/` are immutable and must not be edited.
- Normalised, ingest-ready material belongs under `Inputs/`.
- Generated catalogs, indexes, run receipts and the built apps can all be rebuilt.

## Core workflow

1. Register each uploaded artifact as a Source entity.
2. Preserve the original artifact under `raw/`.
3. Extract and normalise records into `Inputs/`.
4. Resolve, create or update canonical entities.
5. Record relationships and source locations.
6. Rebuild catalogs and the query index.
7. Validate schemas, links and duplicate identities.
8. Write an append-only run receipt under `runs/`.

## Apps

`Apps/` holds self-contained HTML apps compiled from the vault. The vault data is baked
into each HTML file, so browsing needs no server, login or internet — just double-click.

| File | What it is |
|---|---|
| `Apps/wiki-browser.html` | **The main app.** A unified browser across all 18 entity types (~11.3k nodes, ~23.5k cross-links). Three panes: entity-type sidebar · searchable list · detail view. Clickable forward relationships, a "Referenced by" reverse-link section, back/forward navigation, and an **Ask the Wiki** AI chat tab. |
| `Apps/people-directory.html` | A lighter, people-only view — searchable list of every person with a detail card (role, organisation, industry, location, contact). |
| `Apps/Ask the Wiki.command` | Double-click launcher for the Wiki Browser with the AI chat (and editable **To Enhance**). Starts the local server and opens it in your browser. |
| `Apps/People Directory.command` | Double-click launcher for the **editable** People Directory. Starts a local server so the **To Enhance** checkbox saves back to each person's record. |

**Enrichment & To Enhance.** Both apps show an **Enriched** field as *date · provider*
(e.g. `2 Sept 2026 · LinkedIn`, `27 Aug 2026 · Clay`), or `—` when a person has not been
enriched. It reads the provider-neutral `enrichmentProvider` / `enrichmentDate` fields
(falling back to the legacy `clayEnhanced` date). Each person also has an editable **To
Enhance** checkbox — tick it to queue that person for enrichment (`ToEnhance=true`),
untick to clear it (`false`). Ticking saves straight to the person's vault record with an
audit line in `entities/people/log.md`; it only saves through the `.command` launchers
(opening an HTML file directly shows the checkbox read-only).

- **Enrichment runner:** `scripts/run_person_enrichment.py` tries Apollo.io first,
  then configured Clay and LinkedIn fallbacks, carrying forward identifiers and
  fields from each attempt. It clears `ToEnhance` only after a minimum useful
  profile lands; otherwise it records the explicit no-enrichment state the apps show.
- **Enrichment writeback:** `scripts/record_enrichment.py` records a single verified
  Apollo.io, Clay, or LinkedIn result.
- **Ask the Wiki** needs the local server because a static HTML file can't hold an API
  key or call a model; plain browsing of `wiki-browser.html` still works offline.

### Rebuilding the apps

The built HTML/data files are generated artifacts (and are gitignored where they embed
vault data). Rebuild from the vault root after the vault changes:

```bash
python3 scripts/wiki-browser/build_wiki.py                 # rebuilds Apps/wiki-browser.html (+ wiki-data.js)
python3 scripts/people-directory/build_people_directory.py # rebuilds Apps/people-directory.html
```

`scripts/wiki-browser/template_wiki.html` is the empty blueprint (no data) — opening it
directly shows a blank shell. Always open the built files in `Apps/`.

## Pipeline scope

`scripts/wiki_pipeline.py` is specific to the Influential Brands Wiki. It processes this customer's Excel database and Outlook OLM archive and supports ingestion, rebuilding, validation, repair and audit operations for this Wiki only. It is not a shared customer-Wiki utility. The copy under `Alex (Dev)/Scratchpad/influential-brands-build/` is the development/build counterpart; the copy in this folder is the operational customer version.

## System files

Every entity and operational domain contains:

1. `index.md` — curated operating manual and preliminary field registry.
2. `catalog.md` — generated complete listing; never hand-edit.
3. `log.md` — append-only audit ledger.

## Business outcomes

Actions, commitments and decisions found in communications are structured attributes of the Email Message, Meeting/Event, Campaign, Project/Initiative or Sales Opportunity where they originated. They are indexed for retrieval but are not standalone business entities.

## Folder map

- `Apps/` — self-contained browser apps and their double-click launchers.
- `raw/` — immutable original files.
- `Inputs/` — normalised ingest-ready content.
- `entities/` — canonical Wiki records.
- `schemas/` — approved schemas.
- `scripts/` — deterministic ingestion, validation, query and app-build tooling.
- `index/` — generated query indexes.
- `runs/` — dated run receipts.
- `tests/` — automated tests and synthetic fixtures.
- `tmp/` — regenerable staging and extraction material.

## Agent docs

- `AGENTS.md` — the vault constitution (operating rules for working the Wiki).
- `DEVELOPMENT.md` — the Now / Next / Done handoff log for this repo (`christopheryeo/brand-marketing-app`).
- `CLAUDE.md` — imports `AGENTS.md` then `DEVELOPMENT.md` for Claude Code.
