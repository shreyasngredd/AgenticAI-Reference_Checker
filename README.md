# Reference Checker (beta)

A browser chatbot that turns a DOI, DOI link, paper title, or author and year
into a correctly formatted reference and in-text citation. It defaults to
APA 7th edition, with Chicago and Harvard available.

**Live app:** https://reference-checker-beta.onrender.com/

## Why this exists

General-purpose LLMs, and sometimes Google Scholar, can misplace author names,
confuse years, or invent volume, issue, article, or chapter numbers. Reference
managers are slow for a quick check. Reference Checker looks each item up in
Crossref and formats the result in code, so it cannot make up details.

## How it works

- **No AI at runtime and no API keys.** Metadata comes from the free
  [Crossref REST API](https://api.crossref.org).
- **Formatting is done by code** (APA 7 default; Chicago and Harvard on request).
- **Every result has a status, computed in code:**
  - **Verified**: a clear match.
  - **Check**: a close or ambiguous match, or unclear title casing. A
    provisional reference is shown, labelled as the closest match.
  - **Not found**: no reliable match. Nothing is invented.
- Match thresholds: 0.9 or above is a match, 0.75 to 0.9 is Check, below 0.75
  is Not found. If the runner-up is within 0.05 of the top match, the result
  is downgraded to Check.
- Each result links to Google Scholar and Google for a manual check.

## Using it

Type or paste into the single search bar:

| Input | Example |
|---|---|
| DOI | `10.1000/xyz123` |
| DOI link | `https://doi.org/10.1000/xyz123` |
| Title | `Paste the paper title here` |
| Author and year | `mithas 2021` |
| Several items | one per line |

The app shows how it interpreted your input and lets you switch the
interpretation. [Style and field tags such as `#chicago` or `#psychology`
change the settings.] Use **Add to list** on a result to collect it; the list
is searchable and exports as **.txt** or **.csv**.

Commands (optional): `find`, `add N`, `list`, `style apa|chicago|harvard`,
`edit N field value`, `cite N`, `clear`, `help`.

## Run it locally

```bash
git clone https://github.com/shreyasngredd/AgenticAI-Reference_Checker.git
cd AgenticAI-Reference_Checker
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Then open the address Streamlit prints (usually http://localhost:8501).

## Run the tests

```bash
[python -m pytest]        # or: python -m unittest discover tests
```

Tests use a fake Crossref client, so they run offline.

## Project structure

```
app.py            Streamlit interface
refchat.py        Chat logic, input detection, commands
tests/            Automated tests
specs/            Written specification (goal-spec.md)
config/           Field and journal settings
.streamlit/       Theme settings
CLAUDE.md         Instructions used with Claude Code
```

## How it was built

Built with Claude Code using a spec-first workflow: a written specification,
then a plan, then tests derived from the spec, then code. The specification
is in `specs/goal-spec.md`. [Link to the session transcript.]

## Limitations

- Depends on Crossref coverage, which is weaker for books, reports, and some
  conference papers (computer science relies heavily on conferences).
- Field filtering uses journal lists, so papers in unlisted journals can be
  missed under a field filter. Choose "All fields" to avoid this.
- Edits made in the chat last for the session only; the list resets when the
  session ends, so export it to keep it.
- Beta software: always check the Verified, Check, and Not found labels, and
  confirm references against the original source before submitting.

## Course context

Submitted for *Agentic AI Coding: From Specification to Deployment* (IISc).
