"""Tests for `accept`, `cite` and the export (refchat.py, citations.py, export.py).

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 48-65, "Export and in-text citations"), and the expected
results come from the spec's wording, not from reading the code. As in
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import export  # noqa: E402
import refchat  # noqa: E402
from test_refchat import LECUN, MISSING_DOI, ChatTest, FakeCrossref  # noqa: E402

# The CSV header of section 3, in order.
COLUMNS = [
    "number", "status", "confirmed", "authors", "year", "title", "journal", "volume",
    "issue", "pages", "DOI", "formatted reference", "parenthetical citation",
    "narrative citation", "Google Scholar link",
]
LECUN_DOI = "10.1038/nature14539"


def article(doi, title, authors, year=2020, **changes):
    """A complete Crossref journal article; authors are (given, family) pairs."""
    record = {
        "type": "journal-article",
        "title": [title],
        "DOI": doi,
        "author": [{"given": given, "family": family} for given, family in authors],
        "issued": {"date-parts": [[year]]},
        "container-title": ["Journal of Tests"],
        "volume": "1",
        "issue": "2",
        "page": "3-4",
    }
    record.update(changes)
    return record


# Records for the tests: one, two and three authors (section 3's examples),
# an accented author, a title with a comma and quotes, and an incomplete
# record (no volume, so it is Check).
DAVIS = article("10.1234/davis", "Perceived usefulness", [("Fred", "Davis")], 1989)
DAVIS_BAGOZZI = article("10.1234/db", "User acceptance", [("Fred", "Davis"), ("Richard", "Bagozzi")], 1989)
YOO = article("10.1234/yoo", "Paradigm shift", [("Youngjin", "Yoo"), ("Ola", "Henfridsson"), ("Kalle", "Lyytinen")], 2010)
MULLER = article("10.1234/muller", "Accents in names", [("Jörg", "Müller")], 2019)
MILLER = article("10.1234/miller", "Plain names", [("Ann", "Miller")], 2019)
NASH = article("10.1234/nash", "Later names", [("John", "Nash")], 2019)
QUOTED_TITLE = 'Trust, "risk", and adoption'
QUOTED = article("10.1234/quoted", QUOTED_TITLE, [("Ada", "Lovelace")], 2021)
NO_VOLUME = article("10.1234/novolume", "An incomplete record", [("Ada", "Lovelace")], 2018)
del NO_VOLUME["volume"]
NO_YEAR = article("10.1234/noyear", "An undated record", [("Ada", "Lovelace")])
del NO_YEAR["issued"]
ORGANISATION = article("10.1234/who", "Health report", [], 2020,
                       author=[{"name": "World Health Organization", "sequence": "first"}])
RECORDS = [DAVIS, DAVIS_BAGOZZI, YOO, MULLER, MILLER, NASH, QUOTED, NO_VOLUME, NO_YEAR, ORGANISATION]


class ExportTest(ChatTest):
    """A fake Crossref that knows LeCun and every record above."""

    def setUp(self):
        """Start with an empty chat and all the test records on Crossref."""
        super().setUp()
        works = {LECUN_DOI: LECUN}
        works.update({record["DOI"]: record for record in RECORDS})
        self.crossref = FakeCrossref(works=works)

    def paste(self, *records):
        """Paste the DOIs of these records, one per line (references 1, 2, ...)."""
        return self.send("\n".join(record["DOI"] for record in records))

    def txt(self):
        """references.txt, decoded."""
        return export.export_txt(self.state).decode("utf-8")

    def csv_rows(self):
        """references.csv read back by a CSV reader, header row included."""
        text = export.export_csv(self.state).decode("utf-8-sig")
        return list(csv.reader(io.StringIO(text)))


# --- accept N (criteria 48-50) ---

class Criterion48AcceptConfirmsCheck(ExportTest):
    """48. `accept N` on a Check reference confirms it; its status stays Check."""

    def test_accept_check(self):
        """The reply, the flag, and the unchanged status."""
        self.paste(NO_VOLUME)
        self.assertEqual(self.status_of(1), "check")
        reply = self.send("accept 1")
        self.assertTrue(reply.startswith("Reference 1 confirmed by you. It is now in the export."))
        self.assertTrue(self.state["refs"][0]["confirmed"])
        self.assertEqual(self.status_of(1), "check")
        self.assertIn("Status: **Check**", reply)


class Criterion49BadAcceptChangesNothing(ExportTest):
    """49. `accept` on Verified, Not found, already confirmed or a missing N changes nothing."""

    def test_replies(self):
        """Each case gives the section 3 reply and no confirmation."""
        self.send(LECUN_DOI)
        self.send(MISSING_DOI)
        self.paste(NO_VOLUME)
        self.assertEqual(self.send("accept 1"), "Reference 1 is Verified, so it is already in the export.")
        self.assertEqual(self.send("accept 2"),
                         "Reference 2 was not found, so it can't be confirmed or exported. "
                         "Paste its DOI or fix it with `edit` first.")
        self.assertEqual(self.send("accept 9"), "There is no reference 9. Type `list` to see the numbers.")
        self.send("accept 3")
        self.assertEqual(self.send("accept 3"), "Reference 3 is already confirmed.")
        self.assertEqual([ref["confirmed"] for ref in self.state["refs"]], [False, False, True])

    def test_wrong_arguments(self):
        """`accept`, `accept two`, `accept 1 2` get the short help."""
        self.paste(NO_VOLUME)
        for message in ("accept", "accept two", "accept 1 2"):
            with self.subTest(message=message):
                self.assertTrue(self.send(message).startswith("I didn't understand that."))
        self.assertFalse(self.state["refs"][0]["confirmed"])
        self.assertEqual(refchat.parse_command("ACCEPT 3"), ("accept", 3))


class Criterion50EditAndClearRemoveConfirmation(ExportTest):
    """50. A successful edit removes the confirmation; a failed one keeps it; clear removes all."""

    def test_edit(self):
        """A failed edit keeps it, a good one removes it and says so."""
        self.paste(NO_VOLUME)
        self.send("accept 1")
        self.assertTrue(self.send("edit 1 colour red").startswith("Not changed"))
        self.assertTrue(self.state["refs"][0]["confirmed"])
        reply = self.send("edit 1 volume 7")
        self.assertIn("The confirmation was removed: type `accept 1` again if it is still right.", reply)
        self.assertFalse(self.state["refs"][0]["confirmed"])

    def test_clear(self):
        """After clear there are no references, so nothing is confirmed or exported."""
        self.paste(NO_VOLUME)
        self.send("accept 1")
        self.send("clear")
        self.assertEqual(self.state["refs"], [])
        self.assertEqual(self.csv_rows(), [COLUMNS])


# --- The export (criteria 51-58) ---

class Criterion51WhatIsExported(ExportTest):
    """51. Verified and confirmed Check references only; never Not found or unconfirmed Check."""

    def test_contents(self):
        """Of four references, only the Verified one and the confirmed one are exported."""
        self.send(LECUN_DOI)                # 1: Verified
        self.send(MISSING_DOI)              # 2: Not found
        self.paste(NO_VOLUME)               # 3: Check, will be confirmed
        self.paste(NO_YEAR)                 # 4: Check, not confirmed
        self.send("accept 3")
        numbers = [row[0] for row in self.csv_rows()[1:]]
        self.assertEqual(sorted(numbers), ["1", "3"])
        text = self.txt()
        self.assertIn("LeCun", text)
        self.assertIn("An incomplete record", text)
        self.assertNotIn(MISSING_DOI, text)
        self.assertNotIn("An undated record", text)


class Criterion52OrderAndStyle(ExportTest):
    """52. Sorted by first author (no case, no accents), then year; in the current style."""

    def test_order(self):
        """Nash, Müller, Miller, Davis 2020 and Davis 1989 come out Davis 1989, Davis, Miller, Müller, Nash."""
        later_davis = article("10.1234/davis2", "A later paper", [("Fred", "davis")], 2020)
        self.crossref.works["10.1234/davis2"] = later_davis
        self.paste(NASH, MULLER, MILLER, later_davis, DAVIS)
        families = [row[3].split(",")[0] for row in self.csv_rows()[1:]]
        self.assertEqual(families, ["Davis", "davis", "Miller", "Müller", "Nash"])

    def test_current_style_without_italics(self):
        """With Harvard chosen, the export has the Harvard text `list` shows, minus the *."""
        self.send(LECUN_DOI)
        self.send("style harvard")
        listed = self.send("list").split("**1.** ")[1].split("\n\n")[0]
        self.assertIn("*", listed)  # `list` shows italics...
        plain = listed.replace("*", "")
        self.assertIn(plain, self.txt())  # ...the export has the same text without them.
        self.assertEqual(self.csv_rows()[1][11], plain)
        self.assertIn("Harvard", self.txt().splitlines()[0])


class Criterion53TxtLayout(ExportTest):
    """53. Heading with the style, the references, then the APA 7 in-text section."""

    def test_layout(self):
        """Section 3's layout, with N the number in `list`."""
        self.paste(YOO, DAVIS)
        lines = self.txt().splitlines()
        self.assertEqual(lines[0], "Citation Checker beta: reference list (APA 7th)")
        self.assertEqual(lines[1], "Verified references, plus Check references you confirmed. "
                                   "Not found references are never included.")
        section = lines.index("In-text citations (APA 7)")
        self.assertTrue(lines[3].startswith("Davis, F. (1989)."))
        self.assertTrue(lines[5].startswith("Yoo, Y., Henfridsson, O., & Lyytinen, K. (2010)."))
        self.assertEqual(lines[section + 2:], [
            "Reference 2: parenthetical (Davis, 1989); narrative Davis (1989)",
            "Reference 1: parenthetical (Yoo et al., 2010); narrative Yoo et al. (2010)",
        ])

    def test_check_citation_line(self):
        """A confirmed reference with no year gets a Check line with the reason."""
        self.paste(NO_YEAR)
        self.send("accept 1")
        self.assertIn("Reference 1: Check: year not stated", self.txt())


class Criterion54CsvColumns(ExportTest):
    """54. The header, and one row per exported reference with section 3's values."""

    def test_row(self):
        """LeCun's row, field by field."""
        self.send(LECUN_DOI)
        rows = self.csv_rows()
        self.assertEqual(rows[0], COLUMNS)
        self.assertEqual(len(rows), 2)
        row = dict(zip(COLUMNS, rows[1]))
        self.assertEqual(row["number"], "1")
        self.assertEqual(row["status"], "Verified")
        self.assertEqual(row["confirmed"], "no")
        self.assertEqual(row["authors"], "LeCun, Yann; Bengio, Yoshua; Hinton, Geoffrey")
        self.assertEqual(row["year"], "2015")
        self.assertEqual(row["title"], "Deep learning")
        self.assertEqual(row["journal"], "Nature")
        self.assertEqual((row["volume"], row["issue"], row["pages"]), ("521", "7553", "436-444"))
        self.assertEqual(row["DOI"], LECUN_DOI)
        self.assertTrue(row["formatted reference"].startswith("LeCun, Y., Bengio, Y., & Hinton, G. (2015)."))
        self.assertNotIn("*", row["formatted reference"])
        self.assertEqual(row["parenthetical citation"], "(LeCun et al., 2015)")
        self.assertEqual(row["narrative citation"], "LeCun et al. (2015)")
        self.assertEqual(row["Google Scholar link"], "https://scholar.google.com/scholar?q=Deep+learning+LeCun")

    def test_missing_field_is_not_stated(self):
        """A confirmed reference with no volume says `not stated`, and `confirmed` is yes."""
        self.paste(NO_VOLUME)
        self.send("accept 1")
        row = dict(zip(COLUMNS, self.csv_rows()[1]))
        self.assertEqual(row["volume"], "not stated")
        self.assertEqual((row["status"], row["confirmed"]), ("Check", "yes"))


class Criterion55CsvQuoting(ExportTest):
    """55. A title with a comma and quotes reads back unchanged."""

    def test_comma_and_quotes(self):
        """The title cell is exactly the title, and the row has every column."""
        self.paste(QUOTED)
        if self.status_of(1) == "check":
            self.send("accept 1")  # The spec only needs it in the export.
        rows = self.csv_rows()
        self.assertEqual(len(rows[1]), len(COLUMNS))
        self.assertEqual(dict(zip(COLUMNS, rows[1]))["title"], QUOTED_TITLE)
        raw = export.export_csv(self.state).decode("utf-8-sig")
        self.assertIn('"Trust, ""risk"", and adoption"', raw)  # Quoted, quotes doubled.


class Criterion56Accents(ExportTest):
    """56. Müller, Jörg survives in the .txt, the .csv and the citations; the .csv has a BOM."""

    def test_accents(self):
        """Every output keeps the umlauts."""
        self.paste(MULLER)
        if self.status_of(1) == "check":
            self.send("accept 1")
        self.assertIn("Müller, J. (2019).", self.txt())
        self.assertIn("(Müller, 2019)", self.txt())
        data = export.export_csv(self.state)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        row = dict(zip(COLUMNS, self.csv_rows()[1]))
        self.assertEqual(row["authors"], "Müller, Jörg")
        self.assertEqual(row["narrative citation"], "Müller (2019)")
        self.assertIn("Narrative: Müller (2019)", self.send("cite 1"))


class Criterion57EmptyExport(ExportTest):
    """57. An empty export: the .txt says so and the .csv is the header only."""

    def test_no_references(self):
        """A new chat."""
        self.assertIn("No references to export yet.", self.txt())
        self.assertNotIn("In-text citations", self.txt())
        self.assertEqual(self.csv_rows(), [COLUMNS])

    def test_nothing_exportable(self):
        """Only a Not found and an unconfirmed Check reference: still empty."""
        self.send(MISSING_DOI)
        self.paste(NO_VOLUME)
        self.assertIn("No references to export yet.", self.txt())
        self.assertEqual(self.csv_rows(), [COLUMNS])


class Criterion58ExportInMemory(ExportTest):
    """58. Building the export writes no files and asks nothing of the network."""

    def test_no_files_no_requests(self):
        """open, write_text and write_bytes are never called; no URL is requested."""
        self.send(LECUN_DOI)
        requests_before = len(self.crossref.urls)
        with mock.patch("builtins.open") as open_file, \
                mock.patch.object(Path, "write_text") as write_text, \
                mock.patch.object(Path, "write_bytes") as write_bytes, \
                mock.patch("urllib.request.urlopen", self.crossref.urlopen):
            export.export_txt(self.state)
            export.export_csv(self.state)
        open_file.assert_not_called()
        write_text.assert_not_called()
        write_bytes.assert_not_called()
        self.assertEqual(len(self.crossref.urls), requests_before)


# --- cite N (criteria 59-63) ---

class Criterion59CiteForms(ExportTest):
    """59. One, two, and three or more authors, in any current style."""

    def test_forms(self):
        """Section 3's table, exactly."""
        self.paste(DAVIS, DAVIS_BAGOZZI, YOO)
        expected = {
            1: ("(Davis, 1989)", "Davis (1989)"),
            2: ("(Davis & Bagozzi, 1989)", "Davis and Bagozzi (1989)"),
            3: ("(Yoo et al., 2010)", "Yoo et al. (2010)"),
        }
        for style in ("apa", "chicago", "harvard"):
            self.send(f"style {style}")
            for number, (parenthetical, narrative) in expected.items():
                with self.subTest(style=style, number=number):
                    reply = self.send(f"cite {number}")
                    self.assertTrue(reply.startswith(f"**APA 7 in-text citations for reference {number}**"))
                    self.assertIn(f"Parenthetical: {parenthetical}", reply)
                    self.assertIn(f"Narrative: {narrative}", reply)
                    self.assertIn("Citation: **OK**", reply)


class Criterion60CiteMissingAuthorsOrYear(ExportTest):
    """60. No authors or no year: no citation, Check with the reason."""

    def test_no_year(self):
        """Year not stated."""
        self.paste(NO_YEAR)
        reply = self.send("cite 1")
        self.assertIn("Citation: **Check**", reply)
        self.assertIn("year not stated", reply)
        self.assertNotIn("Parenthetical:", reply)

    def test_no_authors(self):
        """A Not found reference has no authors."""
        self.send(MISSING_DOI)
        reply = self.send("cite 1")
        self.assertIn("Citation: **Check**", reply)
        self.assertIn("authors not stated", reply)
        self.assertNotIn("Parenthetical:", reply)
        self.assertIn("Reference status: **Not found**", reply)

    def test_authors_cleared_by_edit(self):
        """Clearing the authors with `edit` gives the same Check."""
        self.paste(DAVIS)
        self.send("edit 1 authors not stated")
        self.assertIn("authors not stated", self.send("cite 1"))


class Criterion61CiteOrganisation(ExportTest):
    """61. An organisation author: no citation, Check naming it."""

    def test_crossref_organisation(self):
        """Crossref lists the WHO by name."""
        self.paste(ORGANISATION)
        reply = self.send("cite 1")
        self.assertIn("Citation: **Check**", reply)
        self.assertIn("World Health Organization", reply)
        self.assertNotIn("Parenthetical:", reply)

    def test_edited_organisation(self):
        """An author typed with no given name may be an organisation."""
        self.paste(DAVIS)
        self.send("edit 1 authors American Psychological Association")
        reply = self.send("cite 1")
        self.assertIn("Citation: **Check**", reply)
        self.assertIn("American Psychological Association", reply)
        self.assertNotIn("Parenthetical:", reply)


class Criterion62SameCitation(ExportTest):
    """62. Two references with the same parenthetical citation are both Check, naming each other."""

    def test_same_author_and_year(self):
        """Two single-author Davis 1989 papers."""
        other = article("10.1234/davis3", "Another 1989 paper", [("Fred", "Davis")], 1989)
        self.crossref.works["10.1234/davis3"] = other
        self.paste(DAVIS, other)
        first, second = self.send("cite 1"), self.send("cite 2")
        self.assertIn("Citation: **Check**", first)
        self.assertIn("reference 2", first)
        self.assertIn("Citation: **Check**", second)
        self.assertIn("reference 1", second)
        self.assertIn("Parenthetical: (Davis, 1989)", first)  # Built, but to check.


class Criterion63CiteBadNumber(ExportTest):
    """63. No reference N, or a bad `cite`, changes nothing."""

    def test_bad_cite(self):
        """The missing-N reply, and short help for `cite` and `cite one`."""
        self.assertEqual(self.send("cite 3"), "There is no reference 3. Type `list` to see the numbers.")
        for message in ("cite", "cite one"):
            with self.subTest(message=message):
                self.assertTrue(self.send(message).startswith("I didn't understand that."))


# --- list and help (criteria 64-65) ---

class Criterion64ListShowsExport(ExportTest):
    """64. `list` starts with the count and each block has its "In export" line."""

    def test_list(self):
        """One reference of each kind."""
        self.send(LECUN_DOI)      # 1: Verified
        self.paste(NO_VOLUME)     # 2: Check, confirmed
        self.paste(NO_YEAR)       # 3: Check
        self.send(MISSING_DOI)    # 4: Not found
        self.send("accept 2")
        reply = self.send("list")
        self.assertTrue(reply.startswith("In the export: 2 of 4 references."))
        blocks = reply.split("\n\n---\n\n")
        self.assertTrue(blocks[0].endswith("In export: **yes** (Verified)"))
        self.assertTrue(blocks[1].endswith("In export: **yes** (confirmed by you)"))
        self.assertTrue(blocks[2].endswith("In export: **no** (Check: type `accept 3` once you have checked it)"))
        self.assertTrue(blocks[3].endswith("In export: **no** (Not found)"))

    def test_other_replies_have_no_export_line(self):
        """A lookup reply doesn't have the line."""
        self.assertNotIn("In export", self.send(LECUN_DOI))


class Criterion65HelpShowsExport(ExportTest):
    """65. `help` (and so the sidebar) lists accept and cite with examples and explains the export."""

    def test_help(self):
        """Both commands, their examples, and what goes in the export."""
        reply = self.send("help")
        for text in ("`accept N`", "`accept 3`", "`cite N`", "`cite 1`", "references.txt",
                     "references.csv", "Verified references plus", "Not found references are never included"):
            self.assertIn(text, reply)
        self.assertEqual(reply, refchat.help_text())


if __name__ == "__main__":
    unittest.main()
