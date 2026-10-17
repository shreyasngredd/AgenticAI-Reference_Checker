"""Tests for live suggestions (suggest.py).

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 139-144; 145 was withdrawn by decision 7.9), and the
limits come from section 7.8, not from reading the code. urllib.request.urlopen is replaced by FakeCrossref
(test_refchat.py), and time by FakeClock, so no test uses the network or
waits.

Run from the project folder:
    python -m unittest discover tests
"""

import os
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import suggest  # noqa: E402
from test_refchat import LECUN, FakeCrossref  # noqa: E402



class FakeClock:
    """A clock the tests move by hand; sleep() moves it on and is recorded."""

    def __init__(self):
        """Start at time 100 (any number would do)."""
        self.time = 100.0
        self.sleeps = []

    def now(self):
        """The current fake time, in seconds."""
        return self.time

    def sleep(self, seconds):
        """Wait without waiting: move the clock on."""
        self.sleeps.append(round(seconds, 3))
        self.time += seconds


def record(title, doi=None, year=2015, family="LeCun", journal="Nature", issns=("0028-0836",)):
    """A Crossref record as the suggestion request returns it (only the selected fields)."""
    item = {"type": "journal-article", "title": [title], "ISSN": list(issns)}
    if doi:
        item["DOI"] = doi
    if year:
        item["issued"] = {"date-parts": [[year]]}
    if family:
        item["author"] = [{"given": "Yann", "family": family}]
    if journal:
        item["container-title"] = [journal]
    return item


class SuggestTest(unittest.TestCase):
    """A fresh memory (cache and timings), a fake clock and a fake Crossref for every test."""

    def setUp(self):
        """No mailto from the shell, so the URLs are as the spec says."""
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("CROSSREF_MAILTO", None)
        self.clock = FakeClock()
        self.memory = suggest.new_memory()
        self.crossref = FakeCrossref(search_items=[record("Deep learning", "10.1038/nature14539")])
        self.request_times = []
        original = self.crossref.urlopen

        def timed_urlopen(request, timeout=None):
            """Note the fake time of each request, then answer it."""
            self.request_times.append(self.clock.now())
            return original(request, timeout)

        self.urlopen = timed_urlopen

    def ask(self, text, issns=None):
        """Call suggest.suggestions with the fakes in place."""
        with mock.patch("urllib.request.urlopen", self.urlopen):
            return suggest.suggestions(text, issns, clock=self.clock.now, sleep=self.clock.sleep,
                                       memory=self.memory)


class Criterion139MinimumLengthAndDoi(SuggestTest):
    """139. No request below 4 characters (after trimming), or for a DOI or DOI link."""

    def test_too_short(self):
        """Empty, 3 characters, and 3 characters padded with spaces."""
        for text in ("", "dee", "   de  ", "   "):
            with self.subTest(text=text):
                self.assertEqual(self.ask(text), ([], None))
        self.assertEqual(self.crossref.urls, [])
        self.assertEqual(suggest.MIN_CHARS, 4)

    def test_four_characters_asks(self):
        """Exactly 4 characters is enough."""
        found, note = self.ask("deep")
        self.assertEqual(len(self.crossref.urls), 1)
        self.assertEqual(len(found), 1)
        self.assertIsNone(note)

    def test_doi(self):
        """A DOI is exact: no suggestions, a note, no request."""
        for text in ("10.1038/nature14539", "https://doi.org/10.1038/nature14539"):
            with self.subTest(text=text):
                self.assertEqual(self.ask(text), ([], suggest.DOI_NOTE))
        self.assertEqual(self.crossref.urls, [])


class Criterion140Cache(SuggestTest):
    """140. The same text and filter twice is one request; another filter is a new one."""

    def test_cache(self):
        """Case and spaces don't matter; the filter does."""
        first = self.ask("Deep learning")
        self.clock.time += 5
        self.assertEqual(self.ask("  deep   LEARNING "), first)
        self.assertEqual(len(self.crossref.urls), 1)
        self.ask("Deep learning", ["0028-0836"])
        self.assertEqual(len(self.crossref.urls), 2)

    def test_cache_is_capped(self):
        """At most CACHE_SIZE answers are kept; the oldest goes first."""
        for number in range(suggest.CACHE_SIZE + 1):
            self.ask(f"title number {number}")
        self.assertEqual(len(self.memory["cache"]), suggest.CACHE_SIZE)
        self.assertNotIn(("title number 0", ()), self.memory["cache"])


class Criterion141OneRequestPerSecond(SuggestTest):
    """141. Requests are never less than 1 second apart; a request too soon waits the rest."""

    def test_spacing(self):
        """Three different texts at once: the 2nd and 3rd wait, each 1 second after the last."""
        self.ask("deep learning")
        self.ask("deep learning in")
        self.clock.time += 0.4
        self.ask("deep learning in nature")
        self.assertEqual(len(self.request_times), 3)
        gaps = [later - earlier for earlier, later in zip(self.request_times, self.request_times[1:])]
        for gap in gaps:
            self.assertGreaterEqual(round(gap, 3), suggest.MIN_INTERVAL)
        self.assertEqual(self.clock.sleeps, [1.0, 0.6])

    def test_no_wait_after_a_pause(self):
        """Two seconds later, no waiting."""
        self.ask("deep learning")
        self.clock.time += 2
        self.ask("deep learning in")
        self.assertEqual(self.clock.sleeps, [])

    def test_typing_pause(self):
        """The browser's pause before sending (the debounce) is 500 ms."""
        self.assertEqual(suggest.TYPING_PAUSE, "500ms")


class Criterion142Request(SuggestTest):
    """142. One request to api.crossref.org/works with the section 3 parameters and the filter."""

    def test_parameters(self):
        """query.bibliographic, rows=5, select, and the field's issn filters."""
        self.ask("Deep learning", ["0028-0836", "1476-4687"])
        (url,) = self.crossref.urls
        parts = urllib.parse.urlsplit(url)
        self.assertEqual((parts.scheme, parts.netloc, parts.path), ("https", "api.crossref.org", "/works"))
        query = {name: values[0] for name, values in urllib.parse.parse_qs(parts.query).items()}
        self.assertEqual(query, {
            "query.bibliographic": "Deep learning",
            "rows": "5",
            "select": "DOI,title,author,issued,container-title,ISSN,type",
            "filter": "issn:0028-0836,issn:1476-4687",
        })

    def test_no_filter(self):
        """All fields: no filter parameter."""
        self.ask("Deep learning")
        self.assertNotIn("filter", urllib.parse.parse_qs(urllib.parse.urlsplit(self.crossref.urls[0]).query))

    def test_mailto(self):
        """CROSSREF_MAILTO is added when set."""
        os.environ["CROSSREF_MAILTO"] = "student@example.org"
        self.ask("Deep learning")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.crossref.urls[0]).query)
        self.assertEqual(query["mailto"], ["student@example.org"])

    def test_outside_the_field_is_dropped(self):
        """A record whose ISSNs are not in the filter is not suggested."""
        self.crossref.search_items = [record("In the field", "10.1/a", issns=("0028-0836",)),
                                      record("Outside", "10.1/b", issns=("9999-9999",))]
        found, _ = self.ask("Deep learning", ["0028-0836"])
        self.assertEqual([s["fill"] for s in found], ["https://doi.org/10.1/a"])

    def test_at_most_five(self):
        """Even if Crossref sends more."""
        self.crossref.search_items = [record(f"Paper {n}", f"10.1/{n}") for n in range(8)]
        self.assertEqual(len(self.ask("Paper")[0]), 5)


class Criterion143Labels(SuggestTest):
    """143. Labels use only Crossref's title, year, first family name and journal; fill is the DOI link."""

    def test_full_label(self):
        """Title (year) · family · journal, and the DOI link."""
        found, _ = self.ask("Deep learning")
        self.assertEqual(found, [{"label": "Deep learning (2015) · LeCun · Nature",
                                  "fill": "https://doi.org/10.1038/nature14539"}])

    def test_missing_parts_left_out(self):
        """No year, no author, no journal, no DOI: just the title, which is also the fill."""
        self.crossref.search_items = [record("A bare record", year=None, family=None, journal=None)]
        found, _ = self.ask("A bare record")
        self.assertEqual(found, [{"label": "A bare record", "fill": "A bare record"}])
        self.assertNotIn("not stated", found[0]["label"])

    def test_record_from_a_lookup(self):
        """A full Crossref record works too (extra fields are ignored)."""
        self.crossref.search_items = [LECUN]
        found, _ = self.ask("Deep learning")
        self.assertEqual(found[0]["fill"], "https://doi.org/10.1038/nature14539")
        self.assertTrue(found[0]["label"].startswith("Deep learning (2015) · LeCun"))


class Criterion144Unavailable(SuggestTest):
    """144. Crossref unavailable: no suggestions, the note, and no request for 30 seconds."""

    def test_backoff(self):
        """Fails, stays quiet for 30 seconds, then asks again."""
        self.crossref.failure = urllib.error.URLError("down")
        self.assertEqual(self.ask("Deep learning"), ([], suggest.UNAVAILABLE_NOTE))
        self.clock.time += 10
        self.assertEqual(self.ask("Something else"), ([], suggest.UNAVAILABLE_NOTE))
        self.assertEqual(len(self.crossref.urls), 1)
        self.crossref.failure = None
        self.clock.time += 21
        found, note = self.ask("Something else")
        self.assertEqual(len(self.crossref.urls), 2)
        self.assertIsNone(note)
        self.assertEqual(len(found), 1)

    def test_failure_not_cached(self):
        """A failed text is asked again once the pause is over."""
        self.crossref.failure = urllib.error.URLError("down")
        self.ask("Deep learning")
        self.crossref.failure = None
        self.clock.time += 31
        self.assertEqual(len(self.ask("Deep learning")[0]), 1)


if __name__ == "__main__":
    unittest.main()
