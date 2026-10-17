"""Tests for My list: the Add to list buttons, Remove, Clear list and its two files.

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 75-87, "My list"), and the expected results come from the
spec's wording, not from reading the code. app.py only draws the buttons and
the sidebar; what they show and do is in mylist.py, tested here. As in
test_refchat.py, urllib.request.urlopen is replaced by FakeCrossref, so no
test uses the network.

Run from the project folder:
    python -m unittest discover tests
"""

import csv
import io
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent  # noqa: E402
import mylist  # noqa: E402
import refchat  # noqa: E402
from test_export import DAVIS, MILLER, MULLER, QUOTED_TITLE, article  # noqa: E402
from test_refchat import (  # noqa: E402
    LECUN, LECUN_APA, MISSING_DOI, RESULT_REASON, TITLE, ChatTest, crossref_item,
)

CHECK_DOI = "10.1234/check"  # No volume, so it is Check (criterion 4).
CHECK_RECORD = dict(crossref_item("A study of something", CHECK_DOI), volume=None)
CANDIDATE_REASON = "title-search candidate, not verified: check it is the right paper"
COLUMNS = ["reference", "style", "status", "provisional", "parenthetical citation",
           "narrative citation", "DOI", "title", "authors", "year", "journal", "Google Scholar link"]
UNAVAILABLE_REASON = "Crossref is unavailable right now. Try again in a minute."


class ListTest(ChatTest):
    """Shared helpers: more records on the fake Crossref, and the list buttons."""

    def setUp(self):
        """Add the Check record and the export test records to the fake Crossref."""
        super().setUp()
        for record in (CHECK_RECORD, DAVIS, MILLER, MULLER):
            self.crossref.works[record["DOI"]] = record

    def last_items(self):
        """The button items of the latest reply that has them."""
        for message in reversed(self.state["history"]):
            if "items" in message:
                return message["items"]
        return []

    def buttons(self, item):
        """The Add to list buttons for one card, as [(label, enabled)]."""
        return [(label, enabled) for label, enabled, _ in mylist.list_buttons_for(self.state, item)]

    def press(self, item, button=0):
        """Press one Add to list button of a card, with the fake Crossref in place."""
        target = mylist.list_buttons_for(self.state, item)[button][2]
        with mock.patch("urllib.request.urlopen", self.crossref.urlopen):
            return mylist.press_list_button(self.state, target)

    def items_shown(self):
        """My list as the sidebar shows it: [(text, status name)]."""
        return [(text, status) for _, text, status in mylist.shown_items(self.state)]

    def csv_rows(self):
        """my_list.csv read back with a CSV reader (header included)."""
        return list(csv.reader(io.StringIO(mylist.list_csv(self.state).decode("utf-8-sig"))))

    def look_up(self, *dois):
        """Look up DOIs, one per line; returns the reply."""
        return self.send("\n".join(dois))


class Criterion75WhichCardsHaveTheButton(ListTest):
    """75. Add to list on Verified, Check and result cards; per candidate; none elsewhere."""

    def test_lookup_cards(self):
        """Verified and Check references have it; Not found without candidates doesn't."""
        self.look_up("10.1038/nature14539", CHECK_DOI, MISSING_DOI)
        verified, check, not_found = self.last_items()
        self.assertEqual(self.buttons(verified), [("Add to list", True)])
        self.assertEqual(self.buttons(check), [("Add to list", True)])
        self.assertEqual(self.buttons(not_found), [])

    def test_unavailable_line_has_none(self):
        """A line Crossref couldn't be asked about has no card item at all."""
        self.crossref.failure = urllib.error.URLError("down")
        self.look_up("10.1038/nature14539")
        self.assertEqual(mylist.list_buttons_for(self.state, None), [])

    def test_one_button_per_candidate(self):
        """A weak title match: the provisional reference, then the other candidates (changed 2026-10-16)."""
        self.search_returns([("10.1234/a", 0.8), ("10.1234/b", 0.78)])
        self.send(TITLE)
        self.assertEqual(self.status_of(1), "check")
        self.assertEqual(self.buttons(self.last_items()[0]),
                         [("Add to list", True), ("Add candidate 2 to list", True)])

    def test_not_found_with_a_candidate(self):
        """A title below the weak threshold offers its closest candidate as a provisional reference."""
        self.search_returns([("10.1234/a", 0.5)])
        self.send(TITLE)
        self.assertEqual(self.status_of(1), "not_found")
        self.assertEqual(self.buttons(self.last_items()[0]), [("Add to list", True)])

    def test_find_results(self):
        """Latest results have it; an older search's results don't."""
        self.crossref.author_items = [LECUN, crossref_item(TITLE, "10.1234/a")]
        self.send("find LeCun 2015")
        old = self.last_items()[0]
        self.assertEqual([self.buttons(item) for item in self.last_items()],
                         [[("Add to list", True)], [("Add to list", True)]])
        self.send("find LeCun 2015")
        self.assertEqual(self.buttons(old), [])


class Criterion76AddReference(ListTest):
    """76. Add to list on a reference: a copy with its status, a chat line, no request."""

    def test_add_verified_reference(self):
        """The item is the reference as shown, Verified."""
        self.look_up("10.1038/nature14539")
        requests = len(self.crossref.urls)
        reply = self.press(self.last_items()[0])
        self.assertTrue(reply.startswith("Added to My list: "), reply)
        self.assertEqual(self.state["history"][-1], {"role": "assistant", "content": reply})
        self.assertEqual(self.items_shown(), [(LECUN_APA, "Verified")])
        self.assertEqual(len(self.crossref.urls), requests)


class Criterion77AddResult(ListTest):
    """77. Add to list on a `find` result: Check, not a reference, no request."""

    def test_add_result(self):
        """The result goes in My list as Check; `list` is unchanged."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        requests = len(self.crossref.urls)
        self.press(self.last_items()[0])
        self.assertEqual(self.items_shown(), [(LECUN_APA, "Check")])
        self.assertEqual(self.state["refs"], [])
        self.assertEqual(self.send("list"), "No references yet.")
        self.assertEqual(len(self.crossref.urls), requests)


class Criterion78AddCandidate(ListTest):
    """78. A candidate is looked up by DOI and added as Check, never Verified."""

    def setUp(self):
        """A weak title match whose second candidate is a complete Crossref record.

        Candidate 1 is the provisional reference (criterion 132), so the
        candidate button tested here is candidate 2's.
        """
        super().setUp()
        self.search_returns([("10.1234/z", 0.8), ("10.1234/a", 0.79)])
        self.crossref.works["10.1234/a"] = crossref_item(f"{TITLE}, part 10.1234/a", "10.1234/a")
        self.send(TITLE)
        self.crossref.urls = []

    def press(self, item, button=1):
        """Press candidate 2's button (the second button) by default."""
        return super().press(item, button)

    def test_candidate_is_check(self):
        """One request for the candidate's DOI; the item is Check with the candidate reason."""
        self.press(self.last_items()[0])
        self.assertEqual(len(self.crossref.urls), 1)
        self.assertEqual(urllib.parse.urlsplit(self.crossref.urls[0]).netloc, "api.crossref.org")
        self.assertIn("10.1234", urllib.parse.unquote(self.crossref.urls[0]))
        self.assertEqual(self.items_shown()[0][1], "Check")
        status, reasons = agent.verify(self.state["my_list"][0]["entry"], crossref_only=True)
        self.assertEqual(status, "check")
        self.assertEqual(reasons[0], CANDIDATE_REASON)

    def test_crossref_unavailable(self):
        """Nothing is added, and the reply says why."""
        self.crossref.failure = urllib.error.URLError("down")
        reply = self.press(self.last_items()[0])
        self.assertIn(UNAVAILABLE_REASON, reply)
        self.assertEqual(self.state["my_list"], [])

    def test_no_record(self):
        """A candidate DOI Crossref doesn't have: nothing added."""
        del self.crossref.works["10.1234/a"]
        reply = self.press(self.last_items()[0])
        self.assertIn("Crossref has no record for DOI", reply)
        self.assertEqual(self.state["my_list"], [])


class Criterion79NoDuplicates(ListTest):
    """79. The same DOI (or, without a DOI, the same title) is added only once."""

    def test_same_doi_twice(self):
        """The second card says Already in list, and pressing it adds nothing."""
        self.look_up("10.1038/nature14539", "10.1038/nature14539")
        first, second = self.last_items()
        self.press(first)
        self.assertEqual(self.buttons(first), [("Already in list", False)])
        self.assertEqual(self.buttons(second), [("Already in list", False)])
        self.assertEqual(mylist.press_list_button(self.state, {"kind": "ref", "number": 2}),
                         "Already in list")
        self.assertEqual(len(self.state["my_list"]), 1)

    def test_result_after_reference(self):
        """A `find` result with a DOI already in the list is a duplicate too."""
        self.look_up("10.1038/nature14539")
        self.press(self.last_items()[0])
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        self.assertEqual(self.buttons(self.last_items()[0]), [("Already in list", False)])

    def test_doi_case_and_prefix(self):
        """DOIs match ignoring case and the https://doi.org/ prefix."""
        self.look_up("10.1038/nature14539")
        entry = refchat.merged_entry(self.state["refs"][0])
        self.assertTrue(mylist.add_to_list(self.state, entry, "verified").startswith("Added"))
        same = dict(entry, doi="https://doi.org/10.1038/NATURE14539")
        self.assertEqual(mylist.add_to_list(self.state, same, "verified"), "Already in list")
        self.assertEqual(len(self.state["my_list"]), 1)

    def test_same_title_without_doi(self):
        """Without a DOI, titles match after agent.normalise."""
        self.look_up("10.1038/nature14539")
        entry = refchat.merged_entry(self.state["refs"][0])
        no_doi = dict(entry, doi="not stated", title="Deep Learning!")
        self.assertTrue(mylist.add_to_list(self.state, no_doi, "check").startswith("Added"))
        other = dict(entry, doi="not stated", title="deep  learning")
        self.assertEqual(mylist.add_to_list(self.state, other, "check"), "Already in list")
        self.assertTrue(mylist.add_to_list(self.state, dict(entry, doi="not stated", title="Other"),
                                           "check").startswith("Added"))
        self.assertEqual(len(self.state["my_list"]), 2)


class Criterion80CheckStaysCheck(ListTest):
    """80. A Check item stays Check, after a style change, `accept` and `edit`."""

    def test_check_stays_check(self):
        """Shown and exported as Check whatever happens to the reference."""
        self.look_up(CHECK_DOI)
        self.press(self.last_items()[0])
        self.send("style harvard")
        self.send("accept 1")
        self.send("edit 1 volume 5")
        self.assertEqual(self.items_shown()[0][1], "Check")
        self.assertEqual(self.csv_rows()[1][2], "Check")
        # A snapshot: the edit made after adding is not in the item.
        self.assertNotEqual(self.state["my_list"][0]["entry"]["volume"], "5")


class Criterion81RemoveAndClear(ListTest):
    """81. Remove takes out one item; Clear list and `clear` empty the list."""

    def test_remove_one(self):
        """Only item 1 goes, and it can be added again."""
        self.look_up("10.1038/nature14539", DAVIS["DOI"])
        lecun, davis = self.last_items()
        self.press(lecun)
        self.press(davis)
        mylist.remove_item(self.state, 1)
        self.assertEqual(len(self.state["my_list"]), 1)
        self.assertIn("Davis", self.items_shown()[0][0])
        self.assertEqual(self.buttons(lecun), [("Add to list", True)])
        self.press(lecun)
        self.assertEqual(len(self.state["my_list"]), 2)

    def test_clear_list(self):
        """Clear list empties My list but keeps the references."""
        self.look_up("10.1038/nature14539")
        self.press(self.last_items()[0])
        mylist.clear_list(self.state)
        self.assertEqual(self.state["my_list"], [])
        self.assertEqual(len(self.state["refs"]), 1)

    def test_clear_command(self):
        """The `clear` command empties My list too."""
        self.look_up("10.1038/nature14539")
        self.press(self.last_items()[0])
        self.send("clear")
        self.assertEqual(self.state["my_list"], [])


class Criterion82TxtFile(ListTest):
    """82. my_list.txt: one reference per line, current style, no *, sorted."""

    def test_sorted_lines(self):
        """Müller sorts as Muller: Davis, Miller, Müller."""
        self.look_up(MULLER["DOI"], MILLER["DOI"], DAVIS["DOI"])
        for item in self.last_items():
            self.press(item)
        entries = [refchat.merged_entry(ref) for ref in self.state["refs"]]
        expected = [agent.shown_text(entries[n], "apa").replace("*", "") for n in (2, 1, 0)]
        text = mylist.list_txt(self.state).decode("utf-8")
        self.assertEqual(text, "\n".join(expected) + "\n")
        self.assertNotIn("*", text)
        self.assertIn("Müller, J.", text)

    def test_empty(self):
        """An empty list gives an empty file."""
        self.assertEqual(mylist.list_txt(self.state), b"")
        self.assertEqual(mylist.list_txt(self.state, in_text=True), b"")

    def test_check_prefix(self):
        """A Check item starts with [CHECK]; a Verified one has no prefix (changed 2026-10-16)."""
        self.look_up("10.1038/nature14539", CHECK_DOI)
        for item in self.last_items():
            self.press(item)
        lines = mylist.list_txt(self.state).decode("utf-8").splitlines()
        self.assertTrue(lines[0].startswith("LeCun, Y."))
        self.assertTrue(lines[1].startswith("[CHECK] Lovelace, A."))

    def test_in_text_lines(self):
        """With the option ticked, each reference is followed by its In-text line."""
        self.look_up(DAVIS["DOI"])
        self.press(self.last_items()[0])
        lines = mylist.list_txt(self.state, in_text=True).decode("utf-8").splitlines()
        self.assertEqual(lines[1], "    In-text: (Davis, 1989) | Davis (1989)")
        self.send("style chicago")
        lines = mylist.list_txt(self.state, in_text=True).decode("utf-8").splitlines()
        self.assertEqual(lines[1], "    In-text: (Davis 1989) | Davis (1989)")


class Criterion83CsvFile(ListTest):
    """83. my_list.csv: BOM, the header, one row per item, `not stated`, quoting."""

    def test_header_and_row(self):
        """Every column, in order, for a Verified reference."""
        self.look_up("10.1038/nature14539")
        self.press(self.last_items()[0])
        data = mylist.list_csv(self.state)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        header, row = self.csv_rows()
        self.assertEqual(header, COLUMNS)
        self.assertEqual(row, [
            LECUN_APA.replace("*", ""), "APA 7", "Verified", "no", "(LeCun et al., 2015)",
            "LeCun et al. (2015)", "10.1038/nature14539", "Deep learning",
            "LeCun, Yann; Bengio, Yoshua; Hinton, Geoffrey", "2015", "Nature",
            agent.search_links(refchat.merged_entry(self.state["refs"][0]))["google_scholar"],
        ])

    def test_missing_field_and_quotes(self):
        """A missing journal is `not stated`; a comma and quotes read back unchanged."""
        record = article("10.1234/quoted", QUOTED_TITLE, [("Ann", "Quinn")])
        del record["container-title"]
        self.crossref.works[record["DOI"]] = record
        self.look_up(record["DOI"])
        self.press(self.last_items()[0])
        row = self.csv_rows()[1]
        self.assertEqual(row[COLUMNS.index("title")], QUOTED_TITLE)
        self.assertEqual(row[COLUMNS.index("journal")], "not stated")
        self.assertNotIn("", row)

    def test_rows_follow_the_txt_order(self):
        """Rows are sorted like the .txt."""
        self.look_up(MULLER["DOI"], DAVIS["DOI"])
        for item in self.last_items():
            self.press(item)
        self.assertEqual([row[COLUMNS.index("DOI")] for row in self.csv_rows()[1:]],
                         [DAVIS["DOI"], MULLER["DOI"]])

    def test_empty(self):
        """An empty list gives the header only."""
        self.assertEqual(self.csv_rows(), [COLUMNS])


class Criterion84StyleChangeReformats(ListTest):
    """84. After a style change, My list, its files and the drawn history use the new style."""

    def test_list_and_files(self):
        """Harvard text in the sidebar, the .txt and the .csv (style column too)."""
        self.look_up("10.1038/nature14539")
        self.press(self.last_items()[0])
        self.send("style harvard")
        entry = refchat.merged_entry(self.state["refs"][0])
        harvard = agent.shown_text(entry, "harvard")
        self.assertNotEqual(harvard, LECUN_APA)
        self.assertEqual(self.items_shown(), [(harvard, "Verified")])
        self.assertEqual(mylist.list_txt(self.state).decode("utf-8"), harvard.replace("*", "") + "\n")
        row = self.csv_rows()[1]
        self.assertEqual(row[:2], [harvard.replace("*", ""), "Harvard"])

    def test_dropdown_order(self):
        """The Style dropdown: APA 7, Harvard, Chicago."""
        self.assertEqual(list(refchat.STYLE_LABELS.items()),
                         [("apa", "APA 7"), ("harvard", "Harvard"), ("chicago", "Chicago")])

    def test_history_is_redrawn(self):
        """Lookup, `add` and `list` blocks redraw in Chicago; `find` stays APA 7."""
        self.crossref.author_items = [LECUN]
        self.look_up("10.1038/nature14539")
        lookup = self.state["history"][-1]
        self.send("find LeCun 2015")
        found = self.state["history"][-1]
        self.send("add 1")
        added = self.state["history"][-1]
        self.send("list")
        listed = self.state["history"][-1]
        self.send("style chicago")
        chicago = agent.shown_text(refchat.merged_entry(self.state["refs"][0]), "chicago")
        for message in (lookup, added, listed):
            drawn = "\n".join(text for text, _ in refchat.render_reply(self.state, message))
            self.assertIn(chicago, drawn)
            self.assertNotIn(LECUN_APA, drawn)
        self.assertIn("Added result 1 as reference 2.",
                      refchat.render_reply(self.state, added)[0][0])
        self.assertIn("In export:", refchat.render_reply(self.state, listed)[0][0])
        drawn_find = refchat.render_reply(self.state, found)[0][0]
        self.assertIn(LECUN_APA, drawn_find)
        self.assertIn("APA 7 preview", drawn_find)
        # The stored history text itself is not changed.
        self.assertIn(LECUN_APA, lookup["content"])


class Criterion85AddCommandUnchanged(ListTest):
    """85. `add N` still adds a result to the references, and not to My list."""

    def test_add_command(self):
        """The reference is added as before; My list stays empty."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        self.assertIn("Added result 1 as reference 1.", self.send("add 1"))
        self.assertEqual(self.state["my_list"], [])
        self.assertIn(RESULT_REASON, refchat.result_block(1, self.state["last_search"][0]))


class Criterion86NoRequestsOrWrites(ListTest):
    """86. Adding (not a candidate), removing, clearing and the files: no request, no write."""

    def test_nothing_requested_or_written(self):
        """Count requests and file writes around every list action."""
        self.crossref.author_items = [DAVIS]
        self.look_up("10.1038/nature14539")
        self.send("find Davis 1989")
        requests = len(self.crossref.urls)
        with mock.patch.object(agent, "save_json") as save_json, \
                mock.patch.object(Path, "write_text") as write_text, \
                mock.patch.object(Path, "write_bytes") as write_bytes:
            self.press(self.state["history"][-3]["items"][0])  # The lookup's reference.
            self.press(self.last_items()[0])                    # The find result.
            mylist.list_txt(self.state)
            mylist.list_csv(self.state)
            mylist.remove_item(self.state, 1)
            mylist.clear_list(self.state)
        self.assertEqual(len(self.crossref.urls), requests)
        save_json.assert_not_called()
        write_text.assert_not_called()
        write_bytes.assert_not_called()


class Criterion87HelpExplainsMyList(ListTest):
    """87. `help` explains My list and still lists every command."""

    def test_help(self):
        """The list controls, the two files and every command word."""
        reply = self.send("help")
        for words in ("My list", "Add to list", "Remove", "Clear list", "my_list.txt", "my_list.csv"):
            self.assertIn(words, reply)
        for command in ("`find SURNAME YEAR", "`add N`", "`list`", "`style", "`edit N",
                        "`clear`", "`help`", "`accept N`", "`cite N`"):
            self.assertIn(command, reply)


if __name__ == "__main__":
    unittest.main()
