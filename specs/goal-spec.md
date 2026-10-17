# Goal spec: Reference Checker (beta), the Streamlit reference chat

## 1. Goal

A chat page in the Streamlit app (`streamlit run app.py`) where the student
pastes DOIs or paper titles and gets back APA 7 references (Chicago or Harvard
on request), each with a status worked out in code, built only from Crossref
metadata and never invented. The student can also search Crossref by author
surname and publication year (`find`), see up to 5 candidates, and add the
right one to the list (`add N`). A **Field** setting (a group, then one or
more sub-fields) limits `find` and title lookups to hand-picked journals, and a
**Top journals** panel limits them to chosen journals or a ranking list such
as FT50, overriding the field (section 3, "Field setting" and "Top
journals"). Only journals whose title and ISSNs were checked against Crossref
by `scripts/verify_journals.py` are ever used (section 7.5). An **Add to list** button beside every result collects references
into **My list** in the sidebar, which downloads as .txt or .csv (section 3,
"My list"). The chat replaces the old card view of `refs/library.json`.

Changed 2026-10-16 (decision 7.9): the interface is simplified to one input bar with auto-detection (DOI, title, or author and year), style and field chips that `#tags` can also set, cards with only **Add to list** and **Copy**, and a sidebar holding only My list. The logic is unchanged.

Added 2026-10-16 (pending approval): every result card shows its in-text
citation (parenthetical and narrative, each with a copy button) in the
selected style (section 3, "In-text citations"); `Check` and `Not found`
title lookups that have a closest candidate show a **provisional** reference
built from that candidate, clearly labelled (section 3, "Provisional
results"); DOI links are accepted like bare DOIs; and a **Suggestions** box
above the chat offers Crossref titles while the student types (section 3,
"Live suggestions").

## 2. Constraints

- **No AI model calls and no API keys.** The chat makes no request to
  Anthropic, OpenAI or any other model provider, and reads no key.
- **Crossref only.** The only host the chat requests is `api.crossref.org`.
  It never contacts OpenAlex or Semantic Scholar (no cross-check), and it
  never requests the Google Scholar or Google links it builds.
- **No duplicated logic.** Lookup, title search, author-and-year search,
  formatting, status and links come from `agent.py` (`resolve_line`,
  `search_crossref_author_year`, `verify`, `shown_text`, `search_links`,
  `parse_value`). The chat code only calls them.
- **Crossref is free and needs no key.** The author-and-year search uses the
  public `api.crossref.org/works` endpoint, like the other lookups.
- **Command parsing is a separate function** (`refchat.parse_command`) in a
  file that does not import Streamlit, so it can be tested on its own.
- **Journal lists are configuration, not code.** The journals for each
  sub-field are in `config/fields.json` and the ranking lists in
  `config/top_journals.json` (name and ISSNs per journal), read with the
  standard library. Changing them needs no code change. The chat only reads
  these files.
- **Journal data is verified, not guessed.** No ISSN is typed from memory.
  `scripts/verify_journals.py` (run by hand, live Crossref) checks every
  journal in both files against `api.crossref.org/journals` and writes
  `config/journals_verified.json` and `reports/journal_verification.md`. The
  chat uses a journal only if it appears, with exactly the same name and
  ISSNs, in `config/journals_verified.json` (section 7.5). The chat only
  reads that file; only the script writes it.
- **Session only.** Chat history, references and edits live in
  `st.session_state`. Nothing is written to disk: not `refs/`, not `notes/`,
  not `drafts/`. Edits are lost when the page is reloaded.
- **Title similarity** is `difflib.SequenceMatcher(...).ratio()` on
  normalised titles (lowercase, accents, HTML tags and punctuation removed,
  spaces collapsed), rounded to 2 decimals (`agent.title_similarity`).
- **Simple and commented** code (university assignment): plain functions,
  a comment on each block, a docstring on each function.
- **Nothing invented.** Every field of a reference, provisional reference or
  in-text citation comes from Crossref's record (or the student's own
  `edit`). Code may only rearrange and punctuate those fields by the rules of
  section 7.7; where a rule needs a judgement code can't make, the citation
  is marked `Check` instead.
- **Crossref etiquette.** Every request to `api.crossref.org` (chat and
  refs mode, through `agent.get_json`) adds `mailto=<address>` (Crossref's "polite pool") when the environment
  variable `CROSSREF_MAILTO` is set; it is not a key and is never written in
  code or committed files. Without it, requests are sent as today. Live
  suggestions are limited further (section 7.8).
- **No new dependency for suggestions.** The Suggestions box is Streamlit's
  own `st.text_input(live=...)` (Streamlit 1.66), not a third-party
  component.

## 3. Inputs and outputs

### Inputs

One message from `st.chat_input`. The whole message is either one command or
a lookup:

| Message | Meaning |
|---|---|
| `style apa`, `style chicago`, `style harvard` | Use that style for later replies. APA 7 is the default. |
| `list` | Show every reference so far, numbered, in the current style. |
| `edit N field value` | Set `field` of reference N to `value` (the rest of the message). |
| `find SURNAME YEAR [topic words]` | Search Crossref for works by that author published in that year, optionally narrowed by topic words. Shows up to 5 candidates. |
| `add N` | Add result N of the latest `find` to the references. |
| `accept N` | Confirm reference N, a `Check` reference you have checked yourself, so it goes in the export. |
| `cite N` | Show the in-text citations (parenthetical and narrative) for reference N, in the current style. |
| `clear` | Forget all references, the latest search and the chat history; style back to APA 7. |
| `help` | Show the full help (the same text as the sidebar, below). |
| anything else | A lookup: each non-blank line is one DOI or title. |

> **Superseded by 7.9:** a one-line message of at most 4 words with a year 1900–2099 after a surname is read as `find <line>`; `#tags` change the style and field. Commands are unchanged.

- Command words are not case-sensitive. A command must be the whole message.
- A message whose first word is a command but whose arguments are wrong
  (e.g. `style mla`, `list 2`, `edit two year 2015`) gets the short help
  message, and nothing is looked up.
- A single word that is not a command and contains no DOI (e.g. `hello`)
  gets the short help message, and nothing is looked up.
- `find`: the **year** is the first word after `find` that is exactly four
  digits. The words before it are the **surname** (so `find van der Berg 2019`
  works), and must contain at least one letter. The words after it are the
  optional **topic words**. A `find` with no surname, no year, or a year that
  is not four digits (`find`, `find smith`, `find 2019`, `find smith 15`,
  `find smith 20x5`) gets the short help message, and nothing is looked up.
- `add N`, `accept N`, `cite N`: N is a whole number. `add`, `add two`,
  `accept 1 2` or `cite` get the short help message.
- **Auto-detection** (`refchat.input_kind`): a line is a **DOI** if it
  contains `10.<4-9 digits>/<non-space characters>` after
  `agent.find_doi` has normalised it; otherwise it is a **title**. So a bare
  DOI, a DOI link or a pasted reference that ends with its DOI link is a DOI
  lookup, and anything else is a title search; `find` is not needed for a
  plain title. Normalising (`agent.find_doi`, changed 2026-10-16):
  - prefixes `https://doi.org/`, `http://doi.org/`, `https://dx.doi.org/`,
    `http://dx.doi.org/`, `https://www.doi.org/`, `doi:` and `DOI:` (with or
    without a space after the colon), in any case, are dropped;
  - percent-encoding in a DOI link is decoded (`10.1038%2Fnature14539` ->
    `10.1038/nature14539`);
  - trailing `.`, `,`, `;`, `)` and `]` are dropped, as now.
  The DOI looked up is exactly what is left; nothing is added to it.
- A title that starts with a command word (e.g. "List decoding of ...")
  would be read as the command. Putting the whole line in double quotes
  (`"List decoding of ..."`) makes it a title search; the quotes are removed
  before searching.
- `edit` fields are the citation fields of `agent.CITATION_FIELDS`. Values are
  checked by `agent.parse_value` (authors as `Family, Given; Family, Given`,
  `not stated` to clear a field). Changing `type` clears the old type's
  fields, as `refs edit` does.

### Outputs

> **Superseded by 7.9:** each card also shows its interpretation line; the in-text citation is one line, and the copy boxes are in the Copy popover.

For each looked-up line, in order, one reply block:

- the reference's **number** (its position in `list`);
- the **reference text** in the current style, with italics rendered. When
  the title search has a closest candidate but no clear match, the
  **provisional reference** instead ("Provisional results", below). When
  there is nothing at all, no reference: only "No match found" and the line
  as typed, labelled "You typed:";
- the **in-text citation** in the current style, parenthetical and
  narrative, each in its own box with a copy button ("In-text citations",
  below). None when no reference or provisional reference was built;
- for APA, the **original title** when the sentence-case title differs;
- the **status**: `Verified`, `Check`, `Not found` or `Unavailable`;
- the **reasons**, for every status except `Verified`;
- for `Verified`, the line **"Verified against Crossref only"**;
- a **Google Scholar** and a **Google** search link (`agent.search_links`):
  title + first author's family name, or the line as typed when nothing was
  found.

### Sidebar

> **Superseded by 7.9:** the sidebar holds only My list (search, Remove, Clear, the two My list downloads) and a collapsed short Help.

The page heading is the title **Reference Checker (beta)**, a one-line subtitle
and a one-line intro; the details are in the sidebar (`st.sidebar`), which
always shows, top to bottom:

- the **Field** setting (group dropdown and sub-field multiselect), and the
  field-list warning when there is one ("Field setting", below);
- the **Top journals** panel: the journal multiselect, one button per ranking
  list, **Reset to all journals**, and the line "Searched in: ..." ("Top
  journals", below);
- **My list (N)**: the items, each with a **Remove** button, a **Clear list**
  button, and two `st.download_button`s, for `my_list.txt` and `my_list.csv`
  ("My list", below);
- an **Export** section: how many references are in the export, a checkbox
  **Include in-text citations in .txt files** (ticked by default; it applies
  to `references.txt` and `my_list.txt`), and two `st.download_button`s, for
  `references.txt` and `references.csv` ("Export", below);
- the full help from `refchat.help_text()`: every command with a one-line
  example, what each status means (`Verified` against Crossref only,
  `Check`, `Not found`, `Unavailable`), and the session note "Edits are kept
  for this session only and are lost when you reload the page."

The `help` command replies with the same `help_text()`, so the two can't
differ.

### Search results (`find`)

`find` asks Crossref once, with `query.author` = the surname,
`filter=from-pub-date:YEAR,until-pub-date:YEAR`, `query.bibliographic` = the
topic words (only when there are any), and `rows=5`. Crossref decides which
works match; the chat does no further author matching (section 6).

For each result, in Crossref's order, numbered from 1 (at most 5):

- the heading **"Result N (APA 7 preview)"**. Results are always shown in
  APA 7, whatever the current style;
- the reference text in APA 7, ending with its DOI link;
- the original title when the sentence-case title differs;
- the status `Check` with the reason
  **"search result, not verified: pick the right one"**, followed by any other
  problem code finds (e.g. a missing volume);
- a Google Scholar and a Google search link, as for a lookup.

Results are not references: `find` adds nothing to `list`. They are kept as
the **latest search** until the next `find` that reaches Crossref, or `clear`.

`add N` copies result N of the latest search to the end of the references and
replies with its reply block (section 3 outputs), under its reference number.
From then on it is an ordinary reference: it follows the current style, and
can be edited. Its status is always `Check` with the reason
**"added from a search; paste its DOI to verify"**; its reference text
includes the DOI so the student can do that. Pasting the DOI is a normal
lookup and adds a new reference; there is no `verify` command.

### Field setting (`find` and title lookups)

The top of the sidebar has a **Group** dropdown and a **Sub-fields**
multiselect. The groups are "All fields" first (the default), then each group
in `config/fields.json` in the file's order (section 7.3): "Computer Science",
"Management Science", and the existing fields' group (see 7.3). The
multiselect offers the chosen group's sub-fields in the file's order; it is
hidden for "All fields". The choice is kept in the chat state
(`state["group"]`, `state["subfields"]`), set by `refchat.set_field`.

- **The search filter.** The ISSNs searched are the union, in file order and
  without repeats, of every *verified* journal (section 7.5) of every selected
  sub-field. A group with no sub-fields selected means all its sub-fields.
  A journal that failed verification is never searched, even if it is listed.
- **All fields** (or a filter with no verified journal at all): `find` and
  title searches send exactly the requests described elsewhere in this spec
  (criteria 21 and 7.1), and replies have no "Searched in" line.
- **A filter chosen:** `find` and the title search add one `issn:ISSN` to the
  `filter` for every ISSN of the filter. Crossref treats repeated `issn`
  filters as "any of these". Up to `ISSN_BATCH_SIZE` (20) ISSNs this is one
  request; a larger set is split into batches whose results are merged
  (section 7.6).
- **Checked again in code.** Each record Crossref returns is also checked in
  code: a record whose `ISSN` list has none of the filter's ISSNs is dropped
  before scoring or showing. So a result outside the filter cannot appear,
  even if Crossref ignored the filter.
- **Shown in the reply.** With a filter, every `find` result and every
  title-lookup block shows **"Searched in: <filter>"**, where <filter> is
  "Computer Science: Machine Learning, Computer Vision" (sub-fields in file
  order), "Computer Science (all sub-fields)" when none is selected, or
  "N selected journals" for Top journals ("1 selected journal" for one).
- **DOI lookups ignore the filter.** A DOI is exact, so a DOI lookup sends the
  same request whatever the field or journals. With a filter, a DOI block
  shows **"Field filter not used: a DOI lookup is exact."** The help text
  under both the Field setting and the Top journals panel says so too.
- **Nothing found with a filter, never widened:** `find` replies "Not found
  in <filter>; try All fields." (for Top journals: "Not found in <filter>;
  try Reset to all journals."). A title lookup that is `Not found` with a
  filter gets that sentence as an extra reason. The search is never repeated
  without the filter automatically.
- `add`, `accept`, `list`, `edit`, `cite` and `style` behave the same
  whatever the filter. `clear` does not change the field or the journals.
- **File problems.** If `config/fields.json` is missing, is not valid JSON, or
  does not have the shape in section 7.3, the Group dropdown offers only "All
  fields", the sidebar shows "Field lists unavailable (config/fields.json:
  <reason>). Using All fields.", and searches work as with "All fields". If
  `config/journals_verified.json` is missing or broken, no journal counts as
  verified: the sidebar shows "Journal lists not verified
  (config/journals_verified.json: <reason>). Run python
  scripts/verify_journals.py. Using All fields." A chosen group or sub-field
  no longer in the file is dropped (no sub-field left means "All fields").
- The files are read again on each message, so an edit takes effect on the
  next message, without a code change or restart.

### Top journals

> **Superseded by 7.9:** withdrawn. The panel was never built and is not part of the page.

A sidebar panel headed **Top journals**, below the Field setting:

- **Journal multiselect** (Streamlit's multiselect, searchable by typing part
  of a name): every verified journal from `config/fields.json` and
  `config/top_journals.json`, each name once, sorted alphabetically
  (ignoring case). Kept as `state["journals"]` (names), set by
  `refchat.set_journals`.
- **Preset buttons**, one per list in `config/top_journals.json`, in the
  file's order (FT50, UTD24, AIS Senior Scholars' Basket of Eight, and later
  ones). Under each button: its source note and "last checked <date>". A
  button replaces the selection with that list's verified journals. If some
  of the list failed verification it says so: "FT50: 48 of 50 journals
  verified; 2 left out (see reports/journal_verification.md)."
- **Override.** When at least one journal is selected, `find` and title
  lookups use exactly those journals' ISSNs and ignore the Field setting; the
  panel shows "Searched in: N selected journals" and the Field setting shows
  "Not used: Top journals selected."
- **Reset to all journals** empties the selection; the Field setting applies
  again.
- **File problems.** If `config/top_journals.json` is missing, not valid JSON,
  or not the shape in 7.4, there are no preset buttons and the panel shows
  "Top journal lists unavailable (config/top_journals.json: <reason>)." The
  multiselect still offers the verified journals of `config/fields.json`. A
  selected name no longer verified is dropped from the selection.

### My list

A second list, separate from the export below: the references the student
picked with **Add to list**. It lives in the chat state (`state["my_list"]`,
so in `st.session_state`) and is lost on reload.

**Which cards get an Add to list button** (`refchat.list_button_for`):

| Card | Button adds |
|---|---|
| A `Verified` or `Check` reference with a built reference (lookup, `add`, `list` replies) | the reference, with its edits as they are now |
| A `find` result of the latest search | the result itself (not added to the references, so `list` is unchanged) |
| A title lookup that is `Check` or `Not found` with a provisional reference (added 2026-10-16) | **Add to list** for the provisional reference (no request: Crossref's record came with the search), keeping its `Check` or `Not found` status; then one button per *other* candidate with a DOI ("Add candidate K to list", K from 2) |
| `Not found` with no candidates, `Unavailable`, results of an older search, a candidate without a DOI | no button |

- **A candidate** has only a title, year and DOI, so adding it looks its DOI
  up on Crossref (one request, as a pasted DOI). If Crossref is unavailable
  nothing is added and the reply says so; if Crossref has no record the reply
  says "Crossref has no record for DOI ...". Nothing else makes a request.
- **Status.** An item keeps the status its card had when it was added:
  `Verified` or `Check`. A `find` result or a candidate is always `Check`,
  with its fixed reason ("search result, not verified: pick the right one";
  "title-search candidate, not verified: check it is the right paper").
  A provisional reference keeps its card's status, `Check` or `Not found`,
  and is marked provisional on the item (added 2026-10-16).
  Nothing in the list ever becomes `Verified` later.
- **A snapshot.** The item is a copy of the entry at the moment it was added.
  A later `edit` of the reference does not change it; remove it and add it
  again to update it.
- **Style.** Items are always shown, and exported, in the **current** style.
  Changing the style re-formats the whole list.
- **No duplicates.** Two items are the same when their DOIs match (ignoring
  case and the `https://doi.org/` prefix), or, when either has no DOI, when
  their titles match after `agent.normalise`. A card whose reference is
  already in the list shows a disabled **Already in list** button instead of
  **Add to list**, so nothing is added twice. Adding through any route
  (`refchat.add_to_list`) a reference already in the list returns "Already in
  list" and changes nothing.
- Each added item appends an assistant line to the chat: "Added to My list:
  <reference text>" or "Already in list".
- **Sidebar:** "My list (N)", then each item in the order added, numbered,
  in the current style, with its status, and a **Remove** button. **Clear
  list** empties it; it is disabled when the list is empty. `clear` (the
  command) also empties it.
- **`my_list.txt`** (UTF-8): one reference per line, in the current style,
  without the `*` italics markers, sorted like the export (first author's
  family name ignoring case and accents, then year). An empty list gives an
  empty file. No heading. (Changed 2026-10-16:) an item that is not
  `Verified` starts with `[CHECK] ` or `[NOT FOUND] `, and a provisional one
  with `[CHECK] (provisional) ` or `[NOT FOUND] (provisional) `. When
  **Include in-text citations in .txt files** is ticked (the default), each
  reference line is followed by one line
  `    In-text: <parenthetical> | <narrative>` (or `    In-text: Check:
  <reasons>` when none was built), in the current style, using the
  same-citation check across the list's items.
- **`my_list.csv`** (UTF-8 with a byte-order mark; quoted by Python's `csv`
  module): a header row, then one row per item, in the same order as the
  .txt. Columns, in order: `reference` (current style, no `*`), `style`
  (the current style's name), `status` (`Verified`, `Check` or `Not found`),
  `provisional` (`yes`/`no`), `parenthetical citation`, `narrative
  citation` (current style, or `Check: <reasons>`), `DOI` (without
  `https://doi.org/`), `title`, `authors` (`Family, Given; Family, Given`),
  `year`, `journal`, `Google Scholar link`. (Changed 2026-10-16: the
  `provisional` and two citation columns are new.) A missing field is
  `not stated`, never blank. An empty list gives the header row only.
- The Status filter offers All / Verified / Check / Not found.
- Both files are built as bytes in memory (`mylist.py`); nothing is written
  to disk.

#### Searching My list (and `list FILTER`)

> **Superseded by 7.9:** the page shows only the search box; Status, Sort and "Export only matching" are removed from the page (the functions stay), and the files always hold the full list.

Matching is in `listsearch.py` (no Streamlit), shared by the sidebar and the
`list FILTER` command. It makes no request.

- **Above the list:** a text box **Search my list**, a **Status** filter (All
  / Verified / Check, default All), a **Sort** choice (Date added (default) /
  Author A-Z / Year (newest first)) and a checkbox **Export only matching**
  (off by default). They are kept in `st.session_state` only.
- **What is searched:** for each item, its authors (given and family names),
  title, journal, year, DOI (without `https://doi.org/`) and the reference
  text in the current style without `*`. Each is a separate piece of text, so
  a phrase never runs from one into the next.
- **How it matches:** case- and accent-insensitive (NFKD, accent marks
  dropped, lowercase, spaces collapsed); punctuation is kept, so a DOI matches
  as typed. The search is split into terms: a `"quoted phrase"` is one term,
  every other word is a term (an unmatched `"` is ignored). An item matches
  when **every** term is a substring of at least one of its pieces (AND).
  A blank search matches everything.
- **Status filter:** Verified or Check keeps only items with that status.
- **Sort** (of the shown items only): Date added = the order added; Author
  A-Z = the export's order (first author's family name, ignoring case and
  accents, then year); Year (newest first) = year descending, items without a
  year last, ties in the order added.
- **What is shown:** the matching items, each with its number in the full
  list (so **Remove** removes the right item), its text, status and Remove
  button. When a search or a status filter is in use, the line "Showing X of
  N"; when nothing matches (and the list is not empty), "No matches in your
  list".
- **The list itself never changes:** searching, filtering and sorting don't
  change `state["my_list"]`, its order, or the heading "My list (N)" (N is
  always the full count). `my_list.txt` and `my_list.csv` hold the full list,
  in their usual order, unless **Export only matching** is ticked; then they
  hold only the matching items (search and status filter), still in their
  usual order. The references export (`references.txt` / `.csv`) is never
  affected.
- **`list FILTER`** in the chat (e.g. `list mithas 2021`) shows only the
  references whose pieces match FILTER by the same rules, with their usual
  numbers and "In export" lines, under the line "Showing X of N references
  matching "FILTER"." and the export header for the shown references. No
  match: "No references match "FILTER". Type `list` to see them all." Plain
  `list` is unchanged. (`list 2` used to be an unknown command; it is now a
  search for "2".)

### Statuses

**Verified** means: DOI resolved in Crossref, or title match above threshold
with a clear lead over the runner-up. In terms of section 7.1, the title match
has similarity at least 0.9 and the runner-up is more than 0.05 below it.
The status is `Verified` only when, in addition, code finds nothing to check.

| Situation | Status | Reasons |
|---|---|---|
| Verified (above), nothing to check | `Verified` | none; shows "Verified against Crossref only" |
| Verified (above), but a required APA 7 field is missing or malformed, the title casing is unclear (7.2), the DOI's title doesn't fit the text typed, or the reference text was typed by hand | `Check` | each problem |
| Title search: several records, too close to call, or weak match (7.1) | `Check` | the 7.1 reasons and candidates; a **provisional** reference from the closest candidate (below), never an ordinary one |
| DOI: Crossref has no record (HTTP 404) | `Not found` | "Crossref has no record for DOI ..."; no reference, no citation ("No match found") |
| Title search: nothing at 0.75 or more, with a closest candidate | `Not found` | the 7.1 reason; a **provisional** reference from the closest candidate |
| Title search: no results at all | `Not found` | the 7.1 reason; no reference, no citation ("No match found") |
| Crossref unreachable: network error, timeout, HTTP 429 or 5xx, invalid JSON | `Unavailable` | "Crossref is unavailable right now. Try again in a minute." |
| A `find` result | `Check` (never `Verified`) | "search result, not verified: pick the right one", plus any other problem |
| A reference added with `add N` | `Check` (never `Verified`, even after edits) | "added from a search; paste its DOI to verify", plus any other problem |

- An `Unavailable` line is not added to the references, so it has no number.
- Edits can change the reference text, and can turn `Verified` into `Check`,
  but they never make an entry `Verified`: a `Not found` or `Check` entry from
  the lookup keeps that status after any edit.
- Status and reasons are always worked out again after a `style` change or an
  `edit`.

### Command replies

- `style X`: "Style set to <style name>."
- `list`: every reference so far as a reply block (above), numbered from 1;
  "No references yet." when there are none.
- `edit N field value`: the updated reply block for reference N. A bad N,
  field or value gives the reason and changes nothing.
- `find ...`: the results (above), separated like lookup blocks. With no
  results: "Crossref found no results for SURNAME YEAR." (with the topic words
  after the year when given). When Crossref is unreachable: status
  `Unavailable` with its reason, and the latest search is kept as it was.
- `add N`: "Added result N as reference M." followed by the reply block for
  reference M. With no search yet: "There are no search results. Use `find`
  first."; with N out of range: "There is no result N. The latest search has K
  result(s)." Neither changes anything.
- `clear`: "Cleared." and an otherwise empty history.
- `help`: the same text as the sidebar: one line per command with an
  example (including `accept N` and `cite N`), what goes in the export
  and the two files, a line explaining the **Field** setting in
  the sidebar (it limits `find` and title lookups to that field's journals,
  DOI lookups ignore it; "All fields" by default), a section on **My list**
  (Add to list, Remove, Clear list, the two downloads), the meaning of each
  status, and "Edits are kept for this session only and are lost when you
  reload the page."
- `accept N`: see "Confirming a reference" below.
- `cite N`: see "In-text citations" below.
- Short help also says: "To search a title that starts with a command word,
  put it in double quotes."
- Short help (wrong arguments, or one unknown word): "I didn't understand
  that." followed by the list of commands.

### Confirming a reference (`accept`)

`accept N` means "I, the student, have checked reference N and it is right".
Code cannot decide that, so it is the student's call, recorded on the
reference as **confirmed**.

- Only a `Check` reference can be confirmed. The reply is "Reference N
  confirmed by you. It is now in the export." followed by its reply block.
  Its status stays `Check`: confirming never makes a reference `Verified`.
- On a `Verified` reference: "Reference N is Verified, so it is already in the
  export." On a `Not found` reference: "Reference N was not found, so it can't
  be confirmed or exported. Paste its DOI or fix it with `edit` first." With
  no reference N: "There is no reference N. Type `list` to see the numbers."
  On a reference already confirmed: "Reference N is already confirmed."
  None of these changes anything.
- A successful `edit` of a confirmed reference removes the confirmation (the
  student confirmed the old text), and the reply says "The confirmation was
  removed: type `accept N` again if it is still right."
- Confirmations live in `st.session_state` like edits, and `clear` removes
  them.

### Export

The **export list** is every reference whose status is `Verified`, plus every
`Check` reference that is confirmed. `Not found` references are never in it
(they can't be confirmed), and neither are unconfirmed `Check` references.

- **Order:** alphabetical by the first author's family name, then year
  (`agent.sort_key`), ignoring case and accents (so `Müller` sorts as
  `Muller`).
- **Style:** the current style, built by the same code as the reply blocks
  (`agent.shown_text`). The files are plain text, so the Markdown italics
  markers (`*`) are removed.
- **In memory only:** both files are built as bytes in memory and handed to
  `st.download_button`. Nothing is written to disk.

`references.txt` (UTF-8):

```
Reference Checker (beta): reference list (<style name>)
Verified references, plus Check references you confirmed. Not found references are never included.

<reference>

<reference>

In-text citations (APA 7)

Reference <N>: parenthetical (<citation>); narrative <citation>
Reference <N>: Check: <reason>; <reason>
```

N is the reference's number in `list`. A citation line that is built but has
a reason to check gets "Check: <reasons>" after it. With an empty export the
file is the first line, then "No references to export yet.", and no in-text
section.

Changed 2026-10-16 (pending approval):
- The in-text section is headed "In-text citations (<style name>)" and uses
  the current style's rules (7.7), not always APA 7.
- It is included only when **Include in-text citations in .txt files** is
  ticked (the default), so the default file is as before.
- A confirmed reference whose text is a provisional reference (below)
  starts with `[CHECK] (provisional) `, so it can't be mistaken for a
  checked one. Other references have no prefix.

`references.csv` (UTF-8 with a byte-order mark, so Excel shows accents; comma
separated; values quoted by Python's `csv` module whenever they contain a
comma, a quote or a line break, with quotes doubled): a header row, then one
row per exported reference, in the export order. The columns, in order:

| Column | Value |
|---|---|
| `number` | The reference's number in `list`. |
| `status` | `Verified` or `Check`. |
| `confirmed` | `yes` if confirmed with `accept`, otherwise `no`. |
| `authors` | `Family, Given; Family, Given` (the form `edit` takes). |
| `year`, `title`, `journal`, `volume`, `issue`, `pages` | The field as stored, after edits (the title as Crossref gives it, not sentence case). |
| `DOI` | The DOI without `https://doi.org/`. |
| `formatted reference` | The reference in the current style, without `*`. |
| `parenthetical citation`, `narrative citation` | The in-text citations in the current style (7.7), or `Check: <reasons>` when none was built. (Changed 2026-10-16: was always APA 7.) |
| `citation check` | `OK`, or `Check: <reasons>` for a citation that was built but needs checking (e.g. a shortened title or `n.d.`). (Added 2026-10-16.) |
| `provisional` | `yes` if the reference text and citations are a provisional reference from the closest candidate, otherwise `no`. (Added 2026-10-16.) |
| `match score` | For a provisional reference, the closest candidate's title similarity (7.1); otherwise `not stated`. (Added 2026-10-16.) |
| `Google Scholar link` | The link from `agent.search_links`. |

A field that is missing is written `not stated`, never left blank. With an
empty export the file is the header row only.

### In-text citations (cards, `cite`, exports)

Changed 2026-10-16 (pending approval): citations follow the current style
(APA 7, Harvard or Chicago author-date), are shown on every card, and
organisation authors, missing authors and missing years are now built
instead of left out. The exact rules, with their sources and the rules
still to be confirmed, are in section 7.7. All of it is in `citations.py`,
in code; the names, years and titles come only from the entry (Crossref's
record after the student's edits).

- **Where:** every card with a reference or a provisional reference (lookup,
  `add`, `list`, `accept` and `find` replies, provisional cards) shows
  "In-text (<style name>)" and two boxes, **Parenthetical** and
  **Narrative**, each a `st.code` block, whose copy icon copies the citation
  exactly. `find` results are an APA 7 preview, so their citations are
  APA 7 too. `refchat.card_citation(state, item)` gives the text for each
  card, so it can be tested without Streamlit.
- **Check:** when a citation is built but something needs a person (e.g. a
  shortened title, `n.d.`, a provisional reference), the boxes are followed
  by "Citation: **Check**" and the reasons. When it can't be built, there
  are no boxes, only "Citation: **Check**" and the reasons. A card with no
  reference ("No match found") has no citation at all.
- **Same citation as another reference**: when another reference in the chat
  (or, for My list files, another item in the list) would get the same
  parenthetical citation, both are built but marked `Check`, naming the
  other one, because every style then adds a letter to the year (1989a,
  1989b) and that order is the student's to decide.
- **`cite N`** shows the same citations for reference N in the current
  style:

```
**<style name> in-text citations for reference N**

Parenthetical: (Davis, 1989)
Narrative: Davis (1989)

Citation: **OK**

Reference status: **<status>**
```

### Provisional results

Added 2026-10-16 (pending approval). A title lookup that is `Check` (weak
match, several records, or too close to call; 7.1) or `Not found` (best
below 0.75) but has at least one candidate shows a **provisional
reference** built from the **closest candidate** (candidate 1, the highest
title similarity).

- **Source:** the title search already receives Crossref's full record for
  every candidate. `agent.search_crossref_title` keeps the closest one's
  fields (`format_citation`), and `resolve_line(..., keep_closest=True)`
  (the chat only) stores them as `title_search["closest"]`, so no extra
  request is made and every field comes from Crossref. Refs mode doesn't
  pass `keep_closest`, so `refs/library.json` is unchanged. Like the rest of
  `title_search`, it is not an editable field and overrides can't touch it.
- **Not the entry's fields:** the entry's own citation fields stay
  `not stated`, as in 7.1, so status, reasons, `accept` and the export work
  as before. Status and reasons are still worked out only by
  `agent.verify`; being provisional never changes them, and a provisional
  reference is never `Verified`.
- **Shown as:** an orange badge with a warning icon,
  `:orange-badge[:material/warning: Provisional: closest match, not verified]`,
  then "Match score: <similarity> (needs 0.9 and a clear lead to be
  verified)", then the reference text as a quote block (`> `), the
  provisional in-text citation (always `Check`, reason "provisional: built
  from the closest candidate, not verified"), then the status and its 7.1
  reasons as usual. Verified cards never have a badge or a quote block, so
  the two can't be confused.
- **Style:** the provisional reference follows the current style, and is
  redrawn after a style change like other reference blocks.
- **Edits:** once the student types a title with `edit`, the card shows the
  edited reference as usual and no longer the provisional one.
- **No candidate at all** (a DOI Crossref has no record of, or a title
  search with no results): no reference and no citation are built. The card
  shows "No match found", "You typed: <line>", the status and reasons, and
  the Google Scholar and Google links.
- **My list:** see the table in "My list"; the item keeps `Check` or
  `Not found` and is marked provisional in both files.
- **Export:** a provisional `Check` reference can be confirmed with
  `accept N` like any `Check` reference; it is then exported with the
  provisional text, marked `[CHECK] (provisional)` in the .txt and
  `provisional` = `yes` in the .csv. A `Not found` one can never be
  confirmed or exported (unchanged).

### Live suggestions

> **Superseded by 7.9:** the Suggestions and Look up boxes are removed from the page; `suggest.py` stays.

Added 2026-10-16 (pending approval). Code in `suggest.py` (no Streamlit,
testable); drawn by `app.py`.

- **The box:** above the chat box, a text input **Suggestions (type a
  title)**: `st.text_input(..., live="500ms")` inside an `@st.fragment`, so
  Streamlit only sends the text after a 500 ms typing pause (the debounce)
  and typing reruns only the box, not the whole chat. `st.chat_input` stays
  as it is, and works whether or not the box does.
- **When Crossref is asked** (`suggest.suggestions(text, issns, now)`, rules
  in 7.8): not for fewer than 4 characters (after trimming), not for a DOI
  or DOI link (a DOI is exact; the box says "A DOI: press Look up"), not
  when the same text and filter were asked before (cache), and never more
  than one request per second (a request that comes too soon waits for the
  rest of the second first).
- **The request:** `api.crossref.org/works` with `query.bibliographic` =
  the text, `rows=5`, `select=DOI,title,author,issued,container-title,ISSN,type`,
  the active Field filter's `issn` filters (and the same `in_journals` check
  in code), and `mailto` when `CROSSREF_MAILTO` is set. DOI lookups and
  `find` are not affected.
- **Shown:** up to 5 suggestions, each a button with Crossref's title,
  year, first author's family name and journal (any part Crossref lacks is
  left out, never filled in). Suggestions are not references and have no
  status.
- **Choosing one** puts its DOI link (`https://doi.org/<DOI>`) in a
  **Look up** text box below (editable). Nothing is sent until the student
  presses **Look up**, which sends the text as a chat message, exactly as if
  typed: a normal DOI lookup with its normal status. A suggestion without a
  DOI puts its title in the box instead.
- **Degrading:** if Crossref can't be reached, the box says "Suggestions
  unavailable right now; use the chat box below." and makes no further
  request for 30 seconds. If the box itself can't be drawn (e.g. an older
  Streamlit without `live`), it is left out with a caption saying so. The
  chat box is always there.

With a `Check` citation, the "Parenthetical" and "Narrative" lines are left
out when no citation was built, and "Citation: **Check**" is followed by the
reasons, one per line. With no reference N: "There is no reference N. Type
`list` to see the numbers."

### Buttons and the Style dropdown

> **Superseded by 7.9:** the Style dropdown becomes the style chip; cards have only Add to list and Copy; the Add to export button is removed from the page (the functions and `accept N` stay).

The commands keep working; the buttons and the dropdown only send the same
commands, so each click shows in the chat as the command and its reply.

- **Style dropdown**, at the top right next to the title, labelled
  **Style**: APA 7 (the default), Harvard, Chicago, in that order. Choosing
  one sends `style apa|harvard|chicago`. It always shows the current style,
  also after a typed `style` command or `clear`.
- **Re-formatting on screen.** After a style change, every reference block
  already in the chat that has buttons (lookup, `add` and `list` replies) is
  drawn again in the new style, from the reference's current state
  (`refchat.render_reply`), and so is My list. `edit`, `accept` and `cite`
  replies are kept as they were sent. `find` results stay an APA 7
  preview (criterion 23). The reply text returned by `handle_message` and
  kept in the history is not changed; only the drawing is.
- **Add to list** sits beside the **Add to export** button on every card that
  has one ("My list", above). The two are independent: one adds to My list,
  the other confirms for the export.
- **A button beside each reference block** (in lookup, `add` and `list`
  replies), worked out from the reference's current state
  (`refchat.button_for`):
  - `Verified`, or `Check` and confirmed: **✓ In export**, disabled;
  - `Check`, not confirmed: **Add to export**, which sends `accept N`;
  - `Not found`: **Not found**, disabled (it can never be exported).
- **A button beside each `find` result** of the latest search: **Add to
  export**, which sends `add N` and then `accept M` for the new reference M.
  Once added, the button shows reference M's state (above), so a result
  can't be added twice by clicking. Results of an older search have no
  button, because `add N` always means the latest search.
- A line Crossref couldn't be asked about (Unavailable) has no button.

### `list` and the export

`list` starts with "In the export: K of M references." and every reply block
in it ends with one line:

| Reference | Line |
|---|---|
| `Verified` | In export: **yes** (Verified) |
| `Check`, confirmed | In export: **yes** (confirmed by you) |
| `Check`, not confirmed | In export: **no** (Check: type `accept N` once you have checked it) |
| `Not found` | In export: **no** (Not found) |

Other replies (lookups, `edit`, `add`) do not have this line.

## 4. Acceptance criteria

Each criterion names what decides it:
- **Test:** an automated test in `tests/test_refchat.py` with Crossref
  responses mocked at `urllib.request.urlopen` (no network). The DOI fixture
  is a recorded Crossref response.
- **Inspection:** reading or searching the source.
- **Manual:** a person using the page with the live API.
- **Reviewed by a human:** a person reads the output, because code cannot
  decide it.

1. Pasting `10.1038/nature14539` gives status `Verified`, the line "Verified
   against Crossref only", a Google Scholar and a Google link, and exactly:
   `LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. *Nature*, *521*(7553), 436–444. https://doi.org/10.1038/nature14539`
   **Decided by:** test.
2. A message with several lines gives one reply block per non-blank line, in
   the same order, numbered 1, 2, 3. **Decided by:** test.
3. Verified follows the definition in section 3: a resolved DOI with nothing
   to check is `Verified`; a title at 0.9 with the runner-up more than 0.05
   below is `Verified`; a title at 0.9 with the runner-up 0.05 or less below,
   a title below 0.9, or several records at 0.9 or more are `Check`; a DOI
   Crossref doesn't have is `Not found`. **Decided by:** test.
4. A resolved DOI with something to check (e.g. a missing required field) is
   `Check` with that reason, not `Verified`. **Decided by:** test.
5. A DOI Crossref answers with 404 gives `Not found` with its reason.
   **Decided by:** test.
6. Every `Check` and `Not found` reply shows at least one reason.
   **Decided by:** test.
7. APA 7 is used until `style` is sent; after `style chicago` or
   `style harvard`, later replies and `list` use that style.
   **Decided by:** test.
8. `list` shows every reference so far, numbered from 1, in the current style;
   with none it says "No references yet." **Decided by:** test.
9. `edit N field value` changes that field, and the reference is formatted and
   its status worked out again. The change is still there after `list` and
   after a `style` change. **Decided by:** test.
10. An edit never makes an entry `Verified`. **Decided by:** test.
11. `edit` with a bad N, unknown field or invalid value gives a reason and
    changes nothing. **Decided by:** test.
12. `clear` forgets all references, the latest search and the history, and
    sets the style back to APA 7. **Decided by:** test.
13. `help` lists every command (including `find SURNAME YEAR [topic words]`
    and `add N`), the meaning of `Verified`, and says edits are lost on
    reload. **Decided by:** test.
14. Wrong arguments to a command, or a single unknown word, give the short
    help message and make no request. **Decided by:** test.
15. When Crossref is unreachable (network error, timeout, HTTP 429, HTTP 500,
    invalid JSON) the line shows `Unavailable` with its reason, nothing
    crashes, and the next message is answered normally. **Decided by:** test.
16. The chat requests only `api.crossref.org`, for lookups and for `find`:
    never OpenAlex, Semantic Scholar, Google Scholar or Google. `add` makes no
    request. **Decided by:** test (every URL requested is recorded).
17. The chat writes no files, including for `find` and `add`.
    **Decided by:** test (`agent.save_json` and file writes are not called)
    + inspection.
18. `refchat.py`, `app.py` and every module they import (including
    `agent.py`) contain no API keys and no model provider calls.
    **Decided by:** inspection (a `grep` for `key`, `token`, `anthropic`,
    `openai`, `claude_agent_sdk`).
19. The history stays on screen across Streamlit reruns, and is gone after a
    page reload. **Decided by:** manual.
20. Proper nouns in APA titles: when the source title is in Title Case, code
    cannot tell a proper noun (e.g. "Facebook", "Australia") from an ordinary
    word, so it lowercases it without a flag (decision 7.2). A person compares
    every formatted APA title with the original title shown next to it, and
    fixes any proper noun. **Decided by:** reviewed by a human.

Author-and-year search (`find` and `add`):

21. `find Smith 2019` sends exactly one request to `api.crossref.org/works`
    with `query.author=Smith`, `filter=from-pub-date:2019,until-pub-date:2019`
    and `rows=5`, and no `query.bibliographic`. With topic words
    (`find Smith 2019 deep learning`) the same request also has
    `query.bibliographic=deep learning`. A multi-word surname
    (`find van der Berg 2019`) is sent whole. **Decided by:** test.
22. Each result is shown numbered from 1 under "Result N (APA 7 preview)",
    as an APA 7 reference ending with its DOI link, with status `Check`, the
    reason "search result, not verified: pick the right one", and a Google
    Scholar and a Google link. **Decided by:** test.
23. Results are in APA 7 even after `style chicago` or `style harvard`.
    **Decided by:** test.
24. At most 5 results are shown, even if Crossref returns more.
    **Decided by:** test.
25. A search result is never `Verified`, even a complete record that would be
    `Verified` if its DOI were pasted. **Decided by:** test.
26. `find` adds nothing to the references: `list` is unchanged.
    **Decided by:** test.
27. `add N` appends result N of the latest search as the next reference and
    says its number. Its reference text includes its DOI link. A later `find`
    replaces the latest search, so `add 1` then adds the new search's first
    result. **Decided by:** test.
28. A reference added with `add N` has status `Check` with the reason "added
    from a search; paste its DOI to verify", and stays `Check` after edits
    and after `style` changes. **Decided by:** test.
29. A reference added with `add N` follows the current style: after
    `style chicago` (or `style harvard`), the reply to `add` and `list` show
    it in that style, not APA. **Decided by:** test.
30. `add N` with no search yet, or with N out of range (0, or more than the
    number of results), gives its reason and changes nothing.
    **Decided by:** test.
31. `find` with no surname, no year, or a year that is not four digits, and
    `add` without a whole number, get the short help message and make no
    request. `parse_command` gives `("find", surname, year, topic)` and
    `("add", N)` for valid input. **Decided by:** test.
32. A search with zero results says "Crossref found no results for ..."
    and nothing else. **Decided by:** test.
33. When Crossref is unreachable (network error, timeout, HTTP 429, HTTP 500,
    invalid JSON), `find` shows `Unavailable` with its reason, nothing
    crashes, the latest search is unchanged, and the next message is
    answered normally. **Decided by:** test.
34. Whether a result is the paper the student means (the right author among
    namesakes, the right work). Code cannot decide it, which is why results
    are never `Verified`. **Decided by:** reviewed by a human (the student
    picks with `add N`, then pastes the DOI).
35. With the live API, `find` returns plausible results for a known author
    and year (e.g. `find LeCun 2015 deep learning`). **Decided by:** manual.

#### Field setting

Tests for 36–46 are in `tests/test_fields.py`.

36. The group options are "All fields" first, then the groups of
    `config/fields.json` in the file's order; each group's sub-field options
    are its sub-fields in file order; "All fields" is the default for a new
    session. **Decided by:** test (the options lists); manual (the sidebar
    shows them).
37. With "All fields", `find` sends exactly the request of criterion 21 and
    a title lookup exactly the request of 7.1 (no `issn` filter), and no
    reply has a "Searched in" line. **Decided by:** test.
38. With sub-fields chosen whose verified ISSNs number 20 or fewer, `find`
    and a title lookup each send exactly one request to
    `api.crossref.org/works`, whose `filter` has one `issn:` entry for every
    ISSN in the union of those sub-fields' verified journals, each once (and,
    for `find`, the year filters), and none for other sub-fields. A group with
    no sub-field selected uses all its sub-fields. **Decided by:** test.
39. With a field chosen, every `find` result and title-lookup block shows
    "Searched in: <field>"; results are otherwise as in criterion 22 (APA 7
    preview, `Check`). A record Crossref returns whose ISSNs are not in the
    field is not shown and not scored. **Decided by:** test.
40. With a filter and zero results, `find` replies "Not found in <filter>;
    try All fields." (Top journals: "...; try Reset to all journals."), a
    `Not found` title lookup has that reason, and no request without the
    filter is sent. **Decided by:** test.
41. With a field chosen, a DOI lookup sends the same request and gives the
    same reference and status as with "All fields", plus the line "Field
    filter not used: a DOI lookup is exact." `add`, `list` and `edit` are
    unchanged. `clear` keeps the chosen field. **Decided by:** test.
42. Editing `config/fields.json` (adding or removing a journal, an ISSN, a
    sub-field or a group) changes the options and the `find` request on the
    next message, with no code change. A chosen group or sub-field no longer
    in the file is dropped. Changing a journal's ISSNs by hand without
    re-running the script makes it unverified, so it is not searched.
    **Decided by:** test (with temporary files).
43. If `config/fields.json` is missing, not valid JSON, or has the wrong shape
    (section 7.3, including the old flat shape), the options are only "All
    fields", the warning "Field lists unavailable (config/fields.json:
    <reason>). Using All fields." is shown, `find` works as with "All
    fields", and nothing crashes. The same holds, with its own warning, for a
    missing or broken `config/journals_verified.json`. **Decided by:** test.
44. `help` explains the Field setting, including that DOI lookups ignore it.
    **Decided by:** test.
45. With a field chosen, the chat still requests only `api.crossref.org` and
    writes no files; `config/fields.json` is only read.
    **Decided by:** test.
46. With the live API and a field chosen, `find` returns only works from that
    field's journals (e.g. `find Kumar 2016` with "Marketing").
    **Decided by:** manual.
47. **Reviewed by a human:** which journals belong to each sub-field, and
    which belong to each ranking list, is a judgement call (or a fact about
    the list's publisher), not something code can decide. The seed lists are
    a starting point; the student checks them, and the verified table and
    failures in `reports/journal_verification.md` are approved before the app
    uses them. **Decided by:** reviewed by a human.

#### Export and in-text citations

Tests for these are in `tests/test_export.py`, set up like
`tests/test_refchat.py` (Crossref mocked, no network).

48. `accept N` on a `Check` reference confirms it: the reply is "Reference N
    confirmed by you. It is now in the export." and its status stays
    `Check`. **Decided by:** test.
49. `accept N` on a `Verified` or `Not found` reference, on a reference
    already confirmed, or with no reference N gives the reply in section 3
    and changes nothing. `accept`, `accept two` and `accept 1 2` get the
    short help message. **Decided by:** test.
50. A successful `edit` of a confirmed reference removes the confirmation
    and says so; a failed `edit` keeps it. `clear` removes all
    confirmations. **Decided by:** test.
51. The export list has every `Verified` reference and every confirmed
    `Check` reference, and no `Not found` or unconfirmed `Check` reference.
    **Decided by:** test.
52. The export is sorted by the first author's family name, ignoring case and
    accents, then by year, and uses the current style (the same text as
    `list`, without `*`). **Decided by:** test.
53. `references.txt` has the heading with the style name, the references,
    and, when the in-text option is ticked (the default), the "In-text
    citations (<style name>)" section with one line per reference in the
    current style, as in section 3; unticked, no in-text section.
    (Changed 2026-10-16.) **Decided by:** test.
54. `references.csv` has the header row with exactly the columns of section
    3, in order (including `citation check`, `provisional` and `match
    score`), and one row per exported reference with those values, the
    citations in the current style; missing fields are `not stated`.
    (Changed 2026-10-16.) **Decided by:** test.
55. A title containing a comma and double quotes is read back unchanged from
    `references.csv` by a CSV reader. **Decided by:** test.
56. An accented author name (e.g. `Müller, Jörg`) is unchanged in the .txt,
    the .csv (decoded as UTF-8) and the in-text citations; the .csv starts
    with the UTF-8 byte-order mark. **Decided by:** test.
57. With an empty export, `references.txt` says "No references to export
    yet." and `references.csv` is the header row only. **Decided by:** test.
58. Building the export writes no files and makes no network request.
    **Decided by:** test.
59. With APA 7, `cite N` gives `(Davis, 1989)` / `Davis (1989)` for one
    author, `(Davis & Bagozzi, 1989)` / `Davis and Bagozzi (1989)` for two,
    and `(Yoo et al., 2010)` / `Yoo et al. (2010)` for three or more, with
    "Citation: **OK**". With Harvard or Chicago it gives that style's forms
    (7.7, criterion 119). (Changed 2026-10-16: was APA 7 in any style.)
    **Decided by:** test.
60. `cite N` with no year builds the citation with the style's no-date form
    (`n.d.` or `no date`) and marks it `Check` ("Crossref gives no year");
    with no authors and a title, it uses the shortened title (7.7) and is
    `Check`; with neither authors nor title, no citation is built.
    (Changed 2026-10-16: no citation was built.) **Decided by:** test.
61. `cite N` with only organisation authors from Crossref builds the
    citation with the organisation's name, as Crossref gives it, and is
    `OK`; organisations and people together (order unknown), or an author
    with no given name, build no citation / are `Check` as in 7.7, naming
    the author. (Changed 2026-10-16.) **Decided by:** test.
62. Two references that would get the same parenthetical citation are both
    `Check`, each naming the other. **Decided by:** test.
63. `cite N` with no reference N gives "There is no reference N. Type `list`
    to see the numbers." `cite` and `cite one` get the short help message.
    **Decided by:** test.
64. `list` starts with "In the export: K of M references." and each block
    has the "In export" line of section 3. **Decided by:** test.
65. `help` (and so the sidebar) lists `accept N` and `cite N` with an
    example and explains what goes in the export. **Decided by:** test.
66. The sidebar shows the two download buttons, and they download
    `references.txt` and `references.csv` with the contents above, also
    when the export is empty. **Decided by:** manual.
67. `references.csv` opens in Excel or LibreOffice with one column per
    field, accents shown correctly, and commas and quotes inside titles kept
    in their cell. **Decided by:** manual.
68. Whether a confirmed reference really is right, and how an organisation
    or a same-author-same-year pair should be cited, is the student's call.
    **Decided by:** reviewed by a human.

#### Buttons and the Style dropdown

Tests for 69–73 are in `tests/test_buttons.py`.

69. Each reference block of a lookup, `add` or `list` reply has a button:
    **Add to export** for an unconfirmed `Check` reference, a disabled
    **✓ In export** for a `Verified` or confirmed one, and a disabled
    **Not found** for a `Not found` one. Unavailable lines have none.
    **Decided by:** test.
70. Clicking **Add to export** on a `Check` reference sends `accept N`: the
    chat shows it and its reply, and the reference is in the export with its
    status still `Check`. **Decided by:** test.
71. Clicking **Add to export** on a `find` result sends `add N` then
    `accept M`; the new reference is in the export, still `Check`, and the
    result's button then shows **✓ In export**. Results of an older search
    have no button. **Decided by:** test.
72. A disabled button, or one clicked a second time, changes nothing.
    **Decided by:** test.
73. `help` (and so the sidebar) explains the buttons and the dropdown.
    **Decided by:** test.
74. The Style dropdown is at the top right, offers APA 7, Harvard, Chicago,
    shows the current style (also after a typed `style` or `clear`), and
    choosing a style restyles later replies, the reference blocks already on
    screen, My list and both exports. **Decided by:** manual.

#### My list

Tests for 75–88 are in `tests/test_mylist.py`, set up like
`tests/test_refchat.py` (the same `FakeCrossref`, no network).

75. A `Verified` reference, a `Check` reference with a built reference, and
    each `find` result of the latest search have an **Add to list** button; a
    title lookup with candidates has one per candidate with a DOI;
    `Not found` without candidates, `Unavailable` lines and older search
    results have none. **Decided by:** test.
76. Pressing **Add to list** on a reference adds a copy of it to My list
    with its current status; the chat gets "Added to My list: ...". It makes
    no network request. **Decided by:** test.
77. Pressing **Add to list** on a `find` result adds it to My list as
    `Check` without adding it to the references (`list` unchanged), and with
    no network request. **Decided by:** test.
78. Pressing **Add to list** on a title-search candidate looks its DOI up on
    Crossref (one request to `api.crossref.org`) and adds it as `Check`,
    never `Verified`, even for a complete record. If Crossref is unavailable
    or has no record, nothing is added and the reply says why.
    **Decided by:** test.
79. Duplicates: adding a reference whose DOI is already in the list (in any
    case, with or without `https://doi.org/`), or, with no DOI, whose
    normalised title is already in the list, adds nothing and replies
    "Already in list"; the card's button is then a disabled **Already in
    list**. **Decided by:** test.
80. A `Check` item stays `Check` in My list and in both My list files, also
    after a style change and after the reference is confirmed or edited.
    **Decided by:** test.
81. **Remove** on item K removes only that item; **Clear list** and the
    `clear` command empty the list. After removing, the reference can be
    added again. **Decided by:** test.
82. `my_list.txt` has one reference per line, in the current style, without
    `*`, sorted by first author (ignoring case and accents) then year, with
    the `[CHECK]` / `[NOT FOUND]` / `(provisional)` prefixes of section 3,
    and, when the in-text option is ticked, an `In-text:` line after each;
    unticked, no `In-text:` lines. An empty list gives an empty file.
    (Changed 2026-10-16.) **Decided by:** test.
83. `my_list.csv` starts with the UTF-8 byte-order mark, has exactly the
    header `reference, style, status, provisional, parenthetical citation,
    narrative citation, DOI, title, authors, year, journal, Google Scholar
    link` (changed 2026-10-16), one row per item in the .txt order, `not stated`
    for missing fields, and a title with a comma and quotes reads back
    unchanged. An empty list gives the header only. **Decided by:** test.
84. After `style harvard` (or `style chicago`), My list, both My list files
    (the `style` column too) and the reference blocks drawn from the history
    (`refchat.render_reply`) use the new style; `find` result blocks stay
    APA 7. **Decided by:** test.
85. The `add N` command still works as in criteria 27–30, and does not add
    to My list. The full command set is unchanged. **Decided by:** test
    (the existing tests, unchanged, plus one check on My list).
86. Building the My list files and adding, removing or clearing items
    (other than a candidate) make no network request and write no files.
    **Decided by:** test.
87. `help` (and so the sidebar) explains My list, Add to list, Remove,
    Clear list and the two downloads, and still lists every command.
    **Decided by:** test.
88. The sidebar shows "My list (N)", a Remove button per item, Clear list and
    the two downloads, and they download the files above.
    **Decided by:** manual.

#### Searching My list

Tests for 107–117 are in `tests/test_listsearch.py` (no network).

107. One word matches an item with that word in any searched piece, ignoring
     case. **Decided by:** test.
108. Several words are ANDed: `mithas 2021` matches only items containing
     both. **Decided by:** test.
109. Accents are ignored both ways: `muller` finds "Müller" and `müller`
     finds "Muller". **Decided by:** test.
110. A DOI, or part of one, matches the item with that DOI, with or without
     `https://doi.org/`. **Decided by:** test.
111. A quoted phrase matches only items containing those words together, in
     that order; the same words unquoted match more. **Decided by:** test.
112. A search with no matches shows "No matches in your list" and "Showing 0
     of N"; a blank search shows every item. **Decided by:** test.
113. The status filter keeps only Verified or only Check items, and combines
     with the search. **Decided by:** test.
114. The three sort orders give the order of section 3 (Year newest first
     puts items without a year last). **Decided by:** test.
115. With **Export only matching** ticked, `my_list.txt` and `my_list.csv`
     hold only the matching items, in their usual order; unticked they hold
     the full list. **Decided by:** test.
116. After any search, filter or sort, `state["my_list"]` (items and order),
     the count N and Remove's numbering are unchanged. **Decided by:** test.
117. `list FILTER` shows only matching references with their usual numbers,
     the "Showing X of N references matching ..." line, or the no-match
     reply; plain `list` is unchanged; `help` lists `list FILTER`.
     **Decided by:** test.
118. The sidebar shows the search box, Status, Sort, Export only matching,
     "Showing X of N" and "No matches in your list". **Decided by:** manual.

#### In-text citations, provisional results, easier input, suggestions

Added 2026-10-16 (pending approval). Tests in `tests/test_citations.py`
(119–126), `tests/test_provisional.py` (127–134), `tests/test_input.py`
(135–138) and `tests/test_suggest.py` (139–145), with Crossref mocked as in
`tests/test_refchat.py` (no network) and a fake clock for 7.8.

119. For each style (APA 7, Harvard, Chicago), `citations.in_text` gives
     exactly the parenthetical and narrative forms of the 7.7 table for one,
     two, three and four authors (e.g. APA `(Mithas et al., 2021)` /
     `Mithas et al. (2021)`). **Decided by:** test.
120. An entry whose only authors are organisations gives the organisation's
     name in every style (`(World Health Organization, 2020)` in APA and
     Harvard, `(World Health Organization 2020)` in Chicago); organisations
     with people, or an author with no given name, follow 7.7.
     **Decided by:** test.
121. An entry with no authors gives the shortened title of 7.7: in quotes for
     an article or chapter, in italics (`*...*`) for a book or report, in
     every style, marked `Check` ("shortened title chosen by code: check
     it"). With no authors and no title, no citation is built.
     **Decided by:** test.
122. An entry with no year gives `n.d.` (APA, Chicago) or `no date`
     (Harvard), marked `Check`. **Decided by:** test.
123. Two references with the same parenthetical citation are both `Check`,
     each naming the other, in every style. **Decided by:** test.
124. Every result card's item gives `refchat.card_citation` = the current
     style's citation (APA 7 for `find` results); a `No match found` card
     gives none. `cite N` follows the current style and its heading names
     it. **Decided by:** test.
125. Every name, year and title in a citation is the entry's own value,
     unchanged apart from the 7.7 punctuation (accents kept); a citation is
     never built from a field that is `not stated`. **Decided by:** test
     (each output's parts are compared with the entry's fields).
126. Whether each rule marked "to be confirmed" in 7.7 matches the course
     guide. **Decided by:** reviewed by a human (the student checks 7.7
     against the guide before the code is final).
127. A title lookup that is `Check` (weak, several records, too close) shows
     the provisional badge, "Match score: X", the closest candidate's
     reference in the current style as a quote block, and its citation
     marked `Check`; its status and reasons are exactly those of
     `agent.verify`. **Decided by:** test.
128. A title lookup that is `Not found` with a closest candidate does the
     same, with status `Not found`. **Decided by:** test.
129. A DOI with no Crossref record, and a title search with no results, show
     "No match found", "You typed: ...", the status, the reasons and the two
     links, and no reference text, provisional text or citation.
     **Decided by:** test.
130. The provisional reference uses only fields from the closest candidate's
     Crossref record; the entry's own citation fields stay `not stated`; no
     extra request is made. **Decided by:** test.
131. A provisional card is never `Verified` and never shows "Verified
     against Crossref only"; a `Verified` card never shows the badge.
     **Decided by:** test.
132. **Add to list** on a provisional card adds it with no request, keeping
     `Check` or `Not found`, marked provisional; the My list .txt prefix and
     the .csv `status` and `provisional` columns say so. **Decided by:** test.
133. `accept N` on a provisional `Check` reference puts it in the export with
     the `[CHECK] (provisional)` prefix in `references.txt` and
     `provisional` = `yes`, `match score` in `references.csv`; a provisional
     `Not found` one can't be accepted. **Decided by:** test.
134. After `style harvard` or `style chicago`, provisional cards are redrawn
     in that style. **Decided by:** test.
135. `https://doi.org/10.1038/nature14539`, `http://dx.doi.org/10.1038/nature14539`,
     `doi:10.1038/nature14539`, `DOI: 10.1038/nature14539`,
     `https://doi.org/10.1038%2Fnature14539` and `10.1038/nature14539.` all
     give the DOI `10.1038/nature14539` and send the same single DOI request
     as the bare DOI. **Decided by:** test.
136. `refchat.input_kind` gives `doi` for each line of 135 and for a pasted
     reference ending in a DOI link, and `title` for a plain title; a title
     is searched by title with no `find`. **Decided by:** test.
137. A quoted line starting with a command word (`"List decoding of ..."`)
     is searched as a title, without the quotes; unquoted it is still the
     command. **Decided by:** test.
138. With `CROSSREF_MAILTO` set, every Crossref request has
     `mailto=<address>`; without it, requests are exactly as before
     (criteria 1, 21, 37). **Decided by:** test.
139. `suggest.suggestions` makes no request for text shorter than 4
     characters after trimming, or for a DOI or DOI link.
     **Decided by:** test.
140. The same text and filter asked twice make one request (the second is
     from the cache); a different filter is a new request.
     **Decided by:** test.
141. Two requests are never less than 1 second apart (fake clock): a request
     that comes too soon waits the rest of the second.
     **Decided by:** test.
142. The suggestion request is to `api.crossref.org/works` with the parameters of "Live suggestions" (section 3), the active field's ISSNs, and no other
     host; records outside the field are dropped. **Decided by:** test.
143. Each suggestion's label uses only Crossref's title, year, first family
     name and journal, leaving out any it lacks; choosing one gives the DOI
     link (or the title when there is no DOI) and sends nothing.
     **Decided by:** test.
144. When Crossref is unavailable, `suggestions` returns no suggestions and
     the "Suggestions unavailable" note, and makes no request for 30
     seconds. **Decided by:** test.
145. *Withdrawn 2026-10-16 (7.9): the Suggestions and Look up boxes are no
     longer on the page.*
146. *Withdrawn 2026-10-16 (7.9).* With the live API, typing a title shows suggestions after a short pause,
     choosing one fills the Look up box without sending it, and the chat box
     still works with the network off. **Decided by:** manual.
147. The copy buttons copy exactly the citation shown. **Decided by:** manual.
148. Whether a provisional reference is the paper the student means.
     **Decided by:** reviewed by a human (that is why it is never
     `Verified`).

#### Interface simplification (7.9)

Agreed on 2026-10-16 (7.9). Tests in `tests/test_simple_ui.py`,
Crossref mocked as in `tests/test_refchat.py` (no network).

149. `refchat.interpret` reads `10.1038/nature14539`,
     `https://doi.org/10.1038/nature14539` and `doi: 10.1038/nature14539` as
     DOI. **Decided by:** test.
150. It reads `Deep learning for computer vision` and `"LeCun 2015"` as
     title. **Decided by:** test.
151. It reads `LeCun 2015`, `van der Berg 2019` and `LeCun 2015 deep
     learning` as author and year, and the reply is exactly that of `find`
     with the same words. **Decided by:** test.
152. Ambiguous and edge lines: `Vision 2020` is author and year (with the
     title button); `2020 vision` (year first), `Smith 2019 deep learning
     methods` (5 words), `Smith 1850` (year out of range) and a 2-line
     message `Smith 2019` / `Jones 2020` are titles; `hello` gets the short
     help. **Decided by:** test.
153. Every lookup and `find` reply keeps how its lines were read
     (`message["read_as"]`), and `refchat.read_as_line` gives the line
     drawn above it. **Decided by:** test.
154. "Search as title instead" sends the quoted line and gives a title
     lookup; "Search as author and year instead" sends `find <line>`; a DOI
     block has no switch button. **Decided by:** test.
155. `split_tags` finds `#apa`, `#Harvard`, `#chicago`, `#all`, and the
     derived field tags (`#psychology`, `#is`, `#information-systems`,
     `#management`, `#gm`), removes them from the text and leaves other
     text (including `C#` and unknown tags) unchanged. **Decided by:** test.
156. A tag inside a lookup or `find` changes the setting before the search:
     `lecun 2015 #psychology` sends Psychology's ISSN filter; the chip label
     (`refchat.chip_labels`) then shows the new style and field.
     **Decided by:** test.
157. A message of tags only (`#chicago`, `#chicago #is`) changes the
     settings, replies "Style set to Chicago." / "Field set to Information
     Systems.", and makes no request. **Decided by:** test.
158. A derived tag shared by two fields is not offered; with a broken
     `config/fields.json` only `#all` and the style tags work.
     **Decided by:** test.
159. An unknown tag stays in the searched text and the reply starts with
     its note. **Decided by:** test.
160. The old commands (`find`, `add N`, `list`, `style`, `edit`, `clear`,
     `help`, `cite`, `accept`) give the same replies as before.
     **Decided by:** test.
161. Results unchanged: for a fixed set of inputs (DOI, DOI link, Verified
     title, Check and Not found titles with provisional references, no
     result, Unavailable, a 3-line paste, `find`, `add`, `list`, `cite`,
     each style), the reply text equals the text recorded from the code
     before the change (`tests/fixtures/before_simplification.json`).
     **Decided by:** test.
163. A card's Copy popover (`refchat.copy_text`) holds the reference in the
     card's style without `*`, and its parenthetical and narrative
     citations; a "No match found" card has none. The card's one list button
     (`mylist.card_list_button`) is Add to list (or Already in list), the
     provisional reference's on a provisional card, never a candidate's.
     **Decided by:** test.
162. With the live API: one bar, the chip row, cards with only Add to list
     and Copy, and a sidebar with only My list and Help; nothing listed as
     removed in 7.9 is on the page. **Decided by:** manual.

#### Field hierarchy, Top journals and journal verification

Tests for 89–104 are in `tests/test_journals.py`, with Crossref mocked by
the `FakeCrossref` of `tests/test_refchat.py` (extended to answer
`/journals?query=` and `/journals/<issn>`). No network.

89. Choosing several sub-fields (from one group) searches the union of their
    verified ISSNs, each ISSN once, in file order, even when a journal is
    listed under two sub-fields. **Decided by:** test.
90. The existing fields (Management, General Management, Information
    Systems, Psychology, Marketing) are still offered as sub-fields under the
    same names and search the same journals as before, less any that fail
    verification. **Decided by:** test.
91. The journal multiselect offers every verified journal of both files once,
    sorted alphabetically. **Decided by:** test.
92. With journals selected, `find` and a title lookup use exactly those
    journals' ISSNs, whatever the Field setting, and replies say "Searched
    in: N selected journals" ("1 selected journal" for one).
    **Decided by:** test.
93. A preset (e.g. "FT50") selects exactly that list's verified journals,
    replacing the selection, and reports how many were left out.
    **Decided by:** test.
94. Reset to all journals empties the selection, and the Field setting
    applies again on the next search. `clear` keeps the journals.
    **Decided by:** test.
95. With more than 20 ISSNs, the ISSNs are split into batches of at most 20
    in order, one request per batch; together the batches hold every ISSN
    exactly once. **Decided by:** test.
96. Batched results are merged: a DOI returned by two batches appears once;
    records outside the filter are dropped; a title search is then scored as
    in 7.1; `find` keeps the 5 with the highest Crossref `score` (ties in
    batch order). **Decided by:** test.
97. If any batch fails (HTTP error, timeout, bad JSON), the search is
    `Unavailable` as for an unbatched search, with no partial results.
    **Decided by:** test.
98. A DOI lookup with journals selected or a big field chosen sends one
    request, the same as with "All fields", and shows "Field filter not used:
    a DOI lookup is exact." **Decided by:** test.
99. If `config/top_journals.json` is missing, invalid JSON, or the wrong
    shape (7.4), there are no presets, the warning is shown, the multiselect
    still offers the verified journals of `config/fields.json`, and nothing
    crashes. **Decided by:** test.
100. A journal not in `config/journals_verified.json`, or listed there with a
     different name or ISSN set, is not offered, not searched and not part of
     a preset. **Decided by:** test.
101. `verify_journals.py` marks a journal verified only when Crossref has a
     journal with the same normalised title whose ISSN set equals the
     configured one, and each configured ISSN's `/journals/<issn>` record has
     that title (7.5). Without `--write` it writes only the report, never
     `config/journals_verified.json`. **Decided by:** test (FakeCrossref).
102. `verify_journals.py` reports, with a reason, each failure: no journal
     with that title, several with that title, ISSNs differ (listing both
     sets), an ISSN unknown to Crossref or belonging to another title, the
     same name with different ISSNs in the two files, and Crossref
     unavailable. Failed journals are not written to
     `config/journals_verified.json`. **Decided by:** test.
103. `verify_journals.py --fill` writes ISSNs only into entries whose `issn`
     list is empty, only from a single exact-title Crossref record, and
     touches nothing else in the config files. **Decided by:** test.
104. The chat requests only `api.crossref.org`, writes no files, and only
     reads the three config files; only `verify_journals.py` writes
     `config/journals_verified.json` and the report. **Decided by:** test.
105. With the live API: the sidebar shows Group, Sub-fields, Top journals,
     the presets with their source notes, and Reset; `find Kumar 2016` with
     "Marketing" or FT50 returns only works from those journals.
     **Decided by:** manual.
106. **Reviewed by a human:** the verified table and failures in
     `reports/journal_verification.md`, and each preset's membership against
     its stated source, are approved by the student before the app uses
     them. **Decided by:** reviewed by a human.

## 5. Output files

| File | Purpose |
|---|---|
| `refchat.py` | Chat logic, no Streamlit: `parse_command`, `handle_message`, reply text, `accept`, `cite`, and `in_export` (which references go in the export). Calls `agent.py` for everything else. |
| `citations.py` | In-text citations in APA 7, Harvard and Chicago author-date (`in_text`, `in_text_all`, rules in 7.7), no Streamlit. |
| `suggest.py` | Live suggestions: minimum length, DOI check, cache, one request per second, the Crossref request and the labels (7.8). No Streamlit. |
| `tests/test_citations.py`, `tests/test_provisional.py`, `tests/test_input.py`, `tests/test_suggest.py` | Tests for criteria 119–145. |
| `export.py` | Builds `references.txt` and `references.csv` as bytes in memory, no Streamlit. |
| `listsearch.py` | Searching My list and `list FILTER`: the searched text of an entry, the terms of a search, matching, status filter and sort. No Streamlit. |
| `tests/test_listsearch.py` | Tests for criteria 107–117. |
| `mylist.py` | My list: add (with the duplicate check), remove, clear, and `my_list.txt` / `my_list.csv` as bytes in memory, no Streamlit. |
| `fields.py` | Reads and checks `config/fields.json` (7.3), `config/top_journals.json` (7.4) and `config/journals_verified.json` (7.5): group, sub-field and journal options, presets, the filter's ISSNs and label, or the warnings. No Streamlit. |
| `config/top_journals.json` | Ranking lists (FT50, UTD24, AIS Basket of Eight, ...) with source note and last-checked date (7.4). Edited by hand; the chat only reads it. |
| `config/journals_verified.json` | Written only by `scripts/verify_journals.py`: the journals that passed verification (7.5). The chat only reads it. |
| `scripts/verify_journals.py` | Checks every journal of both config files against Crossref `/journals` (7.5); `--fill` fills empty ISSN lists from Crossref. Run by hand with the live API. |
| `reports/journal_verification.md` | Written by the script: the verified table and every failure with its reason, for human approval. |
| `tests/test_journals.py` | Tests for criteria 89–104. |
| `tests/test_fields.py` | Tests for criteria 36–45. |
| `tests/test_mylist.py` | Tests for criteria 75–87. |
| `app.py` | Streamlit page: `st.chat_input`, `st.chat_message`, the sidebar with the export buttons, state in `st.session_state`. Only draws what `refchat.py` and `export.py` return. |
| `agent.py` | Small additions only: `resolve_line` can skip the cross-check; `verify` has a Crossref-only mode using `crossref_identified`; Crossref unavailability is marked on the entry; `search_crossref_author_year` for `find`; `verify` gives search results and added references their fixed `Check` reason; `format_citation` keeps Crossref's organisation authors as `organisation_authors`; the title and author-and-year searches take an optional list of ISSNs (Crossref `issn` filter plus the same check in code), split into batches of `ISSN_BATCH_SIZE` (7.6); `verify` has a fixed `Check` reason for a title-search candidate added to My list. Refs mode behaves as before. Since 2026-10-18 it has no `claude_agent_sdk` import, no paper mode and no `refs chat`: only plain functions and the `refs` / `refs edit` command line. |
| `config/fields.json` | Groups, sub-fields and their journals (name and ISSNs) for the Field setting (7.3). Edited by hand (ISSNs only via `--fill` or copied from the report); the chat only reads it. |
| `tests/test_refchat.py` | Tests for criteria 1–17 and 21–33. |
| `tests/test_export.py` | Tests for criteria 48–65. |
| `tests/fixtures/crossref_nature14539.json` | Recorded Crossref response for criterion 1, trimmed to the fields used. |
| `tests/test_simple_ui.py`, `tests/fixtures/before_simplification.json` | Tests for criteria 149–161 and 163 (7.9); the fixture is the reply text recorded before the change. |

## 6. Out of scope

- A separate JavaScript front end (the earlier static browser chat in `web/`).
- Saving chat references or edits between sessions, or writing them to
  `refs/library.json` or `refs/overrides.json` (`refs edit` still does that).
- The old card view of `refs/library.json`.
- Sources other than Crossref in the chat (OpenAlex, Semantic Scholar, Google
  Scholar scraping). Refs mode still cross-checks with them.
- Webpage URLs: a line without a DOI is treated as a title.
- Author disambiguation beyond what Crossref returns for `find`: no ORCID,
  first-name, initials or affiliation matching, and no re-ranking of
  Crossref's results.
- A `verify` command: a reference added from a search is verified only by
  pasting its DOI as a new lookup.
- Field setting for DOI lookups: a DOI is exact, so it is looked up
  whatever the field, and its journal is not compared with the field.
- Merging My list with the export, or saving My list between sessions.
- Keeping each My list item in the style it was added in: the whole list
  always follows the current style.
- Conference papers and book chapters when a field is chosen: the field lists
  hold journals only (no proceedings or book series), so a field search finds
  journal articles only.
- Choosing journals for a sub-field automatically, fetching ranking lists
  automatically, or editing any journal list from the page: they are edited
  by hand in `config/fields.json` and `config/top_journals.json` and checked
  by `scripts/verify_journals.py`.
- Conference proceedings in the Computer Science sub-fields: the lists hold
  journals only, so most CS venues (NeurIPS, CVPR, ACL, CHI, ...) are not
  searched when a CS sub-field is chosen. Use "All fields" for them.
- Widening a search automatically when nothing is found under a filter.
- Running the verification script from the page, or on a schedule.
- Chicago notes-and-bibliography footnotes: the Chicago in-text citations
  are author-date only (7.7).
- Abbreviating organisation names (e.g. WHO) in citations.
- Converting a shortened title to title case: it is used as Crossref gives
  it and marked `Check`.
- Filling `st.chat_input` from a suggestion: Streamlit 1.66's chat input
  can't be filled from code, so a suggestion goes in the Look up box.
- Suggestions for `find`, and suggestions from any source but Crossref.
- Adding the APA year letters (1989a, 1989b) automatically: the citations
  are marked `Check` instead.
- Abbreviating organisation names or deciding the order of mixed
  organisation and person authors automatically.
- Other export formats (BibTeX, RIS, Word) or saving exports on the
  server.
- User accounts, deployment or hosting.
- Any AI model, backend server or API key.
- (7.9) Reading author and year in a pasted list of several lines.
- (7.9) A JavaScript clipboard button: Copy uses Streamlit's own copy icons.
- (7.9) Aliases written in `config/fields.json`: field tags are derived from the names in code.

## 7. Decisions

Agreed on 2026-10-15. They apply to refs mode (`agent.py`) and the
Streamlit chat (`refchat.py`), which share the code in `agent.py`.
Each band and rule has a test in `tests/test_refs.py`
(`python -m unittest discover tests`).

### 7.1 Title search (a line with no DOI)

Crossref is searched with `query.bibliographic` (20 rows). Each result's title
is scored against the line with the title similarity of section 2 (rounded to
2 decimals). A DOI listed twice counts once. Then, in order:

| Best score | Other conditions | Label | Reference text |
|---|---|---|---|
| no results, or < 0.75 | | `Not found` | none |
| 0.75 to < 0.9 | | `Check` (weak match), with candidates | none |
| ≥ 0.9 | another DOI also ≥ 0.9 | `Check` (several records), with candidates | none |
| ≥ 0.9 | runner-up within 0.05 of the best (gap ≤ 0.05 after rounding) | `Check` (too close to call), with candidates | none |
| ≥ 0.9 | runner-up more than 0.05 below | the match: handled as for a DOI | yes |

- The weak-band rule and the runner-up rule both apply below 0.9, so a weak
  match lists both reasons when both hold.
- Candidates: the top 5, best first, with title, year, DOI and score.
- A match is never picked silently: every `Check` or `Not found` keeps the
  fields as `not stated`.
- Constants in `agent.py`: `TITLE_WEAK_SCORE = 0.75`,
  `TITLE_AGREE_SCORE = 0.9`, `RUNNER_UP_MARGIN = 0.05`.

### 7.2 APA 7 sentence case (journal-article titles, APA only)

- Capitalise the first word, and the first word after a colon, `?` or `!`.
- Keep all-caps words (MIS, IT, COVID-19, 3D), mixed-case words (iPhone,
  McDonald) and the pronoun "I" exactly as they are.
- If the source title is already in sentence case (most ordinary words of
  4+ letters are lowercase), keep its capitalised words: they are proper nouns.
- If the source is in Title Case, lowercase the other capitalised words. Flag
  `Check` only where code can see the casing is unclear: a capital after a
  hyphen (Self-Efficacy), a capital after a dash, or a title written all in
  capitals. Other proper nouns are not flagged (criterion 20).
- Em dash (assumption): remove any spaces around an em dash (`—`) and
  capitalise the first word after it, as after a colon. Source: APA
  Publication Manual §6.17 as quoted by a university guide; not confirmed
  against the manual or the course guide. Code can't tell a subtitle dash
  from a dash inside a sentence, so whenever this rule is applied the entry
  is flagged `Check`. Example: "Research Commentary —The New Organizing Logic
  of Digital Innovation: An Agenda for Information Systems Research" ->
  "Research commentary—The new organizing logic of digital innovation: An
  agenda for information systems research", flagged `Check`.
- Spaced en dash (` – `, a space on both sides): left unchanged; the next
  word follows the ordinary rules above. The entry is flagged `Check` with
  the reason "spaced en dash, review casing and punctuation", because it is
  often typed in place of an em dash.
- Show the original title next to the formatted one whenever they differ
  (in `drafts/references_apa.md` and the Streamlit chat).
- A title corrected by hand is used exactly as typed and never flagged.
- Chicago and Harvard keep the title as Crossref gives it.

### 7.3 Field lists (`config/fields.json`)

Agreed on 2026-10-16; hierarchy added 2026-10-16 (pending approval). Tested in
`tests/test_fields.py` (36–45) and `tests/test_journals.py` (89–104).

- The file is one JSON object `{group: {sub-field: [journals]}}`. Keys are
  shown in the dropdown and multiselect as written, in file order. Each group
  has at least one sub-field; each sub-field a non-empty list of journals.
- Each journal is `{"name": "...", "issn": ["....-....", ...]}`: a non-empty
  name and a list of ISSNs, each written `NNNN-NNNC` (C is a digit or `X`).
  An empty list means "not filled yet": allowed in the file, but such a
  journal is never verified, so never used. A journal lists both its print
  and its online ISSN when Crossref has both.
- Anything else (including the old flat `{field: [journals]}` shape) makes
  the whole file unusable, with the warning of section 3 naming the problem.
  There is no partial use of a broken file.
- ISSNs come from Crossref (`--fill`, or copied from the report), never typed
  from memory.
- Groups and sub-fields:
  - **Computer Science**: Artificial Intelligence, Machine Learning, Natural
    Language Processing, Computer Vision, Human-Computer Interaction,
    Databases and Data Mining, Software Engineering, Cybersecurity, Networks
    and Distributed Systems, Computer Systems and Architecture, Theory and
    Algorithms, Graphics and Visualisation, Robotics, Information Retrieval.
  - **Management Science**: Operations Management, Operations Research and
    Optimisation, Supply Chain and Logistics, Decision Analysis, Business
    Analytics, Simulation, Game Theory and Market Design, Information
    Systems, Marketing Science, Finance and Risk.
  - **Existing fields** (pending approval): Management, General Management,
    Information Systems, Psychology and Marketing keep their names and
    current journals. Information Systems becomes the Management Science
    sub-field of the same name (same four journals plus any added);
    Management, General Management and Marketing become further Management
    Science sub-fields; Psychology goes in a third group, "Other". Their
    ISSNs were typed by hand, so they are verified like every other journal;
    one that fails is left out until fixed.
  - Journals per sub-field (3–6 each, journals only) are proposed with the
    verification report and approved by a human (criterion 106).
- Example:

  ```json
  {"Management Science": {"Marketing Science": [{"name": "Marketing Science", "issn": ["0732-2399", "1526-548X"]}]}}
  ```

### 7.4 Ranking lists (`config/top_journals.json`)

- One JSON object `{list name: {"source": "...", "last_checked":
  "YYYY-MM-DD", "journals": [journals]}}`, journals as in 7.3. List names
  are the button labels, in file order.
- `source` names the publisher and URL the membership was copied from (e.g.
  the Financial Times' 2016 FT50 article, UT Dallas' UTD24 page, the AIS
  Senior Scholars' page); `last_checked` is the date it was compared with
  that source. Membership is copied from the source, never from memory.
- Seed lists: FT50, UTD24, AIS Senior Scholars' Basket of Eight. Others are
  added by hand when the student names them.
- Shape problems make the whole file unusable (section 3, "Top journals").

### 7.5 Journal verification (`scripts/verify_journals.py`)

For every journal in both files (a name listed twice with the same ISSNs is
checked once):

1. `GET api.crossref.org/journals?query=<name>&rows=20`. Keep the records
   whose normalised title equals the normalised name (lowercase, `&` read as
   "and", accents and punctuation removed, a leading "The" dropped, spaces
   collapsed). No exact title is a failure; no fuzzy matching.
2. The configured ISSN set must equal the ISSN set of one of those records
   (Crossref's `ISSN` list, upper-case). Otherwise a failure listing both
   sets (or "several Crossref journals with this title" when more than one
   record has the title and none matches).
3. For each configured ISSN, `GET api.crossref.org/journals/<issn>` must
   return a record with the same normalised title.
4. A name with different ISSN sets in the two files fails; so does a network
   error or bad response ("Crossref unavailable, re-run").

**Approval gate.** By default the script only writes the report (a dry
run); `config/journals_verified.json` is written only with `--write`, run
after a human has approved the report (criterion 106). Until then the chat
has no verified journals and every filter behaves as "All fields", with the
"Journal lists not verified" warning.

With `--write`, only journals passing all steps are written to
`config/journals_verified.json` as `{"checked": "YYYY-MM-DD", "journals":
[{"name", "issn", "crossref_title"}]}`. `reports/journal_verification.md`
lists the verified table (name, Crossref title, ISSNs, lists it is in) and
every failure with its reason and Crossref's exact-title records, if any.
The chat uses a journal only if its name and ISSN set match a verified entry
exactly.

`--fill`: before verifying, an entry with an empty `issn` list gets the ISSNs
of the single exact-title Crossref record (step 1); with none or several, it
stays empty and is reported. Nothing else in the config files is changed.
The script waits 1 second between requests and sends a `User-Agent` naming
the project (Crossref's polite-use request).

### 7.6 Batching ISSN filters

- `ISSN_BATCH_SIZE = 20` (constant in `agent.py`). The filter's ISSNs, in
  order, are split into consecutive batches of at most 20; each batch is one
  request with the same other parameters (`rows=5` for `find`, `rows=20` for
  a title search).
- Results are merged in batch order, a repeated DOI keeps its first record,
  and records outside the filter are dropped (`in_journals`).
- Title search: the merged records are scored exactly as in 7.1.
- `find`: the merged records are sorted by Crossref's `score` (highest
  first; missing counts as 0; ties keep batch order) and the first 5 kept.
  With one batch this is Crossref's own order, as before.
- If any batch fails, the whole search fails as Crossref unavailable; no
  partial results are shown.

### 7.7 In-text citation rules

Proposed 2026-10-16, pending approval. **The course guide was not
available when this was written.** The APA 7 rules are from the APA
Publication Manual (7th ed.) as summarised in the APA Style website's
"Author–date citation system" and "Group authors", "Missing reference
information" pages; Harvard is Cite Them Right (12th ed.), which is the
Harvard variant `agent.STYLES` already names; Chicago is the Chicago Manual
of Style (17th ed.) author-date system, ch. 15. Rules marked **to be
confirmed** are the ones where university guides commonly differ or where
code makes a choice; each must be checked against the course guide
(criterion 126) and is changed here, not guessed in code.

Family names are used exactly as stored (accents included). "Year" is the
entry's year.

| Authors | APA 7 parenthetical / narrative | Harvard (Cite Them Right) | Chicago author-date |
|---|---|---|---|
| 1 | (Mithas, 2021) / Mithas (2021) | (Mithas, 2021) / Mithas (2021) | (Mithas 2021) / Mithas (2021) |
| 2 | (Mithas & Rust, 2021) / Mithas and Rust (2021) | (Mithas and Rust, 2021) / Mithas and Rust (2021) | (Mithas and Rust 2021) / Mithas and Rust (2021) |
| 3 | (Mithas et al., 2021) / Mithas et al. (2021) | (Mithas, Rust and Lee, 2021) / Mithas, Rust and Lee (2021) **to be confirmed** | (Mithas, Rust, and Lee 2021) / Mithas, Rust, and Lee (2021) **to be confirmed** |
| 4 or more | (Mithas et al., 2021) / Mithas et al. (2021) | (Mithas et al., 2021) / Mithas et al. (2021) | (Mithas et al. 2021) / Mithas et al. (2021) |
| no year | (Mithas, n.d.) / Mithas (n.d.) | (Mithas, no date) / Mithas (no date) | (Mithas n.d.) / Mithas (n.d.) |

- **Three authors, Harvard and Chicago (to be confirmed).** Cite Them Right
  and Chicago 17th name up to three authors and use "et al." from four.
  Many university Harvard guides use "et al." from three, as APA does. The
  request for this feature listed "3+ = first author et al." under APA; the
  table follows the published sources for Harvard and Chicago until the
  course guide says otherwise.
- **"et al."** is plain text, not italic, in all three styles.
- **Organisation as author.** When Crossref's only authors are
  organisations (`organisation_authors` and no people), the organisation's
  name takes the family name's place, as Crossref gives it, in the same
  table (two organisations = the 2-author row). No abbreviation is made. If
  an entry has both organisations and people, Crossref's order between them
  is not kept (`people()` and `organisation_authors` are separate lists), so
  no citation is built: `Check`, "organisation and person authors: write
  this citation by hand". An author with no given name (typed with `edit`)
  is used as a name, marked `Check`, "author "X" has no given name: if it is
  an organisation this is right; if it is a person, add the given name".
- **No author (to be confirmed).** The title takes the author's place. Code
  can't choose "the first few words" well, so the **shortened title** is
  the main title, Crossref's title up to the first `:`, `?` or `!` (a `?`
  or `!` is kept, a `:` is not; with none, the whole title), with its casing
  as Crossref gives it. Always
  `Check`, "shortened title chosen by code: check it".
  - Article, chapter, webpage: in double quotes. APA puts the comma inside:
    `("Deep Learning," 2015)` / `"Deep Learning" (2015)`; Chicago:
    `("Deep Learning" 2015)`; Harvard: `("Deep Learning", 2015)` **to be
    confirmed** (Cite Them Right's own example uses italics for most works
    without an author).
  - Book, report: in italics (`*...*`): APA `(*Deep Learning*, 2015)`,
    Harvard `(*Deep Learning*, 2015)`, Chicago `(*Deep Learning* 2015)`.
  - No author and no title: no citation is built.
- **No date.** Built with the style's form (table), `Check`, "Crossref gives
  no year: check the source really has no date". Both no author and no date
  combine (e.g. `("Deep Learning," n.d.)`).
- **Same parenthetical citation twice:** both `Check` (section 3); no
  letters are added.
- **Chicago reference list (to be confirmed).** `agent.STYLES` formats the
  Chicago reference list in the notes-and-bibliography form ("Chicago 17th
  (bibliography)", year near the end). Author-date in-text citations
  normally go with an author-date reference list (year after the authors).
  The reference list is not changed by this feature; whether the course
  wants author-date in-text citations with this list is for the student to
  confirm.

### 7.8 Live suggestions and Crossref etiquette

Proposed 2026-10-16, pending approval. Constants in `suggest.py`; tested
with a fake clock, so no test waits.

- `TYPING_PAUSE = "500ms"`: Streamlit's `live` pause, the debounce, done in
  the browser: Python is only called after the student stops typing.
- `MIN_CHARS = 4`: shorter text (after trimming) asks nothing.
- `MIN_INTERVAL = 1.0` seconds between suggestion requests (Crossref asks
  for a low, steady rate). A request that comes sooner sleeps the rest of
  the second first, so the last text typed is always the one asked about.
- Cache: up to 200 entries in memory, key = (text lowercased with spaces
  collapsed, the filter's ISSNs). Lost on restart. A cached answer makes no
  request.
- `PAUSE_AFTER_ERROR = 30` seconds: after a failed request (any error of
  `agent.get_json`), no suggestion request for 30 seconds.
- `rows=5` and `select=` keep each response small.
- `mailto`: from `CROSSREF_MAILTO` only (section 2), on every chat request
  to Crossref, so Crossref can contact the owner instead of blocking. The
  `User-Agent` stays "research-companion (university assignment)".

### 7.9 Interface simplification (one input bar, chips, smaller cards)

Agreed on 2026-10-16. Changes the interface only. The student's answers:
criterion 145 is withdrawn; the references export is removed from the page
and My list's downloads are the download; field tags are derived from the
names; the bar sits inline at the top of the page.

**Reason.** The page had grown to two dropdowns, a suggestions box, a Look
up box, two button types per card, two citation boxes per card, two sets of
downloads, list filters and the full help in the sidebar. A student who
wants one reference has to learn too much of it first. Everything the page
does can come from one input bar plus two small settings, so the rest goes.

**Unchanged:** matching, the 7.1 thresholds, statuses and reasons,
provisional references, in-text citations (7.7), My list rules, both export
modules (`export.py`, `mylist.py`), Crossref only, no AI and no keys. For
the same input, the reply text kept in the history is the same as before
(criterion 161). Every command still works as typed.

**1. One input bar** (`refchat.interpret`, no Streamlit). A message is read
in this order; the first rule that fits decides:

| # | Message | Read as |
|---|---|---|
| 1 | only tags (below) | settings change, nothing searched |
| 2 | starts with a double quote | title(s), as now |
| 3 | first word is a command (`find`, `add`, `list`, `style`, `edit`, `accept`, `cite`, `clear`, `help`) | that command, as now |
| 4 | several non-blank lines | one lookup per line, each a DOI or a title (`input_kind`, as now) |
| 5 | one line with a DOI or DOI link (`agent.find_doi`) | DOI lookup |
| 6 | one line of at most 4 words, one of them a year 1900–2099, with at least one word containing a letter *before* the year | author and year: exactly `find <line>` (surname = words before the year, topic = words after) |
| 7 | one word, not a DOI | short help, as now |
| 8 | anything else | title lookup |

- Author and year are detected only in a single-line message, so pasting a
  list never runs several `find`s (each would replace the latest search that
  `add N` refers to).
- **Interpretation line.** Every lookup or result block shows, above it,
  "Searched as: DOI", "Searched as: title" or "Searched as: author and year
  (SURNAME, YEAR[, topic: WORDS])". It is kept
  beside the reply (`message["read_as"]`, one per line, or one for a
  search), not in the reply text, so the reply text is unchanged.
- **Search as the other type** (one button, sends a message as if typed):
  - author and year → **Search as title instead**, which sends the line in
    double quotes (rule 2);
  - title whose line `find` can read (a four-digit year with a word with a
    letter before it) → **Search as author and year instead**, which sends
    `find <line>`;
  - DOI → no button: a DOI is exact (as for the Field filter).

**Layout.** `st.chat_input` is pinned to the bottom of the page and nothing
can be drawn under it, so the bar is placed inline at the top (inside a
container), the chip row under it, and the replies below, newest first
(each message above its reply).

**2. Style and field chips and tags.** Under the input bar, one row: the
style chip and the field chip, e.g. "APA 7 · All fields". Each is an
`st.popover` holding a small selector; choosing a style sends `style X`
(as the dropdown did), choosing a field calls `refchat.set_field`.

- **Tags** (`refchat.split_tags`, no Streamlit): a word starting with `#`
  at the start of the message or after a space, matched ignoring case.
  `#apa`, `#harvard`, `#chicago` set the style. `#all` sets All fields.
  Field tags are derived in code from the field names in
  `config/fields.json` (read only, never written): the name in lower case
  with spaces as hyphens (`#information-systems`) or removed
  (`#informationsystems`), and for a name of two or more words its initials
  (`#is`, `#gm`). A derived tag that two fields (or a style) would share is
  not offered. With a broken file only `#all` and the style tags exist.
- Known tags are removed from the text and applied **before** the rest of
  the message is read, so `lecun 2015 #psychology` searches Psychology. The
  setting stays, like the chip. Two tags of one kind: the last one wins.
- A `#word` that is not a known tag is left in the text unchanged (it may be
  part of a title, e.g. `#MeToo`) and the reply starts with "#metoo is not a
  tag, so it was searched as text."
- **Tags alone** (rule 1): the reply is "Style set to <style>." and/or
  "Field set to <field>." and nothing is searched.

**3. Result cards.** Each card: the interpretation line, the reference
(provisional ones keep the orange badge, match score and quote block), the
in-text citation as one line "In-text: <parenthetical> · <narrative>" (or
"Citation: **Check**" and the reasons), the status and reasons, the Google
Scholar and Google links, and two buttons only:
- **Add to list** (or a disabled **Already in list**), as before;
- **Copy**: a popover with three `st.code` boxes (the reference without `*`,
  the parenthetical, the narrative), each with Streamlit's own copy icon.
  Streamlit has no clipboard button of its own, and a JavaScript component
  would be a new dependency, so the copy icon is reused.
A "No match found" or Unavailable card has neither button.

**4. Sidebar:** only **My list (N)**: **Search my list**, the matching items
each with **Remove**, **Clear list**, the `my_list.txt` (in-text lines
included) and `my_list.csv` downloads (always the full list), and a
collapsed **Help** expander with a short help (`refchat.quick_help()`).
The `help` command still replies with the full `help_text()`.

**5. Removed from the page** (the functions and their tests stay, except as
noted):

| Removed | Code that stays |
|---|---|
| Top journals panel (section 3): never built; its spec text is withdrawn | — |
| Style dropdown and Field dropdown | replaced by the chips; `style`, `set_field` unchanged |
| Live suggestions box and Look up box | `suggest.py` and criteria 139–144; criterion 145 (an inspection of `app.py` for the box) is withdrawn |
| My list Status filter, Sort and "Export only matching" | `mylist.shown_items`, `sorted_items`, `listsearch` and criteria 107–117 |
| "Add to export" / "✓ In export" button on cards | `button_for`, `press_button`, criteria 69–73; `accept N` still confirms |
| Export section (count, in-text checkbox, `references.txt` / `.csv` downloads) | `export.py` and criteria 48–65 |
| "Add candidate K to list" buttons on provisional cards | `mylist.list_buttons_for`, criteria 75–87 |
| The two citation boxes on each card | `card_citation`; the text moves to the Copy popover |
| Full help in the sidebar | `help_text()`, shown by `help` |
