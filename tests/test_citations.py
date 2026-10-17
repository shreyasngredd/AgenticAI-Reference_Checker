"""Tests for in-text citations in APA 7, Harvard and Chicago author-date (citations.py).

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 119-125), and the expected citations are copied from the
table in section 7.7, not worked out from the code. Entries are built from
Crossref-shaped records with agent.format_citation, as a lookup builds them.
No test uses the network.

Run from the project folder:
    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent  # noqa: E402
import citations  # noqa: E402
import refchat  # noqa: E402
from test_refchat import LECUN, MISSING_DOI, ChatTest  # noqa: E402

STYLES = ("apa", "harvard", "chicago")
FOUR_AUTHORS = [("Sunil", "Mithas"), ("Roland", "Rust"), ("Jiyoung", "Lee"), ("Min", "Kim")]
SHORTENED_REASON = "shortened title chosen by code: check it"
NO_YEAR_REASON = "Crossref gives no year"


def entry(people=FOUR_AUTHORS[:1], orgs=(), year=2021, kind="journal-article",
          title="Digital Transformation: A Review"):
    """An entry as a lookup builds it from a Crossref record.

    people are (given, family) pairs; orgs are organisation names, which
    Crossref lists by "name" with no family name. year=None leaves out the date.
    """
    authors = [{"given": given, "family": family} for given, family in people]
    authors += [{"name": name} for name in orgs]
    record = {"type": kind, "title": [title] if title else [], "DOI": "10.1234/x",
              "author": authors, "container-title": ["MIS Quarterly"]}
    if year:
        record["issued"] = {"date-parts": [[year]]}
    built = agent.format_citation(record)
    built.update({"id": "ref-x", "status": "auto", "input": "10.1234/x"})
    return built


def forms(built, style):
    """(parenthetical, narrative) for one entry in one style."""
    citation = citations.in_text(built, style)
    return citation["parenthetical"], citation["narrative"]


class Criterion119AuthorCounts(unittest.TestCase):
    """119. One, two, three and four authors, exactly as in the 7.7 table, in each style."""

    EXPECTED = {
        "apa": [
            ("(Mithas, 2021)", "Mithas (2021)"),
            ("(Mithas & Rust, 2021)", "Mithas and Rust (2021)"),
            ("(Mithas et al., 2021)", "Mithas et al. (2021)"),
            ("(Mithas et al., 2021)", "Mithas et al. (2021)"),
        ],
        "harvard": [
            ("(Mithas, 2021)", "Mithas (2021)"),
            ("(Mithas and Rust, 2021)", "Mithas and Rust (2021)"),
            ("(Mithas, Rust and Lee, 2021)", "Mithas, Rust and Lee (2021)"),
            ("(Mithas et al., 2021)", "Mithas et al. (2021)"),
        ],
        "chicago": [
            ("(Mithas 2021)", "Mithas (2021)"),
            ("(Mithas and Rust 2021)", "Mithas and Rust (2021)"),
            ("(Mithas, Rust, and Lee 2021)", "Mithas, Rust, and Lee (2021)"),
            ("(Mithas et al. 2021)", "Mithas et al. (2021)"),
        ],
    }

    def test_table(self):
        """Every row and style of the table, with no reason to check."""
        for style, rows in self.EXPECTED.items():
            for count, expected in enumerate(rows, start=1):
                with self.subTest(style=style, authors=count):
                    built = entry(people=FOUR_AUTHORS[:count])
                    self.assertEqual(forms(built, style), expected)
                    self.assertEqual(citations.in_text(built, style)["reasons"], [])

    def test_default_style_is_apa(self):
        """in_text without a style is APA 7, as `cite` was before."""
        self.assertEqual(citations.in_text(entry())["parenthetical"], "(Mithas, 2021)")


class Criterion120Organisations(unittest.TestCase):
    """120. Organisation authors are cited by name; mixed or given-name-less authors follow 7.7."""

    def test_only_organisations(self):
        """The organisation's name as Crossref gives it, in every style, OK."""
        built = entry(people=(), orgs=("World Health Organization",), year=2020)
        expected = {
            "apa": ("(World Health Organization, 2020)", "World Health Organization (2020)"),
            "harvard": ("(World Health Organization, 2020)", "World Health Organization (2020)"),
            "chicago": ("(World Health Organization 2020)", "World Health Organization (2020)"),
        }
        for style in STYLES:
            with self.subTest(style=style):
                self.assertEqual(forms(built, style), expected[style])
                self.assertEqual(citations.in_text(built, style)["reasons"], [])

    def test_two_organisations(self):
        """Two organisations use the two-author row."""
        built = entry(people=(), orgs=("World Health Organization", "UNICEF"), year=2020)
        self.assertEqual(forms(built, "apa"),
                         ("(World Health Organization & UNICEF, 2020)",
                          "World Health Organization and UNICEF (2020)"))

    def test_organisation_and_people(self):
        """Crossref's order between them is lost, so nothing is built."""
        built = entry(people=FOUR_AUTHORS[:1], orgs=("World Health Organization",))
        for style in STYLES:
            with self.subTest(style=style):
                citation = citations.in_text(built, style)
                self.assertIsNone(citation["parenthetical"])
                self.assertIsNone(citation["narrative"])
                self.assertTrue(any("organisation and person authors" in r for r in citation["reasons"]))

    def test_author_without_given_name(self):
        """Used as a name, but Check, naming the author."""
        built = entry(people=[("", "American Psychological Association")], year=2020)
        citation = citations.in_text(built, "apa")
        self.assertEqual(citation["parenthetical"], "(American Psychological Association, 2020)")
        self.assertTrue(any("American Psychological Association" in r and "no given name" in r
                            for r in citation["reasons"]))


class Criterion121NoAuthor(unittest.TestCase):
    """121. No author: the shortened title, quoted for articles, italic for books and reports."""

    def test_article(self):
        """The main title (before the colon) in double quotes, Check."""
        built = entry(people=(), year=2015, title="Deep Learning: A Review")
        expected = {
            "apa": ('("Deep Learning," 2015)', '"Deep Learning" (2015)'),
            "harvard": ('("Deep Learning", 2015)', '"Deep Learning" (2015)'),
            "chicago": ('("Deep Learning" 2015)', '"Deep Learning" (2015)'),
        }
        for style in STYLES:
            with self.subTest(style=style):
                self.assertEqual(forms(built, style), expected[style])
                self.assertIn(SHORTENED_REASON, citations.in_text(built, style)["reasons"])

    def test_book_and_report(self):
        """Books and reports put the title in italics (*...*)."""
        expected = {
            "apa": ("(*Deep Learning*, 2015)", "*Deep Learning* (2015)"),
            "harvard": ("(*Deep Learning*, 2015)", "*Deep Learning* (2015)"),
            "chicago": ("(*Deep Learning* 2015)", "*Deep Learning* (2015)"),
        }
        for kind in ("book", "report"):
            built = entry(people=(), year=2015, kind=kind, title="Deep Learning: A Review")
            for style in STYLES:
                with self.subTest(kind=kind, style=style):
                    self.assertEqual(forms(built, style), expected[style])
                    self.assertIn(SHORTENED_REASON, citations.in_text(built, style)["reasons"])

    def test_title_without_colon(self):
        """With no colon, the whole title is used."""
        built = entry(people=(), year=2015, title="Deep Learning")
        self.assertEqual(forms(built, "chicago")[0], '("Deep Learning" 2015)')

    def test_no_author_no_title(self):
        """Nothing to build from: no citation."""
        built = entry(people=(), title=None)
        for style in STYLES:
            with self.subTest(style=style):
                citation = citations.in_text(built, style)
                self.assertIsNone(citation["parenthetical"])
                self.assertTrue(citation["reasons"])


class Criterion122NoDate(unittest.TestCase):
    """122. No year: n.d. (APA, Chicago) or no date (Harvard), Check."""

    def test_no_year(self):
        """Each style's no-date form, with the reason."""
        built = entry(year=None)
        expected = {
            "apa": ("(Mithas, n.d.)", "Mithas (n.d.)"),
            "harvard": ("(Mithas, no date)", "Mithas (no date)"),
            "chicago": ("(Mithas n.d.)", "Mithas (n.d.)"),
        }
        for style in STYLES:
            with self.subTest(style=style):
                self.assertEqual(forms(built, style), expected[style])
                self.assertTrue(any(NO_YEAR_REASON in r for r in citations.in_text(built, style)["reasons"]))

    def test_no_author_and_no_year(self):
        """Both rules together."""
        built = entry(people=(), year=None, title="Deep Learning")
        self.assertEqual(forms(built, "apa")[0], '("Deep Learning," n.d.)')


class Criterion123SameCitation(unittest.TestCase):
    """123. Two references with the same parenthetical citation are both Check, in every style."""

    def test_same_citation(self):
        """Each names the other; both are still built."""
        first, second = entry(title="One paper"), entry(title="Another paper")
        for style in STYLES:
            with self.subTest(style=style):
                found = citations.in_text_all([(1, first), (2, second)], style)
                self.assertIsNotNone(found[1]["parenthetical"])
                self.assertTrue(any("reference 2" in r for r in found[1]["reasons"]))
                self.assertTrue(any("reference 1" in r for r in found[2]["reasons"]))

    def test_label(self):
        """My list names items instead of references."""
        found = citations.in_text_all([(1, entry()), (2, entry())], "apa", label="item")
        self.assertTrue(any("item 2" in r for r in found[1]["reasons"]))


class Criterion124CardsAndCite(ChatTest):
    """124. Every card's citation is in the current style (find results APA 7); cite N too."""

    def test_lookup_card_follows_style(self):
        """The LeCun card in Harvard, after `style harvard`."""
        self.send("10.1038/nature14539")
        item = {"kind": "ref", "number": 1}
        self.assertEqual(refchat.card_citation(self.state, item)["parenthetical"], "(LeCun et al., 2015)")
        self.send("style harvard")
        card = refchat.card_citation(self.state, item)
        self.assertEqual(card["style"], "Harvard")
        self.assertEqual(card["parenthetical"], "(LeCun, Bengio and Hinton, 2015)")
        self.assertEqual(card["narrative"], "LeCun, Bengio and Hinton (2015)")

    def test_cite_follows_style(self):
        """The heading names the style."""
        self.send("10.1038/nature14539")
        self.send("style chicago")
        reply = self.send("cite 1")
        self.assertTrue(reply.startswith("**Chicago author-date in-text citations for reference 1**"))
        self.assertIn("Parenthetical: (LeCun, Bengio, and Hinton 2015)", reply)
        self.assertIn("Narrative: LeCun, Bengio, and Hinton (2015)", reply)

    def test_find_result_is_apa(self):
        """A find result is an APA 7 preview, so its citation is APA 7 too."""
        self.crossref.author_items = [LECUN]
        self.send("style chicago")
        self.send("find LeCun 2015")
        item = self.state["history"][-1]["items"][0]
        card = refchat.card_citation(self.state, item)
        self.assertEqual(card["style"], "APA 7")
        self.assertEqual(card["parenthetical"], "(LeCun et al., 2015)")

    def test_no_match_card_has_none(self):
        """A DOI Crossref has no record of: no citation at all."""
        self.send(MISSING_DOI)
        self.assertIsNone(refchat.card_citation(self.state, {"kind": "ref", "number": 1}))

    def test_unavailable_line_has_none(self):
        """A line with no card item has no citation."""
        self.assertIsNone(refchat.card_citation(self.state, None))


class Criterion125NothingInvented(unittest.TestCase):
    """125. Names, years and titles come from the entry; `not stated` never appears."""

    def test_parts_come_from_the_entry(self):
        """Every family name and the year in a citation are the entry's own, accents kept."""
        cases = [entry(people=FOUR_AUTHORS[:n]) for n in range(1, 5)]
        cases.append(entry(people=[("Jörg", "Müller")], year=2019))
        for built in cases:
            for style in STYLES:
                with self.subTest(style=style, authors=len(built["authors"])):
                    parenthetical, narrative = forms(built, style)
                    self.assertIn(built["authors"][0]["family"], parenthetical)
                    self.assertIn(str(built["year"]), narrative)
                    # Only names of this entry appear: strip them and nothing but punctuation is left.
                    rest = parenthetical
                    for author in built["authors"]:
                        rest = rest.replace(author["family"], "")
                    rest = rest.replace(str(built["year"]), "").replace("et al.", "").replace("and", "")
                    self.assertEqual("".join(char for char in rest if char not in "()&,. "), "")

    def test_never_not_stated(self):
        """No output of any rule contains `not stated`."""
        cases = [entry(year=None), entry(people=(), title=None), entry(people=(), year=None),
                 entry(people=(), orgs=("World Health Organization",), year=None)]
        for built in cases:
            for style in STYLES:
                citation = citations.in_text(built, style)
                for text in (citation["parenthetical"], citation["narrative"]):
                    self.assertNotIn("not stated", text or "")


if __name__ == "__main__":
    unittest.main()
