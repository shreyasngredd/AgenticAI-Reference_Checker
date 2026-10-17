"""Tests for the Field setting (fields.py and refchat.py).

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 36-45, "Field setting"), and the expected results come
from the spec's wording, not from reading the code. As in test_refchat.py,
urllib.request.urlopen is replaced by FakeCrossref, so no test uses the
network. FakeCrossref does not apply Crossref's filters, so it also stands in
for a Crossref that ignored the ISSN filter (criterion 39).

Most tests use a small field list in a temporary file, so they don't depend
on the journals chosen for config/fields.json; one test checks that file.

Run from the project folder:
    python -m unittest discover tests
"""

import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent  # noqa: E402
import fields  # noqa: E402
import refchat  # noqa: E402
from test_refchat import (  # noqa: E402
    LECUN, LECUN_APA, RESULT_REASON, TITLE, ChatTest, crossref_item,
)

# The field list used by most tests: two fields, three journals.
PSYCHOLOGY_ISSNS = ["1111-1111", "2222-222X", "4444-4444"]
TEST_FIELDS = {
    "Psychology": [
        {"name": "Journal A", "issn": ["1111-1111", "2222-222X"]},
        {"name": "Journal B", "issn": ["4444-4444"]},
    ],
    "Marketing": [{"name": "Journal M", "issn": ["3333-3333"]}],
}
NO_FIELD_LINE = "Searched in:"
DOI_NOTE = "Field filter not used: a DOI lookup is exact."


def in_journal(record, issns):
    """A copy of a Crossref record that says it is in a journal with these ISSNs."""
    return dict(record, ISSN=list(issns))


class FieldTest(ChatTest):
    """Shared set-up: the test field list in a temporary config/fields.json."""

    def setUp(self):
        """Write TEST_FIELDS to a temporary file and point fields.py at it."""
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.fields_path = Path(folder.name) / "fields.json"
        self.write_fields(TEST_FIELDS)
        patcher = mock.patch.object(fields, "FIELDS_PATH", self.fields_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_fields(self, data):
        """Replace the temporary field list (a dict, or raw text for a broken file)."""
        text = data if isinstance(data, str) else json.dumps(data)
        self.fields_path.write_text(text, encoding="utf-8")

    def query(self, number=-1):
        """The query parameters of one request, as {name: [values]}."""
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.crossref.urls[number]).query)

    def filters(self, number=-1):
        """The parts of a request's `filter`, e.g. ["issn:1111-1111", ...]."""
        return self.query(number)["filter"][0].split(",")


class Criterion36FieldOptions(FieldTest):
    """36. "All fields" first, then the file's fields in order; "All fields" by default."""

    def test_options_follow_the_file(self):
        """The options are read from the file, in its order."""
        options, warning = fields.field_options()
        self.assertEqual(options, ["All fields", "Psychology", "Marketing"])
        self.assertIsNone(warning)

    def test_all_fields_is_the_default(self):
        """A new chat searches all fields."""
        self.assertEqual(refchat.new_state()["field"], "All fields")

    def test_the_real_config_file(self):
        """config/fields.json is valid and has the fields agreed in section 7.3."""
        with mock.patch.object(fields, "FIELDS_PATH", fields.PROJECT_FIELDS_PATH):
            options, warning = fields.field_options()
        self.assertIsNone(warning)
        self.assertEqual(options, ["All fields", "Information Systems", "Management",
                                   "General Management", "Psychology", "Marketing"])


class Criterion37AllFieldsSendsTheUsualRequests(FieldTest):
    """37. With "All fields", no issn filter and no "Searched in" line."""

    def test_find(self):
        """`find` sends exactly the request of criterion 21."""
        self.crossref.author_items = [LECUN]
        reply = self.send("find LeCun 2015")
        self.assertEqual(self.query()["filter"], ["from-pub-date:2015,until-pub-date:2015"])
        self.assertNotIn(NO_FIELD_LINE, reply)

    def test_title_lookup(self):
        """A title search has no filter at all."""
        self.search_returns([("10.1234/a", 0.97)])
        reply = self.send(TITLE)
        self.assertNotIn("filter", self.query())
        self.assertNotIn(NO_FIELD_LINE, reply)


class Criterion38FieldAddsItsIssns(FieldTest):
    """38. With a field, one request with an issn filter for each of its ISSNs only."""

    def test_find(self):
        """Year filters, then every Psychology ISSN, and no Marketing ISSN."""
        refchat.set_field(self.state, "Psychology")
        self.send("find Smith 2019")
        self.assertEqual(len(self.crossref.urls), 1)
        self.assertEqual(self.filters(), ["from-pub-date:2019", "until-pub-date:2019"]
                         + [f"issn:{issn}" for issn in PSYCHOLOGY_ISSNS])
        self.assertEqual(self.query()["query.author"], ["Smith"])

    def test_title_lookup(self):
        """The title search keeps its query and rows, plus the ISSN filter."""
        refchat.set_field(self.state, "Psychology")
        self.search_returns([("10.1234/a", 0.97)])
        self.send(TITLE)
        self.assertEqual(len(self.crossref.urls), 1)
        self.assertEqual(self.filters(), [f"issn:{issn}" for issn in PSYCHOLOGY_ISSNS])
        self.assertEqual(self.query()["query.bibliographic"], [TITLE])
        self.assertEqual(self.query()["rows"], ["20"])
        self.assertNotIn("3333-3333", self.crossref.urls[0])


class Criterion39ResultsInsideTheField(FieldTest):
    """39. "Searched in: <field>" on results; records outside the field never appear."""

    def test_find_results(self):
        """Only the in-field record is shown, as an APA 7 preview with the field line."""
        refchat.set_field(self.state, "Psychology")
        self.crossref.author_items = [
            in_journal(LECUN, ["3333-3333"]),                       # Marketing: dropped.
            crossref_item(TITLE, "10.1234/none"),                   # No ISSN: dropped.
            in_journal(crossref_item(TITLE, "10.1234/a"), ["2222-222X"]),
        ]
        reply = self.send("find Lovelace 2020")
        blocks = reply.split(refchat.BLOCK_SEPARATOR)
        self.assertEqual(len(blocks), 1)
        self.assertIn("**Result 1 (APA 7 preview)**", blocks[0])
        self.assertIn("Searched in: Psychology", blocks[0])
        self.assertIn("Status: **Check**", blocks[0])
        self.assertIn(RESULT_REASON, blocks[0])
        self.assertIn("10.1234/a", blocks[0])
        self.assertNotIn("10.1234/none", reply)
        self.assertEqual(len(self.state["last_search"]), 1)

    def test_title_lookup_ignores_records_outside_the_field(self):
        """An out-of-field record close behind the best one doesn't make it "too close"."""
        refchat.set_field(self.state, "Psychology")
        self.search_returns([("10.1234/a", 0.95), ("10.1234/b", 0.94)])
        self.crossref.search_items[0]["ISSN"] = ["1111-1111"]
        self.crossref.search_items[1]["ISSN"] = ["3333-3333"]
        reply = self.send(TITLE)
        self.assertIn("Searched in: Psychology", reply)
        self.assertEqual(self.status_of(1), "verified")
        self.assertNotIn("10.1234/b", reply)


class Criterion40NothingFoundInTheField(FieldTest):
    """40. "Not found in <field>; try All fields." for `find` and title lookups."""

    def test_find_with_no_results(self):
        """The whole reply is the one line."""
        refchat.set_field(self.state, "Psychology")
        self.assertEqual(self.send("find Smith 2019"), "Not found in Psychology; try All fields.")

    def test_find_with_only_records_outside_the_field(self):
        """Records dropped in code count as nothing found."""
        refchat.set_field(self.state, "Psychology")
        self.crossref.author_items = [in_journal(LECUN, ["3333-3333"])]
        self.assertEqual(self.send("find LeCun 2015"), "Not found in Psychology; try All fields.")

    def test_title_lookup_not_found(self):
        """A Not found title lookup gets the reason, after the others."""
        refchat.set_field(self.state, "Psychology")
        reply = self.send(TITLE)
        self.assertEqual(self.status_of(1), "not_found")
        self.assertIn("Searched in: Psychology", reply)
        self.assertIn("- Not found in Psychology; try All fields.", reply)

    def test_all_fields_keeps_the_old_wording(self):
        """With "All fields", `find` says what it said before."""
        self.assertEqual(self.send("find Smith 2019"), "Crossref found no results for Smith 2019.")


class Criterion41DoiLookupsIgnoreTheField(FieldTest):
    """41. DOI lookups are the same with a field, plus a note; other commands unchanged."""

    def test_doi_lookup(self):
        """Same request, same reference and status, plus the DOI note."""
        plain_reply = self.send("10.1038/nature14539")
        plain_urls = list(self.crossref.urls)
        self.state = refchat.new_state()
        self.crossref.urls = []
        refchat.set_field(self.state, "Psychology")
        reply = self.send("10.1038/nature14539")
        self.assertEqual(self.crossref.urls, plain_urls)
        self.assertIn(LECUN_APA, reply)
        self.assertEqual(self.status_of(1), "verified")
        self.assertIn(DOI_NOTE, reply)
        self.assertNotIn(DOI_NOTE, plain_reply)
        self.assertNotIn(NO_FIELD_LINE, reply)

    def test_add_list_edit_and_clear(self):
        """`add`, `list` and `edit` work as usual; `clear` keeps the field."""
        refchat.set_field(self.state, "Psychology")
        self.crossref.author_items = [in_journal(LECUN, ["1111-1111"])]
        self.send("find LeCun 2015")
        self.assertIn("Added result 1 as reference 1.", self.send("add 1"))
        self.assertIn("added from a search; paste its DOI to verify", self.send("list"))
        self.assertIn("Updated reference 1.", self.send("edit 1 year 2016"))
        self.send("clear")
        self.assertEqual(self.state["field"], "Psychology")


class Criterion42EditingTheFileTakesEffect(FieldTest):
    """42. A changed file changes the next request; a removed field means All fields."""

    def test_new_issn_is_used_on_the_next_message(self):
        """The file is read again for each message."""
        refchat.set_field(self.state, "Marketing")
        self.send("find Smith 2019")
        self.assertIn("issn:3333-3333", self.filters())
        self.write_fields({"Marketing": [{"name": "Journal M", "issn": ["5555-5555"]}]})
        self.send("find Smith 2019")
        self.assertIn("issn:5555-5555", self.filters())
        self.assertNotIn("issn:3333-3333", self.filters())

    def test_removed_field_is_all_fields(self):
        """No issn filter and no field line once the field has gone."""
        refchat.set_field(self.state, "Psychology")
        self.write_fields({"Marketing": TEST_FIELDS["Marketing"]})
        self.crossref.author_items = [LECUN]
        reply = self.send("find LeCun 2015")
        self.assertEqual(self.filters(), ["from-pub-date:2015", "until-pub-date:2015"])
        self.assertNotIn(NO_FIELD_LINE, reply)
        self.assertEqual(fields.field_options()[0], ["All fields", "Marketing"])


class Criterion43BrokenFileFallsBack(FieldTest):
    """43. A missing or broken file: only "All fields", a warning, and searches still work."""

    BROKEN = {
        "missing": None,
        "not JSON": "{not json",
        "not an object": json.dumps([1, 2]),
        "empty field": json.dumps({"Psychology": []}),
        "journal without a name": json.dumps({"Psychology": [{"issn": ["1111-1111"]}]}),
        "journal without ISSNs": json.dumps({"Psychology": [{"name": "A", "issn": []}]}),
        "badly written ISSN": json.dumps({"Psychology": [{"name": "A", "issn": ["1111-111"]}]}),
    }

    def test_each_broken_file(self):
        """Options, warning and a `find` with no issn filter, for every kind of problem."""
        for problem, text in self.BROKEN.items():
            with self.subTest(problem=problem):
                if text is None:
                    self.fields_path.unlink(missing_ok=True)
                else:
                    self.write_fields(text)
                options, warning = fields.field_options()
                self.assertEqual(options, ["All fields"])
                self.assertTrue(warning.startswith("Field lists unavailable (config/fields.json: "), warning)
                self.assertTrue(warning.endswith("). Using All fields."), warning)
                # A field chosen before the file broke is treated as All fields.
                self.state = refchat.new_state()
                refchat.set_field(self.state, "Psychology")
                self.crossref.author_items = [LECUN]
                reply = self.send("find LeCun 2015")
                self.assertEqual(self.filters(), ["from-pub-date:2015", "until-pub-date:2015"])
                self.assertIn("**Result 1 (APA 7 preview)**", reply)
                self.assertNotIn(NO_FIELD_LINE, reply)


class Criterion44HelpExplainsTheField(FieldTest):
    """44. `help` explains the Field setting, and that DOI lookups ignore it."""

    def test_help(self):
        """The Field dropdown, what it limits, and the DOI exception."""
        reply = self.send("help")
        self.assertIn("**Field**", reply)
        self.assertIn("title lookups", reply)
        self.assertIn("DOI lookups ignore", reply)
        self.assertIn("All fields", reply)


class Criterion45StillCrossrefOnlyAndNoWrites(FieldTest):
    """45. With a field: only api.crossref.org, no files written, the config only read."""

    def test_only_crossref_and_no_writes(self):
        """Every kind of message with a field chosen."""
        refchat.set_field(self.state, "Psychology")
        self.crossref.author_items = [in_journal(LECUN, ["1111-1111"])]
        self.search_returns([("10.1234/a", 0.97)])
        before = self.fields_path.read_text(encoding="utf-8")
        with mock.patch.object(agent, "save_json") as save_json, \
                mock.patch.object(Path, "write_text") as write_text:
            for message in ("10.1038/nature14539", TITLE, "find LeCun 2015", "add 1", "list", "help"):
                self.send(message)
        save_json.assert_not_called()
        write_text.assert_not_called()
        self.assertEqual(self.fields_path.read_text(encoding="utf-8"), before)
        for url in self.crossref.urls:
            self.assertEqual(urllib.parse.urlsplit(url).netloc, "api.crossref.org")


if __name__ == "__main__":
    unittest.main()
