"""Reference Checker (beta): the Streamlit reference chat.

The page is one input bar (decision 7.9 of specs/goal-spec.md). Paste DOIs,
DOI links or titles (one per line), or type `SURNAME YEAR [topic]` to search
by author and year; each reply says how it was read, with a button to search
the other way. Under the bar, two chips show the style and the field; they
can also be changed by typing #tags (#harvard, #psychology, #all). Each card
has the reference, its in-text citation, its status, Google Scholar and
Google links, and two buttons: Add to list and Copy. The old commands
(find, add, list, style, edit, cite, accept, clear, help) still work.

The sidebar holds only My list (search, Remove, Clear list and the .txt and
.csv downloads) and a short Help.

All the logic is in refchat.py, mylist.py and fields.py; this file only
draws it. Everything lives in st.session_state, so it lasts until the page
is reloaded. The downloads are built in memory. Nothing is written to disk,
and only Crossref is contacted.

Run it from the project folder:
    streamlit run app.py
"""

import streamlit as st

import fields
import mylist
import refchat

st.set_page_config(page_title="Reference Checker (beta)")

# 1. One chat per browser session: kept across Streamlit's reruns.
if "chat" not in st.session_state:
    st.session_state["chat"] = refchat.new_state()
state = st.session_state["chat"]
# A chat started before the Field setting and My list existed gets them now.
state.setdefault("field", fields.ALL_FIELDS)
state.setdefault("my_list", [])


def choose_style():
    """The style chip changed: send the `style` command, as if typed."""
    refchat.handle_message(state, "style " + st.session_state["style_choice"])


def choose_field():
    """The field chip changed: search that field from the next message on."""
    refchat.set_field(state, st.session_state["field_choice"])


# 2. Heading, then the one input bar. Inside a container the chat input is
# drawn here, at the top, instead of pinned to the bottom of the page, so the
# chips can sit under it (7.9, "Layout").
st.title("Reference Checker (beta)")
st.caption("Check references against Crossref. Paste a DOI or a title, or type a surname "
           "and year (e.g. LeCun 2015). Add #harvard or #psychology to change the settings.")
with st.container():
    text = st.chat_input("DOI, title, or SURNAME YEAR [topic]   ·   #apa #harvard #chicago #field")
if text:
    with st.spinner("Looking up on Crossref..."):
        refchat.handle_message(state, text)

# 3. The chip row, drawn after the message so a #tag shows at once.
style_label, field_label = refchat.chip_labels(state)
style_column, field_column, _ = st.columns([1, 2, 3])
with style_column.popover(style_label):
    st.session_state["style_choice"] = state["style"]
    st.radio("Style", list(refchat.STYLE_LABELS), key="style_choice",
             format_func=lambda style: refchat.STYLE_LABELS[style], on_change=choose_style)
with field_column.popover(field_label):
    # The file is read on every run, so an edit shows without a restart.
    field_options, field_warning = fields.field_options()
    if field_warning:
        st.warning(field_warning)
    st.session_state["field_choice"] = field_label
    st.radio("Field", field_options, key="field_choice", on_change=choose_field)
    st.caption("Limits author-and-year and title searches to this field's journals. "
               "DOI lookups ignore it, because a DOI is exact.")


def draw_read_as(column, read, key):
    """How a line was read, and the button to search it the other way (if any)."""
    column.caption(refchat.read_as_line(read))
    switch = refchat.switch_for(read)
    if switch:
        column.button(switch[0], key=f"switch-{key}", on_click=refchat.press_switch, args=(state, read))


def draw_citation(column, item):
    """The card's in-text citation on one line, then any reason to check it."""
    citation = refchat.card_citation(state, item)
    if citation is None:
        return  # No reference on this card ("No match found" or Unavailable).
    if citation["parenthetical"]:
        column.markdown(f"In-text ({citation['style']}): {citation['parenthetical']} · "
                        f"{citation['narrative']}")
    if citation["reasons"]:
        column.markdown("Citation: **Check**\n\n" + "\n".join(f"- {reason}" for reason in citation["reasons"]))


def draw_buttons(column, item, key):
    """The card's two buttons: Add to list, and Copy (a popover with copy icons)."""
    button = mylist.card_list_button(state, item)
    if button:
        label, enabled, target = button
        column.button(label, key=f"list-{key}", disabled=not enabled,
                      on_click=mylist.press_list_button, args=(state, target))
    copied = refchat.copy_text(state, item)
    if copied:
        with column.popover("Copy"):
            # Each st.code box has Streamlit's own copy icon (top right).
            st.caption("Reference")
            st.code(copied["reference"], language=None, wrap_lines=True)
            if copied["parenthetical"]:
                st.caption("Parenthetical")
                st.code(copied["parenthetical"], language=None)
                st.caption("Narrative")
                st.code(copied["narrative"], language=None)


def draw_reply(message, message_number):
    """One assistant reply, in the current style: how it was read, then each card."""
    drawn = refchat.render_reply(state, message)
    read_as = message.get("read_as", [])
    # A search (or one line) was read once: say how above the whole reply.
    if read_as and len(read_as) != len(drawn):
        draw_read_as(st, read_as[0], f"{message_number}-all")
    # No cards: just the text.
    if len(drawn) == 1 and drawn[0][1] is None and not read_as:
        st.markdown(drawn[0][0])
        return
    for block_number, (block, item) in enumerate(drawn):
        key = f"{message_number}-{block_number}"
        if block_number:
            st.divider()
        text_column, button_column = st.columns([5, 1])
        # Several lines pasted: each card says how its own line was read.
        if len(read_as) == len(drawn):
            draw_read_as(text_column, read_as[block_number], key)
        text_column.markdown(block)
        draw_citation(text_column, item)
        draw_buttons(button_column, item, key)


def exchanges(history):
    """The history as [(user message or None, assistant reply or None)], oldest first."""
    pairs = []
    for message in history:
        if message["role"] == "user":
            pairs.append([message, None])
        elif pairs and pairs[-1][1] is None:
            pairs[-1][1] = message
        else:
            pairs.append([None, message])  # e.g. "Cleared." has no message before it.
    return pairs


# 4. The history, newest first, each message above its reply.
for number, (user, assistant) in reversed(list(enumerate(exchanges(state["history"])))):
    if user:
        with st.chat_message("user"):
            st.markdown(user["content"])
    if assistant:
        with st.chat_message("assistant"):
            draw_reply(assistant, number)

# 5. The sidebar: My list only, then a short Help.
with st.sidebar:
    # N is always the full list, whatever the search shows.
    st.subheader(f"My list ({len(state['my_list'])})")
    # The search only changes what is shown, never the list or the files.
    query = st.text_input("Search my list", key="list_query",
                          placeholder='e.g. mithas 2021 or "digital transformation"')
    showing = mylist.showing_line(state, query, "All")
    if showing:
        st.caption(showing)
    shown = mylist.shown_items(state, query)
    if state["my_list"] and not shown:
        st.info(mylist.NO_MATCHES)
    # Each item keeps its number in the full list, so Remove removes the right one.
    for number, item_text, item_status in shown:
        text_column, remove_column = st.columns([4, 1])
        text_column.markdown(f"{number}. {item_text} (**{item_status}**)")
        remove_column.button("Remove", key=f"remove-{number}",
                             on_click=mylist.remove_item, args=(state, number))
    st.button("Clear list", disabled=not state["my_list"],
              on_click=mylist.clear_list, args=(state,))
    # The full list, with each reference's in-text citation in the .txt.
    st.download_button("Download my_list.txt", data=mylist.list_txt(state, in_text=True),
                       file_name="my_list.txt", mime="text/plain")
    st.download_button("Download my_list.csv", data=mylist.list_csv(state),
                       file_name="my_list.csv", mime="text/csv")
    with st.expander("Help"):
        st.markdown(refchat.quick_help())
