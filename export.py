"""The export for the Streamlit reference chat: references.txt and references.csv.

This file has no Streamlit code. It picks the references that go in the
export (refchat.in_export: Verified, or Check and confirmed with `accept N`),
sorts them by first author and year, and builds both files as bytes in
memory for st.download_button. Nothing is written to disk. The rules are in
specs/goal-spec.md, section 3 ("Export").
"""

import csv
import io
import unicodedata

import agent  # Formatting, sort order and search links: one copy of the rules.
import refchat  # Which references are exported, their status and edits.

CSV_COLUMNS = [
    "number", "status", "confirmed", "authors", "year", "title", "journal", "volume",
    "issue", "pages", "DOI", "formatted reference", "parenthetical citation",
    "narrative citation", "Google Scholar link",
]
EMPTY_EXPORT = "No references to export yet."
EXPORT_NOTE = ("Verified references, plus Check references you confirmed. "
               "Not found references are never included.")


def without_accents(text):
    """"Müller" -> "Muller", so accented names sort where a reader expects."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def export_key(entry):
    """Sort key: first author's family name (no case, no accents), then year.

    It is agent.sort_key, with the accents taken out of the name.
    """
    group, name, year = agent.sort_key(entry)
    return (group, without_accents(name), year)


def plain(text):
    """The reference text without the Markdown italics markers (*)."""
    return text.replace("*", "")


def exported_refs(state):
    """The exported references as [(number, ref, entry)], in export order.

    number is the reference's number in `list`; entry has the edits applied.
    """
    rows = [(n, ref, refchat.merged_entry(ref))
            for n, ref in enumerate(state["refs"], start=1) if refchat.in_export(ref)]
    rows.sort(key=lambda row: export_key(row[2]))
    return rows


def citation_cells(citation):
    """The parenthetical and narrative cells, or "Check: <reasons>" in both."""
    if citation["parenthetical"] is None:
        check = "Check: " + "; ".join(citation["reasons"])
        return check, check
    return citation["parenthetical"], citation["narrative"]


def citation_line(number, citation):
    """One line of the .txt in-text section."""
    if citation["parenthetical"] is None:
        return f"Reference {number}: Check: " + "; ".join(citation["reasons"])
    line = f"Reference {number}: parenthetical {citation['parenthetical']}; narrative {citation['narrative']}"
    if citation["reasons"]:
        line += ". Check: " + "; ".join(citation["reasons"])
    return line


def export_txt(state):
    """references.txt as UTF-8 bytes: the list, then the APA 7 in-text citations."""
    style = state["style"]
    lines = [f"Citation Checker beta: reference list ({agent.STYLES[style]})", EXPORT_NOTE, ""]
    rows = exported_refs(state)
    if not rows:
        lines.append(EMPTY_EXPORT)
        return ("\n".join(lines) + "\n").encode("utf-8")

    # 1. The references, one paragraph each, in the current style.
    for _, _, entry in rows:
        lines += [plain(agent.shown_text(entry, style)), ""]

    # 2. The in-text citations, always APA 7, in the same order.
    citations = refchat.all_citations(state)
    lines += ["In-text citations (APA 7)", ""]
    lines += [citation_line(number, citations[number]) for number, _, _ in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def field_cell(entry, field):
    """A field as CSV text, or "not stated" when it is missing (never blank)."""
    value = agent.value(entry, field)
    if value is None:
        return "not stated"
    if field == "authors":
        # The form `edit` takes: "Family, Given; Family, Given".
        return "; ".join(f"{a['family']}, {a['given']}".rstrip(", ") for a in value)
    return str(value)


def export_csv(state):
    """references.csv as bytes: UTF-8 with a byte-order mark, so Excel shows accents.

    The csv module quotes any value with a comma, quote or line break, and
    doubles the quotes inside it.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    citations = refchat.all_citations(state)
    for number, ref, entry in exported_refs(state):
        status = refchat.ref_status(ref)[0]
        parenthetical, narrative = citation_cells(citations[number])
        writer.writerow([
            number,
            refchat.STATUS_NAMES[status],
            "yes" if ref["confirmed"] else "no",
            field_cell(entry, "authors"),
            field_cell(entry, "year"),
            field_cell(entry, "title"),
            field_cell(entry, "journal"),
            field_cell(entry, "volume"),
            field_cell(entry, "issue"),
            field_cell(entry, "pages"),
            field_cell(entry, "doi"),
            plain(agent.shown_text(entry, state["style"])),
            parenthetical,
            narrative,
            agent.search_links(entry)["google_scholar"],
        ])
    return buffer.getvalue().encode("utf-8-sig")
