"""APA 7 in-text citations for the Streamlit reference chat.

This file has no Streamlit code. It builds the parenthetical and narrative
citations from a reference's authors and year, or says why it can't:

    one author      (Davis, 1989)              Davis (1989)
    two authors     (Davis & Bagozzi, 1989)    Davis and Bagozzi (1989)
    three or more   (Yoo et al., 2010)         Yoo et al. (2010)

Missing authors or year, and organisation authors, are marked Check with a
reason instead of being guessed. The rules are in specs/goal-spec.md,
section 3 ("In-text citations").
"""

import agent  # stated() and value(): one copy of "is this field filled in?".


def author_part(families, joiner):
    """The author part of a citation; joiner is "&" or "and" for two authors."""
    if len(families) == 1:
        return families[0]
    if len(families) == 2:
        return f"{families[0]} {joiner} {families[1]}"
    return f"{families[0]} et al."


def in_text(entry):
    """The APA 7 in-text citations for one entry.

    Returns {"parenthetical": text or None, "narrative": text or None,
    "reasons": [why it needs checking]}. When a reason means no citation can
    be built safely, both texts are None.
    """
    reasons = []
    authors = agent.value(entry, "authors")
    year = agent.value(entry, "year")

    # 1. Missing authors or year: nothing to build from, so don't guess.
    if not isinstance(authors, list):
        reasons.append("authors not stated, so no citation was built")
    if year is None:
        reasons.append("year not stated, so no citation was built")

    # 2. Organisations: Crossref lists them by name, and `edit` stores them
    # as an author with no given name. APA cites groups by name and sometimes
    # abbreviates them, which a person has to decide.
    for name in entry.get("organisation_authors") or []:
        reasons.append(f"author is an organisation ({name}): write this citation by hand")
    for author in authors if isinstance(authors, list) else []:
        if not author.get("given", "").strip():
            reasons.append(f"author \"{author['family']}\" has no given name, so it may be "
                           "an organisation: write this citation by hand")

    if reasons:
        return {"parenthetical": None, "narrative": None, "reasons": reasons}

    # 3. Build both forms from the family names, accents and all.
    families = [author["family"] for author in authors]
    return {
        "parenthetical": f"({author_part(families, '&')}, {year})",
        "narrative": f"{author_part(families, 'and')} ({year})",
        "reasons": [],
    }


def in_text_all(numbered_entries):
    """In-text citations for every reference in the chat, by number.

    numbered_entries is a list of (number, entry). Returns {number: citation}
    as in in_text(), and marks two references that would get the same
    parenthetical citation as Check: APA then adds a letter to the year
    (1989a, 1989b), and the order is the student's to decide.
    """
    citations = {number: in_text(entry) for number, entry in numbered_entries}
    for number, citation in citations.items():
        if citation["parenthetical"] is None:
            continue
        for other, other_citation in citations.items():
            if other != number and other_citation["parenthetical"] == citation["parenthetical"]:
                citation["reasons"].append(
                    f"reference {other} has the same citation {citation['parenthetical']}: "
                    "APA adds a letter to the year (e.g. 1989a, 1989b), check by hand")
    return citations
