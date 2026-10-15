"""Streamlit app for checking and fixing the reference list.

Shows every entry in refs/library.json as a card with:
- its verification status in colour (green = verified, amber = check,
  red = not_found) and the warnings, both worked out in code by agent.py;
- an editable text box for the reference; saving writes the text to
  refs/overrides.json (through agent.apply_edit, the same code the
  `refs edit` command uses) and re-generates the reference list;
- "Search Google Scholar" and "Search Google" buttons that open the
  stored search links in a new tab. The app never fetches those pages.

Run it from the project folder:
    streamlit run app.py
"""

import streamlit as st

import agent  # Reuses the refs-mode code, so the rules stay in one place.

# Status colours: Streamlit's success/warning/error boxes are green/amber/red.
STATUS_BOX = {"verified": st.success, "check": st.warning, "not_found": st.error}


def load_data():
    """Read the library, overrides and last-run settings.

    agent.load_json stops the program on invalid JSON (so hand edits aren't
    overwritten); here that becomes an error message instead.
    """
    try:
        library = agent.load_library()
        overrides = agent.load_overrides()
        last_run = agent.load_json(agent.LAST_RUN_PATH, {"style": "apa", "ids": []})
    except SystemExit:
        st.error("refs/library.json, overrides.json or last_run.json is not valid JSON. Fix it and reload.")
        st.stop()
    return library, overrides, last_run


def save_text(ref_id, text, box_key):
    """Save a hand-typed reference to overrides.json and re-generate the list.

    "not stated" removes the typed text, so the reference is built from the
    fetched details again.
    """
    try:
        agent.apply_edit(ref_id, {"reference_text": text}, show=False)
    except (ValueError, SystemExit) as err:
        st.error(f"Not saved: {err}")
        return
    # Forget the text box's old contents so it shows the saved text.
    st.session_state.pop(box_key, None)
    st.session_state["message"] = f"Saved {ref_id} to refs/overrides.json."
    st.rerun()


def show_card(entry, overrides, style):
    """Show one reference as a card: status, warnings, text box and buttons."""
    ref_id = entry["id"]
    merged = agent.apply_overrides(entry, overrides)  # Fetched details + hand corrections.
    current_text = agent.shown_text(merged, style)
    box_key = f"text-{ref_id}"

    with st.container(border=True):
        # 1. Status in colour, with the warnings underneath.
        verification = entry.get("verification")
        if verification:
            show_status = STATUS_BOX.get(verification["status"], st.info)
            show_status(f"**{verification['status']}**")
            for warning in verification["warnings"]:
                st.markdown(f"- {warning}")
        else:
            st.info("Not checked yet. Run `python agent.py refs --input refs.txt`.")

        # 2. How the reference looks (Markdown italics rendered), then the box to edit it.
        st.markdown(current_text)
        # APA puts article titles in sentence case; show the original to compare.
        original = agent.original_title_note(merged)
        if style == "apa" and original:
            st.caption(f"Original title: {original}")
        new_text = st.text_area("Reference", value=current_text, key=box_key, height=110)
        if entry.get("note"):
            st.caption(entry["note"])

        # 3. Buttons: save, back to the generated text, and the two searches.
        links = entry.get("search_links") or agent.search_links(merged)
        save_col, reset_col, scholar_col, google_col = st.columns(4)
        if save_col.button("Save", key=f"save-{ref_id}"):
            if not new_text.strip():
                st.error("The reference is empty. Type it in, or use “Use generated text”.")
            elif new_text.strip() == current_text:
                st.info("No change to save.")
            else:
                save_text(ref_id, new_text.strip(), box_key)
        typed = agent.stated(overrides.get(ref_id, {}).get("reference_text"))
        if typed and reset_col.button("Use generated text", key=f"reset-{ref_id}"):
            save_text(ref_id, "not stated", box_key)
        # link_button opens the URL in a new browser tab.
        scholar_col.link_button("Search Google Scholar", links["google_scholar"])
        google_col.link_button("Search Google", links["google"])


def main():
    """Draw the page: a summary line, then one card per reference."""
    st.set_page_config(page_title="Reference checker", layout="wide")
    st.title("Reference checker")

    library, overrides, last_run = load_data()
    if not library:
        st.info("refs/library.json is empty or missing. Run `python agent.py refs --input refs.txt` first.")
        return

    style = last_run.get("style", "apa")
    statuses = [e.get("verification", {}).get("status", "not checked") for e in library]
    st.write(
        f"{len(library)} references, shown in {agent.STYLES[style]} (the style of the last run). "
        f"Verified: {statuses.count('verified')}, check: {statuses.count('check')}, "
        f"not found: {statuses.count('not_found')}."
    )
    st.caption(
        "Status and warnings are worked out in code. A reference you type by hand is "
        "used exactly as typed, so it is marked “check” because code can't verify it."
    )
    if "message" in st.session_state:
        st.success(st.session_state.pop("message"))

    # Same order as the reference list: alphabetical, unresolved last.
    for entry in sorted(library, key=lambda e: agent.sort_key(agent.apply_overrides(e, overrides))):
        show_card(entry, overrides, style)


main()
