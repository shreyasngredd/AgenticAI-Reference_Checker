# Goal spec: Reference chat (browser)

## 1. Goal

A static browser chat window where the student pastes DOIs or paper titles
and gets back APA 7th references (Chicago or Harvard on request), built only
from Crossref metadata and never invented.

## 2. Constraints

- **No AI model calls.** No requests to Anthropic, OpenAI or any other model
  provider. All matching, checking and formatting is plain JavaScript.
- **No API keys and no credentials** anywhere in the client-side code: no
  keys, tokens, passwords or email addresses (this includes Crossref's
  optional `mailto` "polite pool" parameter, which would expose an email).
- **Crossref only.** The only external host the page requests is
  `https://api.crossref.org`. Google Scholar links are built as text and are
  never requested.
- **Static page.** No backend or build step: the files open directly in a
  browser (or via any static file server). The browser calls Crossref itself
  (Crossref allows cross-origin requests without a key).
- **No dependencies.** Plain HTML, CSS and JavaScript (ES modules). Tests use
  Node's built-in test runner (`node --test`, Node 18+), with no npm packages.
- **Same rules as the Python refs mode** (`agent.py`), so both give the same
  answers for the same metadata:
  - title similarity = Python `difflib.SequenceMatcher(...).ratio()`
    (Ratcliff/Obershelp) on normalised titles (lowercase, accents, HTML tags
    and punctuation removed, spaces collapsed), rounded to 2 decimals;
  - match threshold 0.9, weak band and runner-up margin as in section 7;
  - reference text matches `agent.py`'s `format_reference` for each style,
    including APA sentence case for article titles (section 7).
- **Simple and commented** code (university assignment): plain functions,
  a comment on each block, a doc comment on each function.

## 3. Inputs and outputs

### Inputs

- A chat message typed or pasted into the input box. Each non-blank line is
  one item, looked up separately and answered in order. A line is:
  - a **DOI**, if it contains `10.<4-9 digits>/<non-space characters>`
    (also accepted with `https://doi.org/` or `doi:` in front);
  - a **webpage**, if it is otherwise a URL (`http://` or `https://`);
  - otherwise a **title**.
- A **style selector** next to the input: APA 7th (default), Chicago 17th
  (bibliography) or Harvard (Cite Them Right). It applies to the next message
  sent.
- Crossref responses:
  - DOI: `GET https://api.crossref.org/works/{url-encoded DOI}`
  - Title: `GET https://api.crossref.org/works?query.bibliographic={title}&rows=20`

### Outputs

For each item, one result card in the chat, containing:

- **Label:** `OK`, `Check`, `Not found` or `Unavailable`.
- **Reason(s):** shown for every label except `OK`.
- **Reference text** in the chosen style, only when Crossref returned exactly
  one record for the item. Italics are rendered (not shown as asterisks).
- **Google Scholar link**, opening in a new tab:
  - when there is a reference:
    `https://scholar.google.com/scholar?q=` + URL-encoded
    `"<title> <first author's family name>"` (spaces encoded as `+`);
  - when there is no reference: the same URL built from the line as typed,
    so the student can search by hand.

How labels are decided (all in code):

| Situation | Label | Reason shown |
|---|---|---|
| DOI found; journal article; no missing APA 7 fields | `OK` | none |
| DOI found or single title match; type is not journal article (book, chapter, report, conference paper, preprint, anything else) | `Check` | "Crossref lists this as a <type>; check the details by hand." |
| Journal article missing a required APA 7 field (authors, year, title, journal, volume, pages) | `Check` | "Missing <fields>." |
| Title search: exactly one paper (one DOI) at ≥ 0.9 similarity, runner-up more than 0.05 below | as for a DOI | as for a DOI |
| Title search: several different DOIs at ≥ 0.9 | `Check` | "<n> Crossref records have this title. Paste the DOI." Candidates listed. No reference text. |
| Title search: runner-up within 0.05 of the best | `Check` | The two scores. Candidates listed. No reference text. |
| Title search: best title at ≥ 0.75 but < 0.9 | `Check` | "Only a weak match" with the score. Candidates listed. No reference text. |
| Title search: no title at ≥ 0.75 | `Not found` | "No Crossref record matches this title." No reference text. |
| APA article title whose casing code can't be sure of (section 7) | `Check` | The uncertain words. |
| DOI: Crossref returns 404 | `Not found` | "Crossref has no record for this DOI. Check it was copied correctly." |
| Webpage URL | `Check` | "Webpages aren't in Crossref, so this can't be looked up. Write it by hand." No reference text. |
| Network error, timeout (10 s), HTTP 429 or 5xx, or invalid JSON | `Unavailable` | "Crossref is unavailable right now. Try again in a minute." |

## 4. Acceptance criteria

Each criterion names what decides it:
- **Test:** an automated `node --test` test using recorded Crossref responses
  (no network).
- **Inspection:** reading or searching the source.
- **Manual:** a person using the page in a browser with the live API.
- **Reviewed by a human:** a person reads the output, because code cannot
  decide it (see criterion 18).

1. Pasting `10.1038/nature14539` with APA selected gives `OK` and exactly:
   `LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. *Nature*, *521*(7553), 436–444. https://doi.org/10.1038/nature14539`
   (italics rendered). **Decided by:** test.
2. For every recorded fixture and each of the three styles, the reference text
   equals `agent.py`'s `format_reference` output for the same record (expected
   strings are generated once from `agent.py` and stored as fixtures).
   **Decided by:** test.
3. APA 7th is used when the style selector hasn't been changed; Chicago or
   Harvard is used only after it is set to that style. **Decided by:** test
   (default value of the style setting) + manual.
4. A DOI that Crossref answers with 404 (e.g. `10.9999/definitely-not-real-xyz`)
   gives `Not found` with its reason, and no reference text. **Decided by:** test.
5. A title with no Crossref title at ≥ 0.75 similarity gives `Not found`, and
   no reference text is shown even though Crossref returned results.
   **Decided by:** test.
6. A title matched by several different DOIs at ≥ 0.9 (fixture: "Attention is
   all you need") gives `Check` with the count in the reason, and no reference
   text. **Decided by:** test.
7. A title matched by exactly one DOI at ≥ 0.9 (fixture: "Reducing the
   dimensionality of data with neural networks") gives that paper's reference.
   **Decided by:** test.
8. A record whose Crossref type is not `journal-article` (fixtures: a book, a
   book chapter, a report, a conference paper and a preprint, i.e.
   `posted-content`) gives `Check` with the type in the reason, plus its
   reference text. **Decided by:** test.
9. A journal article missing a required APA 7 field gives `Check` naming the
   missing fields, and the missing parts are left out of the text, never
   filled in. **Decided by:** test.
10. A webpage URL gives `Check` with its reason and no reference text, and
    makes no request to the URL itself. **Decided by:** test (fetch mock
    records no call).
11. Title similarity matches Python's `difflib` ratio (rounded to 2 decimals)
    for every pair in the similarity fixture (pairs and Python scores stored
    in the fixture). **Decided by:** test.
12. Every result has a Google Scholar link in the format of section 3, opening
    in a new tab (`target="_blank"` with `rel="noopener noreferrer"`).
    **Decided by:** test (URL string) + inspection (link attributes).
13. Google Scholar is never requested: across all tests, the fetch mock records
    no call to any host other than `api.crossref.org`. **Decided by:** test.
14. When the request fails (network error, timeout after 10 s, HTTP 429, HTTP
    500, invalid JSON) the item shows `Unavailable` with its reason, the page
    keeps working, and the next message is answered normally.
    **Decided by:** test (each failure mocked) + manual (go offline and send).
15. A message with several lines gives one result per non-blank line, in the
    same order. **Decided by:** test.
16. The source contains no API keys, tokens, email addresses or `mailto`, and
    no URL of a model provider. **Decided by:** inspection (a `grep` for
    `key`, `token`, `@`, `mailto`, `anthropic`, `openai`, `api.` hosts other
    than `api.crossref.org`).
17. Opening `web/index.html` (via a static server) shows the chat, and pasting
    the DOI from criterion 1 shows the same result live. **Decided by:** manual.
18. Proper nouns in APA titles: when the source title is in Title Case, code
    cannot tell a proper noun (e.g. "Facebook", "Australia") from an ordinary
    word, so it lowercases it without a flag (decision 7.2). A person compares
    every formatted APA title with the original title shown next to it, and
    fixes any proper noun, before a reference list is moved out of `drafts/`.
    **Decided by:** reviewed by a human.

## 5. Output files

| File | Purpose |
|---|---|
| `web/index.html` | The chat page: message list, input box, style selector, send button. |
| `web/style.css` | Layout and label colours (OK green, Check amber, Not found red, Unavailable grey). |
| `web/refchat.js` | Pure logic, no DOM: parse lines, call Crossref (through an injectable `fetch`), title similarity, labels and reasons, formatting in three styles, Scholar links. |
| `web/ui.js` | DOM code: reads the input, calls `refchat.js`, renders result cards. |
| `web/tests/refchat.test.js` | `node --test` tests for criteria 1–15, with mocked `fetch`. |
| `web/tests/fixtures/` | Recorded Crossref responses, expected reference strings generated from `agent.py`, and title-similarity pairs with Python's scores. |
| `web/tests/make_fixtures.py` | Script that records the fixtures and expected strings, using `agent.py`. Run once by hand; the tests themselves never use the network. |
| `web/README.md` | How to open the page and run the tests. |

## 6. Out of scope

- User accounts or sign-in.
- Saving chat history (nothing is stored between page loads, including
  `localStorage`).
- Deployment or hosting.
- Any AI model, backend server or API key.
- Sources other than Crossref (OpenAlex, Semantic Scholar, Google Scholar
  scraping).
- Formatting webpages, or editing a reference inside the chat.
- Changes to `agent.py`, `chat.py`, `app.py` or `refs/` (they are only used
  as the reference behaviour for the fixtures). The decisions in section 7
  were made in `agent.py` first; the fixtures must be generated after them.

## 7. Decisions

Agreed on 2026-10-15. They apply to refs mode (`agent.py`) and `chat.py`,
which share the code, and the browser chat must follow them too (section 2).
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
  capitals. Other proper nouns are not flagged (criterion 18).
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
  (in `drafts/references_apa.md`, the Streamlit app and `chat.py`).
- A title corrected by hand is used exactly as typed and never flagged.
- Chicago and Harvard keep the title as Crossref gives it.
