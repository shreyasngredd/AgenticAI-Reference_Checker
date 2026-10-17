"""Searching My list and the `list FILTER` command: which entries match a search.

This file has no Streamlit code and makes no request. The rules are in
specs/goal-spec.md, section 3 ("Searching My list"):

- an entry's searched pieces are its authors, title, journal, year, DOI and
  reference text, each kept separate so a phrase never runs across two;
- matching ignores case and accents but keeps punctuation (so DOIs match);
- a "quoted phrase" is one term, every other word is a term, and an entry
  matches only when every term is found in one of its pieces (AND).
"""

import re
import unicodedata

import agent  # Formatting and the DOI clean-up: one copy of the rules.

# A "quoted phrase", or a run of non-space characters.
TERM_PATTERN = re.compile(r'"([^"]*)"|(\S+)')


def fold(text):
    """Lowercase, accents removed, spaces collapsed: "Jörg  MÜLLER" -> "jorg muller".

    Punctuation is kept, so "10.1234/abc" still matches a DOI.
    """
    # NFKD splits "ü" into "u" + an accent mark; then drop the accent marks.
    decomposed = unicodedata.normalize("NFKD", str(text))
    text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(text.lower().split())


def terms(query):
    """The terms of a search: each quoted phrase, then each other word, folded.

    A quote with no partner is ignored, and empty terms are dropped:
    'mithas "2021' -> ["mithas", "2021"].
    """
    found = []
    for phrase, word in TERM_PATTERN.findall(query):
        term = fold(phrase if phrase else word.replace('"', ""))
        if term:
            found.append(term)
    return found


def pieces(entry, style):
    """The folded pieces of text a search looks in, for one entry."""
    texts = []
    # Authors: "Given Family" for each person, so either name matches.
    authors = entry.get("authors")
    if isinstance(authors, list):
        texts += [f"{person.get('given', '')} {person.get('family', '')}" for person in authors]
    # Title (and Crossref's own title, if the casing was changed), journal and year.
    for field in ("title", "original_title", "journal", "year"):
        if agent.stated(entry.get(field)):
            texts.append(str(entry[field]))
    # The DOI on its own and as a link, so both forms match.
    if agent.stated(entry.get("doi")):
        doi = agent.clean_doi(entry["doi"])
        texts += [doi, "https://doi.org/" + doi]
    # The reference as shown, without the Markdown italics markers.
    texts.append(agent.shown_text(entry, style).replace("*", ""))
    return [fold(text) for text in texts]


def matches(entry, style, query):
    """True if every term of `query` is in one of the entry's pieces (blank matches all)."""
    looked_in = pieces(entry, style)
    return all(any(term in piece for piece in looked_in) for term in terms(query))
