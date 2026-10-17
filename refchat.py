"""Chat logic for the Streamlit reference chat (app.py).

This file has no Streamlit code, so it can be tested on its own. It reads a
chat message, decides whether it is a command or a lookup (parse_command),
and builds the reply (handle_message). Everything else comes from agent.py:
the Crossref lookup, title search and author-and-year search, the formatting,
the status and the search links. The rules are in specs/goal-spec.md.

The chat only contacts Crossref (no OpenAlex or Semantic Scholar), and it
keeps everything in a plain dict ("state") that app.py stores in
st.session_state. Nothing is written to disk.

The Field setting (fields.py) limits `find` and title lookups to one field's
journals; My list (mylist.py) is drawn from the same state. Every card has an
in-text citation (citations.py), and an unsure title search shows a
provisional reference built from its closest candidate, clearly labelled.

The one input bar (decision 7.9): a message may carry #tags that change the
style or field (split_tags), and a single line of the form SURNAME YEAR
[topic] is read as `find` (interpret). Each lookup or search reply keeps how
its lines were read ("read_as"), so app.py can show it with a button to
search the other way (switch_for).
"""

import re

import agent  # Lookup, formatting, status and links: one copy of the rules.
import citations  # APA 7 in-text citations for `cite` and the export.
import fields  # The Field setting's journal lists (config/fields.json).
import listsearch  # Matching for `list FILTER`, shared with the My list search.

# How each status from agent.verify is shown, plus "unavailable" for when
# Crossref could not be reached.
STATUS_NAMES = {
    "verified": "Verified",
    "check": "Check",
    "not_found": "Not found",
    "unavailable": "Unavailable",
}
VERIFIED_NOTE = "Verified against Crossref only"
UNAVAILABLE_REASON = "Crossref is unavailable right now. Try again in a minute."
SESSION_NOTE = "Edits and confirmations are kept for this session only and are lost when you reload the page."
DOI_FIELD_NOTE = "Field filter not used: a DOI lookup is exact."
# A provisional reference (section 3, "Provisional results"): an orange badge
# with a warning icon, so it can't be mistaken for a Verified one.
PROVISIONAL_LABEL = "Provisional: closest match, not verified"
PROVISIONAL_BADGE = f":orange-badge[:material/warning: {PROVISIONAL_LABEL}]"
PROVISIONAL_REASON = "provisional: built from the closest candidate, not verified"
NO_MATCH = "No match found"
QUOTE_HELP = "To search a title that starts with a command word, put it in double quotes."
QUOTES = ('"', "“", "”")  # Straight and curly double quotes.

# The style chip's choices, in the order shown. The `style` command's
# reply still uses agent.STYLES, as refs mode does.
STYLE_LABELS = {"apa": "APA 7", "harvard": "Harvard", "chicago": "Chicago"}

# One line per command, each with an example. Used by "help", the sidebar
# in app.py (through help_text) and the short help message, so they match.
COMMAND_HELP = [
    "- Paste DOIs, DOI links or titles, one per line, to look them up, "
    "e.g. `10.1038/nature14539`, `https://doi.org/10.1038/nature14539` or `Deep learning`. "
    "A DOI or DOI link is looked up exactly; anything else is searched as a title. "
    + QUOTE_HELP,
    "- `find SURNAME YEAR [topic words]`: search Crossref by author and publication year, "
    "e.g. `find LeCun 2015 deep learning`. Shows up to 5 results as an APA 7 preview; "
    "they are never Verified.",
    "- `add N`: add result N of the latest `find` to your references, e.g. `add 2`.",
    "- `accept N`: confirm a Check reference once you have checked it yourself, "
    "so it goes in the export, e.g. `accept 3`.",
    "- `cite N`: show the in-text citations (parenthetical and narrative) "
    "for reference N in the current style, e.g. `cite 1`.",
    "- `list`: show all references so far, numbered, and which are in the export, e.g. `list`.",
    "- `list FILTER`: show only the references matching FILTER (authors, title, journal, year, "
    "DOI or reference text; every word must match, \"quoted phrases\" exactly, case and "
    "accents ignored), e.g. `list mithas 2021`.",
    "- `style apa`, `style chicago` or `style harvard`: change the style "
    "(APA 7 by default), e.g. `style harvard`.",
    "- `edit N field value`: change a field of reference N, e.g. `edit 2 year 2015`.",
    "- `clear`: start again, e.g. `clear`.",
    "- `help`: show this list, e.g. `help`.",
]

# What each status means, for "help" and the sidebar.
STATUS_HELP = [
    f"- **Verified** ({VERIFIED_NOTE}): DOI resolved in Crossref, or title match above "
    "threshold with a clear lead over the runner-up, and nothing else to check.",
    "- **Check**: found, but something needs a human look (a missing field, unclear "
    "title casing, a close or weak title match, or a `find` result). The reasons are shown.",
    "- **Confirmed**: a Check reference you accepted with `accept N`. It stays Check, "
    "but goes in the export.",
    "- **Not found**: Crossref has no record for the DOI, or no title came close enough.",
    f"- **{PROVISIONAL_LABEL}** (orange badge): a Check or Not found title search shows the "
    "closest Crossref candidate as a quoted reference, with its match score. It keeps its "
    "status and is never Verified; check it is the right paper. With no candidate at all, "
    f"only \"{NO_MATCH}\" and the search links are shown.",
    "- **Unavailable**: Crossref could not be reached (network error, timeout or "
    "server error). Try again in a minute; nothing is added.",
]
# What goes in the export, for "help".
EXPORT_HELP = (
    "The page's download is My list. The references export (`references.txt` and "
    "`references.csv`) is no longer offered on the page. It holds Verified references plus "
    "Check references you confirmed with `accept N`, sorted by first author and year, "
    "in the current style. Not found references are never included. A confirmed "
    "provisional reference is marked `[CHECK] (provisional)`."
)
# The in-text citations, for "help".
CITATION_HELP = (
    "Every card shows its in-text citation in the current style (APA 7, Harvard or "
    "Chicago author-date), parenthetical and narrative; the card's **Copy** button has a "
    "copy icon for each, and for the reference. "
    "A citation that needs checking (no year, no author, a provisional reference) says why. "
    "`find` results are an APA 7 preview, so their citations are APA 7."
)
# The one input bar (7.9), for "help" and the short help in the sidebar.
INPUT_HELP = (
    "Type in the one bar at the top. A DOI or DOI link is looked up exactly; one line like "
    "`LeCun 2015` or `LeCun 2015 deep learning` (a surname, a year 1900-2099, at most 4 words) "
    "searches by author and year, like `find`; anything else is searched as a title. Several "
    "lines are looked up one by one (DOI or title). Each reply says how it was read, with a "
    "button to search the other way if the guess was wrong."
)
# The #tags (7.9), for "help" and the short help.
TAG_HELP = (
    "Add `#apa`, `#harvard` or `#chicago` to change the style, and a field tag such as "
    "`#psychology`, `#is` or `#management` (the field's name with hyphens, or its initials) "
    "to change the field; `#all` searches all fields. Tags are taken out of the search, and "
    "a message of tags alone only changes the settings. The chips under the bar show both."
)
# The buttons in app.py, for "help". Each one just sends a command, so the
# chat shows what it did and the commands still work.
BUTTON_HELP = [
    "- Each card has **Add to list** (My list, in the sidebar) and **Copy**.",
    "- **Add to export** is no longer a button: type `accept N` to confirm a Check reference "
    "for the export.",
    "- The **Style** dropdown is now the style chip under the bar; it sends `style apa`, "
    "`style chicago` or `style harvard`.",
    "- Verified references are already in the export; Not found ones can never be.",
]
# The Field setting, for "help".
FIELD_HELP = (
    "The **Field** chip under the bar (or a field tag) limits `find` and title lookups to "
    "that field's journals (listed in `config/fields.json`); replies then say "
    "\"Searched in: <field>\". DOI lookups ignore the field, because a DOI is exact. "
    "The default is All fields."
)
# My list, for "help" and the sidebar.
MY_LIST_HELP = (
    "**Add to list** beside a reference, a `find` result or a title-search candidate puts it "
    "in My list (sidebar), with the status it has now: Check stays Check. The same paper "
    "(same DOI, or same title without one) is only added once (\"Already in list\"). "
    "Each item has a **Remove** button, and **Clear list** empties it. My list downloads as "
    "`my_list.txt` (one reference per line) or `my_list.csv`, in the current style. It is "
    "separate from the export below, and `add N` still adds a `find` result to your references. "
    "**Search my list** only changes what is shown; the downloads always hold the full list."
)
BLOCK_SEPARATOR = "\n\n---\n\n"  # Between the blocks of a reply, one per reference or result.
COMMAND_WORDS = ("style", "list", "edit", "find", "add", "accept", "cite", "clear", "help")
NUMBER_COMMANDS = ("add", "accept", "cite")  # Commands that take one number, N.

# The one input bar (decision 7.9).
YEAR_MIN, YEAR_MAX = 1900, 2099  # A year in this range can start an author-and-year search.
AUTHOR_YEAR_MAX_WORDS = 4  # SURNAME YEAR [topic]: at most 4 words in all.
STYLE_TAGS = {"#apa": "apa", "#harvard": "harvard", "#chicago": "chicago"}
ALL_FIELDS_TAG = "#all"
# A tag: "#" and a letter, then letters, digits, "_" or "-", at the start of
# the text or after a space (so the "#" of "C#" is not one).
TAG_PATTERN = re.compile(r"(?<!\S)#[^\W\d_][\w-]*")
SWITCH_TO_TITLE = "Search as title instead"
SWITCH_TO_AUTHOR_YEAR = "Search as author and year instead"


def new_state():
    """A fresh chat: APA 7, all fields, no references, search results, list or history."""
    return {"style": "apa", "refs": [], "last_search": [], "history": [], "search_count": 0,
            "field": fields.ALL_FIELDS, "my_list": []}


def set_field(state, field):
    """Choose the field searched by `find` and title lookups (the Field dropdown)."""
    state["field"] = field


def active_field(state):
    """The chosen field and its ISSNs, or (None, None) to search everything.

    A field no longer in config/fields.json, or a broken file, means All fields.
    """
    issns = fields.field_issns(state["field"])
    if not issns:
        return None, None
    return state["field"], issns


def not_found_in(field):
    """The reply or reason when nothing was found in a field."""
    return f"Not found in {field}; try {fields.ALL_FIELDS}."


def parse_find(words):
    """Read the words after `find`: SURNAME YEAR [topic words].

    The year is the first word of exactly four digits. The words before it
    are the surname (so "van der Berg" works) and the words after it are the
    topic. Returns ("find", surname, year, topic), or ("unknown",) if there is
    no surname or no four-digit year.
    """
    for position, word in enumerate(words):
        if len(word) == 4 and word.isdigit():
            surname = " ".join(words[:position])
            topic = " ".join(words[position + 1:])
            # The surname must have at least one letter (not "find 15 2019").
            if any(char.isalpha() for char in surname):
                return ("find", surname, int(word), topic)
            return ("unknown",)
    return ("unknown",)  # No four-digit year.


def parse_command(text):
    """Work out what a message asks for. Doesn't look anything up.

    Returns one of:
        ("help",), ("list",), ("list", filter), ("clear",), ("style", style),
        ("edit", number, field, value), ("find", surname, year, topic),
        ("add", number), ("accept", number), ("cite", number), ("lookup", [lines]),
        ("unknown",)  -> answered with the short help message.
    A command must be the whole message. If the first word is a command but
    the rest doesn't fit, or the message is one word that is neither a
    command nor a DOI, the result is ("unknown",). One line of the form
    SURNAME YEAR [topic] (author_year_parts) is read as `find`.
    """
    text = text.strip()
    words = text.split()
    if not words:
        return ("unknown",)
    command = words[0].lower()

    # 0. A message starting with a double quote is a lookup, never a command,
    #    so a title like "List decoding of codes" can be searched.
    if text.startswith(QUOTES):
        return ("lookup", lookup_lines(text))

    # 1. Commands: the first word decides, and the rest must fit exactly.
    if command in COMMAND_WORDS:
        if "\n" in text:
            return ("unknown",)  # A command is one line.
        if command == "list" and len(words) > 1:
            # list FILTER: the filter is the rest of the message, quotes included.
            return ("list", text.split(maxsplit=1)[1])
        if command in ("help", "list", "clear"):
            return (command,) if len(words) == 1 else ("unknown",)
        if command == "style":
            if len(words) == 2 and words[1].lower() in agent.STYLES:
                return ("style", words[1].lower())
            return ("unknown",)
        if command == "find":
            return parse_find(words[1:])
        if command in NUMBER_COMMANDS:
            if len(words) == 2 and words[1].isdigit():
                return (command, int(words[1]))
            return ("unknown",)
        # edit N field value: the value is the rest of the message, spaces included.
        parts = text.split(maxsplit=3)
        if len(parts) == 4 and parts[1].isdigit():
            return ("edit", int(parts[1]), parts[2], parts[3])
        return ("unknown",)

    # 2. One word that isn't a DOI: not a title worth searching for.
    if len(words) == 1 and not agent.find_doi(text):
        return ("unknown",)

    # 3. One line that reads as SURNAME YEAR [topic] (7.9): exactly `find`.
    if "\n" not in text and interpret(text) == "author_year":
        return ("find",) + author_year_parts(text)

    # 4. Anything else: each non-blank line is a DOI or a title.
    return ("lookup", lookup_lines(text))


def unquote_line(line):
    """A line without the double quotes around it, if it has them on both ends."""
    if len(line) > 1 and line[0] in QUOTES and line[-1] in QUOTES:
        return line[1:-1].strip()
    return line


def lookup_lines(text):
    """The non-blank lines of a lookup message, trimmed and without surrounding quotes."""
    lines = [unquote_line(line.strip()) for line in text.splitlines()]
    return [line for line in lines if line]


def input_kind(line):
    """Auto-detection: "doi" for a DOI or DOI link (anywhere in the line), else "title"."""
    return "doi" if agent.find_doi(line) else "title"


def author_year_parts(line):
    """(surname, year, topic) if one line reads as an author-and-year search, else None.

    Decision 7.9, rule 6: at most 4 words, one of them a year 1900-2099, with
    a word containing a letter before it (the surname, as for `find`).
    """
    words = line.split()
    if len(words) > AUTHOR_YEAR_MAX_WORDS:
        return None
    found = parse_find(words)
    if found[0] != "find" or not YEAR_MIN <= found[2] <= YEAR_MAX:
        return None
    return found[1:]


def interpret(line):
    """How one line typed on its own is read: "doi", "author_year" or "title".

    A quoted line is always a title; a DOI or DOI link is a DOI; a line that
    fits author_year_parts is an author-and-year search; anything else is a
    title. (Commands, tags and several lines are handled by handle_message.)
    """
    line = line.strip()
    if line.startswith(QUOTES):
        return "title"
    if agent.find_doi(line):
        return "doi"
    if author_year_parts(line):
        return "author_year"
    return "title"


def field_tags():
    """The field tags, {"#tag": field name}, derived from config/fields.json's names.

    Each field gets its name in lower case with hyphens and without spaces,
    and, for two or more words, its initials. A tag two fields (or a style)
    would share goes to neither. "#all" always means All fields.
    """
    owners = {}  # {tag: set of field names that would get it}
    for name in fields.field_options()[0][1:]:  # [0] is "All fields".
        words = name.lower().split()
        tags = {"#" + "-".join(words), "#" + "".join(words)}
        if len(words) > 1:
            tags.add("#" + "".join(word[0] for word in words))
        for tag in tags:
            owners.setdefault(tag, set()).add(name)
    found = {}
    for tag, names in owners.items():
        if len(names) == 1 and tag not in STYLE_TAGS and tag != ALL_FIELDS_TAG:
            found[tag] = names.pop()
    found[ALL_FIELDS_TAG] = fields.ALL_FIELDS
    return found


def split_tags(text):
    """Take the known #tags out of a message.

    Returns {"text": the message without them, "style": the last style tag's
    style or None, "field": the last field tag's field or None, "unknown":
    other #words, lower case, which stay in the text}. Without a known tag
    the text is returned exactly as typed. Tags are matched ignoring case.
    """
    known_fields = field_tags()
    found = {"style": None, "field": None, "unknown": []}

    def take(match):
        """Remove one known tag (remembering it), or keep an unknown one."""
        tag = match.group(0).lower()
        if tag in STYLE_TAGS:
            found["style"] = STYLE_TAGS[tag]
            return ""
        if tag in known_fields:
            found["field"] = known_fields[tag]
            return ""
        if tag not in found["unknown"]:
            found["unknown"].append(tag)
        return match.group(0)

    cleaned = TAG_PATTERN.sub(take, text)
    if found["style"] or found["field"]:
        # Tidy the spaces the removed tags leave behind, line by line.
        cleaned = "\n".join(" ".join(line.split()) for line in cleaned.split("\n"))
    found["text"] = cleaned
    return found


def chip_labels(state):
    """The labels of the two chips under the bar: (style, field), e.g. ("APA 7", "All fields")."""
    field = state.get("field", fields.ALL_FIELDS)
    # A field no longer in the file is searched, and shown, as All fields.
    if field not in fields.field_options()[0]:
        field = fields.ALL_FIELDS
    return STYLE_LABELS[state["style"]], field


def find_read_as(surname, year, topic):
    """How a `find` (typed, or read from SURNAME YEAR) was read, for read_as."""
    line = " ".join(part for part in (surname, str(year), topic) if part)
    return {"kind": "author_year", "line": line, "surname": surname, "year": year, "topic": topic}


def read_as_line(read):
    """The line drawn above a block: how its input was read."""
    if read["kind"] == "doi":
        return "Searched as: DOI"
    if read["kind"] == "title":
        return "Searched as: title"
    details = f"{read['surname']}, {read['year']}"
    if read["topic"]:
        details += f", topic: {read['topic']}"
    return f"Searched as: author and year ({details})"


def switch_for(read):
    """The "search the other way" button, as (label, message to send), or None.

    Author and year -> the line in double quotes (always a title). A title
    that `find` can read -> `find <line>`. A DOI is exact: no button.
    """
    if read["kind"] == "author_year":
        return (SWITCH_TO_TITLE, f'"{read["line"]}"')
    if read["kind"] == "title" and parse_find(read["line"].split())[0] == "find":
        return (SWITCH_TO_AUTHOR_YEAR, "find " + read["line"])
    return None


def press_switch(state, read):
    """The switch button was pressed: send its message, exactly as if typed."""
    button = switch_for(read)
    if button:
        handle_message(state, button[1])


def merged_entry(ref):
    """The entry with this session's edits laid on top (as overrides.json would be)."""
    entry = ref["entry"]
    return agent.apply_overrides(entry, {entry["id"]: ref["edits"]})


def provisional_entry(ref):
    """The provisional reference for a chat reference, or None.

    It is built only from the closest candidate's Crossref record, kept by
    the title search (title_search["closest"]), and only while the reference
    has no title or typed text of its own (nothing matched and no edit filled
    it in). It is shown and exported as provisional; its status is still the
    reference's own, from ref_status.
    """
    entry = merged_entry(ref)
    closest = (entry.get("title_search") or {}).get("closest")
    if not closest or agent.stated(entry.get("title")) or agent.stated(entry.get("reference_text")):
        return None
    provisional = {"id": entry["id"], "status": "auto", "input": entry["input"]}
    provisional.update(closest)
    provisional["provisional"] = True
    provisional["match_score"] = entry["title_search"]["candidates"][0]["title_similarity"]
    return provisional


def citation_entry(ref):
    """The entry a reference is shown, cited and exported from: its provisional
    reference if it has one, otherwise the entry with its edits."""
    return provisional_entry(ref) or merged_entry(ref)


def is_no_match(ref):
    """True if nothing can be shown for a reference: no title, no typed text, no candidate."""
    entry = citation_entry(ref)
    return not agent.stated(entry.get("title")) and not agent.stated(entry.get("reference_text"))


def ref_status(ref):
    """Status and reasons for a chat reference, worked out in code.

    Crossref only: the edited fields count as checked, but an edit can never
    make an entry "verified" (see agent.crossref_identified).
    """
    return agent.verify(merged_entry(ref), ref["edits"], crossref_only=True)


def links_line(entry):
    """The Google Scholar and Google search links (built, never requested)."""
    links = agent.search_links(entry)
    return f"[Google Scholar]({links['google_scholar']}) · [Google]({links['google']})"


def status_lines(status, reasons):
    """The status in bold, then the Crossref-only note or the reasons."""
    lines = [f"Status: **{STATUS_NAMES[status]}**"]
    if status == "verified":
        lines.append(VERIFIED_NOTE)
    if reasons:
        lines.append("\n".join(f"- {reason}" for reason in reasons))
    return lines


def entry_lines(entry, style, status, reasons):
    """The parts of a reply block: text, original title, status, reasons, links."""
    lines = [agent.shown_text(entry, style)]
    # APA puts article titles in sentence case; show the original to compare.
    original = agent.original_title_note(entry)
    if style == "apa" and original:
        lines.append(f"Original title: {original}")
    lines += status_lines(status, reasons)
    lines.append(links_line(entry))
    return lines


def provisional_lines(provisional, style, status, reasons):
    """The parts of a provisional block: badge, match score, quoted reference, status, links."""
    return [
        PROVISIONAL_BADGE,
        f"Match score: {provisional['match_score']} (needs {agent.TITLE_AGREE_SCORE} "
        "and a clear lead to be verified)",
        # A quote block, so the text can't be mistaken for a checked reference.
        "> " + agent.shown_text(provisional, style),
    ] + status_lines(status, reasons) + [links_line(provisional)]


def no_match_lines(entry, status, reasons):
    """The parts of a block with nothing to show: no reference is built, only what was typed."""
    return [NO_MATCH, f"You typed: {entry['input']}"] + status_lines(status, reasons) + [links_line(entry)]


def reference_block(number, ref, style):
    """One reference as Markdown: number, text, status, reasons and links.

    A reference looked up with a field chosen also says where it was searched
    (or, for a DOI, that the field was not used).
    """
    status, reasons = ref_status(ref)
    entry = merged_entry(ref)
    field = ref.get("field")
    if field and not agent.find_doi(entry["input"]) and status == "not_found":
        reasons = reasons + [not_found_in(field)]
    provisional = provisional_entry(ref)
    if provisional:
        lines = provisional_lines(provisional, style, status, reasons)
    elif is_no_match(ref):
        lines = no_match_lines(entry, status, reasons)
    else:
        lines = entry_lines(entry, style, status, reasons)
    lines[0] = f"**{number}.** {lines[0]}"
    if field:
        note = DOI_FIELD_NOTE if agent.find_doi(entry["input"]) else f"Searched in: {field}"
        lines.insert(1, note)
    return "\n\n".join(lines)


def search_entry(citation):
    """Turn one `find` result into an entry, marked as a search result.

    "from_search" tells agent.verify to make it "check", never "verified".
    """
    line = citation["doi"] if agent.stated(citation["doi"]) else citation["title"]
    entry = {"id": agent.make_id(line), "status": "auto", "input": line}
    entry.update(citation)
    entry["from_search"] = "result"
    return entry


def result_block(number, entry, field=None):
    """One `find` result as Markdown, always in APA 7 (a preview).

    `field` is the field searched, if one was chosen.
    """
    status, reasons = agent.verify(entry, crossref_only=True)
    lines = [f"**Result {number} (APA 7 preview)**"]
    if field:
        lines.append(f"Searched in: {field}")
    lines += entry_lines(entry, "apa", status, reasons)
    return "\n\n".join(lines)


def find_works(state, surname, year, topic):
    """Search Crossref by author and year, keep the results, and show them.

    Returns (reply, items): one item per result block, for the buttons.
    """
    field, issns = active_field(state)
    works, error = agent.search_crossref_author_year(surname, year, topic, issns)
    if error:
        # Crossref couldn't be asked: keep the previous results as they were.
        return "\n\n".join(status_lines("unavailable", [UNAVAILABLE_REASON])), []
    state["last_search"] = [search_entry(work) for work in works]
    # Numbers each search, so buttons on an older search's results can be hidden.
    state["search_count"] += 1
    if not works and field:
        return not_found_in(field), []
    if not works:
        searched = " ".join(part for part in (surname, str(year), topic) if part)
        return f"Crossref found no results for {searched}.", []
    blocks = [result_block(n, entry, field) for n, entry in enumerate(state["last_search"], start=1)]
    # Each result's citation is kept on its item: results stay an APA 7 preview,
    # so it never changes, and the card can show it after a newer search.
    items = [{"kind": "result", "number": n, "search": state["search_count"],
              "citation": citations.in_text(entry, "apa")}
             for n, entry in enumerate(state["last_search"], start=1)]
    return BLOCK_SEPARATOR.join(blocks), items


def add_result(state, number):
    """Add result `number` of the latest search to the references.

    The added reference stays "check" (agent.verify reads "from_search"),
    and from now on follows the current style like any other reference.
    """
    results = state["last_search"]
    if not results:
        return "There are no search results. Use `find` first."
    if not 1 <= number <= len(results):
        return f"There is no result {number}. The latest search has {len(results)} result(s)."
    # A copy, so the search result itself still says "result".
    entry = dict(results[number - 1])
    entry["from_search"] = "added"
    entry.pop("added_as", None)
    state["refs"].append({"entry": entry, "edits": {}, "confirmed": False})
    reference_number = len(state["refs"])
    # Remember it on the result, so its button shows the reference's state.
    results[number - 1]["added_as"] = reference_number
    return (f"Added result {number} as reference {reference_number}.\n\n"
            + reference_block(reference_number, state["refs"][-1], state["style"]))


def unavailable_block(entry):
    """A line Crossref couldn't be asked about. It isn't kept, so it has no number."""
    lines = [entry["input"]] + status_lines("unavailable", [UNAVAILABLE_REASON])
    lines.append(links_line(entry))
    return "\n\n".join(lines)


def look_up(state, lines):
    """Look up each line on Crossref and return one reply block per line, in order.

    Returns (reply, items): one item per block, for the buttons (None for a
    line Crossref couldn't be asked about, as it isn't kept).
    """
    blocks, items = [], []
    # The field limits title searches; resolve_line ignores it for a DOI.
    field, issns = active_field(state)
    for line in lines:
        # Crossref only: no cross-check with OpenAlex or Semantic Scholar.
        entry = agent.resolve_line(line, agent.make_id(line), cross_check_sources=False, issns=issns,
                                   keep_closest=True)
        if entry.get("lookup_unavailable"):
            blocks.append(unavailable_block(entry))
            items.append(None)
            continue
        # Keep it, with no edits yet; its number is its place in the list.
        # "field" remembers the field it was looked up in, for its reply block.
        state["refs"].append({"entry": entry, "edits": {}, "confirmed": False, "field": field})
        blocks.append(reference_block(len(state["refs"]), state["refs"][-1], state["style"]))
        items.append({"kind": "ref", "number": len(state["refs"])})
    return BLOCK_SEPARATOR.join(blocks), items


def edit_reference(state, number, field, text):
    """Change one field of reference `number` for this session, then show it again.

    A bad number, field or value changes nothing and says why.
    """
    if not 1 <= number <= len(state["refs"]):
        return f"There is no reference {number}. Type `list` to see the numbers."
    ref = state["refs"][number - 1]
    try:
        parsed = {field: agent.parse_value(field, text)}
    except ValueError as err:
        return f"Not changed: {err}"
    # Same rule as `refs edit`: a new type clears the old type's fields.
    agent.clear_fields_for_new_type(parsed, merged_entry(ref))
    ref["edits"].update(parsed)
    reply = f"Updated reference {number}."
    # The student confirmed the old text, so a change needs a new `accept`.
    if ref["confirmed"]:
        ref["confirmed"] = False
        reply += f" The confirmation was removed: type `accept {number}` again if it is still right."
    return reply + "\n\n" + reference_block(number, ref, state["style"])


def in_export(ref):
    """True if a reference goes in the export: Verified, or Check and confirmed."""
    status = ref_status(ref)[0]
    return status == "verified" or (status == "check" and ref["confirmed"])


def export_line(number, ref):
    """The "In export" line that `list` adds to each reference."""
    status = ref_status(ref)[0]
    if status == "verified":
        return "In export: **yes** (Verified)"
    if status == "check" and ref["confirmed"]:
        return "In export: **yes** (confirmed by you)"
    if status == "check":
        return f"In export: **no** (Check: type `accept {number}` once you have checked it)"
    return "In export: **no** (Not found)"


def export_header(refs):
    """The line that starts a `list` reply: how many of these references are exported."""
    exported = sum(1 for ref in refs if in_export(ref))
    return f"In the export: {exported} of {len(refs)} references."


def list_block(number, ref, style):
    """One reference of a `list` reply: its block and its "In export" line."""
    return reference_block(number, ref, style) + "\n\n" + export_line(number, ref)


def list_references(state):
    """Every reference so far, numbered, in the current style, and whether it is exported."""
    if not state["refs"]:
        return "No references yet."
    blocks = [list_block(n, ref, state["style"]) for n, ref in enumerate(state["refs"], start=1)]
    return export_header(state["refs"]) + "\n\n" + BLOCK_SEPARATOR.join(blocks)


def showing_references(shown, total, query):
    """The line that starts a `list FILTER` reply."""
    return f'Showing {shown} of {total} references matching "{query}".'


def list_matching(state, query):
    """`list FILTER`: only the references matching `query`. Returns (reply, numbers).

    The references keep their usual numbers, so `accept N` and `edit N` still
    work. The matching is the same as the My list search (listsearch.py).
    """
    if not state["refs"]:
        return "No references yet.", []
    numbers = [n for n, ref in enumerate(state["refs"], start=1)
               if listsearch.matches(merged_entry(ref), state["style"], query)]
    if not numbers:
        return f'No references match "{query}". Type `list` to see them all.', []
    listed = [state["refs"][n - 1] for n in numbers]
    blocks = [list_block(n, state["refs"][n - 1], state["style"]) for n in numbers]
    header = showing_references(len(numbers), len(state["refs"]), query) + "\n\n" + export_header(listed)
    return header + "\n\n" + BLOCK_SEPARATOR.join(blocks), numbers


def accept_reference(state, number):
    """Mark reference `number` as confirmed by the student. Only Check references can be."""
    if not 1 <= number <= len(state["refs"]):
        return f"There is no reference {number}. Type `list` to see the numbers."
    ref = state["refs"][number - 1]
    status = ref_status(ref)[0]
    if status == "verified":
        return f"Reference {number} is Verified, so it is already in the export."
    if status != "check":
        return (f"Reference {number} was not found, so it can't be confirmed or exported. "
                "Paste its DOI or fix it with `edit` first.")
    if ref["confirmed"]:
        return f"Reference {number} is already confirmed."
    # Confirming is the student's call; the status stays Check.
    ref["confirmed"] = True
    return (f"Reference {number} confirmed by you. It is now in the export.\n\n"
            + reference_block(number, ref, state["style"]))


def all_citations(state):
    """In-text citations for every reference in the current style, {number: citation}.

    A provisional reference is cited from its closest candidate, and always
    gets the provisional reason, as its reference is not verified.
    """
    numbered = [(n, citation_entry(ref)) for n, ref in enumerate(state["refs"], start=1)]
    found = citations.in_text_all(numbered, state["style"])
    for number, ref in enumerate(state["refs"], start=1):
        if provisional_entry(ref):
            found[number]["reasons"].insert(0, PROVISIONAL_REASON)
    return found


def card_citation(state, item):
    """The in-text citation drawn on one card, or None for a card without one.

    Returns {"style": style name, "parenthetical", "narrative", "reasons"}
    (as citations.in_text). A `find` result keeps its APA 7 citation; a
    reference follows the current style; a "No match found" card or a line
    Crossref couldn't be asked about has none.
    """
    if item is None:
        return None
    if item["kind"] == "result":
        return dict(item["citation"], style=citations.STYLE_NAMES["apa"]) if "citation" in item else None
    number = item["number"]
    if not 1 <= number <= len(state["refs"]) or is_no_match(state["refs"][number - 1]):
        return None
    return dict(all_citations(state)[number], style=citations.STYLE_NAMES[state["style"]])


def copy_text(state, item):
    """What a card's Copy popover holds: {"reference", "parenthetical", "narrative"}, or None.

    The reference is in the card's style (APA 7 for a `find` result) without
    the `*` italics markers, as plain text to paste. A card with no reference
    ("No match found", Unavailable, a result of an older search) has none.
    A citation that couldn't be built is None.
    """
    citation = card_citation(state, item)
    if citation is None:
        return None
    if item["kind"] == "result":
        if item["search"] != state["search_count"]:
            return None  # The entry went with the older search.
        reference = agent.shown_text(state["last_search"][item["number"] - 1], "apa")
    else:
        reference = agent.shown_text(citation_entry(state["refs"][item["number"] - 1]), state["style"])
    return {"reference": reference.replace("*", ""), "parenthetical": citation["parenthetical"],
            "narrative": citation["narrative"]}


def cite_reference(state, number):
    """The in-text citations for reference `number` in the current style, or why they need checking."""
    if not 1 <= number <= len(state["refs"]):
        return f"There is no reference {number}. Type `list` to see the numbers."
    citation = all_citations(state)[number]
    lines = [f"**{citations.STYLE_NAMES[state['style']]} in-text citations for reference {number}**"]
    if citation["parenthetical"]:
        lines.append(f"Parenthetical: {citation['parenthetical']}\n\nNarrative: {citation['narrative']}")
    if citation["reasons"]:
        lines.append("Citation: **Check**")
        lines.append("\n".join(f"- {reason}" for reason in citation["reasons"]))
    else:
        lines.append("Citation: **OK**")
    status = ref_status(state["refs"][number - 1])[0]
    lines.append(f"Reference status: **{STATUS_NAMES[status]}**")
    return "\n\n".join(lines)


def help_text():
    """The full help: commands, statuses, the export and the session note.

    The `help` command shows this; the sidebar shows the shorter quick_help.
    """
    commands = "**Commands**\n\n" + "\n".join(COMMAND_HELP)
    buttons = "**Buttons**\n\n" + "\n".join(BUTTON_HELP)
    field = "**Field**\n\n" + FIELD_HELP
    in_text = "**In-text citations**\n\n" + CITATION_HELP
    input_bar = "**The input bar**\n\n" + INPUT_HELP
    tags = "**Tags**\n\n" + TAG_HELP
    my_list = "**My list**\n\n" + MY_LIST_HELP
    statuses = "**Statuses**\n\n" + "\n".join(STATUS_HELP)
    export = "**Export**\n\n" + EXPORT_HELP
    session = "**This session**\n\n" + SESSION_NOTE
    return "\n\n".join([input_bar, tags, commands, buttons, in_text, field, my_list, statuses,
                        export, session])


def quick_help():
    """The short help in the sidebar's Help expander; `help` gives the full one."""
    return "\n\n".join([
        INPUT_HELP,
        TAG_HELP,
        "Each card: the reference, its in-text citation, its status, Google Scholar and Google "
        "links, **Add to list** and **Copy**. A provisional (orange) result is only the closest "
        "match: check it is the right paper.",
        f"**Verified** = {VERIFIED_NOTE.lower()}; **Check** = look at the reasons; "
        "**Not found** = nothing close enough on Crossref.",
        "Old commands still work (`find`, `add N`, `list`, `style`, `edit`, `cite N`, "
        "`accept N`, `clear`). Type `help` for all of them. " + SESSION_NOTE,
    ])


def handle_message(state, text):
    """Answer one chat message, updating `state`. Returns the reply (Markdown).

    The message and the reply are both added to state["history"], except
    after "clear", which leaves only its own reply. A reply made of
    reference or result blocks also keeps "items" (see button_for), so
    app.py can draw a button beside each block. A lookup or search reply
    keeps "read_as" (how its lines were read, 7.9), and a reply to a message
    with an unknown #tag keeps that "note", which also starts the reply.
    """
    # 1. #tags change the style and field first, so the search below uses them.
    tags = split_tags(text)
    if tags["style"]:
        state["style"] = tags["style"]
    if tags["field"]:
        set_field(state, tags["field"])
    if (tags["style"] or tags["field"]) and not tags["text"].strip():
        # Tags alone: only the settings change, nothing is searched.
        lines = []
        if tags["style"]:
            lines.append(f"Style set to {agent.STYLES[tags['style']]}.")
        if tags["field"]:
            lines.append(f"Field set to {tags['field']}.")
        reply = "\n\n".join(lines)
        state["history"].append({"role": "user", "content": text})
        state["history"].append({"role": "assistant", "content": reply})
        return reply

    # 2. The rest of the message is a command, a lookup or an author-and-year search.
    command = parse_command(tags["text"])
    name = command[0]
    items = []  # One per block of the reply, when it has buttons.
    read_as = []  # How each looked-up line (or the search) was read.

    # Work out the reply for each kind of message.
    if name == "clear":
        # Everything goes, My list included, except the chosen field.
        field = state.get("field", fields.ALL_FIELDS)
        state.clear()
        state.update(new_state())
        state["field"] = field
        reply = "Cleared."
        state["history"].append({"role": "assistant", "content": reply})
        return reply
    if name == "help":
        reply = help_text()
    elif name == "list" and len(command) == 2:
        reply, numbers = list_matching(state, command[1])
        items = [{"kind": "ref", "number": n} for n in numbers]
    elif name == "list":
        reply = list_references(state)
        items = [{"kind": "ref", "number": n} for n in range(1, len(state["refs"]) + 1)]
    elif name == "style":
        state["style"] = command[1]
        reply = f"Style set to {agent.STYLES[command[1]]}."
    elif name == "edit":
        reply = edit_reference(state, *command[1:])
    elif name == "find":
        reply, items = find_works(state, *command[1:])
        read_as = [find_read_as(*command[1:])]
    elif name == "add":
        before = len(state["refs"])
        reply = add_result(state, command[1])
        if len(state["refs"]) > before:
            items = [{"kind": "ref", "number": len(state["refs"])}]
    elif name == "accept":
        reply = accept_reference(state, command[1])
    elif name == "cite":
        reply = cite_reference(state, command[1])
    elif name == "lookup":
        reply, items = look_up(state, command[1])
        read_as = [{"kind": input_kind(line), "line": line} for line in command[1]]
    else:
        reply = "I didn't understand that.\n" + "\n".join(COMMAND_HELP)

    # 3. An unknown #word stayed in the text; say so first.
    note = " ".join(f"{tag} is not a tag, so it was searched as text." for tag in tags["unknown"])
    if note:
        reply = note + "\n\n" + reply

    state["history"].append({"role": "user", "content": text})
    answer = {"role": "assistant", "content": reply}
    if any(items):
        answer["items"] = items
        answer["kind"] = name  # Which command, so render_reply can redraw it.
    if read_as:
        answer["read_as"] = read_as
    if note:
        answer["note"] = note
    state["history"].append(answer)
    return reply


def button_for(state, item):
    """The button beside one reply block, as (label, enabled), or None for no button.

    item is {"kind": "ref", "number": N} for reference N, or
    {"kind": "result", "number": N, "search": S} for result N of search S.
    The label is worked out from the current state, so it is always up to date.
    """
    if item is None:
        return None
    if item["kind"] == "result":
        # `add N` means the latest search, so older results get no button.
        if item["search"] != state["search_count"]:
            return None
        result = state["last_search"][item["number"] - 1]
        if "added_as" in result:
            return export_button(state, result["added_as"])
        return ("Add to export", True)
    return export_button(state, item["number"])


def export_button(state, number):
    """The button for reference `number`: add it, or say why it can't be added."""
    if not 1 <= number <= len(state["refs"]):
        return None
    ref = state["refs"][number - 1]
    if in_export(ref):
        return ("✓ In export", False)
    if ref_status(ref)[0] == "check":
        return ("Add to export", True)
    return ("Not found", False)  # Not found references are never exported.


def press_button(state, item):
    """Do what a button does, by sending the same commands the student could type.

    A reference's button sends `accept N`; a result's button sends `add N`
    and then `accept` for the new reference. Both show in the chat.
    """
    button = button_for(state, item)
    if button is None or not button[1]:
        return  # Nothing to do (e.g. clicked twice before the page redrew).
    if item["kind"] == "result":
        handle_message(state, f"add {item['number']}")
        number = len(state["refs"])
    else:
        number = item["number"]
    handle_message(state, f"accept {number}")


def render_reply(state, message):
    """An assistant reply as it should be drawn now: [(markdown, item)], one per block.

    Reference blocks of lookup, `add` and `list` replies are built again from
    the reference's current state, so a style change re-formats them. Other
    blocks (`find` results, which stay an APA 7 preview, and Unavailable
    lines) and other replies are drawn as they were sent. The history itself
    is not changed.
    """
    # An unknown-tag note is drawn above the first block, not as part of it.
    note = message.get("note")
    content = message["content"][len(note) + 2:] if note else message["content"]
    blocks = content.split(BLOCK_SEPARATOR)
    items = message.get("items", [])
    # No buttons, or the blocks don't line up with the items: just the text.
    if len(blocks) != len(items):
        return [(message["content"], None)]
    kind = message.get("kind")
    drawn = []
    for position, (block, item) in enumerate(zip(blocks, items)):
        if item is None or item["kind"] != "ref" or not 1 <= item["number"] <= len(state["refs"]):
            drawn.append((block, item))
            continue
        number, ref = item["number"], state["refs"][item["number"] - 1]
        if kind == "list":
            text = list_block(number, ref, state["style"])
            if position == 0:
                # The header counts the references this reply listed.
                listed = [state["refs"][i["number"] - 1] for i in items]
                text = export_header(listed) + "\n\n" + text
                # `list FILTER`: keep its "Showing X of N ..." line as it was sent.
                if block.startswith("Showing "):
                    text = block.split("\n\n", 1)[0] + "\n\n" + text
        else:
            text = reference_block(number, ref, state["style"])
            if kind == "add":
                # Keep "Added result N as reference M." above the block.
                text = block.split("\n\n", 1)[0] + "\n\n" + text
        drawn.append((text, item))
    if note:
        drawn[0] = (note + "\n\n" + drawn[0][0], drawn[0][1])
    return drawn
