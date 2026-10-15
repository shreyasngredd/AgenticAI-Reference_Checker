# Research Companion

A literature research companion agent built in Python with the Claude Agent SDK
(`claude-agent-sdk`). It reads papers and helps write structured reading notes.

This is a **university assignment**, so clarity matters more than cleverness.

## Directory layout

- `papers/`: source papers (PDFs, text). Treat as read-only input.
- `notes/`: finished, human-reviewed notes. **The agent never writes here.**
- `drafts/`: the only place the agent may create or edit notes.
- `refs/`: written by refs mode (`python agent.py refs --input refs.txt`).
  - `library.json`: metadata fetched from Crossref. Entries with
    `"status": "edited"` have hand corrections and are not re-fetched.
  - `overrides.json`: hand corrections by id, applied on top of the library
    when formatting. Only `refs edit` and the `refs chat` agent's
    `edit_reference` tool write it; nothing else may overwrite it.
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
- `chat.py`: terminal reference-formatting chatbot (ClaudeSDKClient, keeps
  context; "exit" quits). Its only tools are `lookup_doi` and
  `search_crossref` (Crossref, using `agent.search_crossref_title`). The
  tools format the reference, set the OK / Check / Not found label and build
  the Google Scholar link in code;
  the model only relays them. It does not touch `refs/`.
- `app.py`: Streamlit app (`streamlit run app.py`) showing each library entry
  as a card: status colour, warnings, an editable reference text box and the
  two search buttons. Saving goes through `agent.apply_edit`, storing the text
  as the `reference_text` override (used exactly as typed, so the entry is
  marked `check`). It never sets the status itself.
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
- Keep API keys in environment variables (`ANTHROPIC_API_KEY`), never in code
  or committed files.
- Draft notes are Markdown files named after the paper, e.g.
  `drafts/smith-2023-attention.md`.
- Draft notes follow `notes/_template.md` (read it, never edit it). The agent
  leaves **My reaction** blank because that section is for the student.
