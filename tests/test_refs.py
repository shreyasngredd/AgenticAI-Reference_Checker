"""Tests for refs mode: Crossref title search and APA 7 sentence case.

The expected results come from the decisions in specs/goal-spec.md
section 7, not from reading the code. No test uses the network: Crossref
is replaced by a fake get_json that returns made-up search results.

Run from the project folder:
    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

# Let the tests import agent.py from the project folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent  # noqa: E402

QUERY = "A study of something"  # The title the student typed.


def crossref_item(title, doi, year=2020):
    """A minimal Crossref search result (journal article)."""
    return {
        "type": "journal-article",
        "title": [title],
        "DOI": doi,
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "issued": {"date-parts": [[year]]},
        "container-title": ["Journal of Tests"],
        "volume": "1",
        "issue": "2",
        "page": "3-4",
    }


def search_with_scores(scores):
    """Run search_crossref_title with Crossref results scoring the given amounts.

    scores is a list of (doi, similarity). Each result gets its own title, and
    title_similarity is replaced so that title gets exactly that score. This
    tests the band rules directly, without depending on difflib.
    """
    items = [crossref_item(f"Title {doi}", doi) for doi, _ in scores]
    by_title = {f"Title {doi}": score for doi, score in scores}

    def fake_get_json(url, source, not_found, headers=None):
        """Pretend to be Crossref's search endpoint."""
        return {"message": {"items": items}}, None

    def fake_similarity(typed, found):
        """The score chosen for each result's title."""
        return by_title[found]

    with mock.patch.object(agent, "get_json", fake_get_json), \
            mock.patch.object(agent, "title_similarity", fake_similarity):
        result, error = agent.search_crossref_title(QUERY)
    assert error is None
    return result


class TitleSearchBands(unittest.TestCase):
    """One test for each band in the title-search decision table."""

    def test_below_weak_threshold_is_not_found(self):
        """Best score under 0.75: no plausible match, so "Not found"."""
        result = search_with_scores([("10.1/a", 0.74), ("10.1/b", 0.40)])
        self.assertEqual(result["outcome"], "not_found")
        self.assertIsNone(result["citation"])
        self.assertTrue(result["reasons"])

    def test_no_results_is_not_found(self):
        """Crossref returned nothing at all: "Not found"."""
        result = search_with_scores([])
        self.assertEqual(result["outcome"], "not_found")

    def test_exactly_weak_threshold_is_check(self):
        """0.75 is the lower edge of the weak band: "Check", not picked."""
        result = search_with_scores([("10.1/a", 0.75)])
        self.assertEqual(result["outcome"], "check")
        self.assertIsNone(result["citation"])
        self.assertIn("weak", " ".join(result["reasons"]))

    def test_just_below_match_threshold_is_check(self):
        """0.89 is still in the weak band: "Check" with the candidates."""
        result = search_with_scores([("10.1/a", 0.89), ("10.1/b", 0.50)])
        self.assertEqual(result["outcome"], "check")
        self.assertEqual(result["candidates"][0]["doi"], "10.1/a")

    def test_exactly_match_threshold_alone_is_match(self):
        """0.9 with no close runner-up: that paper is the match."""
        result = search_with_scores([("10.1/a", 0.90), ("10.1/b", 0.50)])
        self.assertEqual(result["outcome"], "match")
        self.assertEqual(result["citation"]["doi"], "10.1/a")

    def test_several_dois_above_match_threshold_is_check(self):
        """Two different DOIs at 0.9 or more: "Check", with the count."""
        result = search_with_scores([("10.1/a", 1.0), ("10.1/b", 0.91)])
        self.assertEqual(result["outcome"], "check")
        self.assertIsNone(result["citation"])
        self.assertIn("2 Crossref records", " ".join(result["reasons"]))

    def test_same_doi_twice_counts_once(self):
        """Crossref listing one DOI twice is still one paper: a match."""
        result = search_with_scores([("10.1/a", 0.95), ("10.1/A", 0.95)])
        self.assertEqual(result["outcome"], "match")

    def test_runner_up_within_margin_is_check(self):
        """Runner-up exactly 0.05 below the best (0.92 vs 0.87): "Check"."""
        result = search_with_scores([("10.1/a", 0.92), ("10.1/b", 0.87)])
        self.assertEqual(result["outcome"], "check")
        self.assertIn("runner-up", " ".join(result["reasons"]))

    def test_runner_up_just_outside_margin_is_match(self):
        """Runner-up 0.06 below the best (0.92 vs 0.86): the best is the match."""
        result = search_with_scores([("10.1/a", 0.92), ("10.1/b", 0.86)])
        self.assertEqual(result["outcome"], "match")
        self.assertEqual(result["citation"]["doi"], "10.1/a")

    def test_candidates_are_listed_best_first(self):
        """Check results list the nearest papers, best first, at most 5."""
        scores = [(f"10.1/{n}", 0.80 - n / 100) for n in range(8)]
        result = search_with_scores(scores)
        similarities = [c["title_similarity"] for c in result["candidates"]]
        self.assertEqual(len(similarities), 5)
        self.assertEqual(similarities, sorted(similarities, reverse=True))


class CrossrefTitles(unittest.TestCase):
    """Titles are read from Crossref without changing their words."""

    def test_line_breaks_in_titles_are_collapsed(self):
        """Crossref sometimes puts a line break and spaces inside a title."""
        item = crossref_item("Research Commentary\n                    —The New Logic", "10.1/a")
        citation = agent.format_citation(item)
        self.assertEqual(citation["title"], "Research Commentary —The New Logic")
        self.assertEqual(citation["original_title"], "Research Commentary —The New Logic")


class TitleSimilarity(unittest.TestCase):
    """Titles are compared after normalising (case, accents, punctuation)."""

    def test_case_and_punctuation_are_ignored(self):
        """The same title in different case and punctuation scores 1.0."""
        self.assertEqual(agent.title_similarity("Deep Learning!", "deep learning"), 1.0)

    def test_accents_and_html_are_ignored(self):
        """Accents and HTML tags don't count."""
        self.assertEqual(agent.title_similarity("<i>Résumé</i> study", "Resume study"), 1.0)


class ResolveLineWithoutDoi(unittest.TestCase):
    """A line with no DOI is searched by title and never matched silently."""

    def resolve(self, scores):
        """Resolve QUERY against fake Crossref results with the given scores."""
        items = [crossref_item(f"Title {doi}", doi) for doi, _ in scores]
        by_title = {f"Title {doi}": score for doi, score in scores}
        with mock.patch.object(agent, "get_json", lambda *a, **k: ({"message": {"items": items}}, None)), \
                mock.patch.object(agent, "title_similarity", lambda typed, found: by_title[found]), \
                mock.patch.object(agent, "cross_check", lambda citation: None):
            return agent.resolve_line(QUERY, "ref-test")

    def test_clear_match_fills_in_the_paper(self):
        """A clear match is used, like a DOI lookup."""
        entry = self.resolve([("10.1/a", 0.97), ("10.1/b", 0.30)])
        self.assertEqual(entry["doi"], "10.1/a")
        self.assertEqual(entry["title_search"]["outcome"], "match")

    def test_check_keeps_fields_empty_and_lists_candidates(self):
        """Several candidates: nothing filled in; status "check" with the candidates."""
        entry = self.resolve([("10.1/a", 0.95), ("10.1/b", 0.94)])
        self.assertEqual(entry["title"], "not stated")
        self.assertEqual(entry["doi"], "not stated")
        status, warnings = agent.verify(entry)
        self.assertEqual(status, "check")
        self.assertTrue(any("10.1/a" in w for w in warnings))
        self.assertTrue(any("10.1/b" in w for w in warnings))

    def test_no_plausible_match_is_not_found(self):
        """No candidate at 0.75 or more: status "not_found"."""
        entry = self.resolve([("10.1/a", 0.20)])
        self.assertEqual(entry["title"], "not stated")
        status, _ = agent.verify(entry)
        self.assertEqual(status, "not_found")

    def test_not_found_reason_names_the_closest_candidate(self):
        """"Not found" still reports the nearest paper, labelled as not accepted."""
        entry = self.resolve([("10.1/b", 0.40), ("10.1/a", 0.74)])
        self.assertEqual(entry["title"], "not stated")  # Still not used.
        self.assertEqual(entry["doi"], "not stated")
        status, warnings = agent.verify(entry)
        self.assertEqual(status, "not_found")
        reason = " ".join(warnings)
        self.assertIn("closest but below threshold, not accepted", reason.lower())
        # The best candidate (0.74), not the first result Crossref returned.
        self.assertIn("“Title 10.1/a” (2020), DOI 10.1/a, similarity 0.74", reason)
        self.assertNotIn("10.1/b", reason)

    def test_overrides_cannot_change_the_search_result(self):
        """title_search and verification are not editable fields."""
        entry = self.resolve([("10.1/a", 0.95), ("10.1/b", 0.94)])
        overrides = {"ref-test": {"title_search": {"outcome": "match"}, "verification": {"status": "verified"}}}
        merged = agent.apply_overrides(entry, overrides)
        self.assertEqual(merged["title_search"]["outcome"], "check")
        self.assertNotIn("verification", merged)
        with self.assertRaises(ValueError):
            agent.parse_value("title_search", "match")


class SentenceCase(unittest.TestCase):
    """APA 7 sentence case, following the rules in the spec."""

    def check(self, source, expected, uncertain=()):
        """Assert the sentence-case title and the flagged words."""
        text, flagged = agent.sentence_case(source)
        self.assertEqual(text, expected)
        self.assertEqual(flagged, list(uncertain))

    def test_title_case_is_lowercased(self):
        """Ordinary words in a Title Case title become lowercase."""
        self.check(
            "Perceived Usefulness, Perceived Ease of Use, and User Acceptance of Information Technology",
            "Perceived usefulness, perceived ease of use, and user acceptance of information technology",
        )

    def test_first_word_after_each_colon_is_capitalised(self):
        """The first word of the title and after every colon keeps its capital."""
        self.check(
            "Research Commentary: The New Organizing Logic of Digital Innovation: "
            "An Agenda for Information Systems Research",
            "Research commentary: The new organizing logic of digital innovation: "
            "An agenda for information systems research",
        )

    def test_lowercase_word_after_colon_gets_a_capital(self):
        """APA capitalises the first word after a colon even if the source didn't."""
        self.check("Deep learning: a review", "Deep learning: A review")

    def test_question_mark_starts_a_new_part(self):
        """A word after ? starts a new part of the title, like after a colon."""
        self.check("Is Privacy Dead? Evidence From Social Networks", "Is privacy dead? Evidence from social networks")

    def test_acronyms_are_kept(self):
        """All-caps words like MIS and IT keep their capitals."""
        self.check("Understanding MIS Success in IT Projects", "Understanding MIS success in IT projects")

    def test_acronym_with_numbers_is_kept(self):
        """COVID-19 is kept as it is."""
        self.check("COVID-19 and Remote Work Adoption", "COVID-19 and remote work adoption")

    def test_mixed_case_words_are_kept(self):
        """Words like iPhone and McDonald keep their casing."""
        self.check("Why iPhone Owners Visit McDonald Restaurants", "Why iPhone owners visit McDonald restaurants")

    def test_pronoun_i_is_kept(self):
        """The pronoun I stays a capital."""
        self.check("What I Learned From Teaching Statistics", "What I learned from teaching statistics")

    def test_sentence_case_source_keeps_its_proper_nouns(self):
        """A source already in sentence case: its capitals are proper nouns and are kept."""
        self.check("Deep learning in Australian hospitals", "Deep learning in Australian hospitals")

    def test_capital_after_hyphen_is_flagged(self):
        """Self-Efficacy in a Title Case title: lowercased but flagged as uncertain."""
        self.check(
            "Computer Self-Efficacy: Development of a Measure and Initial Test",
            "Computer self-efficacy: Development of a measure and initial test",
            uncertain=["Self-Efficacy"],
        )

    def test_yoo_title_em_dash_starts_a_new_part(self):
        """Spec 7.2 example (Yoo et al., 2010): the em dash loses its space,
        the next word is capitalised like after a colon, and it is flagged."""
        self.check(
            "Research Commentary —The New Organizing Logic of Digital Innovation: "
            "An Agenda for Information Systems Research",
            "Research commentary—The new organizing logic of digital innovation: "
            "An agenda for information systems research",
            uncertain=["Commentary—The"],
        )

    def test_spaced_em_dash_loses_its_spaces(self):
        """An em dash with spaces on both sides is joined up and the next word capitalised."""
        self.check(
            "Big Data Analytics — Promise and Peril for Organizations",
            "Big data analytics—Promise and peril for organizations",
            uncertain=["Analytics—Promise"],
        )

    def test_em_dash_in_sentence_case_source_is_still_flagged(self):
        """The em dash rule is an assumption, so it is flagged whatever the source casing."""
        self.check("Deep learning in hospitals — a review", "Deep learning in hospitals—A review",
                   uncertain=["hospitals—a"])

    def test_spaced_en_dash_is_left_unchanged(self):
        """A spaced en dash is kept as it is; the next word follows the ordinary rules."""
        self.check(
            "Big Data Analytics – Promise and Peril for Organizations",
            "Big data analytics – promise and peril for organizations",
        )

    def test_all_capitals_title_is_flagged(self):
        """A title written all in capitals can't be cased by code: kept and flagged."""
        source = "DEEP LEARNING FOR MEDICAL IMAGES"
        self.check(source, source, uncertain=[source])

    def test_proper_noun_in_title_case_is_not_flagged(self):
        """Option (b): a proper noun in a Title Case title is lowercased without a flag.

        Code can't recognise it; the spec leaves this to human review, with the
        original title shown next to the formatted one.
        """
        self.check("A Study of Facebook Users and Their Habits", "A study of facebook users and their habits")


class ApaReferenceTitles(unittest.TestCase):
    """Sentence case in formatted references and in the verification status."""

    def entry(self, title, **changes):
        """A complete journal article entry with the given title."""
        entry = agent.format_citation(crossref_item(title, "10.1/a", year=1989))
        entry.update({"id": "ref-test", "input": "10.1/a"}, **changes)
        return entry

    def test_apa_reference_uses_sentence_case(self):
        """APA article titles are in sentence case; the journal name is not changed."""
        entry = self.entry("Perceived Usefulness of Information Technology")
        text = agent.format_reference(entry, "apa")
        self.assertIn("(1989). Perceived usefulness of information technology. *Journal of Tests*", text)

    def test_other_styles_keep_the_original_title(self):
        """Chicago and Harvard keep the title as Crossref gives it."""
        entry = self.entry("Perceived Usefulness of Information Technology")
        self.assertIn("Perceived Usefulness of Information Technology", agent.format_reference(entry, "chicago"))
        self.assertIn("Perceived Usefulness of Information Technology", agent.format_reference(entry, "harvard"))

    def test_original_title_is_shown_when_different(self):
        """The original title is available to show next to the APA one."""
        entry = self.entry("Perceived Usefulness of Information Technology")
        self.assertEqual(agent.original_title_note(entry), "Perceived Usefulness of Information Technology")
        self.assertIsNone(agent.original_title_note(self.entry("Perceived usefulness of IT")))

    def test_uncertain_casing_marks_the_entry_check(self):
        """A flagged title gives a "check" warning naming the word."""
        entry = self.entry("Computer Self-Efficacy: Development of a Measure")
        _, warnings = agent.verify(entry)
        self.assertTrue(any("Self-Efficacy" in w for w in warnings))

    def test_em_dash_marks_the_entry_check(self):
        """Whenever the em dash rule is applied, verification says check."""
        entry = self.entry("Research Commentary —The New Organizing Logic of Digital Innovation")
        status, warnings = agent.verify(entry)
        self.assertEqual(status, "check")
        self.assertTrue(any("Commentary—The" in w for w in warnings))

    def test_spaced_en_dash_marks_the_entry_check(self):
        """A spaced en dash gives a "check" with its own reason."""
        entry = self.entry("Big Data Analytics – Promise and Peril for Organizations")
        status, warnings = agent.verify(entry)
        self.assertEqual(status, "check")
        self.assertIn("spaced en dash, review casing and punctuation", warnings)

    def test_hand_edited_title_is_used_as_typed(self):
        """A title corrected by hand is printed exactly as typed, with no casing flag."""
        entry = self.entry("Computer Self-Efficacy: Development of a Measure")
        merged = agent.apply_overrides(entry, {"ref-test": {"title": "Computer Self-Efficacy, as I Typed It"}})
        self.assertIn("Computer Self-Efficacy, as I Typed It.", agent.format_reference(merged, "apa"))
        self.assertEqual(agent.title_case_warnings(merged), [])


if __name__ == "__main__":
    unittest.main()
