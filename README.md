# Influential Brands Wiki

A file-based knowledge vault for Influential Brands contacts, organisations, campaigns, communications and commercial activity.

## Source of truth

- Entity notes under `entities/` are the canonical Wiki records.
- Original uploads under `raw/` are immutable and must not be edited.
- Normalised, ingest-ready material belongs under `Inputs/`.
- Generated catalogs, indexes, dashboards and run receipts can be rebuilt.

## Core workflow

1. Register each uploaded artifact as a Source entity.
2. Preserve the original artifact under `raw/`.
3. Extract and normalise records into `Inputs/`.
4. Resolve, create or update canonical entities.
5. Record relationships and source locations.
6. Rebuild catalogs and the query index.
7. Validate schemas, links and duplicate identities.
8. Write an append-only run receipt under `runs/`.

## Pipeline scope

`scripts/wiki_pipeline.py` is specific to the Influential Brands Wiki. It processes this customer's Excel database and Outlook OLM archive and supports ingestion, rebuilding, validation, repair and audit operations for this Wiki only. It is not a shared customer-Wiki utility: the `tampines-wiki` and `indonesia-politics` customer folders do not contain or use this script. The copy under `Alex (Dev)/Scratchpad/influential-brands-build/` is the development/build counterpart; the copy in this folder is the operational customer version.

## System files

Every entity and operational domain contains:

1. `index.md` — curated operating manual and preliminary field registry.
2. `catalog.md` — generated complete listing; never hand-edit.
3. `log.md` — append-only audit ledger.

## Business outcomes

Actions, commitments and decisions found in communications are structured attributes of the Email Message, Meeting/Event, Campaign, Project/Initiative or Sales Opportunity where they originated. They are indexed for retrieval but are not standalone business entities.

## Folder map

- `raw/` — immutable original files.
- `Inputs/` — normalised ingest-ready content.
- `entities/` — canonical Wiki records.
- `schemas/` — approved schemas.
- `scripts/` — deterministic ingestion, validation and query tooling.
- `index/` — generated query indexes.
- `dashboards/` — dashboard application and definitions.
- `topics/` — topic-monitoring configurations.
- `runs/` — dated run receipts.
- `tests/` — automated tests and synthetic fixtures.
- `tmp/` — regenerable staging and extraction material.
