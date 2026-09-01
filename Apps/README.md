# Influential Brands — Wiki Apps

Self-contained HTML apps for browsing the **Influential Brands** knowledge vault — an
Obsidian-style vault of entity notes (people, organisations, brands, appointments,
emails, campaigns, and more) with JSON frontmatter.

No server, no login, no internet required for browsing: the vault data is baked directly
into each HTML file, so you just double-click to open.

## What's in here

| File | What it is |
|---|---|
| `wiki-browser.html` | **The main app.** A unified browser across all 18 entity types (~11.3k nodes, ~23.5k cross-links). Three panes: entity-type sidebar · searchable list · detail view. Clickable forward relationships, a "Referenced by" reverse-link section, and back/forward navigation. Also hosts the **Ask the Wiki** AI chat tab. |
| `people-directory.html` | A lighter, people-only view — searchable list of every person with a detail card (role, organisation, industry, location, contact, and Clay-enhancement date). |
| `Ask the Wiki.command` | Double-click launcher for the AI chat. Starts the local server and opens the wiki in your browser. |
| `People Directory.command` | Double-click launcher for the **editable** People Directory. Starts a local server and opens the directory in your browser, where the **To Enhance** checkbox saves back to each person's record. |

## How to use

### Browse (no setup)
Double-click **`wiki-browser.html`** (or `people-directory.html`). Everything works
offline — search, click through relationships, navigate back and forth.

### Flag people for enhancement (editable To Enhance)
Double-click **`People Directory.command`**. This starts a local server and opens the
People Directory in your browser. Each person's record shows a **To Enhance** checkbox:
tick it to flag that person for enhancement (`ToEnhance=true`), untick to clear it
(`false`). Changes save straight to the person's vault record (with an audit line in
`entities/people/log.md`). The checkbox only saves through this launcher — opening
`people-directory.html` directly (file double-click) shows it read-only.

### Ask the Wiki (AI chat)
Double-click **`Ask the Wiki.command`**. This launches a small local server that reads
the vault, retrieves the records relevant to your question, and answers with strict
vault-only grounding (answers include clickable source chips that jump into the wiki).

- Ask natural-language questions like *"What have we done with Panasonic?"*
- The chat needs the local server because a static HTML file can't hold an API key or
  call an AI model. The plain double-click of `wiki-browser.html` still works for
  browsing — the Ask tab just shows a "launch the server" message if opened without it.
- Close the Terminal window that opens to stop the server.

## Where the data comes from

These HTML files are **generated artifacts**, compiled from the vault by scripts that
live one level up, in the vault root:

```
influential-brands/
├─ Apps/                         ← this repo (the built apps)
│  ├─ wiki-browser.html
│  ├─ people-directory.html
│  └─ Ask the Wiki.command
├─ entities/                     ← source notes (people, organisations, …)
├─ scripts/
│  ├─ wiki-browser/build_wiki.py            → builds Apps/wiki-browser.html
│  ├─ wiki-browser/ask_server.py            → serves the Ask the Wiki chat
│  ├─ wiki-browser/template_wiki.html       → HTML template (no data)
│  └─ people-directory/build_people_directory.py → builds Apps/people-directory.html
└─ .env.local                    ← API key + DB creds (never committed)
```

> `template_wiki.html` is the empty blueprint (no data) — opening it directly shows a
> blank shell. Always open the built files in this `Apps/` folder.

## Rebuilding after the vault changes

From the vault root (`influential-brands/`):

```bash
python3 scripts/wiki-browser/build_wiki.py                 # rebuilds Apps/wiki-browser.html
python3 scripts/people-directory/build_people_directory.py # rebuilds Apps/people-directory.html
```

Each script reports the node/link counts and file size on completion.

## Notes

- **Clay Enhanced:** person records carry an optional `clayEnhanced` date (the date of
  the latest successful Clay enrichment). Both apps display it; it's set via
  `scripts/mark_clay_enhanced.py <personId>` after a verified enrichment.
- These files are large (the wiki is ~6.6 MB) because all vault data is embedded — this
  is what makes them fully self-contained.
