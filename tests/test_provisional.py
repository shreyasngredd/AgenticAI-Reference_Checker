"""Tests for provisional results: the closest candidate of an unsure title search.

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 127-134), and the expected results come from section 3
("Provisional results"), not from reading the code. As in test_refchat.py,
urllib.request.urlopen is replaced by FakeCrossref, so no test uses the
network. The expected reference text is built by agent.py's existing
formatting from the candidate's Crossref record.

Run from the project folder:
    python -m unittest discover tests
"""

import csv
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent  # noqa: E402
import export  # noqa: E402
import mylist  # noqa: E402
import refchat  # noqa: E402
from test_refchat import MISSING_DOI, TITLE, ChatTest, crossref_item  # noqa: E402

BADGE = "Provisional: closest match, not verified"
PROVISIONAL_REASON = "provisional: built from the closest candidate, not verified"
FIRST, SECOND = "10.1234/a", "10.1234/b"


def candidate_entry(doi):
    """The entry agent.py builds from the search's record for `doi` (see search_returns)."""
    built = agent.format_citation(crossref_item(f"{TITLE}, part {doi}", doi))
    built.update({"id": "ref-x", "status": "auto", "input": TITLE})
    return built


class ProvisionalTest(ChatTest):
    """Helpers: the latest card item and the list buttons."""

    def card(self):
        """The first card item of the latest reply that has cards."""
        for message in reversed(self.state["history"]):
            if "items" in message:
                return message["items"][0]
        return None

    def list_buttons(self):
        """The Add to list buttons of the latest card, as [(label, enabled)]."""
        return [(label, enabled) for label, enabled, _ in mylist.list_buttons_for(self.state, self.card())]

    def press_list(self, button=0):
        """Press one Add to list button of the latest card."""
        target = mylist.list_buttons_for(self.state, self.card())[button][2]
        with mock.patch("urllib.request.urlopen", self.crossref.urlopen):
            return mylist.press_list_button(self.state, target)


class Criterion127CheckIsProvisional(ProvisionalTest):
    """127. A Check title lookup shows the badge, the score, the quoted reference and a Check citation."""

    CASES = {
        "weak match": [(FIRST, 0.8)],
        "several records": [(FIRST, 0.95), (SECOND, 0.94)],
        "too close to call": [(FIRST, 0.92), (SECOND, 0.9)],
    }

    def test_each_kind_of_check(self):
        """The same layout for every 7.1 Check outcome; status and reasons from agent.verify."""
        for name, scores in self.CASES.items():
            with self.subTest(case=name):
                self.state = refchat.new_state()
                self.search_returns(scores)
                reply = self.send(TITLE)
                self.assertEqual(self.status_of(1), "check")
                self.assertIn(BADGE, reply)
                self.assertIn(":orange-badge[", reply)
                self.assertIn(f"Match score: {scores[0][1]}", reply)
                self.assertIn("> " + agent.shown_text(candidate_entry(FIRST), "apa"), reply)
                self.assertIn("Status: **Check**", reply)
                _, reasons = refchat.ref_status(self.state["refs"][0])
                for reason in reasons:
                    self.assertIn(reason, reply)

    def test_citation_is_check(self):
        """The provisional citation is built from the candidate and always Check."""
        self.search_returns([(FIRST, 0.8)])
        self.send(TITLE)
        card = refchat.card_citation(self.state, self.card())
        self.assertEqual(card["parenthetical"], "(Lovelace, 2020)")
        self.assertEqual(card["narrative"], "Lovelace (2020)")
        self.assertIn(PROVISIONAL_REASON, card["reasons"])


class Criterion128NotFoundIsProvisional(ProvisionalTest):
    """128. A Not found title lookup with a closest candidate does the same, as Not found."""

    def test_not_found_with_candidate(self):
        """Similarity 0.5: Not found, but the closest candidate is shown, labelled."""
        self.search_returns([(FIRST, 0.5)])
        reply = self.send(TITLE)
        self.assertEqual(self.status_of(1), "not_found")
        self.assertIn(BADGE, reply)
        self.assertIn("Match score: 0.5", reply)
        self.assertIn("> " + agent.shown_text(candidate_entry(FIRST), "apa"), reply)
        self.assertIn("Status: **Not found**", reply)
        self.assertIn(PROVISIONAL_REASON, refchat.card_citation(self.state, self.card())["reasons"])


class Criterion129NoCandidateNoReference(ProvisionalTest):
    """129. No candidate at all: "No match found", what was typed, links; nothing built."""

    def check_no_match(self, reply, typed):
        """The no-match layout, with no reference, provisional text or citation."""
        self.assertIn("No match found", reply)
        self.assertIn(f"You typed: {typed}", reply)
        self.assertIn("Status: **Not found**", reply)
        self.assertIn("[Google Scholar](https://scholar.google.com/scholar?q=", reply)
        self.assertIn("[Google](https://www.google.com/search?q=", reply)
        self.assertNotIn(BADGE, reply)
        self.assertNotIn("[not resolved]", reply)
        self.assertNotIn("\n> ", reply)
        self.assertIsNone(refchat.card_citation(self.state, self.card()))

    def test_missing_doi(self):
        """A DOI Crossref has no record of."""
        self.check_no_match(self.send(MISSING_DOI), MISSING_DOI)

    def test_title_with_no_results(self):
        """A title search with no results at all."""
        self.crossref.search_items = []
        self.check_no_match(self.send(TITLE), TITLE)


class Criterion130OnlyCrossrefFields(ProvisionalTest):
    """130. The provisional reference is the candidate's record; the entry stays `not stated`; no extra request."""

    def test_fields(self):
        """One request (the title search), and the provisional fields are Crossref's."""
        self.search_returns([(FIRST, 0.8)])
        self.send(TITLE)
        self.assertEqual(len(self.crossref.urls), 1)
        ref = self.state["refs"][0]
        merged = refchat.merged_entry(ref)
        for field in ("title", "authors", "year", "journal", "doi"):
            self.assertEqual(merged[field], "not stated")
        provisional = refchat.provisional_entry(ref)
        expected = candidate_entry(FIRST)
        # Every field Crossref's record gives (format_citation), unchanged.
        for field in expected:
            if field not in ("id", "status", "input"):
                self.assertEqual(provisional[field], expected[field], field)

    def test_closest_is_not_editable(self):
        """The closest record lives in title_search, which no override can change."""
        self.search_returns([(FIRST, 0.8)])
        self.send(TITLE)
        self.assertNotIn("title_search", agent.CITATION_FIELDS)
        self.assertEqual(self.state["refs"][0]["entry"]["title_search"]["closest"]["doi"], FIRST)


class Criterion131NeverVerified(ProvisionalTest):
    """131. A provisional card is never Verified; a Verified card never has the badge."""

    def test_both_ways(self):
        """Even a complete candidate record stays Check, and LeCun has no badge."""
        self.search_returns([(FIRST, 0.8)])
        reply = self.send(TITLE)
        self.assertNotIn("Verified against Crossref only", reply)
        self.assertNotEqual(self.status_of(1), "verified")
        verified = self.send("10.1038/nature14539")
        self.assertIn("Verified against Crossref only", verified)
        self.assertNotIn(BADGE, verified)
        self.assertNotIn(":orange-badge[", verified)


class Criterion132AddProvisionalToList(ProvisionalTest):
    """132. Add to list on a provisional card: no request, status kept, marked provisional."""

    def test_check(self):
        """A Check provisional: one Add to list, then candidates from 2."""
        self.search_returns([(FIRST, 0.8), (SECOND, 0.78)])
        self.send(TITLE)
        self.assertEqual(self.list_buttons(), [("Add to list", True), ("Add candidate 2 to list", True)])
        self.crossref.urls = []
        self.press_list()
        self.assertEqual(self.crossref.urls, [])
        item = self.state["my_list"][0]
        self.assertEqual((item["status"], item["provisional"]), ("check", True))
        text = mylist.list_txt(self.state).decode("utf-8")
        self.assertTrue(text.startswith("[CHECK] (provisional) Lovelace, A. (2020)."))
        header, row = list(csv.reader(io.StringIO(mylist.list_csv(self.state).decode("utf-8-sig"))))
        row = dict(zip(header, row))
        self.assertEqual((row["status"], row["provisional"]), ("Check", "yes"))
        self.assertEqual(row["parenthetical citation"], "(Lovelace, 2020)")
        self.assertEqual(self.list_buttons()[0], ("Already in list", False))

    def test_not_found(self):
        """A Not found provisional keeps Not found."""
        self.search_returns([(FIRST, 0.5)])
        self.send(TITLE)
        self.assertEqual(self.list_buttons(), [("Add to list", True)])
        self.press_list()
        self.assertEqual(self.state["my_list"][0]["status"], "not_found")
        text = mylist.list_txt(self.state).decode("utf-8")
        self.assertTrue(text.startswith("[NOT FOUND] (provisional) "))
        self.assertEqual(mylist.shown_items(self.state)[0][2], "Not found")
        self.assertEqual([n for n, _, _ in mylist.shown_items(self.state, status="Not found")], [1])


class Criterion133AcceptProvisional(ProvisionalTest):
    """133. A provisional Check can be accepted and is exported marked; a Not found one can't."""

    def test_accept_check(self):
        """The .txt prefix and the .csv provisional and match score columns."""
        self.search_returns([(FIRST, 0.8)])
        self.send(TITLE)
        self.assertTrue(self.send("accept 1").startswith("Reference 1 confirmed by you."))
        text = export.export_txt(self.state).decode("utf-8")
        self.assertIn("[CHECK] (provisional) Lovelace, A. (2020).", text)
        header, row = list(csv.reader(io.StringIO(export.export_csv(self.state).decode("utf-8-sig"))))
        row = dict(zip(header, row))
        self.assertEqual((row["status"], row["confirmed"]), ("Check", "yes"))
        self.assertEqual((row["provisional"], row["match score"]), ("yes", "0.8"))
        self.assertEqual(row["DOI"], FIRST)
        self.assertEqual(row["parenthetical citation"], "(Lovelace, 2020)")

    def test_not_found_cannot_be_accepted(self):
        """Not found stays out of the export."""
        self.search_returns([(FIRST, 0.5)])
        self.send(TITLE)
        self.assertIn("was not found, so it can't be confirmed", self.send("accept 1"))
        self.assertIn("No references to export yet.", export.export_txt(self.state).decode("utf-8"))

    def test_ordinary_rows_are_not_provisional(self):
        """A Verified reference: provisional no, match score not stated."""
        self.send("10.1038/nature14539")
        header, row = list(csv.reader(io.StringIO(export.export_csv(self.state).decode("utf-8-sig"))))
        row = dict(zip(header, row))
        self.assertEqual((row["provisional"], row["match score"]), ("no", "not stated"))
        self.assertNotIn("[CHECK]", export.export_txt(self.state).decode("utf-8"))


class Criterion134ProvisionalFollowsStyle(ProvisionalTest):
    """134. After a style change, provisional cards are redrawn in that style."""

    def test_redraw(self):
        """The drawn block has the Harvard text, then the Chicago text."""
        self.search_returns([(FIRST, 0.8)])
        self.send(TITLE)
        message = self.state["history"][-1]
        for style in ("harvard", "chicago"):
            with self.subTest(style=style):
                self.send(f"style {style}")
                drawn = refchat.render_reply(self.state, message)[0][0]
                self.assertIn("> " + agent.shown_text(candidate_entry(FIRST), style), drawn)
                self.assertIn(BADGE, drawn)


if __name__ == "__main__":
    unittest.main()
