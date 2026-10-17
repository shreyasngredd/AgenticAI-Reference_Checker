# Research Companion

A literature research companion built in plain Python. Its main part is the
Streamlit "Reference Checker (beta)": it looks references up on Crossref and
formats and checks them. It is deterministic: no AI model calls, no API keys,
no Agent SDK; the network code uses `urllib` from the standard library. The
only third-party package is `streamlit` (`requirements.txt`).

This is a **university assignment**, so clarity matters more than cleverness.

## Directory layout

- `papers/`: source papers (PDFs, text). Treat as read-only input.
- `notes/`: finished, human-reviewed notes. **The agent never writes here.**
- `drafts/`: the only place the agent may create or edit notes.
- `refs/`: written by refs mode (`python agent.py refs --input refs.txt`).
  - `library.json`: metadata fetched from Crossref. Entries with
    `"status": "edited"` have hand corrections and are not re-fetched.
  - `overrides.json`: hand corrections by id, applied on top of the library
    when formatting. Only `refs edit` writes it; nothing else may
    overwrite it.
  - `references.md` and `last_run.json`: the generated list and the settings
    used to re-generate it. Unmatched or incomplete entries go under
    "Needs checking" with a reason, never into the main list.
  - Hand edits are recorded as a `note` in `library.json`, never in the
    reference text.
  - A line with no DOI is searched on Crossref by title. The thresholds
    (0.75 weak, 0.9 match, runner-up margin 0.05) are decisions in
    `specs/goal-spec.md` section 7. Only a clear match is used; otherwise the
    fields stay `not stated` and `title_search: {outcome, reasons,
    candidates}` is stored (not editable, like `verification`).
  - APA article titles are put into sentence case in code (`sentence_case`).
    `original_title` (Crossref's title, not editable) is shown next to it.
    Unclear casing is flagged `check`; proper nouns need human review.
  - Each resolved entry has a `cross_check` comparing Crossref's title, first
    author and year with OpenAlex and Semantic Scholar. The comparison is done
    in code (difflib title similarity, threshold 0.9), never by the model.
    Optional `SEMANTIC_SCHOLAR_API_KEY` env var avoids rate limits.
  - Each entry has `verification: {status, warnings}`, where status is
    `verified`, `check` or `not_found`. It is computed only in code
    (`validate_reference` for APA 7 fields + the cross-check). The model must
    never be able to set it: it is not an editable field and overrides
    cannot touch it. (`status` = `auto`/`edited` is a separate field.)
  - Each entry also has `search_links` (Google Scholar and Google searches for
    title + first author's family name, or the original line if not found).
    These URLs are only built, never requested or scraped.
- `agent.py`: the shared lookup, formatting, status and link code, plus the
  plain command-line refs mode (`refs`, `refs edit`). Removed 2026-10-18:
  the Agent SDK paper mode, the `refs chat` agent and `chat.py`.
- `app.py`: Streamlit reference chat "Reference Checker (beta)" (`streamlit run app.py`), spec in
  `specs/goal-spec.md`. It only draws; the logic is in `refchat.py` (no
  Streamlit import, so `parse_command` and `handle_message` are testable). The sidebar shows `refchat.help_text()`, the same text as `help`.
  Paste DOIs or titles; commands `style`, `list`, `edit N field value`,
  `find SURNAME YEAR [topic words]`, `add N`, `clear`, `help`. `find`
  (`agent.search_crossref_author_year`) shows up to 5 "APA 7 preview" results
  and `add N` keeps one; both are always `Check` (`from_search` on the entry,
  read by `verify`), never Verified. Crossref only (`resolve_line(..., cross_check_sources=False)`
  and `verify(..., crossref_only=True)`): Verified means the DOI resolved or
  the title search found a clear match (`crossref_identified`), with nothing
  else to check, and is shown as "Verified against Crossref only". Edits live
  in `st.session_state` only (lost on reload); it never writes `refs/` or any
  file. Tests: `tests/test_refchat.py`, one class per acceptance criterion.
  `accept N` confirms a Check reference (the student's call; it stays Check).
  Each reference / latest `find` result has an "Add to export" button and a
  Style dropdown sits top right; they only send `accept N`, `add N` then
  `accept M`, or `style X` (`refchat.button_for` / `press_button`, history
  `items`), so the commands still work. Tests: `tests/test_buttons.py` (69–73).
  The Field dropdown (`fields.py`, reads `config/fields.json`, never writes
  it) limits `find` and title lookups to a field's ISSNs (Crossref `issn`
  filter plus `agent.in_journals` in code); DOI lookups ignore it. A broken
  file falls back to "All fields" with a warning. Tests:
  `tests/test_fields.py` (36–45). **My list** (`mylist.py`) is separate from
  the export: "Add to list" beside each reference, latest `find` result or
  title-search candidate (candidates are looked up by DOI, always `Check`)
  keeps a snapshot with its status; no duplicates (DOI, else normalised
  title); always shown in the current style; `my_list.txt` / `my_list.csv`
  built in memory. **Search my list** (`listsearch.py`, shared with `list
  FILTER`): case- and accent-insensitive, words ANDed, quoted phrases exact,
  plus Status filter and Sort; it never changes the list, and the files hold
  the full list unless "Export only matching" is ticked. Tests:
  `tests/test_listsearch.py` (107–117). `refchat.render_reply` redraws lookup/`add`/`list` blocks
  in the current style. Tests: `tests/test_mylist.py` (75–87).
  The export (sidebar `st.download_button`s, built in memory by `export.py`)
  is Verified + confirmed references, sorted by first author and year, as
  `references.txt` and `references.csv` (UTF-8 with BOM). `cite N` gives the
  in-text citations in the current style (`citations.py`, rules in spec 7.7):
  organisation-only authors (`organisation_authors`) are cited by name; no
  author uses the shortened title and no year uses n.d. / no date, both
  `Check`; mixed organisation and person authors build nothing; duplicate
  citations are `Check`. Never guessed.
  Tests: `tests/test_export.py` (criteria 48–65).
  Added 2026-10-16 (spec section 3 "In-text citations", "Provisional
  results", "Live suggestions"; decisions 7.7, 7.8): every card shows its
  in-text citation in the current style (`citations.py`, APA 7 / Harvard /
  Chicago author-date; `refchat.card_citation`), drawn as two `st.code`
  boxes. A Check or Not found title search with a closest candidate shows a
  **provisional** reference from `title_search["closest"]` (kept only with
  `resolve_line(..., keep_closest=True)`), labelled with an orange badge and
  its match score; it keeps its status, is never Verified, and is marked
  `[CHECK] (provisional)` in the .txt files and `provisional` in the .csv
  files. No candidate: "No match found", nothing built. DOI links
  (`doi.org`, `dx.doi.org`, `doi:`, percent-encoded) are found by
  `agent.find_doi`; `refchat.input_kind` auto-detects DOI vs title; a quoted
  line is always a title. `suggest.py` gives live Crossref suggestions
  (4+ characters, cache, 1 request/second, 30 s pause after an error) for
  `st.text_input(live="500ms")`; choosing one only fills the Look up box.
  `CROSSREF_MAILTO` (env var, optional) adds Crossref's `mailto`. Tests:
  `tests/test_citations.py`, `test_provisional.py`, `test_input.py`,
  `test_suggest.py` (criteria 119–145).
  Changed 2026-10-16 (decision 7.9, interface only): one input bar at the
  top. A single line `SURNAME YEAR [topic]` (at most 4 words, year
  1900-2099) is `find` (`refchat.interpret`); several lines stay DOI/title
  lookups. Each reply keeps `read_as` (not in the reply text) and offers a
  "Search as ... instead" button (`switch_for`). `#apa #harvard #chicago`,
  `#all` and field tags derived from the names in `config/fields.json`
  (`#psychology`, `#is`, `#information-systems`; `refchat.split_tags`)
  change the settings shown by the style and field chips (popovers).
  Cards have only Add to list (`mylist.card_list_button`) and Copy
  (`refchat.copy_text`). The sidebar has only My list (search, Remove,
  Clear, my_list.txt/.csv) and a Help expander (`refchat.quick_help`).
  Removed from the page (code and tests kept): the dropdowns, suggestions,
  Add to export, the references export downloads, Status/Sort/Export only
  matching, candidate buttons. Tests: `tests/test_simple_ui.py` (149-163);
  criterion 161 compares replies with
  `tests/fixtures/before_simplification.json` (recorded before 7.9).
- `drafts/references_apa.md`: written on every refs run or edit, always in
  APA 7: each reference followed by its status, warnings and the two links.

## Hard rules

### 1. Write only to `drafts/`
- The agent writes new notes only to `drafts/`, never to `notes/`.
- It must not create, edit, move, or delete anything in `notes/` (or `papers/`).
- Enforce this in code, not just in the prompt. Restrict the agent's write tools
  (for example with a permission callback or hook) so writes outside `drafts/`
  are rejected.
- A human moves a draft into `notes/` after reviewing it.

### 2. Never invent citations or claims
- Every claim, number, author, year, venue, or citation must come from the
  source paper the agent was given. No guessing, no filling gaps from memory.
- If a field is missing from the source, write exactly `not stated`.
  Do not leave it blank and do not estimate it.
- Do not make up references, DOIs, URLs, or page numbers.
- If unsure whether the source supports something, leave it out or mark it
  `not stated`.

### 3. Keep code simple and commented
- Prefer plain functions and straightforward control flow over abstractions,
  classes, or clever one-liners.
- Add short comments explaining *what* each block does and *why*, so a
  marker reading it can follow along.
- Give every function a docstring.
- Avoid unnecessary dependencies. Use the standard library where it is enough.
- Keep files small and focused. Readable beats compact.

## Conventions

- Python 3.10+.
- Tests: `python -m unittest discover tests` (standard library, no network).
- No AI model calls and no `claude_agent_sdk` / `anthropic` imports anywhere.
  Optional keys (`SEMANTIC_SCHOLAR_API_KEY`) live in environment variables,
  never in code or committed files.
- `requirements.txt` lists only third-party packages actually imported
  (currently just `streamlit`).
- Draft notes are Markdown files named after the paper, e.g.
  `drafts/smith-2023-attention.md`.
- Draft notes follow `notes/_template.md` (read it, never edit it). The agent
  leaves **My reaction** blank because that section is for the student.
