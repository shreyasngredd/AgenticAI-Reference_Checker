# Goal spec: Citation Checker beta (Streamlit reference chat)

## 1. Goal

A chat page in the Streamlit app (`streamlit run app.py`) where the student
pastes DOIs or paper titles and gets back APA 7 references (Chicago or Harvard
on request), each with a status worked out in code, built only from Crossref
metadata and never invented. The student can also search Crossref by author
surname and publication year (`find`), see up to 5 candidates, and add the
right one to the list (`add N`). A **field** setting in the sidebar can limit
`find` to a hand-picked list of journals for one field (section 3, "Field
setting"). The chat replaces the old card view of `refs/library.json`.

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
- **Field lists are configuration, not code.** The journals for each field
  are in `config/fields.json` (name and ISSNs), read with the standard
  library. Changing them needs no code change. The chat only reads this file.
- **Session only.** Chat history, references and edits live in
  `st.session_state`. Nothing is written to disk: not `refs/`, not `notes/`,
  not `drafts/`. Edits are lost when the page is reloaded.
- **Title similarity** is `difflib.SequenceMatcher(...).ratio()` on
  normalised titles (lowercase, accents, HTML tags and punctuation removed,
  spaces collapsed), rounded to 2 decimals (`agent.title_similarity`).
- **Simple and commented** code (university assignment): plain functions,
  a comment on each block, a docstring on each function.

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
| `cite N` | Show the APA 7 in-text citations (parenthetical and narrative) for reference N. |
| `clear` | Forget all references, the latest search and the chat history; style back to APA 7. |
| `help` | Show the full help (the same text as the sidebar, below). |
| anything else | A lookup: each non-blank line is one DOI or title. |

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
- A line is a **DOI** if it contains `10.<4-9 digits>/<non-space characters>`
  (with or without `https://doi.org/` or `doi:` in front); otherwise it is a
  **title**.
- `edit` fields are the citation fields of `agent.CITATION_FIELDS`. Values are
  checked by `agent.parse_value` (authors as `Family, Given; Family, Given`,
  `not stated` to clear a field). Changing `type` clears the old type's
  fields, as `refs edit` does.

### Outputs

For each looked-up line, in order, one reply block:

- the reference's **number** (its position in `list`);
- the **reference text** in the current style, with italics rendered. When
  nothing was found it is the line as typed;
- for APA, the **original title** when the sentence-case title differs;
- the **status**: `Verified`, `Check`, `Not found` or `Unavailable`;
- the **reasons**, for every status except `Verified`;
- for `Verified`, the line **"Verified against Crossref only"**;
- a **Google Scholar** and a **Google** search link (`agent.search_links`):
  title + first author's family name, or the line as typed when nothing was
  found.

### Sidebar

The page heading is the title **Citation Checker beta**, a one-line subtitle
and a one-line intro; the details are in the sidebar (`st.sidebar`), which
always shows:

- at the top, a reserved slot for the **Field** dropdown ("Field setting",
  below);
- an **Export** section: how many references are in the export, and two
  `st.download_button`s, for `references.txt` and `references.csv`
  ("Export", below);
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

### Field setting (`find` only)

A dropdown in the sidebar labelled **Field** offers "All fields" first, then
each field in `config/fields.json` in the file's order (seeded with
"Information Systems", "Marketing" and "General Management"). "All fields" is
the default.

- **All fields:** `find` sends exactly the request described above, and
  results have no field label.
- **A field:** `find` sends the same single request, with one `issn:ISSN`
  added to the `filter` for every ISSN of every journal listed for that field
  (Crossref treats repeated `issn` filters as "any of these"). It uses
  Crossref's free public API and needs no key. Each result shows the line
  **"limited to: <field> journals"** under its heading; the rest of the
  result is as above.
- **Nothing found with a field:** "Crossref found no results for SURNAME YEAR
  in <field> journals. Try “All fields” in the sidebar." (with the topic
  words after the year when given).
- **`find` only.** DOI and title lookups, `add`, `list`, `edit` and `style`
  behave the same whatever the field. `clear` does not change the field.
- **File problems.** If `config/fields.json` is missing, is not valid JSON, or
  does not have the shape in section 7.3, the dropdown offers only "All
  fields", the page shows the warning "Field lists unavailable
  (config/fields.json: <reason>). Using All fields.", and `find` works as
  with "All fields". A chosen field that is no longer in the file is treated
  as "All fields".
- The file is read again on each message, so an edit takes effect on the next
  message, without a code change or restart.

### Statuses

**Verified** means: DOI resolved in Crossref, or title match above threshold
with a clear lead over the runner-up. In terms of section 7.1, the title match
has similarity at least 0.9 and the runner-up is more than 0.05 below it.
The status is `Verified` only when, in addition, code finds nothing to check.

| Situation | Status | Reasons |
|---|---|---|
| Verified (above), nothing to check | `Verified` | none; shows "Verified against Crossref only" |
| Verified (above), but a required APA 7 field is missing or malformed, the title casing is unclear (7.2), the DOI's title doesn't fit the text typed, or the reference text was typed by hand | `Check` | each problem |
| Title search: several records, too close to call, or weak match (7.1) | `Check` | the 7.1 reasons and candidates; no reference built |
| DOI: Crossref has no record (HTTP 404) | `Not found` | "Crossref has no record for DOI ..." |
| Title search: nothing at 0.75 or more | `Not found` | the 7.1 reason |
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
  the sidebar (it limits `find` to that field's journals; "All fields" by
  default), the meaning of each status, and "Edits are kept
  for this session only and are lost when you reload the page."
- `accept N`: see "Confirming a reference" below.
- `cite N`: see "In-text citations" below.
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
Citation Checker beta: reference list (<style name>)
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
| `parenthetical citation`, `narrative citation` | The APA 7 in-text citations, or `Check: <reasons>` when none was built. |
| `Google Scholar link` | The link from `agent.search_links`. |

A field that is missing is written `not stated`, never left blank. With an
empty export the file is the header row only.

### In-text citations (`cite`)

APA 7 only, whatever the current style (the reply says so). Built in code
from the reference's authors and year after edits:

| Authors | Parenthetical | Narrative |
|---|---|---|
| One | (Davis, 1989) | Davis (1989) |
| Two | (Davis & Bagozzi, 1989) | Davis and Bagozzi (1989) |
| Three or more | (Yoo et al., 2010) | Yoo et al. (2010) |

The names are the family names exactly as stored, accents included.

The citation is marked `Check`, with each reason, instead of guessing:

- **Authors not stated** or **year not stated**: no citation is built.
- **Organisation author**: Crossref lists an organisation as an author, or an
  author has no given name (which is how an organisation is typed with
  `edit`). APA cites groups by name and sometimes abbreviates them, which
  needs a person, so no citation is built. Crossref's organisation names are
  kept on the entry as `organisation_authors` (not an editable field) so
  they can be named in the reason.
- **Same citation as another reference**: when another reference in the chat
  would get the same parenthetical citation, both are built but marked
  `Check`, naming the other reference, because APA then adds a letter to the
  year (1989a, 1989b) and that order is the student's to decide.

Otherwise the citation is `OK`. The reply to `cite N` is:

```
**APA 7 in-text citations for reference N**

Parenthetical: (Davis, 1989)
Narrative: Davis (1989)

Citation: **OK**

Reference status: **<status>**
```

With a `Check` citation, the "Parenthetical" and "Narrative" lines are left
out when no citation was built, and "Citation: **Check**" is followed by the
reasons, one per line. With no reference N: "There is no reference N. Type
`list` to see the numbers."

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
18. `refchat.py` and `app.py` contain no API keys and no model provider
    calls. **Decided by:** inspection (a `grep` for `key`, `token`,
    `anthropic`, `openai`, `claude_agent_sdk`).
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

36. The field options are "All fields" first, then the fields of
    `config/fields.json` in the file's order, and "All fields" is the default
    for a new session. **Decided by:** test (the options list);
    manual (the sidebar dropdown shows them).
37. With "All fields", `find` sends exactly the request of criterion 21 (no
    `issn` filter), and no result has a "limited to" line.
    **Decided by:** test.
38. With a field chosen, `find` sends exactly one request to
    `api.crossref.org/works`, whose `filter` has the year filters and one
    `issn:` entry for every ISSN listed for that field, and none for other
    fields. **Decided by:** test.
39. With a field chosen, every result shows "limited to: <field> journals"
    and is otherwise as in criterion 22 (APA 7 preview, `Check`).
    **Decided by:** test.
40. With a field chosen and zero results, the reply is "Crossref found no
    results for SURNAME YEAR [topic words] in <field> journals. Try “All
    fields” in the sidebar." **Decided by:** test.
41. The field applies only to `find`: with a field chosen, DOI and title
    lookups send the same requests and give the same replies as with "All
    fields", and `add`, `list` and `edit` are unchanged. `clear` keeps the
    chosen field. **Decided by:** test.
42. Editing `config/fields.json` (adding or removing a journal, an ISSN or a
    field) changes the options and the `find` request on the next message,
    with no code change. A chosen field that is no longer in the file is
    treated as "All fields". **Decided by:** test (with a temporary file).
43. If `config/fields.json` is missing, not valid JSON, or has the wrong shape
    (section 7.3), the options are only "All fields", the warning "Field
    lists unavailable (config/fields.json: <reason>). Using All fields." is
    shown, `find` works as with "All fields", and nothing crashes.
    **Decided by:** test.
44. `help` explains the Field setting. **Decided by:** test.
45. With a field chosen, the chat still requests only `api.crossref.org` and
    writes no files; `config/fields.json` is only read.
    **Decided by:** test.
46. With the live API and a field chosen, `find` returns only works from that
    field's journals (e.g. `find Kumar 2016` with "Marketing").
    **Decided by:** manual.
47. **Reviewed by a human:** which journals belong to each field is a
    judgement call, not something code can decide. The seed lists are a
    starting point; the student or marker checks them and edits
    `config/fields.json`. The ISSNs were taken from Crossref's journal records
    (`api.crossref.org/journals`) on 2026-10-16, not typed from memory.
    **Decided by:** reviewed by a human.

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
    and the "In-text citations (APA 7)" section with one line per reference,
    as in section 3. **Decided by:** test.
54. `references.csv` has the header row with exactly the columns of section
    3, in order, and one row per exported reference with those values;
    missing fields are `not stated`. **Decided by:** test.
55. A title containing a comma and double quotes is read back unchanged from
    `references.csv` by a CSV reader. **Decided by:** test.
56. An accented author name (e.g. `Müller, Jörg`) is unchanged in the .txt,
    the .csv (decoded as UTF-8) and the in-text citations; the .csv starts
    with the UTF-8 byte-order mark. **Decided by:** test.
57. With an empty export, `references.txt` says "No references to export
    yet." and `references.csv` is the header row only. **Decided by:** test.
58. Building the export writes no files and makes no network request.
    **Decided by:** test.
59. `cite N` gives `(Davis, 1989)` / `Davis (1989)` for one author,
    `(Davis & Bagozzi, 1989)` / `Davis and Bagozzi (1989)` for two, and
    `(Yoo et al., 2010)` / `Yoo et al. (2010)` for three or more, with
    "Citation: **OK**", in any current style. **Decided by:** test.
60. `cite N` with authors or year not stated builds no citation and shows
    "Citation: **Check**" with the reason. **Decided by:** test.
61. `cite N` with an organisation author (from Crossref, or an author with no
    given name) builds no citation and shows "Citation: **Check**" naming
    the organisation. **Decided by:** test.
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

## 5. Output files

| File | Purpose |
|---|---|
| `refchat.py` | Chat logic, no Streamlit: `parse_command`, `handle_message`, reply text, `accept`, `cite`, and `in_export` (which references go in the export). Calls `agent.py` for everything else. |
| `citations.py` | APA 7 in-text citations (`in_text`, `in_text_all`), no Streamlit. |
| `export.py` | Builds `references.txt` and `references.csv` as bytes in memory, no Streamlit. |
| `app.py` | Streamlit page: `st.chat_input`, `st.chat_message`, the sidebar with the export buttons, state in `st.session_state`. Only draws what `refchat.py` and `export.py` return. |
| `agent.py` | Small additions only: `resolve_line` can skip the cross-check; `verify` has a Crossref-only mode using `crossref_identified`; Crossref unavailability is marked on the entry; `search_crossref_author_year` for `find`; `verify` gives search results and added references their fixed `Check` reason; `format_citation` keeps Crossref's organisation authors as `organisation_authors`. Refs mode behaves as before. |
| `config/fields.json` | Journal lists for the Field setting (name and ISSNs per journal). Edited by hand; the chat only reads it. |
| `tests/test_refchat.py` | Tests for criteria 1–17, 21–33 and 36–45. |
| `tests/test_export.py` | Tests for criteria 48–65. |
| `tests/fixtures/crossref_nature14539.json` | Recorded Crossref response for criterion 1, trimmed to the fields used. |

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
- Field setting for anything but `find`: DOI and title lookups ignore it.
- Conference papers and book chapters when a field is chosen: the field lists
  hold journals only (no proceedings or book series), so a field search finds
  journal articles only.
- Choosing journals for a field automatically (e.g. from ranking lists), or
  editing the field lists from the page: they are edited by hand in
  `config/fields.json`.
- In-text citations in Chicago or Harvard style: `cite` and the export's
  in-text section are APA 7 only.
- Adding the APA year letters (1989a, 1989b) automatically: the citations
  are marked `Check` instead.
- Writing organisation citations (names, abbreviations) automatically.
- Other export formats (BibTeX, RIS, Word) or saving exports on the
  server.
- User accounts, deployment or hosting.
- Any AI model, backend server or API key.

## 7. Decisions

Agreed on 2026-10-15. They apply to refs mode (`agent.py`), `chat.py` and
the Streamlit chat (`refchat.py`), which all share the code in `agent.py`.
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
  (in `drafts/references_apa.md`, the Streamlit chat and `chat.py`).
- A title corrected by hand is used exactly as typed and never flagged.
- Chicago and Harvard keep the title as Crossref gives it.

### 7.3 Field lists (`config/fields.json`)

Agreed on 2026-10-16. Tested in `tests/test_refchat.py` (criteria 36–45).

- The file is one JSON object. Each key is a field name, as shown in the
  dropdown. Each value is a non-empty list of journals.
- Each journal is `{"name": "...", "issn": ["....-....", ...]}`: a non-empty
  name and a non-empty list of ISSNs, each written `NNNN-NNNC` (C is a digit
  or `X`). A journal lists both its print and its online ISSN when Crossref
  has both, because Crossref may index an article under either.
- Anything else (not an object, an empty field, a journal without a name or
  ISSNs, a badly written ISSN) makes the whole file unusable: the chat falls
  back to "All fields" with the warning of section 3, and the reason names
  the problem. There is no partial use of a broken file.
- ISSNs are copied from Crossref's journal records
  (`api.crossref.org/journals?query=...`, checked again with
  `api.crossref.org/journals/ISSN`), never typed from memory.
- Example:

  ```json
  {"Marketing": [{"name": "Journal of Marketing Research", "issn": ["0022-2437", "1547-7193"]}]}
  ```
