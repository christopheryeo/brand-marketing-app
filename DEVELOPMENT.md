# DEVELOPMENT.md (draft for review)

Handoff file for Brand Marketing App (`christopheryeo/brand-marketing-app`). This is not the wiki constitution. Wiki rules stay in `AGENTS.md`. Shipped features stay in the Features section of `../../Alex (Dev)/Knowledge/Product Inventory.md`. Human-blocked work stays on Owen’s ClickUp.

## Roles

**Grok Bot (Felix).** Updates Now and Next. After a merged PR, writes a Features line only for a user-facing capability he can name. Does not copy every PR. Does not implement the front-end or the vault.

**Claude Code.** Implements front-end work listed under Now and named for Claude Code. Appends Done with implement or maintenance. Commits that work to a branch and opens or updates a PR. Does not invent features. Does not keep Now and Next. Does not write Product Inventory. Does not use the wiki tag.

**ChatGPT Codex.** Works the Influential Brands vault. Implements Now items named for ChatGPT Codex. Appends Done with the wiki tag only. Commits only tracked files for that Now line, on a branch, and opens or updates a PR. Does not keep Now and Next. Does not write Product Inventory. ChatGPT the chat product is not this role and cannot git.

**Morgan.** Does not keep this log.

**Christopher.** Does not keep this log and does not commit. Looks only when a line is blocked on his yes, and that wait is not recorded here.

## Policies

1. Features come from Now, or from a merged PR Felix has logged. Do not invent.
2. Now is work in implementation. Next is queued and not started. Every Now and Next line names one tool: Claude Code or ChatGPT Codex. One Now line is one tool and one branch. Claude Code implements only Now lines named for it. ChatGPT Codex implements only Now lines named for it. Felix moves a line from Next to Now when implementation starts.
3. If a line is waiting on a human, it does not belong here.
4. Do not copy wiki operating rules into this file. `AGENTS.md` stays the vault constitution, not a log.
5. Native GitHub only. Merged PRs on `christopheryeo/brand-marketing-app` wake Felix.
6. Use Singapore Time (SGT, UTC+8) on Done lines.
7. A merged PR is the gate, not the feature list. Felix writes a Features line in `../../Alex (Dev)/Knowledge/Product Inventory.md` only for a user-facing capability he can name. Bug fixes, refactors, docs, dependency bumps, and vault ingest do not go there. GitHub stays the source. A Done line never counts as shipped. Work that never gets a PR is not shipped. Claude Code and ChatGPT Codex do not write Product Inventory. Do not create another catalogue in this repo.
8. Done is one dated handoff list. Each line is tagged implement, wiki, or maintenance, then who, then what. Tags sit on the line. ChatGPT Codex uses wiki only. Claude Code uses implement or maintenance only. Do not make separate headings. Do not add a Feature tag.
9. `CLAUDE.md` imports `AGENTS.md` first, then this file.
10. The tool named on a Now line commits that work to a branch and opens or updates a PR. Nobody pushes to `main`. Nobody commits gitignored files (`entities/*` person notes, `Apps/wiki-data.js`, `Apps/people-directory.html`). ChatGPT Codex on a wiki line commits only tracked files (`scripts/`, `index.md`, `log.md`). Claude Code does the same for implement lines.

## Now

- (none)

## Next

- (none)

## Done

Format: `YYYY-MM-DD SGT — implement|wiki|maintenance — who — what`

- (none)
