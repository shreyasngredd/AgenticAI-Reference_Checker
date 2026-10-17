"""Tests for the buttons beside references and `find` results (refchat.py).

Each test class is one acceptance criterion from specs/goal-spec.md
section 4 (criteria 69-73, "Buttons and the Style dropdown"). app.py only
draws the buttons; what they show and do is refchat.button_for and
refchat.press_button, tested here. As in test_refchat.py, urllib.request.urlopen
is replaced by FakeCrossref, so no test uses the network.

Run from the project folder:
    python -m unittest discover tests
"""

import sys
import urllib.error
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import refchat  # noqa: E402
from test_refchat import LECUN, MISSING_DOI, ChatTest, crossref_item  # noqa: E402

# A record with no volume, so it is Check (criterion 4).
CHECK_DOI = "10.1234/check"
CHECK_RECORD = dict(crossref_item("A study of something", CHECK_DOI), volume=None)


class ButtonTest(ChatTest):
    """Shared helpers: a Check record on Crossref, and clicking a button."""

    def setUp(self):
        """Add a Check record to the fake Crossref."""
        super().setUp()
        self.crossref.works[CHECK_DOI] = CHECK_RECORD

    def last_items(self):
        """The button items of the latest reply."""
        return self.state["history"][-1].get("items", [])

    def label(self, item):
        """The (label, enabled) of an item's button, or None."""
        return refchat.button_for(self.state, item)

    def click(self, item):
        """Press a button, with the fake Crossref in place."""
        with mock.patch("urllib.request.urlopen", self.crossref.urlopen):
            refchat.press_button(self.state, item)


class Criterion69ReferenceButtons(ButtonTest):
    """69. Each reference block has the right button; Unavailable lines have none."""

    def test_lookup_buttons(self):
        """Verified, Check and Not found, in the order of the lines."""
        reply = self.send(f"10.1038/nature14539\n{CHECK_DOI}\n{MISSING_DOI}")
        items = self.last_items()
        # One item per block, so app.py can put each button beside its block.
        self.assertEqual(len(reply.split(refchat.BLOCK_SEPARATOR)), len(items))
        self.assertEqual([self.label(item) for item in items], [
            ("✓ In export", False), ("Add to export", True), ("Not found", False)])

    def test_list_and_add_buttons(self):
        """`list` has one button per reference, and `add` one for the new reference."""
        self.send(f"10.1038/nature14539\n{CHECK_DOI}")
        self.send("list")
        self.assertEqual([self.label(item) for item in self.last_items()],
                         [("✓ In export", False), ("Add to export", True)])
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        self.send("add 1")
        self.assertEqual(self.last_items(), [{"kind": "ref", "number": 3}])

    def test_unavailable_has_no_button(self):
        """A line Crossref couldn't be asked about gets no button."""
        self.crossref.failure = urllib.error.URLError("no route to host")
        self.send("10.1038/nature14539")
        self.assertNotIn("items", self.state["history"][-1])


class Criterion70AddReferenceSendsAccept(ButtonTest):
    """70. The button on a Check reference sends `accept N`."""

    def test_click(self):
        """The chat shows `accept 1`; the reference is exported but still Check."""
        self.send(CHECK_DOI)
        self.click(self.last_items()[0])
        self.assertEqual(self.state["history"][-2], {"role": "user", "content": "accept 1"})
        self.assertIn("Reference 1 confirmed by you.", self.state["history"][-1]["content"])
        self.assertTrue(refchat.in_export(self.state["refs"][0]))
        self.assertEqual(self.status_of(1), "check")
        self.assertEqual(self.label({"kind": "ref", "number": 1}), ("✓ In export", False))


class Criterion71AddResultSendsAddAndAccept(ButtonTest):
    """71. The button on a `find` result sends `add N`, then `accept M`."""

    def test_click(self):
        """Result 2 becomes reference 1, confirmed and still Check."""
        self.crossref.author_items = [LECUN, crossref_item("Another study", "10.1234/b")]
        self.send("find LeCun 2015")
        result = self.last_items()[1]
        self.assertEqual(self.label(result), ("Add to export", True))
        self.click(result)
        sent = [m["content"] for m in self.state["history"] if m["role"] == "user"]
        self.assertEqual(sent[-2:], ["add 2", "accept 1"])
        self.assertEqual(len(self.state["refs"]), 1)
        self.assertTrue(refchat.in_export(self.state["refs"][0]))
        self.assertEqual(self.status_of(1), "check")
        self.assertEqual(self.label(result), ("✓ In export", False))

    def test_older_search_has_no_button(self):
        """After a new `find`, the old results' buttons are gone."""
        self.crossref.author_items = [LECUN]
        self.send("find LeCun 2015")
        old = self.last_items()[0]
        self.send("find LeCun 2015")
        self.assertIsNone(self.label(old))
        self.assertEqual(self.label(self.last_items()[0]), ("Add to export", True))


class Criterion72DisabledButtonsDoNothing(ButtonTest):
    """72. A disabled button, or a second click, changes nothing."""

    def test_second_click_and_disabled(self):
        """Clicking twice, or on Verified / Not found, sends nothing."""
        self.crossref.author_items = [LECUN]
        self.send(f"10.1038/nature14539\n{MISSING_DOI}")
        verified, not_found = self.last_items()
        self.send("find LeCun 2015")
        result = self.last_items()[0]
        self.click(result)
        before = list(self.state["history"])
        for item in (result, verified, not_found):
            self.click(item)
        self.assertEqual(self.state["history"], before)
        self.assertEqual(len(self.state["refs"]), 3)


class Criterion73HelpExplainsButtons(ChatTest):
    """73. `help` explains the buttons and the Style dropdown."""

    def test_help(self):
        """The help names both buttons' commands and the dropdown."""
        reply = self.send("help")
        self.assertIn("**Buttons**", reply)
        self.assertIn("Add to export", reply)
        self.assertIn("`accept N`", reply)
        self.assertIn("**Style** dropdown", reply)


if __name__ == "__main__":
    unittest.main()
