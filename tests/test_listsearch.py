"""Tests for searching My list and the `list FILTER` command.

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 107-117, "Searching My list"); the expected results come
from the spec's wording. The matching is in listsearch.py and the sidebar's
view of the list in mylist.py; app.py only draws them. As in
test_refchat.py, urllib.request.urlopen is replaced by FakeCrossref, so no
test uses the network.

Run from the project folder:
    python -m unittest discover tests
"""

import csv
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import listsearch  # noqa: E402
import mylist  # noqa: E402
import refchat  # noqa: E402
from test_export import MILLER, MULLER, NO_YEAR, article  # noqa: E402
from test_refchat import ChatTest  # noqa: E402

# Records for the searches below. MULLER is "Jörg Müller" (2019), MILLER is
# "Ann Miller" (2019) and NO_YEAR has no year, so it is Check.
MITHAS_2021 = article("10.1234/mithas21", "Digital transformation strategy",
                      [("Sunil", "Mithas")], 2021)
MITHAS_2019 = article("10.1234/mithas19", "Strategy for digital transformation",
                      [("Sunil", "Mithas")], 2019)
OTHER_2021 = article("10.1234/other21", "Something else entirely",
                     [("Ada", "Lovelace")], 2021)
PLAIN_MULLER = article("10.1234/muller2", "Plain spelling", [("Karl", "Muller")], 2017)
RECORDS = [MITHAS_2021, MITHAS_2019, OTHER_2021, MULLER, PLAIN_MULLER, MILLER, NO_YEAR]


class SearchTest(ChatTest):
    """Shared helpers: put records in My list, and read the list back."""

    def setUp(self):
        """Put the records on the fake Crossref."""
        super().setUp()
        for record in RECORDS:
            self.crossref.works[record["DOI"]] = record

    def fill_list(self, *records):
        """Look the records up and add each reference to My list, in this order."""
        self.send("\n".join(record["DOI"] for record in records))
        for ref in self.state["refs"][-len(records):]:
            mylist.add_to_list(self.state, refchat.merged_entry(ref), refchat.ref_status(ref)[0])

    def dois(self, query="", status="All", sort="Date added"):
        """The DOIs of the items the sidebar shows, in the order shown."""
        shown = mylist.shown_items(self.state, query, status, sort)
        return [self.state["my_list"][number - 1]["entry"]["doi"] for number, _, _ in shown]


class Criterion107OneWordMatches(SearchTest):
    """107. One word matches any searched piece, ignoring case."""

    def test_author_word(self):
        """A surname in any case finds both of that author's items."""
        self.fill_list(MITHAS_2021, OTHER_2021, MITHAS_2019)
        self.assertEqual(self.dois("MITHAS"), ["10.1234/mithas21", "10.1234/mithas19"])

    def test_title_and_journal_words(self):
        """A title word and a journal word match too."""
        self.fill_list(MITHAS_2021, OTHER_2021)
        self.assertEqual(self.dois("entirely"), ["10.1234/other21"])
        self.assertEqual(len(self.dois("tests")), 2)  # Both are in the Journal of Tests.


class Criterion108WordsAreAnded(SearchTest):
    """108. Several words must all match."""

    def test_author_and_year(self):
        """`mithas 2021` finds only the item with both."""
        self.fill_list(MITHAS_2021, MITHAS_2019, OTHER_2021)
        self.assertEqual(self.dois("mithas 2021"), ["10.1234/mithas21"])

    def test_words_can_match_different_pieces(self):
        """One word in the title and one in the authors is still a match."""
        self.fill_list(MITHAS_2021, OTHER_2021)
        self.assertEqual(self.dois("sunil digital"), ["10.1234/mithas21"])


class Criterion109AccentsAreIgnored(SearchTest):
    """109. `muller` finds "Müller", and `müller` finds "Muller"."""

    def test_both_ways(self):
        """Both spellings find both items, and not "Miller"."""
        self.fill_list(MULLER, PLAIN_MULLER, MILLER)
        both = ["10.1234/muller", "10.1234/muller2"]
        self.assertEqual(self.dois("muller"), both)
        self.assertEqual(self.dois("Müller"), both)


class Criterion110DoiMatches(SearchTest):
    """110. A DOI, part of one, or a doi.org link finds its item."""

    def test_doi_forms(self):
        """Each form finds only that item."""
        self.fill_list(MITHAS_2021, MITHAS_2019)
        for query in ("10.1234/mithas21", "mithas21", "https://doi.org/10.1234/mithas21"):
            with self.subTest(query=query):
                self.assertEqual(self.dois(query), ["10.1234/mithas21"])


class Criterion111QuotedPhrase(SearchTest):
    """111. A quoted phrase matches its words together and in order."""

    def test_phrase_is_narrower(self):
        """Unquoted, both titles match; quoted, only the one with the phrase."""
        self.fill_list(MITHAS_2021, MITHAS_2019)
        self.assertEqual(len(self.dois("transformation strategy")), 2)
        self.assertEqual(self.dois('"transformation strategy"'), ["10.1234/mithas21"])

    def test_phrase_with_a_word(self):
        """A phrase and a word together are ANDed."""
        self.fill_list(MITHAS_2021, MITHAS_2019)
        self.assertEqual(self.dois('"for digital" 2019'), ["10.1234/mithas19"])
        self.assertEqual(self.dois('"for digital" 2021'), [])

    def test_terms(self):
        """The search is split into phrases and words; a stray quote is ignored."""
        self.assertEqual(listsearch.terms('"Digital  Transformation" Mithas 2021'),
                         ["digital transformation", "mithas", "2021"])
        self.assertEqual(listsearch.terms('mithas "2021'), ["mithas", "2021"])
        self.assertEqual(listsearch.terms("   "), [])


class Criterion112EmptyResult(SearchTest):
    """112. No match says so; a blank search shows everything."""

    def test_no_matches(self):
        """Nothing shown, "Showing 0 of 2" and the no-match message."""
        self.fill_list(MITHAS_2021, OTHER_2021)
        self.assertEqual(self.dois("nonexistent"), [])
        self.assertEqual(mylist.showing_line(self.state, "nonexistent", "All"),
                         "Showing 0 of 2")
        self.assertEqual(mylist.NO_MATCHES, "No matches in your list")

    def test_blank_search(self):
        """A blank search and no filter: every item, and no "Showing" line."""
        self.fill_list(MITHAS_2021, OTHER_2021)
        self.assertEqual(len(self.dois("  ")), 2)
        self.assertIsNone(mylist.showing_line(self.state, "  ", "All"))

    def test_some_matches(self):
        """A search in use always shows the line."""
        self.fill_list(MITHAS_2021, OTHER_2021)
        self.assertEqual(mylist.showing_line(self.state, "mithas", "All"), "Showing 1 of 2")


class Criterion113StatusFilter(SearchTest):
    """113. Verified or Check only, combined with the search."""

    def test_filter(self):
        """NO_YEAR is the only Check item."""
        self.fill_list(MITHAS_2021, NO_YEAR, OTHER_2021)
        self.assertEqual(self.dois(status="Check"), ["10.1234/noyear"])
        self.assertEqual(self.dois(status="Verified"), ["10.1234/mithas21", "10.1234/other21"])
        self.assertEqual(len(self.dois(status="All")), 3)
        self.assertEqual(mylist.showing_line(self.state, "", "Check"), "Showing 1 of 3")

    def test_with_search(self):
        """A search and a status filter must both hold."""
        self.fill_list(MITHAS_2021, NO_YEAR, OTHER_2021)
        self.assertEqual(self.dois("lovelace", "Verified"), ["10.1234/other21"])
        self.assertEqual(self.dois("mithas", "Check"), [])


class Criterion114SortOrders(SearchTest):
    """114. Date added, Author A-Z, Year (newest first)."""

    def setUp(self):
        """Add the items out of every order: Mithas 2019, Müller 2019, no year, Lovelace 2021, Miller 2019."""
        super().setUp()
        self.fill_list(MITHAS_2019, MULLER, NO_YEAR, OTHER_2021, MILLER)

    def test_date_added(self):
        """The default is the order added."""
        self.assertEqual(self.dois(), ["10.1234/mithas19", "10.1234/muller", "10.1234/noyear",
                                       "10.1234/other21", "10.1234/miller"])

    def test_author(self):
        """First author A-Z, ignoring accents (Müller as Muller), then year."""
        self.assertEqual(self.dois(sort="Author A-Z"),
                         ["10.1234/other21", "10.1234/noyear", "10.1234/miller",
                          "10.1234/mithas19", "10.1234/muller"])

    def test_year(self):
        """Newest first, ties in the order added, no year last."""
        self.assertEqual(self.dois(sort="Year (newest first)"),
                         ["10.1234/other21", "10.1234/mithas19", "10.1234/muller",
                          "10.1234/miller", "10.1234/noyear"])

    def test_numbers_follow_the_items(self):
        """Sorting keeps each item's number in the full list."""
        shown = mylist.shown_items(self.state, "", "All", "Year (newest first)")
        self.assertEqual([number for number, _, _ in shown], [4, 1, 2, 5, 3])


class Criterion115ExportOnlyMatching(SearchTest):
    """115. The My list files hold the matching items only when the box is ticked."""

    def setUp(self):
        """Three items, two by Mithas."""
        super().setUp()
        self.fill_list(OTHER_2021, MITHAS_2021, MITHAS_2019)

    def csv_dois(self, **options):
        """The DOI column of my_list.csv."""
        text = mylist.list_csv(self.state, **options).decode("utf-8-sig")
        return [row[mylist.CSV_COLUMNS.index("DOI")] for row in list(csv.reader(io.StringIO(text)))[1:]]

    def test_unticked_is_the_full_list(self):
        """A search alone does not change the files."""
        options = {"query": "mithas", "status": "All", "only_matching": False}
        self.assertEqual(mylist.list_txt(self.state, **options), mylist.list_txt(self.state))
        self.assertEqual(len(self.csv_dois(**options)), 3)

    def test_ticked(self):
        """Only the matching items, still in bibliography order."""
        options = {"query": "mithas", "status": "All", "only_matching": True}
        self.assertEqual(self.csv_dois(**options), ["10.1234/mithas19", "10.1234/mithas21"])
        lines = mylist.list_txt(self.state, **options).decode("utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("Mithas" in line for line in lines))

    def test_ticked_with_status(self):
        """The status filter counts as part of "matching"."""
        self.assertEqual(self.csv_dois(query="", status="Check", only_matching=True), [])


class Criterion116ListUnchanged(SearchTest):
    """116. Searching, filtering and sorting never change the list."""

    def test_unchanged(self):
        """Items, order and count are the same after every kind of view."""
        self.fill_list(MITHAS_2019, NO_YEAR, OTHER_2021)
        before = [dict(item, entry=dict(item["entry"])) for item in self.state["my_list"]]
        for query, status, sort in [("mithas", "All", "Author A-Z"), ("zzz", "Check", "Date added"),
                                    ('"x', "Verified", "Year (newest first)")]:
            mylist.shown_items(self.state, query, status, sort)
            mylist.showing_line(self.state, query, status)
            mylist.list_csv(self.state, query=query, status=status, only_matching=True)
        self.assertEqual(self.state["my_list"], before)

    def test_remove_uses_full_numbers(self):
        """Remove on a filtered item removes that item, not the Nth shown."""
        self.fill_list(OTHER_2021, MITHAS_2021)
        [(number, _, _)] = mylist.shown_items(self.state, "mithas", "All", "Date added")
        mylist.remove_item(self.state, number)
        self.assertEqual([item["entry"]["doi"] for item in self.state["my_list"]], ["10.1234/other21"])


class Criterion117ListFilterCommand(SearchTest):
    """117. `list FILTER` in the chat, with the same matching."""

    def setUp(self):
        """Three references: Mithas 2021, Lovelace 2021, Mithas 2019."""
        super().setUp()
        self.send("\n".join(record["DOI"] for record in (MITHAS_2021, OTHER_2021, MITHAS_2019)))

    def test_parse(self):
        """The rest of the message is the filter; plain `list` is unchanged."""
        self.assertEqual(refchat.parse_command("list mithas 2021"), ("list", "mithas 2021"))
        self.assertEqual(refchat.parse_command('LIST "digital transformation"'),
                         ("list", '"digital transformation"'))
        self.assertEqual(refchat.parse_command("list"), ("list",))

    def test_filtered_reply(self):
        """Only the match, under its usual number, with the Showing line."""
        reply = self.send("list mithas 2021")
        self.assertTrue(reply.startswith('Showing 1 of 3 references matching "mithas 2021".'))
        self.assertIn("In export:", reply)
        self.assertNotIn("Lovelace", reply)
        self.assertEqual(self.state["history"][-1]["items"], [{"kind": "ref", "number": 1}])

    def test_keeps_usual_numbers(self):
        """The 2019 paper is still reference 3."""
        self.send("list 2019")
        self.assertEqual(self.state["history"][-1]["items"], [{"kind": "ref", "number": 3}])

    def test_no_match(self):
        """The no-match reply, with no buttons."""
        reply = self.send("list nonexistent")
        self.assertEqual(reply, 'No references match "nonexistent". Type `list` to see them all.')
        self.assertNotIn("items", self.state["history"][-1])

    def test_plain_list_unchanged(self):
        """Plain `list` shows all three, as before."""
        self.assertEqual(self.send("list"), refchat.list_references(self.state))
        self.assertEqual(len(self.state["history"][-1]["items"]), 3)

    def test_redrawn_after_style_change(self):
        """The Showing line survives the redraw in a new style."""
        self.send("list mithas")
        message = self.state["history"][-1]
        self.send("style harvard")
        drawn = refchat.render_reply(self.state, message)
        self.assertEqual(len(drawn), 2)
        self.assertTrue(drawn[0][0].startswith('Showing 2 of 3 references matching "mithas".'))

    def test_help(self):
        """`help` lists the command with an example."""
        self.assertIn("`list FILTER`", refchat.help_text())
        self.assertIn("`list mithas 2021`", refchat.help_text())


if __name__ == "__main__":
    unittest.main()
