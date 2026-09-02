# DEVELOPMENT.md

Handoff file for Brand Marketing App (`christopheryeo/brand-marketing-app`). This is not the wiki constitution. Wiki rules stay in `AGENTS.md`. Shipped features stay in the Features section of `../../Alex (Dev)/Knowledge/Product Inventory.md`. Human-blocked work stays on Owen’s ClickUp.

## Roles

**Grok Bot (Felix).** Updates Now and Next. Writes each Now line as a short prompt the named tool can follow. After a merged PR, writes a Features line only for a user-facing capability he can name. Does not copy every PR. Does not implement the front-end or the vault.

**Claude Code.** Implements the Now prompt named for Claude Code. Appends Done with implement or maintenance. Commits that work to a branch and opens or updates a PR. In that same PR, deletes only the Now line it just finished. Must not add Now or Next. Does not invent features. Does not write Product Inventory. Does not use the wiki tag.

**ChatGPT Codex.** Works the Influential Brands vault. Implements the Now prompt named for ChatGPT Codex. Appends Done with the wiki tag only. Commits only tracked files for that Now line, on a branch, and opens or updates a PR. In that same PR, deletes only the Now line it just finished. Must not add Now or Next. Does not write Product Inventory. ChatGPT the chat product is not this role and cannot git.

**Morgan.** Does not keep this log.

**Christopher.** Does not keep this log and does not commit. Looks only when a line is blocked on his yes, and that wait is not recorded here.

## Policies

1. Features come from Now, or from a merged PR Felix has logged. Do not invent.
2. Now is a short prompt for one named tool, not a title. Next is queued and not started. Every Now and Next line names one tool: Claude Code or ChatGPT Codex. One Now line is one tool and one branch. The prompt names the surface, files it may touch, files it must not touch, the git rules, and a link to the PR for detail when one exists. Do not open or link GitHub Issues. Queued work stays in Next. Do not dump a novel. Claude Code already loads this file through `CLAUDE.md`. Claude Code implements only Now prompts named for it. ChatGPT Codex implements only Now prompts named for it. Felix moves a line from Next to Now when implementation starts.
3. If a line is waiting on a human, it does not belong here.
4. Do not copy wiki operating rules into this file. `AGENTS.md` stays the vault constitution, not a log.
5. Native GitHub only. Merged PRs on `christopheryeo/brand-marketing-app` wake Felix.
6. Use Singapore Time (SGT, UTC+8) on Done lines.
7. A merged PR is the gate, not the feature list. Felix writes a Features line in `../../Alex (Dev)/Knowledge/Product Inventory.md` only for a user-facing capability he can name. Bug fixes, refactors, docs, dependency bumps, and vault ingest do not go there. GitHub stays the source. A Done line never counts as shipped. Work that never gets a PR is not shipped. Claude Code and ChatGPT Codex do not write Product Inventory. Do not create another catalogue in this repo.
8. Done is one dated handoff list. Each line is tagged implement, wiki, or maintenance, then who, then what. Tags sit on the line. ChatGPT Codex uses wiki only. Claude Code uses implement or maintenance only. Do not make separate headings. Do not add a Feature tag. Done gets a line only when the named tool actually opened this file.
9. `CLAUDE.md` imports `AGENTS.md` first, then this file.
10. The tool named on a Now line commits that work to a branch and opens or updates a PR. Nobody pushes to `main`. Nobody commits gitignored files (`entities/*` person notes, `Apps/wiki-data.js`, `Apps/people-directory.html`). ChatGPT Codex on a wiki line commits only tracked files (`scripts/`, `index.md`, `log.md`). Claude Code does the same for implement lines.
11. One Now cycle is one branch and one PR. In that same PR the named tool must (a) commit the Now work, (b) delete only the Now line it just finished, and (c) append one Done line. Do not open a second PR only to clear Now. Do not clear Now without Done. Do not add Now or Next. Felix still writes Now and Next.

## Now (prompt for the named tool)

Format: tool — surface — files it may touch — files it must not touch — git — link

- Claude Code — docs: consolidate to one root `README.md` for this repo (`christopheryeo/brand-marketing-app`). Keep the vault workflow. Folder map must match disk: include `Apps/`, `DEVELOPMENT.md`, and `CLAUDE.md`; drop phantom `dashboards/` and `topics/`. Fold in useful Apps content (Wiki Browser, People Directory, To Enhance, rebuild commands, **Enriched** as provider + date on both surfaces). Delete `Apps/README.md`. Do not invent Features. Do not commit gitignored app data (`wiki-data.js`, `people-directory.html`) or person notes. Do not push to `main`. Finish in one PR with work, clear this Now line, and one Done line (Policy 11).


## Next

- (none)

## Done

Format: `YYYY-MM-DD SGT — implement|wiki|maintenance — who — what`

- 2026-09-02 SGT — wiki — ChatGPT Codex — completed the `ToEnhance` Person batch: Clay found no verified contact match for the sole queued record, so the LinkedIn fallback recorded the verified profile, current role, and professional history; the queue is now clear
- 2026-09-02 SGT — implement — Claude Code — People Directory now surfaces provider+date (build passes `enrichmentProvider`/`enrichmentDate`; shows "Enriched: date · provider"); To Enhance checkbox simplified to a bare box to match the Wiki Browser
- 2026-09-02 SGT — implement — Claude Code — People Directory and Wiki Browser show enrichment provider-neutrally ("Enriched: date · provider", reading `enrichmentProvider`/`enrichmentDate` with `clayEnhanced` fallback) instead of Clay-only framing; `ToEnhance` kept as the editable queue flag
- 2026-09-02 SGT — wiki — ChatGPT Codex — added provider-neutral person enrichment writeback (scripts/record_enrichment.py; Clay mark path updated); Now was cleared in a separate PR, so this line records the missing Done.
- 2026-09-01 SGT — maintenance — Claude Code — audited committed HTML (`Apps/wiki-browser.html` and tracked `scripts/**/*.html` templates) for private data such as emails and company names; none found (data stays in gitignored `wiki-data.js` / `people-directory.html`)
