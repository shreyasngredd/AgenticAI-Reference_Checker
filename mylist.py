"""My list for the Streamlit reference chat: Add to list, Remove, Clear list, and its files.

This file has no Streamlit code. My list is the references the student picked
with an "Add to list" button, kept in the chat state (state["my_list"]) next
to the references. Each item is a copy of the entry as it was when added, and
the status it had then ("verified", "check" or, for a provisional reference,
"not_found"), so a Check item stays Check. Items are always shown and
exported in the current style, with their in-text citations.

It is separate from the export in export.py. The files (my_list.txt and
my_list.csv) are built as bytes in memory; nothing is written to disk. The
rules are in specs/goal-spec.md, section 3 ("My list").
"""

import csv
import io

import agent  # Formatting, DOI lookup and title normalising: one copy of the rules.
import citations  # In-text citations in the current style.
import export  # The export's sort order and CSV cells, reused for My list.
import listsearch  # Matching a search, shared with the `list FILTER` command.
import refchat  # The chat state: references, search results, status names.

ADD_LABEL = "Add to list"
ALREADY_LABEL = "Already in list"
# The sidebar's Status filter and Sort choices; the first of each is the default.
STATUS_FILTERS = ["All", "Verified", "Check", "Not found"]
SORTS = ["Date added", "Author A-Z", "Year (newest first)"]
NO_MATCHES = "No matches in your list"
CSV_COLUMNS = ["reference", "style", "status", "provisional", "parenthetical citation",
               "narrative citation", "DOI", "title", "authors", "year", "journal",
               "Google Scholar link"]
# The .txt marks every item that is not Verified, so it can't be taken for a checked one.
TXT_PREFIXES = {"verified": "", "check": "[CHECK] ", "not_found": "[NOT FOUND] "}


# --- Is this paper already in the list? ---

def doi_of(entry):
    """The entry's DOI, lowercase and without "https://doi.org/", or None."""
    doi = entry.get("doi")
    return agent.clean_doi(doi).lower() if agent.stated(doi) else None


def same_paper(a, b):
    """True if two entries are the same paper: same DOI, or same title when either has no DOI."""
    if doi_of(a) and doi_of(b):
        return doi_of(a) == doi_of(b)
    titles = [agent.normalise(e.get("title")) for e in (a, b) if agent.stated(e.get("title"))]
    return len(titles) == 2 and titles[0] == titles[1]


def in_list(state, entry):
    """True if this paper is already in My list."""
    return any(same_paper(item["entry"], entry) for item in state["my_list"])


# --- Adding, removing and clearing ---

def add_to_list(state, entry, status, provisional=False):
    """Add a copy of `entry` with its status ("verified", "check" or "not_found"). Returns the reply.

    provisional marks a provisional reference (the closest candidate of an
    unsure title search). The same paper is never added twice.
    """
    if in_list(state, entry):
        return ALREADY_LABEL
    state["my_list"].append({"entry": dict(entry), "status": status, "provisional": provisional})
    return "Added to My list: " + agent.shown_text(entry, state["style"])


def remove_item(state, number):
    """Remove item `number` (counted from 1, in the order added)."""
    if 1 <= number <= len(state["my_list"]):
        del state["my_list"][number - 1]


def clear_list(state):
    """Empty My list. The references and the export are not touched."""
    state["my_list"].clear()


# --- The Add to list buttons beside each card ---

def candidates_of(entry):
    """The title-search candidates that have a DOI, best first."""
    candidates = (entry.get("title_search") or {}).get("candidates", [])
    return [c for c in candidates if agent.stated(c.get("doi"))]


def button(state, label, entry, target):
    """One button as (label, enabled, target): disabled if the paper is already in the list."""
    if in_list(state, entry):
        return (ALREADY_LABEL, False, target)
    return (label, True, target)


def list_buttons_for(state, item):
    """The Add to list buttons beside one card, as [(label, enabled, target)].

    item is a reply item from refchat ({"kind": "ref", ...} or
    {"kind": "result", ...}), or None for a line with no card. target is what
    press_list_button needs. A reference with a built reference gets one
    button; a title lookup with candidates gets one per candidate with a DOI;
    a result of an older search gets none.
    """
    if item is None:
        return []
    if item["kind"] == "result":
        # Only the latest search's results, as for `add N`.
        if item["search"] != state["search_count"]:
            return []
        entry = state["last_search"][item["number"] - 1]
        return [button(state, ADD_LABEL, entry, item)]

    number = item["number"]
    if not 1 <= number <= len(state["refs"]):
        return []
    ref = state["refs"][number - 1]
    entry = refchat.merged_entry(ref)
    if agent.stated(entry.get("title")) and refchat.ref_status(ref)[0] in ("verified", "check"):
        return [button(state, ADD_LABEL, entry, {"kind": "ref", "number": number})]
    # No reference built: offer the provisional reference (candidate 1, whose
    # record came with the search), then each other candidate instead.
    buttons, first = [], 1
    provisional = refchat.provisional_entry(ref)
    if provisional:
        buttons.append(button(state, ADD_LABEL, provisional, {"kind": "provisional", "number": number}))
        first = 2
    buttons += [button(state, f"Add candidate {k} to list", candidate,
                       {"kind": "candidate", "number": number, "candidate": k})
                for k, candidate in enumerate(candidates_of(entry), start=1) if k >= first]
    return buttons


def card_list_button(state, item):
    """The one Add to list button on a card (7.9), as (label, enabled, target), or None.

    It is the first button of list_buttons_for, unless that is for a
    title-search candidate: candidate buttons are no longer on the cards.
    """
    buttons = [found for found in list_buttons_for(state, item) if found[2]["kind"] != "candidate"]
    return buttons[0] if buttons else None


def candidate_entry(candidate):
    """Look a candidate's DOI up on Crossref. Returns (entry, None) or (None, reason).

    The entry is marked as a candidate, so agent.verify always makes it "check".
    """
    doi = agent.clean_doi(candidate["doi"])
    citation, error = agent.lookup_doi(doi)
    if error == agent.doi_not_found_message(doi):
        return None, error
    if error:
        return None, refchat.UNAVAILABLE_REASON  # Crossref couldn't be reached.
    entry = {"id": agent.make_id(doi), "status": "auto", "input": doi}
    entry.update(citation)
    entry["from_search"] = "candidate"
    return entry, None


def press_list_button(state, target):
    """Do what an Add to list button does, and say so in the chat. Returns the reply."""
    if target["kind"] == "result":
        # A copy of the result; it stays "check" (agent.verify reads "from_search").
        entry, status = dict(state["last_search"][target["number"] - 1]), "check"
    elif target["kind"] == "ref":
        ref = state["refs"][target["number"] - 1]
        entry, status = refchat.merged_entry(ref), refchat.ref_status(ref)[0]
    elif target["kind"] == "provisional":
        # No request: the closest candidate's record came with the title search.
        # It keeps the reference's own status, Check or Not found.
        ref = state["refs"][target["number"] - 1]
        reply = add_to_list(state, refchat.provisional_entry(ref), refchat.ref_status(ref)[0],
                            provisional=True)
        state["history"].append({"role": "assistant", "content": reply})
        return reply
    else:
        ref_entry = refchat.merged_entry(state["refs"][target["number"] - 1])
        candidate = candidates_of(ref_entry)[target["candidate"] - 1]
        entry, status = None, "check"
        # Already in the list: no need to ask Crossref.
        if in_list(state, candidate):
            reply = ALREADY_LABEL
        else:
            entry, reason = candidate_entry(candidate)
            reply = reason
    if entry is not None:
        reply = add_to_list(state, entry, status)
    state["history"].append({"role": "assistant", "content": reply})
    return reply


# --- Searching the list (this never changes the list itself) ---

def matching_items(state, query="", status="All"):
    """The items that match the search and the Status filter: [(number, item)].

    number is the item's place in the full list (for Remove), and the order
    is the order added. state["my_list"] is only read.
    """
    found = []
    for number, item in enumerate(state["my_list"], start=1):
        # The Status filter compares with the shown name, "Verified" or "Check".
        if status != "All" and refchat.STATUS_NAMES[item["status"]] != status:
            continue
        if listsearch.matches(item["entry"], state["style"], query):
            found.append((number, item))
    return found


def year_key(numbered):
    """Sort key for Year (newest first): newest year first, no year last.

    Python's sort is stable, so items with the same year keep the order added.
    """
    year = str(numbered[1]["entry"].get("year", ""))
    return (0, -int(year)) if year.isdigit() else (1, 0)


def showing_line(state, query, status):
    """ "Showing X of N" when a search or a status filter is in use, else None."""
    if not listsearch.terms(query) and status == "All":
        return None
    return f"Showing {len(matching_items(state, query, status))} of {len(state['my_list'])}"


# --- Showing the list and its files ---

def shown_items(state, query="", status="All", sort="Date added"):
    """My list as the sidebar shows it: [(number, text, status name)].

    Only the items matching the search and the Status filter, in the chosen
    sort order. number is always the item's place in the full list.
    """
    numbered = matching_items(state, query, status)
    if sort == "Author A-Z":
        numbered.sort(key=lambda pair: export.export_key(pair[1]["entry"]))
    elif sort == "Year (newest first)":
        numbered.sort(key=year_key)
    return [(n, agent.shown_text(item["entry"], state["style"]), refchat.STATUS_NAMES[item["status"]])
            for n, item in numbered]


def sorted_items(state, query="", status="All", only_matching=False):
    """The items for the files, in bibliography order: first author (no case, no accents), then year.

    The full list, unless only_matching (the Export only matching box) is set:
    then only the items matching the search and the Status filter.
    """
    if only_matching:
        items = [item for _, item in matching_items(state, query, status)]
    else:
        items = state["my_list"]
    return sorted(items, key=lambda item: export.export_key(item["entry"]))


def item_citations(state, items):
    """The in-text citations of these items in the current style, in the same order.

    Two items with the same parenthetical citation are marked Check, naming
    each other ("item N", N counted in this order).
    """
    found = citations.in_text_all(list(enumerate((item["entry"] for item in items), start=1)),
                                  state["style"], label="item")
    return [found[n] for n in range(1, len(items) + 1)]


def txt_prefix(item):
    """[CHECK] or [NOT FOUND] for an item that is not Verified, plus (provisional)."""
    prefix = TXT_PREFIXES[item["status"]]
    return prefix + export.PROVISIONAL_PREFIX if item.get("provisional") else prefix


def in_text_line(citation):
    """The line under a reference in my_list.txt: its two citations, or why there are none."""
    if citation["parenthetical"] is None:
        return "    In-text: Check: " + "; ".join(citation["reasons"])
    return f"    In-text: {citation['parenthetical']} | {citation['narrative']}"


def list_txt(state, query="", status="All", only_matching=False, in_text=False):
    """my_list.txt as UTF-8 bytes: one reference per line, current style, no `*`.

    With in_text (the "Include in-text citations" box), each reference is
    followed by an "In-text:" line.
    """
    items = sorted_items(state, query, status, only_matching)
    lines = []
    for item, citation in zip(items, item_citations(state, items)):
        lines.append(txt_prefix(item) + export.plain(agent.shown_text(item["entry"], state["style"])) + "\n")
        if in_text:
            lines.append(in_text_line(citation) + "\n")
    return "".join(lines).encode("utf-8")


def list_csv(state, query="", status="All", only_matching=False):
    """my_list.csv as bytes: UTF-8 with a byte-order mark, so Excel shows accents."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    style = state["style"]
    items = sorted_items(state, query, status, only_matching)
    for item, citation in zip(items, item_citations(state, items)):
        entry = item["entry"]
        parenthetical, narrative = export.citation_cells(citation)
        writer.writerow([
            export.plain(agent.shown_text(entry, style)),
            refchat.STYLE_LABELS[style],
            refchat.STATUS_NAMES[item["status"]],
            "yes" if item.get("provisional") else "no",
            parenthetical,
            narrative,
            export.field_cell(entry, "doi"),
            export.field_cell(entry, "title"),
            export.field_cell(entry, "authors"),
            export.field_cell(entry, "year"),
            export.field_cell(entry, "journal"),
            agent.search_links(entry)["google_scholar"],
        ])
    return buffer.getvalue().encode("utf-8-sig")
