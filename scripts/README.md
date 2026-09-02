# Influential Brands Wiki Pipeline

Run commands from the Wiki root with the bundled Python runtime. The bundled runtime includes the JSON Schema validator required by the C0 entity gate.

```bash
python3 scripts/wiki_pipeline.py inventory --run-id <run-id>
python3 scripts/wiki_pipeline.py productionise --run-id <run-id>
python3 scripts/wiki_pipeline.py prepare --run-id <run-id>
python3 scripts/wiki_pipeline.py pilot --run-id <run-id>
IB_LLM_COMMAND='python3 scripts/ollama_semantic_adapter.py' IB_LLM_PROVIDER='Local Ollama' IB_LLM_MODEL='phi3:latest' IB_SEMANTIC_BATCH_CHARS=18000 IB_SEMANTIC_BATCH_ITEMS=16 python3 scripts/wiki_pipeline.py semantic --run-id <run-id>
python3 scripts/wiki_pipeline.py ingest --run-id <run-id>
python3 scripts/wiki_pipeline.py rebuild --run-id <run-id>
python3 scripts/wiki_pipeline.py validate --run-id <run-id> --scope all
python3 scripts/wiki_pipeline.py audit --run-id <run-id>
```

## MySQL query replica

The Markdown entity notes remain canonical. After rebuilding and validating the local SQLite index, synchronise its complete contents to the MySQL query replica configured in the ignored `.env.local` file:

```bash
python3 scripts/wiki_pipeline.py rebuild --run-id <run-id>
python3 scripts/wiki_pipeline.py validate --run-id <run-id> --scope all
python3 scripts/sync_mysql.py --run-id <run-id>
```

Use `python3 scripts/sync_mysql.py --check-only` to validate local inputs without connecting to or changing MySQL. The live sync replaces replica rows inside a transaction and verifies all table counts plus relationship integrity before commit. It writes a receipt under `runs/<run-id>/` and never copies credentials into that receipt.

The pipeline never edits the original source files. The default semantic adapter uses the locally installed Ollama model over localhost, so private OLM content does not leave the Mac. The optional `codex_semantic_adapter.py` is disabled by default and must not be used on private content without explicit external-transfer approval.

All failures produce a run receipt. Repairable generated-state failures can be retried with `repair`; ambiguous source facts remain in the run review queue. Every published semantic entity or outcome must pass exact-evidence, source-name, confidence and outcome-marker gates.

## Person enrichment

Run provider adapters in the fixed Apollo.io, Clay, LinkedIn order. Apollo is
required; Clay and LinkedIn are optional fallbacks. Each later adapter receives
the identifiers and profile fields returned by earlier adapters. A provider is
recorded only when the combined result reaches the minimum useful profile:
either a verified email/phone, or a LinkedIn URL plus a professional detail.

```bash
python3 scripts/run_person_enrichment.py <personId> \
  --provider-command 'apollo=path/to/apollo-adapter' \
  --provider-command 'clay=path/to/clay-adapter' \
  --provider-command 'linkedin=path/to/linkedin-adapter'
```

Adapters read a JSON request from standard input and return either a profile
object or `{"profile": {...}}` as JSON. If every configured provider fails to
produce a minimum useful profile, the runner keeps `ToEnhance` queued and writes
`enrichmentStatus: not_found` plus `enrichmentFound: false` for the apps.

`record_enrichment.py` remains available for recording a single already-
verified result from Apollo.io, Clay, or LinkedIn. It rejects incomplete
profiles rather than writing a misleading Enriched stamp.

## Legacy Clay enrichment writeback

After the Clay connector has successfully enhanced a canonical Person record,
record the completion date in SGT:

```bash
python3 scripts/mark_clay_enhanced.py <personId>
```

Use `--date YYYY-MM-DD` only when recording a verified earlier enhancement. The
command preserves the existing Person record and body, updates `updatedAt`, is
idempotent for the same date, and appends an audit entry to the People log. Do
not run it for queued, failed or unverified Clay operations.

## Canonical Markdown queries

`query.py` answers questions from canonical records under `entities/`. It uses
generated Markdown catalogs for navigation and reads entity-note frontmatter,
relationships, structured business outcomes and `sourceRefs` for evidence. It
does not read raw uploads, normalised inputs or generated database files.

Deterministic commands work without an API key:

```bash
python3 scripts/query.py resolve "UOB"
python3 scripts/query.py inspect organisation-uob-a508cdd695
python3 scripts/query.py search "Top Employer Award" --domains email-messages meetings-events
python3 scripts/query.py related organisation-uob-a508cdd695
python3 scripts/query.py outcomes --entity organisation-uob-a508cdd695
python3 scripts/query.py list organisations --limit 100
```

Autonomous and HTTP modes send selected canonical evidence to the OpenAI
Responses API. They are disabled by default. Use them only after the data owner
has approved that transfer, then set `QUERY_ALLOW_EXTERNAL=true` and provide
`OPENAI_API_KEY` through the process environment or ignored `.env.local` file:

```bash
QUERY_ALLOW_EXTERNAL=true python3 scripts/query.py ask "Who at UOB appears in the Wiki?" --json
QUERY_ALLOW_EXTERNAL=true python3 scripts/query.py serve --port 8080
```

Both cache switches default to on. Use `--no-cache-read` or `--no-cache-write`
for a read-through or non-persistent query. `QUERY_CACHE_READ`,
`QUERY_CACHE_WRITE`, `QUERY_MODEL` and `QUERY_PORT` provide environment-level
defaults. `QUERY_ALLOW_EXTERNAL` is an explicit safety gate, not a convenience
default.
