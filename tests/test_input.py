"""Tests for easier input: DOI links, auto-detection, quoted titles and Crossref's mailto.

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 135-138), and the expected results come from section 3
("Inputs") and section 2, not from reading the code. As in test_refchat.py,
urllib.request.urlopen is replaced by FakeCrossref, so no test uses the
network.

Run from the project folder:
    python -m unittest discover tests
"""

import os
import sys
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent  # noqa: E402
import refchat  # noqa: E402
from test_refchat import ChatTest  # noqa: E402

DOI = "10.1038/nature14539"
DOI_URL = "https://api.crossref.org/works/" + urllib.parse.quote(DOI)
DOI_FORMS = [
    "https://doi.org/10.1038/nature14539",
    "http://dx.doi.org/10.1038/nature14539",
    "https://dx.doi.org/10.1038/nature14539",
    "https://www.doi.org/10.1038/nature14539",
    "doi:10.1038/nature14539",
    "DOI: 10.1038/nature14539",
    "https://doi.org/10.1038%2Fnature14539",
    "10.1038/nature14539.",
]


def query_of(url):
    """The query parameters of a requested URL, as {name: value}."""
    return {name: values[0] for name, values in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}


class Criterion135DoiLinks(ChatTest):
    """135. Every DOI form gives the same DOI and the same single request as the bare DOI."""

    def test_find_doi(self):
        """agent.find_doi gives exactly the DOI, nothing added."""
        for form in DOI_FORMS:
            with self.subTest(form=form):
                self.assertEqual(agent.find_doi(form), DOI)

    def test_one_request_each(self):
        """Each form sends one request, to the bare DOI's URL, and is Verified."""
        for form in DOI_FORMS:
            with self.subTest(form=form):
                self.state = refchat.new_state()
                self.crossref.urls = []
                self.send(form)
                self.assertEqual(self.crossref.urls, [DOI_URL])
                self.assertEqual(self.status_of(1), "verified")

    def test_clean_doi(self):
        """clean_doi drops the dx.doi.org and www prefixes too."""
        for prefix in ("https://dx.doi.org/", "http://dx.doi.org/", "https://www.doi.org/", "DOI:", "doi: "):
            with self.subTest(prefix=prefix):
                self.assertEqual(agent.clean_doi(prefix + DOI), DOI)


class Criterion136AutoDetection(ChatTest):
    """136. A DOI or DOI link is a DOI lookup; anything else a title search, without `find`."""

    def test_input_kind(self):
        """Every DOI form, and a pasted reference ending in its DOI link, is a DOI."""
        for form in DOI_FORMS + [DOI]:
            with self.subTest(form=form):
                self.assertEqual(refchat.input_kind(form), "doi")
        pasted = ("LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), "
                  "436–444. https://doi.org/10.1038/nature14539")
        self.assertEqual(refchat.input_kind(pasted), "doi")
        self.assertEqual(refchat.input_kind("Deep learning in neural networks"), "title")

    def test_plain_title_is_searched(self):
        """A plain title sends one title search, with no `find`."""
        self.send("Deep learning in neural networks")
        self.assertEqual(len(self.crossref.urls), 1)
        self.assertEqual(query_of(self.crossref.urls[0])["query.bibliographic"], "Deep learning in neural networks")


class Criterion137QuotedTitles(ChatTest):
    """137. A quoted line starting with a command word is a title; unquoted it is the command."""

    def test_quoted(self):
        """Straight and curly quotes: a title search for the words inside."""
        for line in ('"List decoding of codes"', "“List decoding of codes”"):
            with self.subTest(line=line):
                self.crossref.urls = []
                self.assertEqual(refchat.parse_command(line), ("lookup", ["List decoding of codes"]))
                self.send(line)
                self.assertEqual(len(self.crossref.urls), 1)
                self.assertEqual(query_of(self.crossref.urls[0])["query.bibliographic"], "List decoding of codes")

    def test_unquoted_is_the_command(self):
        """Without quotes it is `list FILTER`, and nothing is requested."""
        self.assertEqual(refchat.parse_command("List decoding of codes"), ("list", "decoding of codes"))
        self.send("List decoding of codes")
        self.assertEqual(self.crossref.urls, [])

    def test_short_help_says_so(self):
        """The short help explains the quotes."""
        reply = self.send("hello")
        self.assertIn("To search a title that starts with a command word, put it in double quotes.", reply)


class Criterion138Mailto(ChatTest):
    """138. With CROSSREF_MAILTO set, every Crossref request has mailto; without it, nothing changes."""

    def test_with_mailto(self):
        """DOI lookup, title search and find all carry it."""
        os.environ["CROSSREF_MAILTO"] = "student@example.org"
        self.crossref.author_items = []
        self.send(DOI)
        self.send("Deep learning in neural networks")
        self.send("find LeCun 2015")
        self.assertEqual(len(self.crossref.urls), 3)
        for url in self.crossref.urls:
            with self.subTest(url=url):
                self.assertEqual(query_of(url)["mailto"], "student@example.org")
        self.assertEqual(self.status_of(1), "verified")

    def test_without_mailto(self):
        """Exactly the URL of criterion 1."""
        self.send(DOI)
        self.assertEqual(self.crossref.urls, [DOI_URL])
