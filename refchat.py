"""Chat logic for the Streamlit reference chat (app.py).

This file has no Streamlit code, so it can be tested on its own. It reads a
chat message, decides whether it is a command or a lookup (parse_command),
and builds the reply (handle_message). Everything else comes from agent.py:
the Crossref lookup, title search and author-and-year search, the formatting,
the status and the search links. The rules are in specs/goal-spec.md.

The chat only contacts Crossref (no OpenAlex or Semantic Scholar), and it
keeps everything in a plain dict ("state") that app.py stores in
st.session_state. Nothing is written to disk.
"""

import agent  # Lookup, formatting, status and links: one copy of the rules.
import citations  # APA 7 in-text citations for `cite` and the export.

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

# One line per command, each with an example. Used by "help", the sidebar
# in app.py (through help_text) and the short help message, so they match.
COMMAND_HELP = [
    "- Paste DOIs or titles, one per line, to look them up, "
    "e.g. `10.1038/nature14539` or `Deep learning`.",
    "- `find SURNAME YEAR [topic words]`: search Crossref by author and publication year, "
    "e.g. `find LeCun 2015 deep learning`. Shows up to 5 results as an APA 7 preview; "
    "they are never Verified.",
    "- `add N`: add result N of the latest `find` to your references, e.g. `add 2`.",
    "- `accept N`: confirm a Check reference once you have checked it yourself, "
    "so it goes in the export, e.g. `accept 3`.",
    "- `cite N`: show the APA 7 in-text citations (parenthetical and narrative) "
    "for reference N, e.g. `cite 1`.",
    "- `list`: show all references so far, numbered, and which are in the export, e.g. `list`.",
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
    "- **Unavailable**: Crossref could not be reached (network error, timeout or "
    "server error). Try again in a minute; nothing is added.",
]
# What goes in the export, for "help" and the sidebar.
EXPORT_HELP = (
    "The sidebar buttons download the export as `references.txt` (the list, then the "
    "APA 7 in-text citations) or `references.csv`. It holds Verified references plus "
    "Check references you confirmed with `accept N`, sorted by first author and year, "
    "in the current style. Not found references are never included."
)
COMMAND_WORDS = ("style", "list", "edit", "find", "add", "accept", "cite", "clear", "help")
NUMBER_COMMANDS = ("add", "accept", "cite")  # Commands that take one number, N.


def new_state():
    """A fresh chat: APA 7, no references, no search results, no history."""
    return {"style": "apa", "refs": [], "last_search": [], "history": []}


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
        ("help",), ("list",), ("clear",), ("style", style),
        ("edit", number, field, value), ("find", surname, year, topic),
        ("add", number), ("accept", number), ("cite", number), ("lookup", [lines]),
        ("unknown",)  -> answered with the short help message.
    A command must be the whole message. If the first word is a command but
    the rest doesn't fit, or the message is one word that is neither a
    command nor a DOI, the result is ("unknown",).
    """
    text = text.strip()
    words = text.split()
    if not words:
        return ("unknown",)
    command = words[0].lower()

    # 1. Commands: the first word decides, and the rest must fit exactly.
    if command in COMMAND_WORDS:
        if "\n" in text:
            return ("unknown",)  # A command is one line.
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

    # 3. Anything else: each non-blank line is a DOI or a title.
    return ("lookup", [line.strip() for line in text.splitlines() if line.strip()])


def merged_entry(ref):
    """The entry with this session's edits laid on top (as overrides.json would be)."""
    entry = ref["entry"]
    return agent.apply_overrides(entry, {entry["id"]: ref["edits"]})


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


def reference_block(number, ref, style):
    """One reference as Markdown: number, text, status, reasons and links."""
    status, reasons = ref_status(ref)
    lines = entry_lines(merged_entry(ref), style, status, reasons)
    lines[0] = f"**{number}.** {lines[0]}"
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


def result_block(number, entry):
    """One `find` result as Markdown, always in APA 7 (a preview)."""
    status, reasons = agent.verify(entry, crossref_only=True)
    lines = [f"**Result {number} (APA 7 preview)**"] + entry_lines(entry, "apa", status, reasons)
    return "\n\n".join(lines)


def find_works(state, surname, year, topic):
    """Search Crossref by author and year, keep the results, and show them."""
    citations, error = agent.search_crossref_author_year(surname, year, topic)
    if error:
        # Crossref couldn't be asked: keep the previous results as they were.
        return "\n\n".join(status_lines("unavailable", [UNAVAILABLE_REASON]))
    state["last_search"] = [search_entry(citation) for citation in citations]
    if not citations:
        searched = " ".join(part for part in (surname, str(year), topic) if part)
        return f"Crossref found no results for {searched}."
    blocks = [result_block(n, entry) for n, entry in enumerate(state["last_search"], start=1)]
    return "\n\n---\n\n".join(blocks)


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
    state["refs"].append({"entry": entry, "edits": {}, "confirmed": False})
    reference_number = len(state["refs"])
    return (f"Added result {number} as reference {reference_number}.\n\n"
            + reference_block(reference_number, state["refs"][-1], state["style"]))


def unavailable_block(entry):
    """A line Crossref couldn't be asked about. It isn't kept, so it has no number."""
    lines = [entry["input"]] + status_lines("unavailable", [UNAVAILABLE_REASON])
    lines.append(links_line(entry))
    return "\n\n".join(lines)


def look_up(state, lines):
    """Look up each line on Crossref and return one reply block per line, in order."""
    blocks = []
    for line in lines:
        # Crossref only: no cross-check with OpenAlex or Semantic Scholar.
        entry = agent.resolve_line(line, agent.make_id(line), cross_check_sources=False)
        if entry.get("lookup_unavailable"):
            blocks.append(unavailable_block(entry))
            continue
        # Keep it, with no edits yet; its number is its place in the list.
        state["refs"].append({"entry": entry, "edits": {}, "confirmed": False})
        blocks.append(reference_block(len(state["refs"]), state["refs"][-1], state["style"]))
    return "\n\n---\n\n".join(blocks)


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


def list_references(state):
    """Every reference so far, numbered, in the current style, and whether it is exported."""
    if not state["refs"]:
        return "No references yet."
    exported = sum(1 for ref in state["refs"] if in_export(ref))
    blocks = [reference_block(n, ref, state["style"]) + "\n\n" + export_line(n, ref)
              for n, ref in enumerate(state["refs"], start=1)]
    header = f"In the export: {exported} of {len(state['refs'])} references."
    return header + "\n\n" + "\n\n---\n\n".join(blocks)


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
    """APA 7 in-text citations for every reference, {number: citation}."""
    numbered = [(n, merged_entry(ref)) for n, ref in enumerate(state["refs"], start=1)]
    return citations.in_text_all(numbered)


def cite_reference(state, number):
    """The APA 7 in-text citations for reference `number`, or why they need checking."""
    if not 1 <= number <= len(state["refs"]):
        return f"There is no reference {number}. Type `list` to see the numbers."
    citation = all_citations(state)[number]
    lines = [f"**APA 7 in-text citations for reference {number}**"]
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

    The `help` command and the sidebar in app.py both show this, so they
    can't drift apart.
    """
    commands = "**Commands**\n\n" + "\n".join(COMMAND_HELP)
    statuses = "**Statuses**\n\n" + "\n".join(STATUS_HELP)
    export = "**Export**\n\n" + EXPORT_HELP
    session = "**This session**\n\n" + SESSION_NOTE
    return f"{commands}\n\n{statuses}\n\n{export}\n\n{session}"


def handle_message(state, text):
    """Answer one chat message, updating `state`. Returns the reply (Markdown).

    The message and the reply are both added to state["history"], except
    after "clear", which leaves only its own reply.
    """
    command = parse_command(text)
    name = command[0]

    # Work out the reply for each kind of message.
    if name == "clear":
        state.clear()
        state.update(new_state())
        reply = "Cleared."
        state["history"].append({"role": "assistant", "content": reply})
        return reply
    if name == "help":
        reply = help_text()
    elif name == "list":
        reply = list_references(state)
    elif name == "style":
        state["style"] = command[1]
        reply = f"Style set to {agent.STYLES[command[1]]}."
    elif name == "edit":
        reply = edit_reference(state, *command[1:])
    elif name == "find":
        reply = find_works(state, *command[1:])
    elif name == "add":
        reply = add_result(state, command[1])
    elif name == "accept":
        reply = accept_reference(state, command[1])
    elif name == "cite":
        reply = cite_reference(state, command[1])
    elif name == "lookup":
        reply = look_up(state, command[1])
    else:
        reply = "I didn't understand that.\n" + "\n".join(COMMAND_HELP)

    state["history"].append({"role": "user", "content": text})
    state["history"].append({"role": "assistant", "content": reply})
    return reply
