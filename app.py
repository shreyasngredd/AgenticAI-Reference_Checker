"""Citation Checker beta: the Streamlit reference chat.

Paste DOIs or titles (one per line) and get APA 7 references with a status
(Verified, Check, Not found or Unavailable), the reasons, and Google Scholar
and Google search links. `find SURNAME YEAR` searches Crossref by author
and year, and `add N` keeps a result. The sidebar shows the commands and
what the statuses mean (the same text as the "help" command).

All the chat logic is in refchat.py; this file only draws it. The chat
history, references and edits live in st.session_state, so they last until
the page is reloaded. The export (sidebar) is built in memory by export.py.
Nothing is written to disk, and only Crossref is contacted.

Run it from the project folder:
    streamlit run app.py
"""

import streamlit as st

import export
import refchat

st.set_page_config(page_title="Citation Checker beta")

# Sidebar, top to bottom: field dropdown (later), export, then the full help
# (the same text as the "help" command).
with st.sidebar:
    # Reserved for the field dropdown (spec section 3, "Field setting").
    field_slot = st.container()
    # Filled in at the end, once this run's message has been answered.
    export_slot = st.container()
    st.markdown(refchat.help_text())

# Heading: title, one-line subtitle and a short intro; details are in the sidebar.
st.title("Citation Checker beta")
st.markdown("*Check references against Crossref and format them in APA 7, Chicago or Harvard.*")
st.caption("Paste DOIs or titles, one per line. Commands and statuses are in the sidebar.")

# 1. One chat per browser session: kept across Streamlit's reruns.
if "chat" not in st.session_state:
    st.session_state["chat"] = refchat.new_state()
state = st.session_state["chat"]

# 2. Answer a new message first, so it is in the history drawn below.
text = st.chat_input("DOIs or titles, one per line, or a command (e.g. find LeCun 2015)")
if text:
    with st.spinner("Looking up on Crossref..."):
        refchat.handle_message(state, text)

# 3. Draw the whole history.
for message in state["history"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. The export buttons. Both files are built in memory; nothing goes to disk.
with export_slot:
    st.subheader("Export")
    exported = sum(1 for ref in state["refs"] if refchat.in_export(ref))
    st.caption(f"{exported} of {len(state['refs'])} references in the export.")
    st.download_button("Download .txt", data=export.export_txt(state),
                       file_name="references.txt", mime="text/plain")
    st.download_button("Download .csv", data=export.export_csv(state),
                       file_name="references.csv", mime="text/csv")
