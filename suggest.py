"""Live suggestions for the Streamlit reference chat: Crossref titles while the student types.

This file has no Streamlit code, so it can be tested on its own. app.py draws
the Suggestions box with st.text_input(live=TYPING_PAUSE): the browser waits
for a pause in typing (the debounce) before it sends the text, and only then
is suggestions() called. This file adds the rest of the limits of
specs/goal-spec.md section 7.8:

- nothing is asked for fewer than MIN_CHARS characters, or for a DOI;
- the same text and filter are answered from a cache;
- Crossref is asked at most once every MIN_INTERVAL seconds;
- after a failed request, nothing is asked for PAUSE_AFTER_ERROR seconds.

Suggestions are not references: they have no status, and choosing one only
fills the Look up box (app.py); nothing is sent until the student presses
Look up. Every part of a label comes from Crossref's record.
"""

import time
import urllib.parse

import agent  # get_json (with mailto), find_doi, format_citation and in_journals.

TYPING_PAUSE = "500ms"  # Streamlit's live pause before the text is sent.
MIN_CHARS = 4  # Shorter text asks nothing.
MIN_INTERVAL = 1.0  # Seconds between two suggestion requests.
PAUSE_AFTER_ERROR = 30  # Seconds without requests after one failed.
CACHE_SIZE = 200  # Answers kept in memory; the oldest goes first.
ROWS = 5  # Suggestions per request.
# Only the fields a label needs, so each response stays small.
SELECT = "DOI,title,author,issued,container-title,ISSN,type"
DOI_NOTE = "A DOI: press Look up."
UNAVAILABLE_NOTE = "Suggestions unavailable right now; use the chat box below."


def new_memory():
    """A fresh cache and timings. Tests use their own; the app shares one (MEMORY)."""
    return {"cache": {}, "last_request": None, "failed_at": None}


# Shared by every session of the app. Crossref's records are public, so
# sharing the cache is safe, and it keeps the request rate down.
MEMORY = new_memory()


def label_for(item):
    """A suggestion's label: "Title (year) · Family · Journal", leaving out what Crossref lacks."""
    citation = agent.format_citation(item)
    label = citation["title"]
    if agent.stated(citation["year"]):
        label += f" ({citation['year']})"
    authors = citation["authors"]
    if isinstance(authors, list) and authors:
        label += f" · {authors[0]['family']}"
    if agent.stated(citation["journal"]):
        label += f" · {citation['journal']}"
    return label


def fill_for(item):
    """What choosing a suggestion puts in the Look up box: its DOI link, or its title."""
    citation = agent.format_citation(item)
    if agent.stated(citation["doi"]):
        return "https://doi.org/" + citation["doi"]
    return citation["title"]


def request_url(text, issns):
    """The Crossref request for one suggestion search (agent.get_json adds mailto)."""
    params = {"query.bibliographic": text, "rows": ROWS, "select": SELECT}
    if issns:
        params["filter"] = ",".join(agent.issn_filter(issns))
    return agent.CROSSREF_SEARCH_URL + urllib.parse.urlencode(params)


def remember(memory, key, answer):
    """Keep an answer in the cache, dropping the oldest when it is full."""
    memory["cache"][key] = answer
    if len(memory["cache"]) > CACHE_SIZE:
        oldest = next(iter(memory["cache"]))  # Dicts keep the order things were added.
        del memory["cache"][oldest]


def suggestions(text, issns=None, clock=time.monotonic, sleep=time.sleep, memory=MEMORY):
    """Crossref suggestions for what the student has typed so far.

    Returns (suggestions, note): suggestions is a list of {"label", "fill"}
    (at most ROWS), note is a line to show under the box, or None. issns is
    the active Field filter (None for All fields). clock and sleep are
    time.monotonic and time.sleep; tests pass a fake clock.
    """
    text = " ".join(text.split())  # Trim, and collapse runs of spaces.

    # 1. Too short, or a DOI (exact, so nothing to suggest): ask nothing.
    if len(text) < MIN_CHARS:
        return [], None
    if agent.find_doi(text):
        return [], DOI_NOTE

    # 2. Asked before with the same filter: the cached answer.
    key = (text.lower(), tuple(issns or ()))
    if key in memory["cache"]:
        return memory["cache"][key], None

    # 3. Crossref failed recently: wait before asking again.
    if memory["failed_at"] is not None and clock() - memory["failed_at"] < PAUSE_AFTER_ERROR:
        return [], UNAVAILABLE_NOTE

    # 4. At most one request per MIN_INTERVAL: wait for the rest of it, so the
    #    latest text is still the one asked about.
    if memory["last_request"] is not None:
        waited = clock() - memory["last_request"]
        if waited < MIN_INTERVAL:
            sleep(MIN_INTERVAL - waited)
    memory["last_request"] = clock()

    # 5. Ask Crossref. A failure is not cached, so the text is asked again later.
    data, error = agent.get_json(request_url(text, issns), "Crossref", not_found="Crossref found nothing.")
    if error:
        memory["failed_at"] = clock()
        return [], UNAVAILABLE_NOTE
    memory["failed_at"] = None
    items = data.get("message", {}).get("items", [])
    if issns:
        # Drop anything outside the field, even if Crossref ignored the filter.
        items = [item for item in items if agent.in_journals(item, issns)]
    answer = [{"label": label_for(item), "fill": fill_for(item)} for item in items[:ROWS]]
    remember(memory, key, answer)
    return answer, None
