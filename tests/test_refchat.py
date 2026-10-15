"""Tests for the Streamlit reference chat (refchat.py).

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 1-17 and 21-33), and the expected results come from the spec's wording, not from
reading the code. No test uses the network: urllib.request.urlopen is
replaced by FakeCrossref, which answers like Crossref and records every URL
requested. The real lookup, formatting and status code in agent.py runs.

Run from the project folder:
    python -m unittest discover tests
"""

import copy
import io
import json
import sys
import urllib.error
import urllib.parse
import unittest
from pathlib import Path
from unittest import mock

# Let the tests import agent.py and refchat.py from the project folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent  # noqa: E402
import refchat  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Recorded Crossref response for 10.1038/nature14539 (criterion 1).
LECUN = json.loads((FIXTURES / "crossref_nature14539.json").read_text(encoding="utf-8"))["message"]
LECUN_APA = (
    "LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. *Nature*, *521*(7553), "
    "436–444. https://doi.org/10.1038/nature14539"
)
MISSING_DOI = "10.9999/definitely-not-real-xyz"  # Crossref answers 404.
TITLE = "A study of something"  # A title the student types.

# The two fixed reasons for `find` results and added references (section 3).
RESULT_REASON = "search result, not verified: pick the right one"
ADDED_REASON = "added from a search; paste its DOI to verify"
# crossref_item(TITLE, "10.1234/a") in APA 7, by the rules of section 3.
LOVELACE_APA = (
    "Lovelace, A. (2020). A study of something. *Journal of Tests*, *1*(2), 3–4. "
    "https://doi.org/10.1234/a"
)


def crossref_item(title, doi):
    """A minimal, complete Crossref journal article."""
    return {
        "type": "journal-article",
        "title": [title],
        "DOI": doi,
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "issued": {"date-parts": [[2020]]},
        "container-title": ["Journal of Tests"],
        "volume": "1",
        "issue": "2",
        "page": "3-4",
    }


class FakeCrossref:
    """Stands in for urllib.request.urlopen and records each URL requested.

    works:        {doi: Crossref record} for DOI lookups (others get HTTP 404).
    search_items: the records a title search returns.
    author_items: the records an author-and-year search (`find`) returns.
    failure:      an exception to raise for every request, or "bad_json".
    """

    def __init__(self, works=None, search_items=(), failure=None):
        """Store what to answer with."""
        self.works = {doi.lower(): record for doi, record in (works or {}).items()}
        self.search_items = list(search_items)
        self.author_items = []
        self.failure = failure
        self.urls = []

    def urlopen(self, request, timeout=None):
        """Answer one request the way Crossref would."""
        url = request.full_url
        self.urls.append(url)
        parts = urllib.parse.urlsplit(url)
        if parts.netloc != "api.crossref.org":
            raise urllib.error.URLError("only Crossref is faked")
        if self.failure == "bad_json":
            return io.BytesIO(b"<html>Service down</html>")
        if self.failure:
            raise self.failure
        if "query.author" in urllib.parse.parse_qs(parts.query):  # `find`.
            body = {"message": {"items": self.author_items}}
        elif parts.query:  # /works?query.bibliographic=...: a title search.
            body = {"message": {"items": self.search_items}}
        else:  # /works/<doi>: a DOI lookup.
            doi = urllib.parse.unquote(parts.path[len("/works/"):]).lower()
            if doi not in self.works:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())
            body = {"message": self.works[doi]}
        return io.BytesIO(json.dumps(body).encode("utf-8"))


class ChatTest(unittest.TestCase):
    """Shared set-up: a fresh chat and a fake Crossref for every test."""

    def setUp(self):
        """Start each test with an empty chat and the LeCun record on Crossref."""
        self.state = refchat.new_state()
        self.crossref = FakeCrossref(works={"10.1038/nature14539": LECUN})
        self.title_scores = {}  # {title: similarity} when a test sets scores.

    def send(self, text):
        """Send one message with the fake Crossref in place; return the reply."""
        patches = [mock.patch("urllib.request.urlopen", self.crossref.urlopen)]
        if self.title_scores:
            # Give each search result exactly the similarity the test chose.
            patches.append(mock.patch.object(agent, "title_similarity", lambda typed, found: self.title_scores[found]))
        with patches[0]:
            if len(patches) == 1:
                return refchat.handle_message(self.state, text)
            with patches[1]:
                return refchat.handle_message(self.state, text)

    def search_returns(self, scores):
        """Make the next title search return one record per (doi, similarity)."""
        self.crossref.search_items = [crossref_item(f"{TITLE}, part {doi}", doi) for doi, _ in scores]
        self.title_scores = {f"{TITLE}, part {doi}": score for doi, score in scores}

    def status_of(self, number):
        """The status ("verified", "check" or "not_found") of reference `number`."""
        return refchat.ref_status(self.state["refs"][number - 1])[0]


class Criterion01DoiGivesVerifiedApaReference(ChatTest):
    """1. 10.1038/nature14539 gives Verified, the Crossref-only line, links and the exact APA text."""

    def test_doi_reply(self):
        """The reply has the exact reference, the status, the note and both links."""
        reply = self.send("10.1038/nature14539")
        self.assertIn(LECUN_APA, reply)
        self.assertIn("Status: **Verified**", reply)
        self.assertIn("Verified against Crossref only", reply)
        self.assertIn("https://scholar.google.com/scholar?q=Deep+learning+LeCun", reply)
        self.assertIn("https://www.google.com/search?q=Deep+learning+LeCun", reply)

    def test_doi_link_form_is_accepted(self):
        """The same DOI pasted as a doi.org link gives the same reference."""
        reply = self.send("https://doi.org/10.1038/nature14539")
        self.assertIn(LECUN_APA, reply)


class Criterion02OneReplyPerLineInOrder(ChatTest):
    """2. Several lines give one numbered reply block per non-blank line, in order."""

    def test_three_lines(self):
        """DOI, missing DOI, title: blocks 1, 2, 3 in that order; blank lines skipped."""
        self.search_returns([("10.1234/a", 0.2)])
        reply = self.send(f"10.1038/nature14539\n\n{MISSING_DOI}\n{TITLE}\n")
        blocks = reply.split("\n\n---\n\n")
        self.assertEqual(len(blocks), 3)
        self.assertTrue(blocks[0].startswith("**1.** LeCun"))
        self.assertTrue(blocks[1].startswith(f"**2.** {MISSING_DOI}"))
        self.assertTrue(blocks[2].startswith(f"**3.** {TITLE}"))
        self.assertEqual(len(self.state["refs"]), 3)


class Criterion03VerifiedDefinition(ChatTest):
    """3. Verified = DOI resolved in Crossref, or title match above threshold
    with a clear lead over the runner-up (at least 0.9, runner-up more than
    0.05 below). Everything else is Check or Not found."""

    def test_resolved_doi_is_verified(self):
        """A DOI Crossref resolves, with nothing to check."""
        self.send("10.1038/nature14539")
        self.assertEqual(self.status_of(1), "verified")

    def test_clear_title_match_is_verified(self):
        """Best title 0.97, runner-up far below."""
        self.search_returns([("10.1234/a", 0.97), ("10.1234/b", 0.30)])
        reply = self.send(TITLE)
        self.assertEqual(self.status_of(1), "verified")
        self.assertIn("Verified against Crossref only", reply)

    def test_title_exactly_at_threshold_with_lead_is_verified(self):
        """0.9 counts as above the threshold; runner-up 0.84 is more than 0.05 below."""
        self.search_returns([("10.1234/a", 0.90), ("10.1234/b", 0.84)])
        self.send(TITLE)
        self.assertEqual(self.status_of(1), "verified")

    def test_runner_up_within_margin_is_check(self):
        """No clear lead: runner-up exactly 0.05 below the best."""
        self.search_returns([("10.1234/a", 0.92), ("10.1234/b", 0.87)])
        reply = self.send(TITLE)
        self.assertEqual(self.status_of(1), "check")
        self.assertNotIn("Verified against Crossref only", reply)

    def test_title_below_threshold_is_check(self):
        """0.89 is below the 0.9 threshold: a weak match, not Verified."""
        self.search_returns([("10.1234/a", 0.89)])
        self.send(TITLE)
        self.assertEqual(self.status_of(1), "check")

    def test_several_records_at_threshold_is_check(self):
        """Two different DOIs at 0.9 or more: no single match."""
        self.search_returns([("10.1234/a", 0.99), ("10.1234/b", 0.95)])
        self.send(TITLE)
        self.assertEqual(self.status_of(1), "check")

    def test_unresolved_doi_is_not_found(self):
        """A DOI Crossref has no record of."""
        self.send(MISSING_DOI)
        self.assertEqual(self.status_of(1), "not_found")

    def test_verified_does_not_need_other_sources(self):
        """No OpenAlex or Semantic Scholar answer is needed (or asked for)."""
        self.send("10.1038/nature14539")
        _, reasons = refchat.ref_status(self.state["refs"][0])
        self.assertEqual(reasons, [])


class Criterion04ResolvedButIncompleteIsCheck(ChatTest):
    """4. A resolved DOI with something to check is Check with the reason."""

    def test_missing_volume(self):
        """Crossref's record has no volume: Check, naming the volume."""
        record = dict(LECUN)
        del record["volume"]
        self.crossref.works["10.1038/nature14539"] = record
        reply = self.send("10.1038/nature14539")
        self.assertIn("Status: **Check**", reply)
        self.assertIn("Missing volume", reply)
        self.assertNotIn("Verified against Crossref only", reply)


class Criterion05MissingDoiIsNotFound(ChatTest):
    """5. A DOI Crossref answers with 404 gives Not found with its reason."""

    def test_404(self):
        """Not found, with Crossref's "no record" reason."""
        reply = self.send(MISSING_DOI)
        self.assertIn("Status: **Not found**", reply)
        self.assertIn("Crossref has no record for DOI", reply)


class Criterion06CheckAndNotFoundShowReasons(ChatTest):
    """6. Every Check and Not found reply shows at least one reason."""

    def test_each_case_has_a_reason(self):
        """Weak match, too close, several records, nothing close, missing DOI."""
        cases = [
            [("10.1234/a", 0.80)],
            [("10.1234/a", 0.92), ("10.1234/b", 0.88)],
            [("10.1234/a", 0.95), ("10.1234/b", 0.94)],
            [("10.1234/a", 0.10)],
        ]
        replies = []
        for scores in cases:
            self.search_returns(scores)
            replies.append(self.send(TITLE))
        replies.append(self.send(MISSING_DOI))
        for reply in replies:
            with self.subTest(reply=reply[:60]):
                status_and_rest = reply.split("Status: ", 1)[1]
                self.assertTrue(status_and_rest.startswith(("**Check**", "**Not found**")))
                self.assertIn("\n- ", status_and_rest)  # At least one reason line.


class Criterion07Style(ChatTest):
    """7. APA 7 until `style` is sent; then later replies and `list` use the new style."""

    def test_apa_is_the_default(self):
        """A new chat is in APA 7."""
        self.assertEqual(self.state["style"], "apa")
        self.assertIn(LECUN_APA, self.send("10.1038/nature14539"))

    def test_chicago_and_harvard(self):
        """After `style X`, lookups and `list` are in style X, not APA."""
        citation = agent.format_citation(LECUN)
        for style in ("chicago", "harvard"):
            with self.subTest(style=style):
                self.state = refchat.new_state()
                self.assertEqual(self.send(f"style {style}"), f"Style set to {agent.STYLES[style]}.")
                reply = self.send("10.1038/nature14539")
                self.assertIn(agent.format_reference(citation, style), reply)
                self.assertNotIn(LECUN_APA, reply)
                self.assertIn(agent.format_reference(citation, style), self.send("list"))


class Criterion08List(ChatTest):
    """8. `list` shows every reference so far, numbered from 1, in the current style."""

    def test_empty_list(self):
        """No references yet."""
        self.assertEqual(self.send("list"), "No references yet.")

    def test_numbered_list(self):
        """References from two messages are numbered 1 and 2."""
        self.send("10.1038/nature14539")
        self.send(MISSING_DOI)
        reply = self.send("list")
        self.assertIn("**1.** " + LECUN_APA, reply)
        self.assertIn(f"**2.** {MISSING_DOI}", reply)


class Criterion09Edit(ChatTest):
    """9. `edit N field value` changes the field, re-formats and re-checks, and it lasts."""

    def test_edit_year_lasts_through_list_and_style_change(self):
        """The new year shows straight away, in `list`, and in another style."""
        self.send("10.1038/nature14539")
        reply = self.send("edit 1 year 2016")
        self.assertIn("LeCun, Y., Bengio, Y., & Hinton, G. (2016).", reply)
        self.assertIn("(2016)", self.send("list"))
        self.send("style harvard")
        self.assertIn("2016", self.send("list"))
        self.assertNotIn("2015", self.send("list").split("Status:")[0])

    def test_status_is_worked_out_again(self):
        """Clearing the volume turns Verified into Check, naming the volume."""
        self.send("10.1038/nature14539")
        reply = self.send("edit 1 volume not stated")
        self.assertIn("Status: **Check**", reply)
        self.assertIn("Missing volume", reply)

    def test_value_can_contain_spaces(self):
        """Authors are typed as "Family, Given; Family, Given"."""
        self.send("10.1038/nature14539")
        reply = self.send("edit 1 authors LeCun, Yann; Hinton, Geoffrey")
        self.assertIn("LeCun, Y., & Hinton, G. (2015).", reply)


class Criterion10EditNeverMakesVerified(ChatTest):
    """10. An edit never makes an entry Verified."""

    def test_not_found_stays_not_found(self):
        """Typing in every field of a missing DOI doesn't verify it."""
        self.send(MISSING_DOI)
        for message in (
            "edit 1 title Deep learning",
            "edit 1 authors LeCun, Yann",
            "edit 1 year 2015",
            "edit 1 journal Nature",
            "edit 1 volume 521",
            "edit 1 pages 436-444",
        ):
            self.send(message)
        self.assertEqual(self.status_of(1), "not_found")
        self.assertNotIn("Verified against Crossref only", self.send("list"))

    def test_check_stays_check(self):
        """A too-close-to-call title search stays Check after a title edit."""
        self.search_returns([("10.1234/a", 0.95), ("10.1234/b", 0.94)])
        self.send(TITLE)
        self.send(f"edit 1 title {TITLE}, part 10.1234/a")
        self.assertNotEqual(self.status_of(1), "verified")


class Criterion11BadEditChangesNothing(ChatTest):
    """11. `edit` with a bad N, field or value gives a reason and changes nothing."""

    def test_bad_edits(self):
        """Each bad edit says why; the references are exactly as before."""
        self.send("10.1038/nature14539")
        before = copy.deepcopy(self.state["refs"])
        for message, reason in (
            ("edit 5 year 2016", "There is no reference 5"),
            ("edit 0 year 2016", "There is no reference 0"),
            ("edit 1 colour blue", "Unknown field 'colour'"),
            ("edit 1 type novel", "Unknown type 'novel'"),
        ):
            with self.subTest(message=message):
                self.assertIn(reason, self.send(message))
                self.assertEqual(self.state["refs"], before)


class Criterion12Clear(ChatTest):
    """12. `clear` forgets all references and history and goes back to APA 7."""

    def test_clear(self):
        """After clear: no references, only the "Cleared." reply, APA style."""
        self.send("style harvard")
        self.send("10.1038/nature14539")
        self.assertEqual(self.send("clear"), "Cleared.")
        self.assertEqual(self.state["refs"], [])
        self.assertEqual(self.state["style"], "apa")
        self.assertEqual(self.state["history"], [{"role": "assistant", "content": "Cleared."}])
        self.assertEqual(self.send("list"), "No references yet.")

    def test_clear_forgets_the_latest_search(self):
        """After clear, `add 1` has nothing to add."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        self.send("clear")
        self.assertEqual(self.send("add 1"), "There are no search results. Use `find` first.")


class Criterion13Help(ChatTest):
    """13. `help` lists every command, what Verified means, and the session note."""

    def test_help(self):
        """Every command, the definition, and "lost when you reload"."""
        reply = self.send("help")
        for command in ("style apa", "style chicago", "style harvard", "list", "edit N field value",
                        "find SURNAME YEAR [topic words]", "add N", "clear", "help"):
            self.assertIn(command, reply)
        self.assertIn("DOI resolved in Crossref, or title match above threshold "
                      "with a clear lead over the runner-up", reply)
        self.assertIn("lost when you reload the page", reply)


class Criterion14UnknownInputGetsShortHelp(ChatTest):
    """14. Wrong command arguments or one unknown word: short help, no request."""

    def test_short_help(self):
        """Each message gets the short help message and Crossref is never asked."""
        for message in ("style mla", "list 2", "help me", "clear all", "edit two year 2015",
                        "edit 1 year", "Edit", "hello", "list\nlist"):
            with self.subTest(message=message):
                reply = self.send(message)
                self.assertTrue(reply.startswith("I didn't understand that."))
                self.assertIn("`help`", reply)
        self.assertEqual(self.crossref.urls, [])
        self.assertEqual(self.state["refs"], [])

    def test_parse_command(self):
        """parse_command works without Streamlit or the network."""
        self.assertEqual(refchat.parse_command("STYLE Chicago"), ("style", "chicago"))
        self.assertEqual(refchat.parse_command(" list "), ("list",))
        self.assertEqual(refchat.parse_command("edit 2 title A new title"), ("edit", 2, "title", "A new title"))
        self.assertEqual(refchat.parse_command("10.1038/nature14539"), ("lookup", ["10.1038/nature14539"]))
        self.assertEqual(refchat.parse_command("Deep learning\n\n 10.1/x "), ("lookup", ["Deep learning", "10.1/x"]))
        self.assertEqual(refchat.parse_command("hello"), ("unknown",))
        self.assertEqual(refchat.parse_command("   "), ("unknown",))


class Criterion15CrossrefUnavailable(ChatTest):
    """15. Crossref unreachable: Unavailable with its reason, no crash, next message works."""

    FAILURES = {
        "network error": urllib.error.URLError("no route to host"),
        "timeout": TimeoutError("timed out"),
        "HTTP 429": urllib.error.HTTPError("https://api.crossref.org", 429, "Too Many Requests", {}, io.BytesIO()),
        "HTTP 500": urllib.error.HTTPError("https://api.crossref.org", 500, "Server Error", {}, io.BytesIO()),
        "invalid JSON": "bad_json",
    }

    @classmethod
    def tearDownClass(cls):
        """Close the HTTP errors' (empty) bodies, so Python doesn't warn about them."""
        for failure in cls.FAILURES.values():
            if isinstance(failure, urllib.error.HTTPError):
                failure.close()

    def test_each_failure(self):
        """DOI and title lookups both show Unavailable, then a normal lookup works."""
        for name, failure in self.FAILURES.items():
            for line in ("10.1038/nature14539", TITLE):
                with self.subTest(failure=name, line=line):
                    self.state = refchat.new_state()
                    self.crossref.failure = failure
                    reply = self.send(line)
                    self.assertIn("Status: **Unavailable**", reply)
                    self.assertIn("Crossref is unavailable right now. Try again in a minute.", reply)
                    self.assertEqual(self.state["refs"], [])  # Not kept, so no number.
                    # Crossref is back: the next message is answered normally.
                    self.crossref.failure = None
                    self.assertIn(LECUN_APA, self.send("10.1038/nature14539"))


class Criterion16CrossrefOnly(ChatTest):
    """16. The chat requests only api.crossref.org."""

    def test_only_crossref_is_requested(self):
        """DOI and title lookups, list, edit and style: every URL is Crossref's."""
        self.search_returns([("10.1234/a", 0.97)])
        self.send(f"10.1038/nature14539\n{TITLE}\n{MISSING_DOI}")
        self.send("list")
        self.send("edit 1 year 2016")
        self.send("style chicago")
        self.assertEqual(len(self.crossref.urls), 3)
        for url in self.crossref.urls:
            self.assertEqual(urllib.parse.urlsplit(url).netloc, "api.crossref.org")

    def test_find_asks_only_crossref_and_add_asks_nothing(self):
        """`find` makes one Crossref request; `add` makes none."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        self.assertEqual(len(self.crossref.urls), 1)
        self.assertEqual(urllib.parse.urlsplit(self.crossref.urls[0]).netloc, "api.crossref.org")
        self.send("add 1")
        self.assertEqual(len(self.crossref.urls), 1)


class Criterion17NoFilesWritten(ChatTest):
    """17. The chat writes no files."""

    def test_nothing_saved(self):
        """No JSON saved, no reference list written, for every kind of message."""
        with mock.patch.object(agent, "save_json") as save_json, \
                mock.patch.object(agent, "write_output") as write_output, \
                mock.patch.object(Path, "write_text") as write_text:
            self.crossref.author_items = [LECUN]
            for message in ("10.1038/nature14539", "edit 1 year 2016", "style harvard", "list",
                            "find LeCun 2015", "add 1", "help", "clear"):
                self.send(message)
        save_json.assert_not_called()
        write_output.assert_not_called()
        write_text.assert_not_called()



# --- Author-and-year search: `find` and `add` (criteria 21-33) ---

class FindTest(ChatTest):
    """Shared helpers for the `find` and `add` tests."""

    def last_query(self):
        """The query parameters of the last request, as {name: [values]}."""
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.crossref.urls[-1]).query)


class Criterion21FindRequest(FindTest):
    """21. `find` sends one request with author, year filter, 5 rows, and topic only if given."""

    def test_without_topic(self):
        """Author and year only: no query.bibliographic."""
        self.send("find Smith 2019")
        self.assertEqual(len(self.crossref.urls), 1)
        self.assertTrue(self.crossref.urls[0].startswith("https://api.crossref.org/works?"))
        query = self.last_query()
        self.assertEqual(query["query.author"], ["Smith"])
        self.assertEqual(query["filter"], ["from-pub-date:2019,until-pub-date:2019"])
        self.assertEqual(query["rows"], ["5"])
        self.assertNotIn("query.bibliographic", query)

    def test_with_topic(self):
        """Topic words go in query.bibliographic."""
        self.send("find Smith 2019 deep learning")
        query = self.last_query()
        self.assertEqual(query["query.author"], ["Smith"])
        self.assertEqual(query["query.bibliographic"], ["deep learning"])

    def test_multi_word_surname(self):
        """Every word before the year is the surname."""
        self.send("find van der Berg 2019")
        self.assertEqual(self.last_query()["query.author"], ["van der Berg"])


class Criterion22ResultBlocks(FindTest):
    """22. Results: numbered, "APA 7 preview", APA text with DOI, Check with the reason, links."""

    def test_two_results(self):
        """Each block has every part, in order, numbered 1 and 2."""
        self.crossref.author_items = [LECUN, crossref_item(TITLE, "10.1234/a")]
        blocks = self.send("find LeCun 2015").split("\n\n---\n\n")
        self.assertEqual(len(blocks), 2)
        for number, (block, text, search) in enumerate([
            (blocks[0], LECUN_APA, "Deep+learning+LeCun"),
            (blocks[1], LOVELACE_APA, "A+study+of+something+Lovelace"),
        ], start=1):
            with self.subTest(result=number):
                self.assertTrue(block.startswith(f"**Result {number} (APA 7 preview)**\n\n{text}\n\n"))
                self.assertIn("Status: **Check**", block)
                self.assertIn(f"- {RESULT_REASON}", block)
                self.assertIn(f"https://scholar.google.com/scholar?q={search}", block)
                self.assertIn(f"https://www.google.com/search?q={search}", block)


class Criterion23ResultsAlwaysApa(FindTest):
    """23. Results are in APA 7 whatever the current style."""

    def test_after_style_change(self):
        """After `style chicago` or `style harvard`, the result is still the APA text."""
        self.crossref.author_items = [LECUN]
        for style in ("chicago", "harvard"):
            with self.subTest(style=style):
                self.send(f"style {style}")
                reply = self.send("find LeCun 2015")
                self.assertIn("Result 1 (APA 7 preview)", reply)
                self.assertIn(LECUN_APA, reply)


class Criterion24AtMostFiveResults(FindTest):
    """24. At most 5 results are shown, even if Crossref returns more."""

    def test_seven_returned(self):
        """Crossref sends 7: results 1-5 are shown, 6 and 7 are not."""
        self.crossref.author_items = [crossref_item(f"Paper {n}", f"10.1234/{n}") for n in range(1, 8)]
        reply = self.send("find Lovelace 2020")
        self.assertIn("Result 5 (APA 7 preview)", reply)
        self.assertNotIn("Result 6", reply)
        self.assertIn("There is no result 6", self.send("add 6"))


class Criterion25ResultNeverVerified(FindTest):
    """25. A search result is never Verified, even a record that is Verified by DOI."""

    def test_complete_record(self):
        """The LeCun record is Verified when its DOI is pasted, but not as a result."""
        self.crossref.author_items = [LECUN]
        reply = self.send("find LeCun 2015")
        self.assertNotIn("Verified", reply)
        self.assertIn("Status: **Check**", reply)
        self.assertIn("Status: **Verified**", self.send("10.1038/nature14539"))


class Criterion26FindAddsNothing(FindTest):
    """26. `find` adds nothing to the references."""

    def test_list_unchanged(self):
        """With and without earlier references, `list` is the same after `find`."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        self.assertEqual(self.send("list"), "No references yet.")
        self.send(MISSING_DOI)
        before = self.send("list")
        self.send("find LeCun 2015")
        self.assertEqual(self.send("list"), before)
        self.assertEqual(len(self.state["refs"]), 1)


class Criterion27AddAppends(FindTest):
    """27. `add N` appends result N, says its number, includes the DOI; a new find replaces the old."""

    def test_add_second_result(self):
        """With one reference already, result 2 becomes reference 2, with its DOI link."""
        self.send(MISSING_DOI)
        self.crossref.author_items = [LECUN, crossref_item(TITLE, "10.1234/a")]
        self.send("find Lovelace 2020")
        reply = self.send("add 2")
        self.assertTrue(reply.startswith("Added result 2 as reference 2."))
        self.assertIn(f"**2.** {LOVELACE_APA}", reply)
        self.assertIn("https://doi.org/10.1234/a", reply)
        self.assertEqual(len(self.state["refs"]), 2)

    def test_later_find_replaces_the_latest_search(self):
        """After a second find, `add 1` adds the second search's first result."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        self.crossref.author_items = [crossref_item(TITLE, "10.1234/a")]
        self.send("find Lovelace 2020")
        self.assertIn(LOVELACE_APA, self.send("add 1"))


class Criterion28AddedStaysCheck(FindTest):
    """28. An added reference is Check with the "added" reason, after edits and style changes too."""

    def test_reason_and_status(self):
        """Check with the reason straight away, after edits, and after `style`."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        reply = self.send("add 1")
        self.assertIn("Status: **Check**", reply)
        self.assertIn(f"- {ADDED_REASON}", reply)
        self.assertNotIn(RESULT_REASON, reply)
        for message in ("edit 1 title Deep learning", "edit 1 year 2015", "style harvard", "list"):
            with self.subTest(message=message):
                reply = self.send(message)
                if message != "style harvard":
                    self.assertIn(ADDED_REASON, reply)
                self.assertNotIn("Verified", reply)
                self.assertEqual(self.status_of(1), "check")


class Criterion29AddedFollowsStyle(FindTest):
    """29. An added reference follows the current style, not APA."""

    def test_chicago_and_harvard(self):
        """The `add` reply and `list` show the reference in the current style."""
        self.crossref.author_items = [LECUN]
        citation = agent.format_citation(LECUN)
        for style in ("chicago", "harvard"):
            with self.subTest(style=style):
                self.state = refchat.new_state()
                self.send(f"style {style}")
                self.send("find LeCun 2015")
                expected = agent.format_reference(citation, style)
                for reply in (self.send("add 1"), self.send("list")):
                    self.assertIn(f"**1.** {expected}", reply)
                    self.assertNotIn(LECUN_APA, reply)
                    self.assertIn("https://doi.org/10.1038/nature14539", reply)

    def test_style_change_after_add(self):
        """Added in APA, then `style chicago`: `list` shows Chicago."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        self.assertIn(LECUN_APA, self.send("add 1"))
        self.send("style chicago")
        reply = self.send("list")
        self.assertIn("“Deep learning.”", reply)
        self.assertNotIn(LECUN_APA, reply)


class Criterion30BadAddChangesNothing(FindTest):
    """30. `add N` with no search, or N out of range, gives a reason and changes nothing."""

    def test_no_search_yet(self):
        """No `find` yet."""
        self.assertEqual(self.send("add 1"), "There are no search results. Use `find` first.")
        self.assertEqual(self.state["refs"], [])

    def test_out_of_range(self):
        """0 and 3 with two results: the reason, and nothing changes."""
        self.crossref.author_items = [LECUN, crossref_item(TITLE, "10.1234/a")]
        self.send("find LeCun 2015")
        before = copy.deepcopy((self.state["refs"], self.state["last_search"]))
        for number in (0, 3):
            with self.subTest(number=number):
                self.assertEqual(self.send(f"add {number}"),
                                 f"There is no result {number}. The latest search has 2 result(s).")
                self.assertEqual((self.state["refs"], self.state["last_search"]), before)


class Criterion31BadFindOrAddGetsShortHelp(FindTest):
    """31. Bad `find` or `add`: short help, no request; parse_command reads good ones."""

    def test_short_help(self):
        """No surname, no year, a year that isn't four digits, or `add` without a number."""
        for message in ("find", "find smith", "find 2019", "find smith 15", "find smith 20x5",
                        "find smith 201", "find 12 2019", "add", "add two", "add 1 2",
                        "find smith 2019\nfind jones 2020"):
            with self.subTest(message=message):
                self.assertTrue(self.send(message).startswith("I didn't understand that."))
        self.assertEqual(self.crossref.urls, [])
        self.assertEqual(self.state["refs"], [])

    def test_parse_command(self):
        """parse_command works without Streamlit or the network."""
        self.assertEqual(refchat.parse_command("find Smith 2019"), ("find", "Smith", 2019, ""))
        self.assertEqual(refchat.parse_command("FIND smith 2019 deep  learning"),
                         ("find", "smith", 2019, "deep learning"))
        self.assertEqual(refchat.parse_command("find van der Berg 2019 trust"),
                         ("find", "van der Berg", 2019, "trust"))
        self.assertEqual(refchat.parse_command("add 3"), ("add", 3))
        self.assertEqual(refchat.parse_command("find smith"), ("unknown",))
        self.assertEqual(refchat.parse_command("add x"), ("unknown",))


class Criterion32ZeroResults(FindTest):
    """32. Zero results says so plainly."""

    def test_no_results(self):
        """The plain message, with the topic words when given, and nothing to add."""
        self.assertEqual(self.send("find Smith 2019"), "Crossref found no results for Smith 2019.")
        self.assertEqual(self.send("find Smith 2019 deep learning"),
                         "Crossref found no results for Smith 2019 deep learning.")
        self.assertEqual(self.send("add 1"), "There are no search results. Use `find` first.")


class Criterion33FindCrossrefUnavailable(FindTest):
    """33. Crossref unreachable: Unavailable, no crash, latest search kept, next message works."""

    def test_each_failure(self):
        """Every failure of criterion 15, for `find`."""
        for name, failure in Criterion15CrossrefUnavailable.FAILURES.items():
            with self.subTest(failure=name):
                self.state = refchat.new_state()
                self.crossref.failure = None
                self.crossref.author_items = [LECUN]
                self.send("find LeCun 2015")
                before = copy.deepcopy(self.state["last_search"])
                self.crossref.failure = failure
                reply = self.send("find Smith 2019")
                self.assertIn("Status: **Unavailable**", reply)
                self.assertIn("Crossref is unavailable right now. Try again in a minute.", reply)
                self.assertEqual(self.state["last_search"], before)
                # Crossref is back: the next message is answered normally.
                self.crossref.failure = None
                self.assertIn(LECUN_APA, self.send("add 1"))
                self.assertIn("Result 1 (APA 7 preview)", self.send("find LeCun 2015"))


if __name__ == "__main__":
    unittest.main()
