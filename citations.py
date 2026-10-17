"""In-text citations in APA 7, Harvard and Chicago author-date.

This file has no Streamlit code. It builds the parenthetical and narrative
citations from a reference's authors, year and title, in the chosen style:

    authors        APA 7                     Harvard                       Chicago author-date
    one            (Davis, 1989)             (Davis, 1989)                 (Davis 1989)
    two            (Davis & Bagozzi, 1989)   (Davis and Bagozzi, 1989)     (Davis and Bagozzi 1989)
    three          (Yoo et al., 2010)        (Yoo, Henfridsson and         (Yoo, Henfridsson, and
                                              Lyytinen, 2010)               Lyytinen 2010)
    four or more   (Yoo et al., 2010)        (Yoo et al., 2010)            (Yoo et al. 2010)

Every name, year and title comes from the entry (Crossref's record after the
student's edits); code only puts them in order and punctuates them. Where a
rule needs a judgement code can't make (a shortened title, a missing year,
an author who may be an organisation), the citation is marked Check with a
reason instead. The rules and their sources are in specs/goal-spec.md,
section 7.7.
"""

import agent  # stated() and value(): one copy of "is this field filled in?".

# The style names shown with citations ("In-text (APA 7)", `cite N`, the .txt).
STYLE_NAMES = {"apa": "APA 7", "harvard": "Harvard", "chicago": "Chicago author-date"}
# How each style writes a missing year (7.7).
NO_DATE = {"apa": "n.d.", "harvard": "no date", "chicago": "n.d."}
# From how many authors each style uses "et al." (7.7; Harvard and Chicago to be confirmed).
ET_AL_FROM = {"apa": 3, "harvard": 4, "chicago": 4}
# Works whose title is in italics when it stands in for the author; others are quoted.
ITALIC_TYPES = ("book", "report")

SHORTENED_REASON = "shortened title chosen by code: check it"
NO_YEAR_REASON = "Crossref gives no year: check the source really has no date"
MIXED_REASON = "organisation and person authors: write this citation by hand"


def author_part(names, style, parenthetical):
    """The author part of a citation, e.g. "Davis & Bagozzi" or "Yoo, Henfridsson and Lyytinen"."""
    if len(names) >= ET_AL_FROM[style]:
        return f"{names[0]} et al."
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        # Only APA uses "&", and only inside the brackets.
        joiner = "&" if style == "apa" and parenthetical else "and"
        return f"{names[0]} {joiner} {names[1]}"
    # Three names (Harvard and Chicago): Chicago puts a comma before "and".
    comma = "," if style == "chicago" else ""
    return f"{names[0]}, {names[1]}{comma} and {names[2]}"


def short_title(title):
    """The main title: the title up to the first ":", "?" or "!" (a "?" or "!" is kept)."""
    for position, char in enumerate(title):
        if char == ":":
            return title[:position].strip()
        if char in "?!":
            return title[:position + 1].strip()
    return title.strip()


def title_citation(entry, year, style):
    """Citations for a work with no author: its shortened title takes the author's place."""
    title = short_title(agent.value(entry, "title"))
    if entry.get("type") in ITALIC_TYPES:
        shown = f"*{title}*"
        parenthetical = f"({shown}, {year})" if style != "chicago" else f"({shown} {year})"
    else:
        shown = f'"{title}"'
        # APA puts the comma inside the quotes; Chicago has no comma at all.
        parenthetical = {"apa": f'("{title}," {year})', "harvard": f'("{title}", {year})',
                         "chicago": f'("{title}" {year})'}[style]
    return parenthetical, f"{shown} ({year})"


def in_text(entry, style="apa"):
    """The in-text citations for one entry in one style.

    Returns {"parenthetical": text or None, "narrative": text or None,
    "reasons": [why it needs checking]}. When no citation can be built
    safely, both texts are None and the reasons say why.
    """
    reasons = []
    people = agent.value(entry, "authors")
    people = people if isinstance(people, list) else []
    organisations = entry.get("organisation_authors") or []
    year = agent.value(entry, "year")

    # 1. No year: the style's no-date form, but a person checks it.
    if year is None:
        year = NO_DATE[style]
        reasons.append(NO_YEAR_REASON)

    # 2. Who takes the author's place.
    if people and organisations:
        # Crossref's order between people and organisations is not kept, so
        # the first author can't be known: don't guess.
        return {"parenthetical": None, "narrative": None, "reasons": [MIXED_REASON]}
    if organisations:
        # Only organisations: their names, as Crossref gives them.
        names = list(organisations)
    elif people:
        names = [person["family"] for person in people]
        # `edit` stores an organisation as an author with no given name, but
        # it may be a person whose given name is missing.
        for person in people:
            if not person.get("given", "").strip():
                reasons.append(f"author \"{person['family']}\" has no given name: if it is an "
                               "organisation this is right; if it is a person, add the given name")
    elif agent.value(entry, "title"):
        # 3. No author: the shortened title instead.
        parenthetical, narrative = title_citation(entry, year, style)
        return {"parenthetical": parenthetical, "narrative": narrative,
                "reasons": [SHORTENED_REASON] + reasons}
    else:
        return {"parenthetical": None, "narrative": None,
                "reasons": ["authors not stated and no title, so no citation was built"]}

    # 4. Build both forms. Chicago has no comma between author and year.
    separator = " " if style == "chicago" else ", "
    return {
        "parenthetical": f"({author_part(names, style, True)}{separator}{year})",
        "narrative": f"{author_part(names, style, False)} ({year})",
        "reasons": reasons,
    }


def in_text_all(numbered_entries, style="apa", label="reference"):
    """In-text citations for every reference (or My list item), by number.

    numbered_entries is a list of (number, entry). Returns {number: citation}
    as in in_text(), and marks two that would get the same parenthetical
    citation as Check: every style then adds a letter to the year (1989a,
    1989b), and the order is the student's to decide. label names them in
    the reason ("reference 2" or "item 2").
    """
    citations = {number: in_text(entry, style) for number, entry in numbered_entries}
    for number, citation in citations.items():
        if citation["parenthetical"] is None:
            continue
        for other, other_citation in citations.items():
            if other != number and other_citation["parenthetical"] == citation["parenthetical"]:
                citation["reasons"].append(
                    f"{label} {other} has the same citation {citation['parenthetical']}: "
                    "a letter is added to the year (e.g. 1989a, 1989b), check by hand")
    return citations
