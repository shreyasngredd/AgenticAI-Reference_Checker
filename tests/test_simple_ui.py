"""Tests for the interface simplification (specs/goal-spec.md decision 7.9).

Each test class is one acceptance criterion (149-161 and 163). The expected results
come from the spec's wording. As in test_refchat.py, no test uses the
network: Crossref is the FakeCrossref of test_refchat.py.

Criterion 161 compares the reply text with
tests/fixtures/before_simplification.json, recorded from the code as it was
before 7.9 by running this file directly:
    python tests/test_simple_ui.py --record
"""

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fields  # noqa: E402
import mylist  # noqa: E402
import refchat  # noqa: E402
from test_refchat import LECUN_APA, MISSING_DOI, TITLE, ChatTest, crossref_item  # noqa: E402

BASELINE = Path(__file__).resolve().parent / "fixtures" / "before_simplification.json"

# Criterion 161: the inputs whose replies must not change. Each scenario is
# (title search results as (doi, similarity), find results, failure, messages).
SCENARIOS = {
    "doi": ([], [], None, ["10.1038/nature14539"]),
    "doi_link": ([], [], None, ["https://doi.org/10.1038/nature14539"]),
    "doi_prefix": ([], [], None, ["doi: 10.1038/nature14539"]),
    "missing_doi": ([], [], None, [MISSING_DOI]),
    "title_verified": ([("10.1234/a", 0.95)], [], None, [TITLE]),
    "title_check_provisional": ([("10.1234/a", 0.85), ("10.1234/b", 0.6)], [], None, [TITLE]),
    "title_not_found_provisional": ([("10.1234/a", 0.5)], [], None, [TITLE]),
    "title_no_result": ([], [], None, [TITLE]),
    "quoted_title": ([("10.1234/a", 0.95)], [], None, ['"List of things"']),
    "unavailable": ([], [], "down", ["10.1038/nature14539", TITLE]),
    "three_lines": ([("10.1234/a", 0.95)], [], None,
                    ["10.1038/nature14539\n" + TITLE + "\n" + MISSING_DOI]),
    "find_add_list_cite_accept": ([], [crossref_item(TITLE, "10.1234/a")], None,
                                  ["find Lovelace 2020", "add 1", "list", "cite 1", "accept 1", "list"]),
    "find_nothing": ([], [], None, ["find Nobody 2020 topic words"]),
    "styles": ([], [], None, ["10.1038/nature14539", "style harvard", "list", "cite 1",
                              "style chicago", "list", "cite 1", "style apa", "list"]),
    "edit_and_errors": ([], [], None, ["10.1038/nature14539", "edit 1 year 2016", "list lecun",
                                       "hello", "style mla", "add 1", "find smith", "clear", "list"]),
}


def run_scenario(test, name):
    """Send a scenario's messages through `test` (a ChatTest); return the replies."""
    scores, author_items, failure, messages = SCENARIOS[name]
    if scores:
        test.search_returns(scores)
    test.crossref.author_items = author_items
    if failure:
        test.crossref.failure = urllib.error.URLError(failure)
    return [test.send(message) for message in messages]


# The field names of config/fields.json, so the derived tags are the real ones.
UI_FIELDS = {
    "Information Systems": [{"name": "Journal IS", "issn": ["1111-1111"]}],
    "Management": [{"name": "Journal MG", "issn": ["2222-2222"]}],
    "General Management": [{"name": "Journal GM", "issn": ["3333-3333"]}],
    "Psychology": [{"name": "Journal P", "issn": ["4444-4444", "5555-555X"]}],
    "Marketing": [{"name": "Journal MK", "issn": ["6666-6666"]}],
}
AUTHOR_YEAR = "author_year"


class UiTest(ChatTest):
    """Shared set-up: UI_FIELDS in a temporary config/fields.json."""

    def setUp(self):
        """Write UI_FIELDS to a temporary file and point fields.py at it."""
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.fields_path = Path(folder.name) / "fields.json"
        self.write_fields(UI_FIELDS)
        patcher = mock.patch.object(fields, "FIELDS_PATH", self.fields_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_fields(self, data):
        """Replace the temporary field list (a dict, or raw text for a broken file)."""
        text = data if isinstance(data, str) else json.dumps(data)
        self.fields_path.write_text(text, encoding="utf-8")

    def last_read_as(self):
        """The interpretations kept with the latest reply."""
        return self.state["history"][-1].get("read_as")

    def filters(self, number=-1):
        """The parts of a request's `filter`, or [] when it has none."""
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.crossref.urls[number]).query)
        return query["filter"][0].split(",") if "filter" in query else []


class Criterion149DoiDetected(UiTest):
    """149. A DOI, a DOI link and a `doi:` DOI are read as DOI."""

    def test_doi_forms(self):
        """Each form is a DOI, and the reply is a DOI lookup."""
        for line in ("10.1038/nature14539", "https://doi.org/10.1038/nature14539", "doi: 10.1038/nature14539"):
            with self.subTest(line=line):
                self.assertEqual(refchat.interpret(line), "doi")
                self.send(line)
                self.assertEqual(self.last_read_as(), [{"kind": "doi", "line": line}])


class Criterion150TitleDetected(UiTest):
    """150. A plain title, and a quoted line with a year, are read as title."""

    def test_titles(self):
        """No year, or quotes, means title."""
        self.assertEqual(refchat.interpret("Deep learning for computer vision"), "title")
        self.assertEqual(refchat.interpret('"LeCun 2015"'), "title")

    def test_quoted_line_is_a_title_search(self):
        """The quoted line searches Crossref by title, not by author."""
        self.send('"LeCun 2015"')
        self.assertNotIn("query.author", self.crossref.urls[-1])
        self.assertEqual(self.last_read_as(), [{"kind": "title", "line": "LeCun 2015"}])


class Criterion151AuthorYearDetected(UiTest):
    """151. SURNAME YEAR [topic] (at most 4 words) is read as author and year, exactly like `find`."""

    def test_detected(self):
        """Three shapes of author and year."""
        for line in ("LeCun 2015", "van der Berg 2019", "LeCun 2015 deep learning"):
            with self.subTest(line=line):
                self.assertEqual(refchat.interpret(line), AUTHOR_YEAR)

    def test_same_reply_as_find(self):
        """The reply and the request equal those of the `find` command."""
        self.crossref.author_items = [crossref_item(TITLE, "10.1234/a")]
        typed = self.send("LeCun 2015 deep learning")
        typed_url = self.crossref.urls[-1]
        self.setUp()
        self.crossref.author_items = [crossref_item(TITLE, "10.1234/a")]
        self.assertEqual(self.send("find LeCun 2015 deep learning"), typed)
        self.assertEqual(self.crossref.urls[-1], typed_url)
        self.assertEqual(self.last_read_as()[0]["kind"], AUTHOR_YEAR)


class Criterion152AmbiguousLines(UiTest):
    """152. Edge cases of the author-and-year rule."""

    def test_vision_2020_is_author_and_year(self):
        """A two-word title with a year is guessed as author and year (the button fixes it)."""
        self.assertEqual(refchat.interpret("Vision 2020"), AUTHOR_YEAR)

    def test_titles(self):
        """Year first, five words, a year out of range: titles."""
        for line in ("2020 vision", "Smith 2019 deep learning methods", "Smith 1850"):
            with self.subTest(line=line):
                self.assertEqual(refchat.interpret(line), "title")

    def test_several_lines_are_never_author_and_year(self):
        """Two author-and-year lines pasted together are two title lookups."""
        self.send("Smith 2019\nJones 2020")
        self.assertEqual([read["kind"] for read in self.last_read_as()], ["title", "title"])
        self.assertFalse(any("query.author" in url for url in self.crossref.urls))

    def test_one_word_gets_short_help(self):
        """`hello` is still answered with the short help, and nothing is asked."""
        self.assertTrue(self.send("hello").startswith("I didn't understand that."))
        self.assertEqual(self.crossref.urls, [])


class Criterion153InterpretationShown(UiTest):
    """153. Every lookup and search reply keeps how it was read, and the line to draw above it."""

    def test_lines(self):
        """The three wordings of section 7.9."""
        self.assertEqual(refchat.read_as_line({"kind": "doi", "line": "10.1/x"}), "Searched as: DOI")
        self.assertEqual(refchat.read_as_line({"kind": "title", "line": TITLE}), "Searched as: title")
        read = {"kind": AUTHOR_YEAR, "line": "LeCun 2015 deep learning",
                "surname": "LeCun", "year": 2015, "topic": "deep learning"}
        self.assertEqual(refchat.read_as_line(read),
                         "Searched as: author and year (LeCun, 2015, topic: deep learning)")

    def test_kept_for_each_line_and_search(self):
        """One per pasted line; one for a search, even with no results."""
        self.send("10.1038/nature14539\n" + TITLE)
        self.assertEqual(self.last_read_as(), [{"kind": "doi", "line": "10.1038/nature14539"},
                                               {"kind": "title", "line": TITLE}])
        self.send("Nobody 2020")
        self.assertEqual(self.last_read_as(), [{"kind": AUTHOR_YEAR, "line": "Nobody 2020",
                                                "surname": "Nobody", "year": 2020, "topic": ""}])

    def test_not_in_reply_text(self):
        """The interpretation is kept beside the reply, so the reply text is unchanged."""
        reply = self.send("10.1038/nature14539")
        self.assertNotIn("Searched as", reply)


class Criterion154SearchAsOtherType(UiTest):
    """154. The switch button sends the other reading, as if typed; a DOI has none."""

    def test_author_year_to_title(self):
        """Search as title instead sends the quoted line and gives a title lookup."""
        self.send("Vision 2020")
        read = self.last_read_as()[0]
        self.assertEqual(refchat.switch_for(read), ("Search as title instead", '"Vision 2020"'))
        self.send(refchat.switch_for(read)[1])
        self.assertEqual(self.last_read_as(), [{"kind": "title", "line": "Vision 2020"}])
        self.assertNotIn("query.author", self.crossref.urls[-1])

    def test_title_to_author_year(self):
        """A title `find` can read gets Search as author and year instead, which sends `find`."""
        self.send("Smith 2019\nJones 2020")
        read = self.last_read_as()[0]
        self.assertEqual(refchat.switch_for(read), ("Search as author and year instead", "find Smith 2019"))
        with mock.patch("urllib.request.urlopen", self.crossref.urlopen):
            refchat.press_switch(self.state, read)
        self.assertEqual(self.state["history"][-2]["content"], "find Smith 2019")
        self.assertIn("query.author", self.crossref.urls[-1])

    def test_no_button(self):
        """A DOI, and a title with no year, have no switch button."""
        self.assertIsNone(refchat.switch_for({"kind": "doi", "line": "10.1038/nature14539"}))
        self.assertIsNone(refchat.switch_for({"kind": "title", "line": TITLE}))


class Criterion155TagParsing(UiTest):
    """155. split_tags finds style, field and #all tags and leaves other text alone."""

    def test_style_tags(self):
        """Any case; the tag is removed from the text."""
        self.assertEqual(refchat.split_tags("Deep learning #Harvard"),
                         {"text": "Deep learning", "style": "harvard", "field": None, "unknown": []})
        self.assertEqual(refchat.split_tags("#apa")["style"], "apa")
        self.assertEqual(refchat.split_tags("#chicago")["style"], "chicago")

    def test_field_tags(self):
        """Derived from the names: lower case, hyphens, no spaces, initials."""
        expected = {"#psychology": "Psychology", "#is": "Information Systems",
                    "#information-systems": "Information Systems",
                    "#informationsystems": "Information Systems", "#management": "Management",
                    "#gm": "General Management", "#all": fields.ALL_FIELDS}
        for tag, field in expected.items():
            with self.subTest(tag=tag):
                parts = refchat.split_tags(f"LeCun 2015 {tag}")
                self.assertEqual((parts["text"], parts["field"]), ("LeCun 2015", field))

    def test_other_text_unchanged(self):
        """C# and unknown tags stay in the text; a message without tags is unchanged."""
        self.assertEqual(refchat.split_tags("Programming in C# today")["text"], "Programming in C# today")
        parts = refchat.split_tags("The #MeToo movement")
        self.assertEqual((parts["text"], parts["unknown"]), ("The #MeToo movement", ["#metoo"]))
        self.assertEqual(refchat.split_tags("a  b\nc")["text"], "a  b\nc")

    def test_last_tag_wins(self):
        """Two style tags: the last one."""
        self.assertEqual(refchat.split_tags("#apa #chicago")["style"], "chicago")


class Criterion156TagInSearch(UiTest):
    """156. A tag in a search changes the setting first; the chips follow."""

    def test_field_tag_filters_the_search(self):
        """lecun 2015 #psychology sends Psychology's ISSNs, as `find` does with the field set."""
        self.send("lecun 2015 #psychology")
        self.assertIn("query.author", self.crossref.urls[-1])
        self.assertEqual([part for part in self.filters() if part.startswith("issn:")],
                         ["issn:4444-4444", "issn:5555-555X"])
        self.assertEqual(refchat.chip_labels(self.state), ("APA 7", "Psychology"))

    def test_style_tag_formats_the_reply(self):
        """A style tag in a lookup: the reply is in that style, and the chip says so."""
        reply = self.send("10.1038/nature14539 #harvard")
        self.assertEqual(refchat.chip_labels(self.state), ("Harvard", "All fields"))
        self.assertIn("LeCun, Y., Bengio, Y. and Hinton, G.", reply)


class Criterion157StandaloneTags(UiTest):
    """157. A message of tags only changes the settings and searches nothing."""

    def test_style(self):
        """#chicago alone."""
        reply = self.send("#chicago")
        self.assertEqual(reply, f"Style set to {refchat.agent.STYLES['chicago']}.")
        self.assertEqual(self.state["style"], "chicago")
        self.assertEqual(self.crossref.urls, [])

    def test_style_and_field(self):
        """#chicago #is: both settings, both lines."""
        reply = self.send("#chicago #is")
        self.assertEqual(reply, f"Style set to {refchat.agent.STYLES['chicago']}.\n\n"
                                "Field set to Information Systems.")
        self.assertEqual(refchat.chip_labels(self.state), ("Chicago", "Information Systems"))
        self.assertEqual(self.crossref.urls, [])


class Criterion158SharedAndBrokenTags(UiTest):
    """158. A tag two fields share is not offered; a broken file leaves #all and the styles."""

    def test_shared_initials(self):
        """Information Systems and Intelligent Systems both give #is: neither gets it."""
        self.write_fields(dict(UI_FIELDS, **{"Intelligent Systems": [{"name": "J", "issn": ["7777-7777"]}]}))
        tags = refchat.field_tags()
        self.assertNotIn("#is", tags)
        self.assertEqual(tags["#intelligent-systems"], "Intelligent Systems")
        self.assertIsNone(refchat.split_tags("x #is")["field"])

    def test_broken_file(self):
        """Only #all is a field tag; style tags still work."""
        self.write_fields("{not json")
        self.assertEqual(refchat.field_tags(), {"#all": fields.ALL_FIELDS})
        self.assertEqual(refchat.split_tags("#harvard")["style"], "harvard")
        self.assertEqual(refchat.split_tags("x #psychology")["unknown"], ["#psychology"])


class Criterion159UnknownTag(UiTest):
    """159. An unknown tag is searched as text, and the reply says so first."""

    def test_note(self):
        """The title search gets the tag; the reply starts with the note."""
        reply = self.send("The #MeToo movement online")
        self.assertTrue(reply.startswith("#metoo is not a tag, so it was searched as text."))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.crossref.urls[-1]).query)
        self.assertEqual(query["query.bibliographic"], ["The #MeToo movement online"])

    def test_redrawn_with_note(self):
        """render_reply keeps the note above the redrawn blocks."""
        self.send("The #MeToo movement online")
        drawn = refchat.render_reply(self.state, self.state["history"][-1])
        self.assertTrue(drawn[0][0].startswith("#metoo is not a tag"))


class Criterion160OldCommandsStillWork(UiTest):
    """160. Every old command still gives its usual reply."""

    def test_commands(self):
        """find, add, list, style, edit, cite, accept, help, clear."""
        self.crossref.author_items = [crossref_item(TITLE, "10.1234/a")]
        self.assertTrue(self.send("find Lovelace 2020").startswith("**Result 1 (APA 7 preview)**"))
        self.assertTrue(self.send("add 1").startswith("Added result 1 as reference 1."))
        self.assertTrue(self.send("list").startswith("In the export: 0 of 1 references."))
        self.assertTrue(self.send("edit 1 year 2021").startswith("Updated reference 1."))
        self.assertTrue(self.send("cite 1").startswith("**APA 7 in-text citations for reference 1**"))
        self.assertTrue(self.send("accept 1").startswith("Reference 1 confirmed by you."))
        self.assertEqual(self.send("style harvard"), f"Style set to {refchat.agent.STYLES['harvard']}.")
        self.assertEqual(self.send("help"), refchat.help_text())
        self.assertEqual(self.send("clear"), "Cleared.")


class Criterion163CardButtons(UiTest):
    """163. The Copy popover's text, and the card's one Add to list button."""

    def test_copy_text(self):
        """LeCun in APA 7 without `*`, and both citations."""
        self.send("10.1038/nature14539")
        copied = refchat.copy_text(self.state, {"kind": "ref", "number": 1})
        self.assertEqual(copied, {
            "reference": LECUN_APA.replace("*", ""),
            "parenthetical": "(LeCun et al., 2015)", "narrative": "LeCun et al. (2015)"})

    def test_copy_text_follows_style(self):
        """After a style change the copied reference is in the new style."""
        self.send("10.1038/nature14539")
        self.send("#harvard")
        copied = refchat.copy_text(self.state, {"kind": "ref", "number": 1})
        self.assertTrue(copied["reference"].startswith("LeCun, Y., Bengio, Y. and Hinton, G."))

    def test_no_match_has_nothing(self):
        """A DOI Crossref doesn't have: no Copy text, no list button."""
        self.send(MISSING_DOI)
        item = {"kind": "ref", "number": 1}
        self.assertIsNone(refchat.copy_text(self.state, item))
        self.assertIsNone(mylist.card_list_button(self.state, item))

    def test_provisional_card_has_one_button(self):
        """Two candidates: one Add to list button, for the provisional reference."""
        self.search_returns([("10.1234/a", 0.85), ("10.1234/b", 0.6)])
        self.send(TITLE)
        item = {"kind": "ref", "number": 1}
        self.assertEqual(len(mylist.list_buttons_for(self.state, item)), 2)  # Still there in code.
        label, enabled, target = mylist.card_list_button(self.state, item)
        self.assertEqual((label, enabled, target["kind"]), (mylist.ADD_LABEL, True, "provisional"))


class Criterion161ResultsUnchanged(ChatTest):
    """161. For the same inputs, the reply text is the text recorded before 7.9."""

    def test_every_scenario(self):
        """Each scenario's replies equal the recorded ones, message by message."""
        recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(sorted(recorded), sorted(SCENARIOS))
        for name in SCENARIOS:
            with self.subTest(scenario=name):
                self.setUp()  # A fresh chat and Crossref for each scenario.
                self.assertEqual(run_scenario(self, name), recorded[name])


def record():
    """Write the baseline fixture from the code as it is now (run once, before 7.9)."""
    test = ChatTest()
    replies = {}
    for name in SCENARIOS:
        test.setUp()
        replies[name] = run_scenario(test, name)
        test.doCleanups()
    BASELINE.write_text(json.dumps(replies, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if "--record" in sys.argv:
        record()
    else:
        unittest.main()
