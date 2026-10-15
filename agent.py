"""Literature research companion agent.

Two modes:

1. Paper mode: reads one paper (PDF), extracts the fields from
   notes/_template.md, looks for related papers in notes/, and writes one
   draft note to drafts/.

2. Refs mode: reads a list of references (one per line), looks up each DOI
   on Crossref (or searches Crossref by title when a line has no DOI), saves the metadata to refs/library.json, and writes a
   formatted reference list to refs/references.md. Hand corrections go in
   refs/overrides.json and are applied on top of the fetched metadata.
   It also writes drafts/references_apa.md: each reference in APA 7 with
   its status, warnings, and Google Scholar / Google search links.
   This mode is plain Python and does not call Claude.

Usage:
    python agent.py papers/some-paper.pdf
    python agent.py refs --input refs.txt [--style apa|chicago|harvard]
    python agent.py refs edit <id> --field year --value 2020 [--style ...]
    python agent.py refs chat
"""

import argparse
import asyncio
import difflib
import hashlib
import itertools
import json
import os
import re
import shutil
import sys
import textwrap
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

# Folder this script lives in, so paths work no matter where it is run from.
PROJECT_DIR = Path(__file__).resolve().parent
DRAFTS_DIR = PROJECT_DIR / "drafts"
REFS_DIR = PROJECT_DIR / "refs"
LIBRARY_PATH = REFS_DIR / "library.json"  # Metadata fetched from Crossref.
OVERRIDES_PATH = REFS_DIR / "overrides.json"  # Hand corrections, by id. Never overwritten.
OUTPUT_PATH = REFS_DIR / "references.md"  # The formatted reference list.
LAST_RUN_PATH = REFS_DIR / "last_run.json"  # Style and ids of the last list, for re-generating.
APA_REPORT_PATH = DRAFTS_DIR / "references_apa.md"  # APA list with status, warnings and search links.

# The only built-in tools the agent gets. No Bash, so it cannot run shell commands.
# Edit lets the agent fill in Connections after the draft is first written.
TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]

# Custom tools are named mcp__<server name>__<tool name>.
LIT_TOOLS = [
    "mcp__lit__lookup_paper",
    "mcp__lit__lookup_openalex",
    "mcp__lit__search_semantic_scholar",
]

# Free citation metadata APIs. None of them needs an API key.
CROSSREF_URL = "https://api.crossref.org/works/"
OPENALEX_URL = "https://api.openalex.org/works/https://doi.org/"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search/match"
# Semantic Scholar often rate-limits requests without a key. An optional free
# key (https://www.semanticscholar.org/product/api) can be set in this env var.
SEMANTIC_SCHOLAR_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")

# Titles at least this similar (0 to 1) count as the same title.
TITLE_AGREE_SCORE = 0.9

# Searching Crossref by title (a line with no DOI). These are decisions
# recorded in specs/goal-spec.md section 7:
# - best score below TITLE_WEAK_SCORE: "Not found" (no plausible match);
# - best score from TITLE_WEAK_SCORE up to (not including) 0.9: "Check" (weak);
# - several different DOIs at 0.9 or more: "Check";
# - runner-up within RUNNER_UP_MARGIN of the best: "Check" (too close to call);
# - otherwise the best one is the match.
CROSSREF_SEARCH_URL = "https://api.crossref.org/works?"
TITLE_WEAK_SCORE = 0.75
RUNNER_UP_MARGIN = 0.05
CANDIDATES_SHOWN = 5  # How many near misses to list for the student.

# Searching Crossref by author surname and year (the chat's `find`). Results
# are only candidates: verify() always marks them "check" with one of these
# reasons, so a search can never make a reference "verified".
AUTHOR_SEARCH_ROWS = 5
SEARCH_REASONS = {
    "result": "search result, not verified: pick the right one",
    "added": "added from a search; paste its DOI to verify",
}

# Search links stored with each reference. They are only built, never fetched.
SCHOLAR_SEARCH_URL = "https://scholar.google.com/scholar?q="
GOOGLE_SEARCH_URL = "https://www.google.com/search?q="

SYSTEM_PROMPT = """You are a literature research companion. You help a student
turn one research paper into a structured draft reading note.

Steps:
1. Read notes/_template.md to see the fields a note must have.
2. Read the paper at the path you are given.
3. Fill in each template field using only what the paper says.
   If the paper prints a DOI, call lookup_paper with it to get accurate
   citation metadata for the Citation field. Only use a DOI that appears in
   the paper; never guess one. If the lookup fails, build the citation from
   the paper alone. lookup_paper also checks the title, first author and year
   against OpenAlex and Semantic Scholar; for any field in its "disagree"
   list, use what the paper itself prints.
   lookup_openalex (by DOI) and search_semantic_scholar (by the title exactly
   as printed in the paper) give a second opinion when there is no DOI or
   Crossref fails. Only use a search result if its title_similarity is at
   least 0.9; otherwise ignore it.
4. Write exactly one draft note to drafts/, named after the paper,
   for example drafts/smith-2023-attention.md. For now, put "not stated"
   under each Connections line.
5. After the draft is written, compare it against the existing notes:
   - Use Glob to list notes/*.md (skip notes/_template.md) and Read each one.
     Use Grep to find notes that share key terms, methods, or datasets.
   - Supports: a note whose findings agree with this paper's findings.
   - Contradicts: a note whose findings disagree with this paper's findings.
   - Same dataset: a note about a paper that uses the same dataset.
6. Use Edit to update the Connections section of the draft. Cite the note
   each connection comes from by its file path, plus one short reason taken
   from both papers, in this format:
   - **Supports:** notes/jones-2021-transformers.md (both report X)
   Put several notes on one line separated by "; ". If no note fits a line,
   leave it as "not stated". Only cite notes you actually read, and only
   claim a connection that both the draft and the cited note clearly support.

Rules:
- Never write to notes/. Only write to drafts/.
- Never invent citations, claims, numbers, authors, or years. Every field must
  come from the paper itself, or from an existing note for Connections.
- If the paper does not give a field, write exactly: not stated
- Leave the "My reaction" section empty. It is for the student.
"""


def error_result(message):
    """Build a tool result that tells Claude the tool call failed."""
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def get_json(url, source, not_found, headers=None):
    """Download JSON from a URL.

    Returns (data, None) on success, or (None, error message) on failure.
    `not_found` is the message to use when the source has no record (HTTP 404).
    This is a normal (blocking) function, so the tools run it in a background
    thread to avoid freezing the agent while it waits.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": "research-companion (university assignment)", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response), None
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None, not_found
        if err.code == 429:
            return None, f"{source} is rate-limiting requests. Try again in a minute."
        return None, f"{source} returned HTTP error {err.code}."
    except urllib.error.URLError as err:
        return None, f"Could not reach {source} (network problem): {err.reason}"
    except (TimeoutError, json.JSONDecodeError) as err:
        return None, f"{source} lookup failed: {err}"


def format_citation(record):
    """Pick the citation fields out of a Crossref record.

    Any field Crossref does not have is set to "not stated", never guessed.
    """
    # Crossref stores titles and journal/book names as lists; take the first item.
    title = record.get("title") or ["not stated"]
    container = (record.get("container-title") or ["not stated"])[0]

    # Crossref says what kind of work it is. We format three kinds.
    crossref_type = record.get("type", "")
    if crossref_type == "book-chapter":
        work_type = "book-chapter"
    elif crossref_type in ("book", "monograph", "edited-book"):
        work_type = "book"
    elif crossref_type == "report":
        work_type = "report"
    else:
        work_type = "journal-article"

    # The year is the first number in "date-parts", e.g. [[2023, 5, 1]].
    date_parts = record.get("issued", {}).get("date-parts", [[None]])
    year = date_parts[0][0] if date_parts and date_parts[0] else None

    # Some titles contain HTML tags like <i>, or line breaks; remove them.
    clean_title = " ".join(re.sub(r"<[^>]+>", "", title[0]).split())

    return {
        "type": work_type,
        "title": clean_title,
        # The title exactly as Crossref gives it. It is not a citation field,
        # so overrides can't change it: it is shown next to the APA
        # sentence-case title, and tells us whether the title was hand-edited.
        "original_title": clean_title,
        "authors": people(record.get("author", [])),
        # Authors that are organisations have a "name" and no family name, so
        # people() leaves them out. Keep their names (not a citation field) so
        # the in-text citation can be marked Check instead of guessed.
        "organisation_authors": [a["name"] for a in record.get("author", []) if a.get("name") and not a.get("family")],
        "year": year or "not stated",
        # For a chapter the container is the book; otherwise it is the journal.
        "journal": container if work_type == "journal-article" else "not stated",
        "volume": record.get("volume", "not stated"),
        "issue": record.get("issue", "not stated"),
        "pages": record.get("page", "not stated"),
        "book_title": container if work_type == "book-chapter" else "not stated",
        "editors": people(record.get("editor", [])),
        "publisher": record.get("publisher", "not stated"),
        "place": record.get("publisher-location", "not stated"),
        "report_number": "not stated",
        "site_name": "not stated",
        "doi": record.get("DOI", "not stated"),
        "url": "not stated",  # The DOI link is used instead.
    }


def people(crossref_people):
    """Turn Crossref's author/editor list into [{"given": ..., "family": ...}].

    Both name parts are kept, because reference styles need the family name
    and initials separately. Returns "not stated" if there is nobody.
    """
    result = []
    for person in crossref_people:
        if person.get("family"):
            result.append({"given": person.get("given", ""), "family": person["family"]})
    return result or "not stated"


def clean_doi(doi):
    """Remove spaces and any "https://doi.org/" or "doi:" prefix from a DOI."""
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def doi_not_found_message(doi):
    """The message for a DOI Crossref has no record of (HTTP 404)."""
    return f"Crossref has no record for DOI '{doi}'. Check it was copied correctly."


def lookup_doi(doi):
    """Look up one DOI on Crossref.

    Returns (citation, None) on success, or (None, error message) on failure.
    Used by both the lookup_paper tool and refs mode.
    """
    # quote() makes characters like "/" in the DOI safe to put in a URL.
    data, error = get_json(
        CROSSREF_URL + urllib.parse.quote(doi), "Crossref", not_found=doi_not_found_message(doi),
    )
    if error:
        return None, error
    return format_citation(data["message"]), None


def lookup_openalex_doi(doi):
    """Look up one DOI on OpenAlex.

    Returns ({title, authors, year, venue, doi}, None) or (None, error message).
    """
    data, error = get_json(
        OPENALEX_URL + urllib.parse.quote(doi), "OpenAlex",
        not_found=f"OpenAlex has no record for DOI '{doi}'.",
    )
    if error:
        return None, error
    # The journal (or other venue) is inside "primary_location" -> "source".
    source = (data.get("primary_location") or {}).get("source") or {}
    return {
        "title": data.get("title") or "not stated",
        "authors": [a["author"]["display_name"] for a in data.get("authorships", [])] or "not stated",
        "year": data.get("publication_year") or "not stated",
        "venue": source.get("display_name") or "not stated",
        "doi": doi,
    }, None


def search_semantic_scholar_title(title):
    """Find the paper whose title best matches `title` on Semantic Scholar.

    Returns ({title, authors, year, venue, doi, title_similarity}, None) or
    (None, error message). title_similarity (0 to 1) is worked out in code
    and shows how close the found title is to the one searched for.
    """
    url = SEMANTIC_SCHOLAR_URL + "?" + urllib.parse.urlencode(
        {"query": title, "fields": "title,authors,year,venue,externalIds"}
    )
    headers = {"x-api-key": SEMANTIC_SCHOLAR_KEY} if SEMANTIC_SCHOLAR_KEY else {}
    not_found = f"Semantic Scholar found no paper matching the title '{title}'."
    data, error = get_json(url, "Semantic Scholar", not_found, headers)
    if error and "rate-limiting" in error:
        # Without a key, requests are often refused for a moment. Wait, try once more.
        time.sleep(3)
        data, error = get_json(url, "Semantic Scholar", not_found, headers)
    if error:
        return None, error
    if not data.get("data"):
        return None, not_found

    paper = data["data"][0]
    return {
        "title": paper.get("title") or "not stated",
        "authors": [a["name"] for a in paper.get("authors", [])] or "not stated",
        "year": paper.get("year") or "not stated",
        "venue": paper.get("venue") or "not stated",
        "doi": (paper.get("externalIds") or {}).get("DOI", "not stated"),
        "title_similarity": title_similarity(title, paper.get("title") or ""),
    }, None


# --- Comparing sources (done in code, not by the model) ---

def normalise(text):
    """Lowercase, drop accents, HTML tags and punctuation: "Ré-sumé!" -> "re sume"."""
    text = re.sub(r"<[^>]+>", "", str(text))
    # NFKD splits "é" into "e" + an accent mark; then drop the accent marks.
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def title_similarity(a, b):
    """How similar two titles are, from 0 (nothing alike) to 1 (the same).

    Uses difflib's SequenceMatcher, which compares the characters of the two
    normalised titles.
    """
    return round(difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio(), 2)


def same_person(family, full_name):
    """True if a full name like "Geoffrey E. Hinton" ends with the family name "Hinton"."""
    family, full_name = normalise(family), normalise(full_name)
    return bool(family) and (full_name == family or full_name.endswith(" " + family))


def cross_check(citation):
    """Compare Crossref's title, first author and year with OpenAlex and Semantic Scholar.

    OpenAlex is looked up by DOI; Semantic Scholar is searched by title.
    Returns what each source said, a per-field comparison, and lists of the
    fields that agree, disagree, or could not be checked.
    """
    has_doi = citation.get("doi") not in (None, "not stated")
    has_title = citation.get("title") not in (None, "not stated")
    others = {
        "openalex": lookup_openalex_doi(citation["doi"]) if has_doi else (None, "No DOI to look up."),
        "semantic_scholar": search_semantic_scholar_title(citation["title"]) if has_title else (None, "No title to search for."),
    }

    # A title search can find a different paper with a similar title (e.g. a
    # book also called "Deep learning"). If its DOI differs from ours, it's not
    # the same paper, so it can't tell us anything: leave it out.
    found, _ = others["semantic_scholar"]
    if found and has_doi and found["doi"] != "not stated" and found["doi"].lower() != citation["doi"].lower():
        others["semantic_scholar"] = (None, f"Title search found a different paper (DOI {found['doi']}).")

    # What Crossref says, used as the baseline.
    authors = citation.get("authors")
    crossref = {
        "title": citation.get("title"),
        "first_author": authors[0]["family"] if isinstance(authors, list) and authors else "not stated",
        "year": citation.get("year"),
    }
    result = {"sources": {"crossref": crossref}, "fields": {}, "agree": [], "disagree": [], "unchecked": []}

    # Keep a short summary of what each other source said (or why it failed).
    for name, (found, error) in others.items():
        if found is None:
            result["sources"][name] = {"error": error}
        else:
            other_authors = found["authors"]
            result["sources"][name] = {
                "title": found["title"],
                "first_author": other_authors[0] if isinstance(other_authors, list) else "not stated",
                "year": found["year"],
            }

    # Compare each field against Crossref, source by source.
    for field in ("title", "first_author", "year"):
        comparisons = {}
        for name, said in result["sources"].items():
            if name == "crossref" or "error" in said:
                continue
            ours, theirs = crossref[field], said[field]
            if "not stated" in (ours, theirs) or None in (ours, theirs):
                continue  # Nothing to compare.
            if field == "title":
                score = title_similarity(ours, theirs)
                comparisons[name] = {"value": theirs, "score": score, "agree": score >= TITLE_AGREE_SCORE}
            elif field == "first_author":
                comparisons[name] = {"value": theirs, "agree": same_person(ours, theirs)}
            else:
                comparisons[name] = {"value": theirs, "agree": str(ours) == str(theirs)}

        result["fields"][field] = comparisons
        if not comparisons:
            result["unchecked"].append(field)
        elif all(c["agree"] for c in comparisons.values()):
            result["agree"].append(field)
        else:
            result["disagree"].append(field)
    return result


def tool_json(data):
    """Build a successful tool result containing JSON."""
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}]}


@tool(
    "lookup_paper",
    "Look up citation metadata (title, authors, year, journal, etc.) for a "
    "DOI using the Crossref API, and cross-check the title, first author and "
    "year against OpenAlex and Semantic Scholar. Only pass a DOI printed in the paper.",
    {"doi": str},
)
async def lookup_paper(args):
    """Custom tool: fetch citation metadata for one DOI from Crossref, then cross-check it."""
    doi = clean_doi(args.get("doi", ""))
    if not doi:
        return error_result("No DOI given. Pass a DOI like 10.1000/xyz123.")

    # These functions wait on the network, so run them in a background thread.
    citation, error = await asyncio.to_thread(lookup_doi, doi)
    if error:
        return error_result(error)
    check = await asyncio.to_thread(cross_check, citation)
    return tool_json({"crossref": citation, "cross_check": check})


@tool(
    "lookup_openalex",
    "Look up a DOI on OpenAlex: title, authors, year, venue. Only pass a DOI printed in the paper.",
    {"doi": str},
)
async def lookup_openalex(args):
    """Custom tool: fetch metadata for one DOI from OpenAlex."""
    doi = clean_doi(args.get("doi", ""))
    if not doi:
        return error_result("No DOI given. Pass a DOI like 10.1000/xyz123.")
    found, error = await asyncio.to_thread(lookup_openalex_doi, doi)
    return error_result(error) if error else tool_json(found)


@tool(
    "search_semantic_scholar",
    "Search Semantic Scholar for the paper best matching a title. Returns its "
    "title, authors, year, venue, DOI and a title_similarity score (0 to 1). "
    "Pass the title exactly as printed in the paper.",
    {"title": str},
)
async def search_semantic_scholar(args):
    """Custom tool: find a paper on Semantic Scholar by title."""
    title = args.get("title", "").strip()
    if not title:
        return error_result("No title given.")
    found, error = await asyncio.to_thread(search_semantic_scholar_title, title)
    return error_result(error) if error else tool_json(found)


# Bundle the custom tools into an in-process MCP server named "lit".
LIT_SERVER = create_sdk_mcp_server(name="lit", tools=[lookup_paper, lookup_openalex, search_semantic_scholar])


async def only_write_to_drafts(input_data, tool_use_id, context):
    """Hook that runs before every Write or Edit call.

    Blocks the change unless the target file is inside drafts/. This enforces
    the drafts-only rule in code, so it holds even if the model ignores the
    system prompt.
    """
    file_path = input_data["tool_input"].get("file_path", "")

    # Resolve the path so tricks like "drafts/../notes/x.md" are caught.
    target = (PROJECT_DIR / file_path).resolve()

    if target.is_relative_to(DRAFTS_DIR):
        return {}  # Empty result means "no objection", so the write goes ahead.

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "You may only write files inside drafts/.",
        }
    }


async def main():
    """Check the command-line argument, run the agent, and print its output."""
    # 1. Get the PDF path from the command line.
    if len(sys.argv) != 2:
        print("Usage: python agent.py <path-to-paper.pdf>")
        print("   or: python agent.py refs --input refs.txt [--style apa|chicago|harvard]")
        sys.exit(1)

    pdf_path = Path(sys.argv[1]).resolve()
    if not pdf_path.is_file():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    # 2. Configure the agent.
    options = ClaudeAgentOptions(
        model="claude-opus-5-5",
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,  # The only tools that exist for the agent.
        mcp_servers={"lit": LIT_SERVER},  # Adds our custom lookup_paper tool.
        # Run these without asking for permission each time.
        allowed_tools=TOOLS + LIT_TOOLS,
        disallowed_tools=["Bash"],  # Extra safety: Bash is never available.
        cwd=str(PROJECT_DIR),  # Relative paths like drafts/ resolve here.
        hooks={
            # Check every Write and Edit call before it runs ("|" means "or").
            "PreToolUse": [HookMatcher(matcher="Write|Edit", hooks=[only_write_to_drafts])],
        },
    )

    prompt = f"Create a draft note for the paper at: {pdf_path}"

    # 3. Run the agent and print what it says and which tools it calls.
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    print(f"[tool] {block.name}: {block.input}")
        elif isinstance(message, ResultMessage):
            # The last message: says whether the run succeeded and what it cost.
            print(f"\nDone. Error: {message.is_error}. Cost: ${message.total_cost_usd}")


# ---------------------------------------------------------------------------
# Refs mode: python agent.py refs --input refs.txt [--style apa|chicago|harvard]
# ---------------------------------------------------------------------------

STYLES = {"apa": "APA 7th", "chicago": "Chicago 17th (bibliography)", "harvard": "Harvard (Cite Them Right)"}

# A DOI always starts with "10.", then a number, a slash, and the rest.
DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+")


def find_doi(line):
    """Return the DOI in a line of text, or None if there isn't one."""
    match = DOI_PATTERN.search(line)
    if not match:
        return None
    # Drop punctuation that ends the sentence rather than the DOI.
    return match.group(0).rstrip(".,;)]")


def make_id(line):
    """Make a stable id for a reference, so re-runs find the same entry.

    The id comes from the DOI (or the line itself if there is no DOI), so the
    same source always gets the same id, whatever order the file is in.
    """
    doi = find_doi(line)
    key = doi.lower() if doi else " ".join(line.lower().split())
    return "ref-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


# The kinds of source we can format, with the names used in messages.
TYPE_NAMES = {
    "journal-article": "journal article",
    "book": "book",
    "book-chapter": "book chapter",
    "report": "report",
    "webpage": "webpage",
}
WORK_TYPES = list(TYPE_NAMES)

# Every citation field. All of them can be corrected with "refs edit".
CITATION_FIELDS = [
    "type", "title", "authors", "year", "journal", "volume", "issue", "pages",
    "book_title", "editors", "publisher", "place", "report_number", "site_name",
    "doi", "url",
    # The whole reference typed by hand (from the Streamlit app). When set, it
    # is printed exactly as typed instead of being built from the fields above.
    "reference_text",
]

# Fields whose meaning depends on the type (cleared when the type changes).
TYPE_SPECIFIC_FIELDS = [
    "journal", "volume", "issue", "pages", "book_title", "editors",
    "publisher", "place", "report_number", "site_name",
]

# Fields APA 7 requires for each type of source. The chat asks the student
# for any that are missing instead of guessing them. (For a report or
# webpage, the author can be an organisation, e.g. "World Health Organization".)
APA7_REQUIRED = {
    "journal-article": ["authors", "year", "title", "journal", "volume", "pages"],
    "book": ["authors", "year", "title", "publisher"],
    "book-chapter": ["authors", "year", "title", "editors", "book_title", "pages", "publisher"],
    "report": ["authors", "year", "title", "publisher"],
    "webpage": ["authors", "year", "title", "site_name", "url"],
}


def missing_fields(entry, style):
    """List the required fields this entry has no value for."""
    required = list(APA7_REQUIRED[entry.get("type", "journal-article")])
    # Chicago and Harvard also give the place of publication for books and reports.
    if style != "apa" and entry.get("type") in ("book", "book-chapter", "report"):
        required.append("place")
    return [field for field in required if not stated(entry.get(field))]


def validate_reference(metadata, source_type):
    """Check a reference against APA 7's requirements for its source type.

    Returns a list of warnings (empty if everything needed is there and
    looks right). Only checks what code can check: missing fields and
    obviously wrong formats. It never fills anything in.
    """
    if source_type not in APA7_REQUIRED:
        return [f"Unknown source type '{source_type}'. Types: {', '.join(WORK_TYPES)}."]
    type_name = TYPE_NAMES[source_type]
    warnings = []

    # 1. Required fields.
    for field in APA7_REQUIRED[source_type]:
        if not stated(metadata.get(field)):
            warnings.append(f"Missing {field.replace('_', ' ')} (APA 7 needs it for a {type_name}).")

    # 2. Formats of the fields that are there.
    year = metadata.get("year")
    if stated(year) and not re.fullmatch(r"(1[5-9]|20)\d\d", str(year)):
        warnings.append(f"Year '{year}' doesn't look like a year.")

    for field in ("authors", "editors"):
        names = metadata.get(field)
        if stated(names) and not (isinstance(names, list) and all(p.get("family") for p in names)):
            warnings.append(f"{field.capitalize()} are not in 'Family, Given; Family, Given' form.")

    pages = metadata.get("pages")
    # "45-67", "45–67", "e1002" (article number), or a single page "12".
    if stated(pages) and not re.fullmatch(r"[A-Za-z]?\d+([-–][A-Za-z]?\d+)?", str(pages)):
        warnings.append(f"Pages '{pages}' should look like 45-67 or an article number.")

    doi = metadata.get("doi")
    if stated(doi) and not DOI_PATTERN.fullmatch(str(doi)):
        warnings.append(f"DOI '{doi}' doesn't look like a DOI (they start with 10.).")

    url = metadata.get("url")
    if stated(url) and not str(url).startswith(("http://", "https://")):
        warnings.append(f"URL '{url}' should start with http:// or https://.")

    # 3. APA 7 includes a DOI for a journal article whenever one exists.
    if source_type == "journal-article" and not stated(doi):
        warnings.append("No DOI. APA 7 includes one whenever the article has one; check.")

    return warnings


def load_json(path, empty):
    """Read a JSON file, or return `empty` if the file doesn't exist yet."""
    if not path.exists():
        return empty
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        # Stop rather than overwrite the file and lose hand edits.
        print(f"{path} is not valid JSON ({err}). Fix it and run again.")
        sys.exit(1)


def save_json(path, data):
    """Write data to a JSON file, creating refs/ if needed."""
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_library():
    """Read refs/library.json: a list of entries fetched from Crossref."""
    return load_json(LIBRARY_PATH, [])


def load_overrides():
    """Read refs/overrides.json: {id: {field: corrected value}}."""
    return load_json(OVERRIDES_PATH, {})


def apply_overrides(entry, overrides):
    """Return a copy of the entry with any hand corrections laid on top.

    The library entry itself is not changed, so the fetched value is still
    there if an override is later removed. Only citation fields can be
    overridden, so an override can never set the verification status.
    """
    merged = dict(entry)
    for field, new_value in overrides.get(entry["id"], {}).items():
        if field in CITATION_FIELDS:
            merged[field] = new_value
    return merged


# --- Finding a paper by its title (refs mode and chat.py) ---

def search_crossref_title(title):
    """Search Crossref for a title and decide, in code, whether one paper matches.

    Crossref always returns its nearest papers, even for a made-up title, so
    each result is scored with title_similarity and the rules at the top of
    this file (TITLE_WEAK_SCORE, TITLE_AGREE_SCORE, RUNNER_UP_MARGIN) decide.
    Returns (result, None) or (None, error message). result is:
        {"outcome": "match" | "check" | "not_found",
         "citation": the matched paper's metadata (only for "match"),
         "reasons": why it is "check" or "not_found",
         "candidates": the nearest papers, best first}
    A paper is never picked unless it is clearly the only good match.
    """
    # 20 results, because the right paper is often not in Crossref's top 5.
    query = urllib.parse.urlencode({"query.bibliographic": title, "rows": 20})
    data, error = get_json(CROSSREF_SEARCH_URL + query, "Crossref", not_found="Crossref found nothing.")
    if error:
        return None, error

    # 1. Score every result, keeping each DOI once (Crossref sometimes
    #    repeats a record). Records without a DOI are all kept.
    best_by_doi = {}
    for number, item in enumerate(data.get("message", {}).get("items", [])):
        citation = format_citation(item)
        score = title_similarity(title, citation["title"])
        key = citation["doi"].lower() if stated(citation["doi"]) else f"no-doi-{number}"
        if key not in best_by_doi or score > best_by_doi[key][0]:
            best_by_doi[key] = (score, citation)
    scored = sorted(best_by_doi.values(), key=lambda pair: pair[0], reverse=True)

    candidates = [
        {"title": c["title"], "year": c["year"], "doi": c["doi"], "title_similarity": score}
        for score, c in scored[:CANDIDATES_SHOWN]
    ]
    result = {"outcome": "not_found", "citation": None, "reasons": [], "candidates": candidates}

    # 2. No plausible match: nothing scores at least TITLE_WEAK_SCORE.
    best = scored[0][0] if scored else 0
    if best < TITLE_WEAK_SCORE:
        result["reasons"] = [
            f"No Crossref title is close enough to this one (best similarity {best}, "
            f"needs {TITLE_WEAK_SCORE} to be worth checking)."
        ]
        # Show the nearest paper anyway so the student can see what was rejected.
        # It is only reported, never used: the thresholds stay as they are.
        if scored:
            closest = candidates[0]
            result["reasons"].append(
                f"Closest but below threshold, not accepted: “{closest['title']}” "
                f"({closest['year']}), DOI {closest['doi']}, similarity {closest['title_similarity']}."
            )
        return result, None

    # 3. Reasons not to pick the best one by itself.
    reasons = []
    if best < TITLE_AGREE_SCORE:
        reasons.append(f"The closest Crossref title is only a weak match (similarity {best}, below {TITLE_AGREE_SCORE}).")
    strong = [score for score, _ in scored if score >= TITLE_AGREE_SCORE]
    if len(strong) > 1:
        reasons.append(f"{len(strong)} Crossref records have this title (similarity {TITLE_AGREE_SCORE} or more). Paste the DOI.")
    elif len(scored) > 1:
        runner_up = scored[1][0]
        # Round the gap, because 0.92 - 0.87 is 0.05000000000000004 in floating point.
        if round(best - runner_up, 2) <= RUNNER_UP_MARGIN:
            reasons.append(
                f"The runner-up (similarity {runner_up}) is within {RUNNER_UP_MARGIN} "
                f"of the best match ({best}), so it is too close to call."
            )

    # 4. Check if there is any reason; otherwise the best one is the match.
    if reasons:
        result["outcome"], result["reasons"] = "check", reasons
    else:
        result["outcome"], result["citation"] = "match", scored[0][1]
    return result, None


def candidate_lines(candidates):
    """Describe candidate papers for a warning: “Title” (year), DOI, similarity."""
    return [
        f"Candidate: “{c['title']}” ({c['year']}), DOI {c['doi']}, similarity {c['title_similarity']}."
        for c in candidates
    ]


def search_crossref_author_year(surname, year, topic=""):
    """Search Crossref for works by `surname` published in `year`.

    `topic` (optional words) narrows the results. Crossref decides what
    matches; nothing is re-ranked or filtered here (no author disambiguation).
    Returns (list of citations, None), at most AUTHOR_SEARCH_ROWS of them in
    Crossref's order, or (None, error message) if Crossref couldn't be asked.
    """
    # Author and year filter; topic words only when there are any.
    params = {
        "query.author": surname,
        "filter": f"from-pub-date:{year},until-pub-date:{year}",
        "rows": AUTHOR_SEARCH_ROWS,
    }
    if topic:
        params["query.bibliographic"] = topic
    url = CROSSREF_SEARCH_URL + urllib.parse.urlencode(params)
    data, error = get_json(url, "Crossref", not_found="Crossref found nothing.")
    if error:
        return None, error
    # Pick the citation fields out of each record, keeping Crossref's order.
    items = data.get("message", {}).get("items", [])[:AUTHOR_SEARCH_ROWS]
    return [format_citation(item) for item in items], None


def resolve_line(line, ref_id, cross_check_sources=True):
    """Build a library entry for one line of the input file.

    A line with a DOI is looked up by DOI. A line without one is searched on
    Crossref by title, and only a clear match (see search_crossref_title) is
    used. Otherwise all its fields stay "not stated" and the search result
    (reasons and candidates) is stored under "title_search" for verify().

    cross_check_sources=False skips OpenAlex and Semantic Scholar, so only
    Crossref is contacted (the Streamlit chat). If Crossref could not be
    reached at all (not a 404), the entry gets "lookup_unavailable": True.
    """
    entry = {"id": ref_id, "status": "auto", "input": line}
    empty = {field: "not stated" for field in CITATION_FIELDS}
    empty["type"] = "journal-article"

    doi = find_doi(line)
    if not doi:
        search, error = search_crossref_title(line)
        if error:
            entry.update(empty)
            entry["lookup_error"] = error
            entry["lookup_unavailable"] = True  # The search itself failed.
            return entry
        # Stored on the entry, outside the citation fields, so no override can change it.
        entry["title_search"] = {
            "outcome": search["outcome"],
            "reasons": search["reasons"],
            "candidates": search["candidates"],
        }
        if search["outcome"] != "match":
            # "check" or "not_found": never fill in a paper we aren't sure of.
            entry.update(empty)
            entry["lookup_error"] = " ".join(search["reasons"])
            return entry
        entry.update(search["citation"])
        if cross_check_sources:
            entry["cross_check"] = cross_check(search["citation"])
        return entry

    citation, error = lookup_doi(clean_doi(doi))
    if error:
        entry.update(empty)
        entry["doi"] = doi
        entry["lookup_error"] = error
        # Anything but "no record" means Crossref could not be reached.
        if error != doi_not_found_message(clean_doi(doi)):
            entry["lookup_unavailable"] = True
    else:
        entry.update(citation)
        # Compare title, first author and year with OpenAlex and Semantic Scholar.
        if cross_check_sources:
            entry["cross_check"] = cross_check(citation)
    return entry


# --- Helpers for formatting references ---

def stated(value):
    """True if a field has a real value (not missing and not "not stated")."""
    return value not in (None, "", "not stated", [])


def end_with_period(text):
    """Add a full stop unless the text already ends with . ? or !"""
    return text if text.endswith((".", "?", "!")) else text + "."


def initials(given, spaced=True):
    """Turn given names into initials: "Geoffrey E." -> "G. E." (or "G.E.")."""
    parts = []
    for name in given.split():
        # Hyphenated names keep the hyphen: "Jean-Paul" -> "J.-P."
        parts.append("-".join(piece[0] + "." for piece in name.split("-") if piece))
    return (" " if spaced else "").join(parts)


def join_names(names, last_joiner):
    """Join names as "A, B, and C" style lists. last_joiner is e.g. ", & "."""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + last_joiner + names[-1]


def authors_apa(authors):
    """APA 7: "Family, G. G., Family, G., & Family, G." (up to 20 authors)."""
    names = [f"{a['family']}, {initials(a['given'])}".rstrip(", ") for a in authors]
    if len(names) > 20:
        # APA 7: first 19 authors, an ellipsis, then the last author.
        return ", ".join(names[:19]) + ", . . . " + names[-1]
    if len(names) == 2:
        return names[0] + ", & " + names[1]
    return join_names(names, ", & ")


def authors_chicago(authors):
    """Chicago: first author "Family, Given", the rest "Given Family"."""
    first = f"{authors[0]['family']}, {authors[0]['given']}".rstrip(", ")
    rest = [f"{a['given']} {a['family']}".strip() for a in authors[1:]]
    # Chicago 17: more than 10 authors -> list the first 7, then "et al."
    if len(authors) > 10:
        return ", ".join([first] + rest[:6]) + ", et al"
    if not rest:
        return first
    if len(rest) == 1:
        return f"{first}, and {rest[0]}"
    return join_names([first] + rest, ", and ")


def authors_harvard(people_list):
    """Harvard: "Family, G., Family, G. and Family, G." (also used for editors)."""
    names = [f"{a['family']}, {initials(a['given'], spaced=False)}".rstrip(", ") for a in people_list]
    return join_names(names, " and ")


def editors_apa(editors):
    """APA 7 editors inside a chapter reference: "E. E. Editor & F. Editor"."""
    names = [f"{initials(e['given'])} {e['family']}".strip() for e in editors]
    if len(names) == 2:
        return names[0] + " & " + names[1]
    return join_names(names, ", & ")


def editors_chicago(editors):
    """Chicago editors: "Given Family and Given Family"."""
    names = [f"{e['given']} {e['family']}".strip() for e in editors]
    if len(names) == 2:
        return names[0] + " and " + names[1]
    return join_names(names, ", and ")


def value(entry, field):
    """Return a field's value, or None if it is missing or "not stated"."""
    return entry.get(field) if stated(entry.get(field)) else None


def place_and_publisher(entry):
    """"Place: Publisher", or whichever of the two is known (or None)."""
    known = [part for part in (value(entry, "place"), value(entry, "publisher")) if part]
    return ": ".join(known) or None


# --- APA 7 sentence case for article titles ---
# APA capitalises only the first word, the first word after a colon (or ? or !),
# and proper nouns. Code can't recognise proper nouns, so the rules are
# (decisions in specs/goal-spec.md section 7.2):
# - all-caps words (MIS, IT, COVID-19, 3D) and mixed-case words (iPhone,
#   McDonald) are kept exactly as they are;
# - if the source title is already in sentence case, its capitalised words
#   are taken to be proper nouns and kept;
# - if it is in Title Case, the other capitalised words are lowercased. Only
#   the cases code can see are unclear are flagged: a capital after a hyphen
#   (Self-Efficacy) or after a dash (Big Data — Promise), and a title written
#   all in capitals. Other proper nouns are left to a human to check.
# - an em dash loses its spaces and the word after it is capitalised, like
#   after a colon. This is an assumption (not confirmed against the APA
#   manual or the course guide), so it is always flagged;
# - a spaced en dash (" – ") is left as it is, but flagged for review
#   (see title_case_warnings).

SUBTITLE_MARKS = (":", "?", "!")  # The next word starts a new part of the title.
DASHES = ("--", "-")  # Dashes written as their own word, e.g. "Data -- Promise".
EM_DASH = "—"
SPACED_EN_DASH_REASON = "spaced en dash, review casing and punctuation"


def letters_of(text):
    """The letters in a piece of text: "COVID-19" -> "COVID"."""
    return "".join(c for c in text if c.isalpha())


def keeps_its_case(part):
    """True for words whose casing is never changed.

    All capitals (MIS, IT, COVID, 3D), mixed case (iPhone, McDonald, LaTeX),
    and the pronoun "I".
    """
    letters = letters_of(part)
    if not letters:
        return True  # Numbers and symbols have no case.
    if letters == "I":
        return True
    if letters.isupper() and (len(letters) >= 2 or any(c.isdigit() for c in part)):
        return True
    # A capital anywhere after the first letter means mixed case.
    return any(c.isupper() for c in letters[1:])


def is_capitalised(part):
    """True for an ordinary capitalised word like "Usefulness" (not MIS, not iPhone)."""
    letters = letters_of(part)
    return bool(letters) and letters[0].isupper() and not keeps_its_case(part)


def split_title(title):
    """Split a title into word pieces, noting what comes before each one.

    Returns a list of dicts: {"word": the whole word as in the source,
    "core": the word without the punctuation around it,
    "lead"/"trail": that punctuation, "pieces": [(joiner, text)], where
    joiner is "" for the first piece, "-" after a hyphen or a dash character,
    "starts": True if the word starts the title or follows a colon, ? or !,
    "after_dash": True if the word follows a dash written as its own word}.
    """
    words = []
    starts, after_dash = True, False
    for word in title.split():
        # Punctuation around the word, e.g. "(MIS)," -> "(", "MIS", "),".
        match = re.fullmatch(r"(\W*)(.*?)(\W*)", word)
        lead, core, trail = match.groups()
        if not core:
            # A word that is only punctuation, like "—" or "&".
            words.append({"word": word, "core": "", "lead": word, "trail": "", "pieces": [],
                          "starts": False, "after_dash": False})
            after_dash = word in DASHES
            starts = starts or word.endswith(SUBTITLE_MARKS)
            continue
        # Hyphens and dashes inside the word: "Self-Efficacy" -> "Self", "-", "Efficacy".
        bits = re.split(r"([-–—])", core)
        pieces = [("", bits[0])] + [(bits[i], bits[i + 1]) for i in range(1, len(bits), 2)]
        # A dash can also be written against the word: "Data –Promise".
        after_dash = after_dash or "–" in lead
        words.append({"word": word, "core": core, "lead": lead, "trail": trail, "pieces": pieces,
                      "starts": starts, "after_dash": after_dash})
        starts = trail.endswith(SUBTITLE_MARKS)
        after_dash = False
    return words


def looks_title_case(words):
    """True if the title is written in Title Case rather than sentence case.

    Looks at ordinary words of 4+ letters that don't start the title or a
    subtitle (short words like "of" are lowercase in Title Case too): if
    more than half are capitalised, it is Title Case.
    """
    # Words after an em dash start a new part too, so they are skipped.
    checked = [
        text for w in words if not w["starts"]
        for joiner, text in w["pieces"]
        if joiner != EM_DASH and len(letters_of(text)) >= 4 and not keeps_its_case(text)
    ]
    capitalised = [text for text in checked if is_capitalised(text)]
    return bool(checked) and len(capitalised) / len(checked) > 0.5


def sentence_case(title):
    """Put a title into APA 7 sentence case.

    Returns (new title, uncertain words). uncertain lists the source words
    whose casing code could not be sure of, so the entry is marked "check".
    Example: "Computer Self-Efficacy: Development of a Measure" ->
    ("Computer self-efficacy: Development of a measure", ["Self-Efficacy"]).
    """
    # Em dashes are written with no spaces: "Commentary —The" -> "Commentary—The".
    # The word after it then becomes a piece joined by "—" (see split_title).
    title = re.sub(r"\s*" + EM_DASH + r"\s*", EM_DASH, title)
    words = split_title(title)
    title_case = looks_title_case(words)
    uncertain = []

    # A title written all in capitals keeps them (they look like acronyms),
    # but code can't tell which words really are acronyms.
    long_words = [text for w in words for _, text in w["pieces"] if len(letters_of(text)) >= 2]
    if len(long_words) >= 3 and all(letters_of(t).isupper() for t in long_words):
        uncertain.append(title)

    result = []
    for w in words:
        if not w["pieces"]:
            result.append(w["word"])  # Punctuation only: unchanged.
            continue
        new_pieces = []
        for number, (joiner, text) in enumerate(w["pieces"]):
            first_of_part = w["starts"] and number == 0
            if keeps_its_case(text):
                new_text = text
            elif joiner == EM_DASH:
                # After an em dash: capitalised like after a colon (an
                # assumption in the spec), so always flagged for review.
                new_text = text[0].upper() + text[1:]
                if w["core"] not in uncertain:
                    uncertain.append(w["core"])
            elif first_of_part:
                new_text = text[0].upper() + text[1:]  # First word of the title or subtitle.
            elif title_case:
                new_text = text.lower()
                # Lowercased after a hyphen or dash: could be a proper noun.
                after_dash = (number == 0 and w["after_dash"]) or joiner == "–"
                if is_capitalised(text) and (joiner == "-" or after_dash):
                    if w["core"] not in uncertain:
                        uncertain.append(w["core"])
            else:
                new_text = text  # Sentence case already: a capital means a proper noun.
            new_pieces.append(joiner + new_text)
        result.append(w["lead"] + "".join(new_pieces) + w["trail"])
    return " ".join(result), uncertain


def title_edited_by_hand(entry):
    """True if the student corrected the title (it differs from Crossref's)."""
    return entry["title"] != entry.get("original_title", entry["title"])


def apa_title(entry):
    """An article's title for APA 7: (title, uncertain words).

    A title the student corrected by hand is used exactly as typed, with
    nothing flagged.
    """
    if title_edited_by_hand(entry):
        return entry["title"], []
    return sentence_case(entry["title"])


def title_case_warnings(entry):
    """Warnings if code isn't sure of the APA casing of an article's title."""
    if entry.get("type", "journal-article") != "journal-article" or not stated(entry.get("title")):
        return []
    warnings = []
    _, uncertain = apa_title(entry)
    if uncertain:
        words_text = ", ".join(f"“{word}”" for word in uncertain)
        warnings.append(f"Title casing is uncertain for {words_text}: compare the APA title with the original title.")
    # A spaced en dash is left as it is but often stands in for an em dash.
    # A title corrected by hand is used as typed, so it is not flagged.
    if not title_edited_by_hand(entry) and re.search(r"\s–\s", entry["title"]):
        warnings.append(SPACED_EN_DASH_REASON)
    return warnings


def original_title_note(entry):
    """The original title, if the APA title shows it differently (else None).

    Used to show the original next to the sentence-case title.
    """
    if (entry.get("type", "journal-article") != "journal-article" or not stated(entry.get("title"))
            or stated(entry.get("reference_text"))):
        return None
    original = entry.get("original_title", entry["title"])
    return original if apa_title(entry)[0] != original else None


def format_reference(entry, style):
    """Format one entry in the chosen style.

    Missing parts are left out instead of being guessed. Italics use
    Markdown *asterisks*. In APA, article titles are put into sentence
    case (see sentence_case); other titles are printed as given.
    A hand-typed reference_text is used exactly as typed, in every style.
    """
    if stated(entry.get("reference_text")):
        return entry["reference_text"]
    if not stated(entry.get("title")):
        return f"[not resolved] {entry['input']}  ({entry.get('lookup_error', 'no title')})"

    # Values shared by every type and style.
    authors = value(entry, "authors")
    year = value(entry, "year")
    # Page ranges use an en dash: 436-444 -> 436–444
    pages = str(entry["pages"]).replace("-", "–") if value(entry, "pages") else None
    # The link at the end: the DOI if there is one, otherwise the URL.
    link = f"https://doi.org/{entry['doi']}" if value(entry, "doi") else value(entry, "url")

    # Author part, e.g. "LeCun, Y., & Hinton, G." (APA) - empty if unknown.
    if not authors:
        author_text = ""
    elif style == "apa":
        author_text = end_with_period(authors_apa(authors)) + " "
    elif style == "chicago":
        author_text = end_with_period(authors_chicago(authors)) + " "
    else:
        author_text = authors_harvard(authors) + " "

    work_type = entry.get("type", "journal-article")
    if work_type == "book-chapter":
        body = format_chapter(entry, style, year, pages)
    elif work_type == "book":
        body = format_book(entry, style, year)
    elif work_type == "report":
        body = format_report(entry, style, year)
    elif work_type == "webpage":
        body = format_webpage(entry, style, year)
    else:
        body = format_article(entry, style, year, pages)

    text = author_text + body
    if link:
        text += {"apa": f" {link}", "chicago": f" {link}.", "harvard": f" Available at: {link}."}[style]
    return text


def format_article(entry, style, year, pages):
    """Everything after the authors for a journal article."""
    title, journal = entry["title"], value(entry, "journal")
    volume, issue = value(entry, "volume"), value(entry, "issue")

    if style == "apa":
        # (Year). Title. *Journal*, *Vol*(Issue), pages. The title is in sentence case.
        title = apa_title(entry)[0]
        text = f"({year or 'n.d.'}). {end_with_period(title)}"
        if journal:
            text += f" *{journal}*"
            if volume:
                text += f", *{volume}*" + (f"({issue})" if issue else "")
            if pages:
                text += f", {pages}"
            text += "."
        return text

    if style == "chicago":
        # "Title." *Journal* Vol, no. Issue (Year): pages.
        text = f"“{end_with_period(title)}”"
        if journal:
            text += f" *{journal}*"
            if volume:
                text += f" {volume}"
            if issue:
                text += f", no. {issue}"
        text += f" ({year or 'n.d.'})"
        if pages:
            text += f": {pages}"
        return text + "."

    # Harvard: (Year) 'Title', *Journal*, Vol(Issue), pp. pages.
    text = f"({year or 'no date'}) ‘{title}’"
    if journal:
        text += f", *{journal}*"
        if volume:
            text += f", {volume}" + (f"({issue})" if issue else "")
    if pages:
        text += f", pp. {pages}"
    return text + "."


def format_chapter(entry, style, year, pages):
    """Everything after the authors for a chapter in an edited book."""
    title, book = entry["title"], value(entry, "book_title")
    editors, publisher = value(entry, "editors"), value(entry, "publisher")

    if style == "apa":
        # (Year). Title. In E. Editor (Ed.), *Book* (pp. pages). Publisher.
        text = f"({year or 'n.d.'}). {end_with_period(title)} In"
        if editors:
            text += f" {editors_apa(editors)} ({'Ed.' if len(editors) == 1 else 'Eds.'}),"
        if book:
            text += f" *{book}*"
        if pages:
            text += f" (pp. {pages})"
        text += "."
        if publisher:
            text += f" {end_with_period(publisher)}"
        return text

    if style == "chicago":
        # "Title." In *Book*, edited by Given Family, pages. Place: Publisher, Year.
        text = f"“{end_with_period(title)}” In"
        if book:
            text += f" *{book}*"
        if editors:
            text += f", edited by {editors_chicago(editors)}"
        if pages:
            text += f", {pages}"
        text += "."
        where = place_and_publisher(entry)
        text += f" {where}, {year or 'n.d.'}." if where else f" {year or 'n.d.'}."
        return text

    # Harvard: (Year) 'Title', in Family, E. (ed.) *Book*. Place: Publisher, pp. pages.
    text = f"({year or 'no date'}) ‘{title}’, in"
    if editors:
        text += f" {authors_harvard(editors)} ({'ed.' if len(editors) == 1 else 'eds'})"
    if book:
        text += f" *{book}*"
    text += "."
    where = place_and_publisher(entry)
    if where:
        text += f" {where}"
    if pages:
        text += f", pp. {pages}" if where else f" pp. {pages}"
    return text + ("." if where or pages else "")


def italic_title(title):
    """A book title in Markdown italics, followed by a full stop: *Title*."""
    return f"*{title}*" + ("" if title.endswith((".", "?", "!")) else ".")


def format_book(entry, style, year):
    """Everything after the authors for a whole book."""
    title = entry["title"]
    where = place_and_publisher(entry)

    if style == "apa":
        # (Year). *Title*. Publisher.  (APA 7 leaves out the place.)
        text = f"({year or 'n.d.'}). " + italic_title(title)
        publisher = value(entry, "publisher")
        return text + (f" {end_with_period(publisher)}" if publisher else "")

    if style == "chicago":
        # *Title*. Place: Publisher, Year.
        text = italic_title(title)
        return text + (f" {where}, {year or 'n.d.'}." if where else f" {year or 'n.d.'}.")

    # Harvard: (Year) *Title*. Place: Publisher.
    text = f"({year or 'no date'}) " + italic_title(title)
    return text + (f" {end_with_period(where)}" if where else "")


def format_report(entry, style, year):
    """Everything after the authors for a report."""
    title = entry["title"]
    number = value(entry, "report_number")
    where = place_and_publisher(entry)

    if style == "apa":
        # (Year). *Title* (Report No. 12). Publisher.
        text = f"({year or 'n.d.'}). *{title}*"
        text += f" (Report No. {number})." if number else ("" if title.endswith((".", "?", "!")) else ".")
        publisher = value(entry, "publisher")
        return text + (f" {end_with_period(publisher)}" if publisher else "")

    if style == "chicago":
        # *Title*. Report 12. Place: Publisher, Year.
        text = italic_title(title)
        if number:
            text += f" Report {number}."
        return text + (f" {where}, {year or 'n.d.'}." if where else f" {year or 'n.d.'}.")

    # Harvard: (Year) *Title*. Report 12. Place: Publisher.
    text = f"({year or 'no date'}) " + italic_title(title)
    if number:
        text += f" Report {number}."
    return text + (f" {end_with_period(where)}" if where else "")


def format_webpage(entry, style, year):
    """Everything after the authors for a webpage (the URL is added after)."""
    title, site = entry["title"], value(entry, "site_name")

    if style == "apa":
        # (Year). *Title*. Site Name.
        text = f"({year or 'n.d.'}). " + italic_title(title)
        return text + (f" {end_with_period(site)}" if site else "")

    if style == "chicago":
        # "Title." Site Name. Year.
        text = f"“{end_with_period(title)}”"
        if site:
            text += f" {end_with_period(site)}"
        return text + f" {year or 'n.d.'}."

    # Harvard: (Year) *Title*. Site Name.
    text = f"({year or 'no date'}) " + italic_title(title)
    return text + (f" {end_with_period(site)}" if site else "")


def sort_key(entry):
    """Sort references by first author's family name, then year.

    Unresolved entries go last.
    """
    if not stated(entry.get("title")):
        return (1, entry["input"].lower(), "")
    authors = entry.get("authors")
    first = authors[0]["family"].lower() if isinstance(authors, list) and authors else entry["title"].lower()
    return (0, first, str(entry.get("year", "")))


def words(text):
    """Split text into lowercase words and numbers: "45-67 Smith" -> {"45", "67", "smith"}."""
    return set(re.findall(r"\w+", text.lower()))


def confident_match(entry):
    """Check the title Crossref returned fits the text the student gave.

    A wrong DOI in refs.txt would fetch a different paper. If the line has
    more than a DOI, at least half of the title's longer words must appear
    in it. A line with only a DOI can't be checked, so it counts as a match.
    """
    # Remove the DOI (and any doi.org link or "doi:" before it) from the line.
    text = re.sub(r"(https?://)?(dx\.)?doi\.org/|doi:", "", entry["input"], flags=re.IGNORECASE)
    typed = words(DOI_PATTERN.sub("", text))
    if len(typed) < 3:
        return True
    title_words = {w for w in words(entry["title"]) if len(w) > 3}
    if not title_words:
        return True
    return len(title_words & typed) / len(title_words) >= 0.5


# Which library field each cross-checked field belongs to.
CHECKED_FIELD_FOR = {"title": "title", "first_author": "authors", "year": "year"}

SOURCE_NAMES = {"openalex": "OpenAlex", "semantic_scholar": "Semantic Scholar"}


def disagreement_reasons(entry, edited_fields):
    """Describe the fields where OpenAlex or Semantic Scholar disagree with Crossref.

    Fields the student has corrected by hand are skipped: they've checked them.
    """
    check = entry.get("cross_check") or {}
    reasons = []
    for field in check.get("disagree", []):
        if CHECKED_FIELD_FOR[field] in edited_fields:
            continue
        crossref_value = check["sources"]["crossref"][field]
        details = []
        for source, result in check["fields"][field].items():
            if not result["agree"]:
                score = f", similarity {result['score']}" if "score" in result else ""
                details.append(f"{SOURCE_NAMES[source]} has “{result['value']}”{score}")
        reasons.append(
            f"Sources disagree on {field.replace('_', ' ')}: Crossref has "
            f"“{crossref_value}”, {'; '.join(details)}."
        )
    return reasons


def unchecked_reasons(entry, edited_fields):
    """Describe fields no other source could confirm.

    "verified" means the sources agree, so a field nobody else could check
    is a warning, unless the student has corrected it by hand.
    """
    check = entry.get("cross_check")
    if check is None:
        unchecked = list(CHECKED_FIELD_FOR)  # Never cross-checked at all.
        why = "it was not looked up in other sources"
    else:
        unchecked = check["unchecked"]
        errors = [f"{SOURCE_NAMES[s]}: {r['error']}" for s, r in check["sources"].items() if "error" in r]
        why = "no other source answered" + (f" ({' '.join(errors)})" if errors else "")

    fields = [f.replace("_", " ") for f in unchecked if CHECKED_FIELD_FOR[f] not in edited_fields]
    return [f"Could not confirm {', '.join(fields)}: {why}."] if fields else []


def crossref_identified(entry):
    """True if Crossref identified the paper: the Streamlit chat's "Verified".

    That is: the DOI resolved in Crossref, or the title search found a match
    (similarity at least TITLE_AGREE_SCORE with the runner-up more than
    RUNNER_UP_MARGIN below; see search_crossref_title). Every other result
    stores a "lookup_error". Edits can't change this: they only touch
    citation fields.
    """
    if "lookup_error" in entry:
        return False  # DOI not found, Crossref unreachable, or no clear title match.
    search = entry.get("title_search")
    return search is None or search.get("outcome") == "match"


def verify(entry, edited_fields=(), crossref_only=False):
    """Work out an entry's verification status and warnings. Done in code only.

    - "not_found": no source had a record, or a title search found no
                   plausible match.
    - "check":     anything to look at: APA 7 problems, sources disagreeing,
                   a title search with several or weak candidates, uncertain
                   title casing,
                   fields no source could confirm, or a DOI that seems to
                   belong to a different paper.
    - "verified":  sources agree and nothing is missing.
    Fields the student corrected by hand (edited_fields) count as confirmed.
    crossref_only=True (the Streamlit chat) skips the other sources: an entry
    can only be "verified" if crossref_identified is True, and no warning is
    given for fields OpenAlex or Semantic Scholar didn't confirm.
    Returns (status, list of warnings).
    """
    # Code can't check text typed by hand, so say so instead of passing it.
    typed = []
    if stated(entry.get("reference_text")):
        typed = ["Reference text was typed by hand, so it is not checked against the fetched details."]
    # Not identified: no title, or (Crossref only) no DOI or clear title match,
    # even if a title was typed in later with an edit.
    if not stated(entry.get("title")) or (crossref_only and not crossref_identified(entry)):
        search = entry.get("title_search") or {}
        if search.get("outcome") == "check":
            # Possible matches, but none clear enough to pick: list them for the student.
            return "check", search["reasons"] + candidate_lines(search["candidates"]) + typed
        return "not_found", [f"No match found. {entry.get('lookup_error', '')}".strip()] + typed

    warnings = validate_reference(entry, entry.get("type", "journal-article"))
    # Found by an author-and-year search: always "check", reason first.
    # "from_search" is not a citation field, so no edit can remove it.
    if entry.get("from_search") in SEARCH_REASONS:
        warnings.insert(0, SEARCH_REASONS[entry["from_search"]])
    if "title" not in edited_fields and not confident_match(entry):
        warnings.append(f"Crossref's title “{entry['title']}” doesn't match your text. Check the DOI.")
    if not crossref_only:
        # Only refs mode compares with OpenAlex and Semantic Scholar.
        warnings += disagreement_reasons(entry, edited_fields)
        warnings += unchecked_reasons(entry, edited_fields)
    if "title" not in edited_fields:
        warnings += title_case_warnings(entry)
    warnings += typed
    return ("check" if warnings else "verified"), warnings


def search_links(entry):
    """Build a Google Scholar and a Google search link for an entry.

    The search text is the title plus the first author's family name. If no
    record was found, the student's original line is used instead.
    The links are only built here; nothing ever requests these pages.
    """
    if stated(entry.get("title")):
        terms = [entry["title"]]
        authors = entry.get("authors")
        if isinstance(authors, list) and authors and authors[0].get("family"):
            terms.append(authors[0]["family"])
    else:
        terms = [entry["input"]]
    search = urllib.parse.quote_plus(" ".join(terms))  # URL-encode, spaces become "+".
    return {"google_scholar": SCHOLAR_SEARCH_URL + search, "google": GOOGLE_SEARCH_URL + search}


def write_apa_report(rows):
    """Write drafts/references_apa.md: each reference in APA 7 followed by
    its status, warnings, and the two search links.

    rows is a list of (reference text, status, warnings, links, original
    title or None), already sorted. The original title is shown when the
    APA sentence-case title differs from it, so the two can be compared.
    """
    blocks = []
    for text, status, warnings, links, original in rows:
        warning_lines = "".join(f"\n  - {w}" for w in warnings) if warnings else " none"
        original_line = f"- Original title: {original}\n" if original else ""
        blocks.append(
            f"{text}\n\n"
            f"{original_line}"
            f"- Status: {status}\n"
            f"- Warnings:{warning_lines}\n"
            f"- Google Scholar: <{links['google_scholar']}>\n"
            f"- Google: <{links['google']}>"
        )
    header = (
        f"# References ({STYLES['apa']}) with checks\n\n"
        "Status and warnings are worked out in code (see refs/library.json). "
        "The links are searches to help you check each source by hand.\n\n"
    )
    DRAFTS_DIR.mkdir(exist_ok=True)
    APA_REPORT_PATH.write_text(header + "\n\n---\n\n".join(blocks) + "\n", encoding="utf-8")


def mark_edited(entry, edited_fields):
    """Mark a library entry as hand-edited, with a note saying what changed.

    The note lives only in library.json; it never appears in the reference text.
    """
    entry["status"] = "edited"
    entry["note"] = (
        f"Edited by hand (last change {date.today().isoformat()}): "
        f"{', '.join(edited_fields)}. Corrected values are in overrides.json."
    )


def shown_text(entry, style):
    """The text to show for an entry: the formatted reference, or the
    original input line if nothing was found and nothing was typed by hand.
    """
    if stated(entry.get("title")) or stated(entry.get("reference_text")):
        return format_reference(entry, style)
    return entry["input"]


def write_output(ids, style, library, overrides, show=True):
    """Verify and format the given entries and save them to refs/references.md.

    Each entry's verification status and warnings are worked out in code
    (see verify) and stored in refs/library.json. Entries that are not
    "verified" go in a separate "Needs checking" section with their reasons.
    Prints the list too unless show is False. Also records the style and ids
    in refs/last_run.json, so edits can re-generate exactly the same list.
    Each entry's search links are stored too, and drafts/references_apa.md
    is written (always in APA, whatever the style).
    """
    by_id = {entry["id"]: entry for entry in library}
    # Lay the overrides on top of the fetched metadata before formatting.
    entries = [apply_overrides(by_id[ref_id], overrides) for ref_id in ids if ref_id in by_id]

    # Split the entries into the reference list and the ones to check.
    references, to_check = [], []
    apa_rows = []  # For drafts/references_apa.md.
    for entry in sorted(entries, key=sort_key):
        status, warnings = verify(entry, overrides.get(entry["id"], {}))
        links = search_links(entry)  # Built from the corrected title and author.
        # Save the results on the library entry (not the merged copy).
        by_id[entry["id"]]["verification"] = {"status": status, "warnings": warnings}
        by_id[entry["id"]]["search_links"] = links
        apa_text = shown_text(entry, "apa")
        apa_rows.append((apa_text, status, warnings, links, original_title_note(entry)))

        reasons = list(warnings)
        # Chicago and Harvard need a few fields APA 7 doesn't (e.g. place).
        extra = [f for f in missing_fields(entry, style) if f not in APA7_REQUIRED.get(entry.get("type"), [])]
        if status != "not_found" and extra:
            reasons.append(f"Missing {', '.join(extra)} (needed in {STYLES[style]}).")
        if not reasons:
            references.append(format_reference(entry, style))
        else:
            # Show the formatted text if there is one, else the original line.
            text = shown_text(entry, style)
            to_check.append(f"- {text}\n  - Reason: {' '.join(reasons)}")

    output = f"# References ({STYLES[style]})\n\n" + "\n\n".join(references) + "\n"
    if to_check:
        output += "\n## Needs checking\n\n" + "\n".join(to_check) + "\n"
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    write_apa_report(apa_rows)
    save_json(LIBRARY_PATH, library)  # Stores each entry's verification and links.
    save_json(LAST_RUN_PATH, {"style": style, "ids": ids})

    if show:
        print("\n" + output)
        print(f"Saved to {OUTPUT_PATH.relative_to(PROJECT_DIR)}")
        print(f"Saved the APA list with checks and links to {APA_REPORT_PATH.relative_to(PROJECT_DIR)}")


def parse_value(field, text):
    """Convert typed text into the form stored for that field.

    Raises ValueError if the text is not allowed for the field.
    """
    if field not in CITATION_FIELDS:
        raise ValueError(f"Unknown field '{field}'. Fields: {', '.join(CITATION_FIELDS)}")
    if text == "not stated":
        return text
    if field == "type" and text not in WORK_TYPES:
        raise ValueError(f"Unknown type '{text}'. Types: {', '.join(WORK_TYPES)}")
    if field in ("authors", "editors"):
        # "LeCun, Yann; Bengio, Yoshua" -> [{"family": "LeCun", "given": "Yann"}, ...]
        names = []
        for person in text.split(";"):
            family, _, given = person.partition(",")
            if family.strip():
                names.append({"given": given.strip(), "family": family.strip()})
        return names or "not stated"
    if field == "year" and text.isdigit():
        return int(text)  # Store years as numbers, like Crossref does.
    return text


def clear_fields_for_new_type(parsed, old_entry):
    """When an edit changes the type, clear the old type's details.

    E.g. a journal's volume would be wrong for a book. Fields given new
    values in the same edit are kept. The cleared fields then show up as
    missing, so the student is asked for them. Changes `parsed` in place.
    """
    if "type" in parsed and parsed["type"] != old_entry.get("type", "journal-article"):
        for field in TYPE_SPECIFIC_FIELDS:
            parsed.setdefault(field, "not stated")


def apply_edit(ref_id, changes, style=None, show=True):
    """Save hand corrections for one entry and re-generate the reference list.

    changes is {field: text}. Corrections go to overrides.json (other
    overrides for the entry are kept) and the entry is marked "edited".
    Returns (old reference, new reference, missing required fields).
    Raises ValueError for an unknown id, field, or type.
    """
    library = load_library()
    entry = next((e for e in library if e["id"] == ref_id), None)
    if entry is None:
        raise ValueError(f"No entry with id {ref_id} in {LIBRARY_PATH.relative_to(PROJECT_DIR)}.")

    # Check every change before saving any, so a bad one saves nothing.
    parsed = {field: parse_value(field, text) for field, text in changes.items()}

    last_run = load_json(LAST_RUN_PATH, {"style": "apa", "ids": [ref_id]})
    style = style or last_run["style"]
    overrides = load_overrides()
    old_entry = apply_overrides(entry, overrides)
    old = format_reference(old_entry, style)

    clear_fields_for_new_type(parsed, old_entry)

    # Save the overrides and mark the entry as edited.
    overrides.setdefault(ref_id, {}).update(parsed)
    save_json(OVERRIDES_PATH, overrides)
    mark_edited(entry, overrides[ref_id])
    save_json(LIBRARY_PATH, library)

    # Re-generate the last reference list (adding this entry if it wasn't in it).
    ids = last_run["ids"] if ref_id in last_run["ids"] else last_run["ids"] + [ref_id]
    write_output(ids, style, library, overrides, show=show)

    new_entry = apply_overrides(entry, overrides)
    return old, format_reference(new_entry, style), missing_fields(new_entry, style)


def run_edit(args):
    """Refs edit: save one hand correction to overrides.json and re-generate."""
    # 1. Read the command-line options.
    parser = argparse.ArgumentParser(prog="python agent.py refs edit")
    parser.add_argument("id", help="the entry id, e.g. ref-4e2bb7a35f")
    parser.add_argument("--field", required=True, choices=CITATION_FIELDS)
    parser.add_argument(
        "--value", required=True,
        help='new value; for authors/editors use "Family, Given; Family, Given"',
    )
    parser.add_argument("--style", choices=STYLES.keys(), help="default: the style of the last run")
    options = parser.parse_args(args)

    # 2. Save the change and re-generate the list.
    try:
        _, _, missing = apply_edit(options.id, {options.field: options.value}, options.style)
    except ValueError as err:
        print(err)
        sys.exit(1)

    print(f"Set {options.field} of {options.id} to {options.value!r} (status: edited)")
    if missing:
        print(f"Still missing: {', '.join(missing)}")


def run_refs(args):
    """Refs mode: resolve each reference, update the library, write the list."""
    # "refs edit ..." and "refs chat" are separate commands.
    if args and args[0] == "edit":
        run_edit(args[1:])
        return
    if args and args[0] == "chat":
        asyncio.run(run_chat())
        return

    # 1. Read the command-line options.
    parser = argparse.ArgumentParser(prog="python agent.py refs")
    parser.add_argument("--input", required=True, help="text file with one reference (or DOI) per line")
    parser.add_argument("--style", choices=STYLES.keys(), default="apa", help="reference style (default: apa)")
    options = parser.parse_args(args)

    input_path = Path(options.input)
    if not input_path.is_file():
        print(f"File not found: {input_path}")
        sys.exit(1)

    # 2. Read the input, skipping blank lines and comment lines starting with #.
    lines = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]

    # 3. Load the existing library and overrides so hand edits are kept.
    library = load_library()
    overrides = load_overrides()  # Only read here, never written.
    by_id = {entry["id"]: entry for entry in library}

    used = []  # Entries for this input file, in order, without duplicates.
    for line in lines:
        ref_id = make_id(line)
        if any(entry["id"] == ref_id for entry in used):
            continue  # Same source listed twice.

        existing = by_id.get(ref_id)
        if existing and existing.get("status") == "edited":
            # Never overwrite an entry the student has corrected by hand.
            print(f"kept   {ref_id} (edited)")
            used.append(existing)
            continue

        entry = resolve_line(line, ref_id)
        if ref_id in overrides:
            mark_edited(entry, overrides[ref_id])  # It has hand corrections in overrides.json.
        if entry.get("title_search", {}).get("outcome") == "check":
            result = "check "  # Title search found candidates but none was clear.
        else:
            result = "failed" if "lookup_error" in entry else "found "
        print(f"{result} {ref_id} {line}")
        if existing:
            existing.clear()
            existing.update(entry)  # Refresh in place so the order stays the same.
        else:
            library.append(entry)
            by_id[ref_id] = entry
        used.append(by_id[ref_id])

    # 4. Save every entry (including ones not in this input file).
    save_json(LIBRARY_PATH, library)
    print(f"\nSaved {len(library)} entries to {LIBRARY_PATH.relative_to(PROJECT_DIR)}")

    # 5. Write the formatted list, with overrides applied, sorted alphabetically.
    write_output([entry["id"] for entry in used], options.style, library, overrides)


# ---------------------------------------------------------------------------
# Refs chat: python agent.py refs chat
# Talk to an agent to fix references, e.g. "change reference 4 to a book
# chapter and add editors". It can only change refs/overrides.json, through
# the edit_reference tool below.
# ---------------------------------------------------------------------------

CHAT_PROMPT = """You help a student fix entries in their reference list.
You can only see and change references through your tools. References are
numbered as in the list shown at the start of the chat; use those numbers.

How to handle a request:
1. Call get_reference to see the reference's current fields.
2. Work out every field the change needs. For example, a book chapter needs
   book_title, editors, publisher and pages (and place in Chicago or Harvard).
3. If the student has not given you a value for any of these, ask for all of
   them in one short message and wait for the answer. Never fill in a value
   yourself, even if you think you know it: no guessing, no remembering, no
   copying from other references. edit_reference rejects values the student
   did not type.
4. When you have the values, call edit_reference once with all the changes.
   The old and new reference are shown to the student automatically, so do
   not repeat them.
5. If edit_reference says fields are still missing, ask the student for them.
   If the student says a detail is unknown, set it to "not stated" and stop
   asking about it.

Each reference has a status (verified, check, or not_found) and warnings.
These are worked out by code; you cannot set or change them. Use the
warnings to see what to ask the student about.

Field formats:
- type: journal-article, book-chapter, book, report, or webpage
- authors, editors: "Family, Given; Family, Given". An organisation as author
  is just its name, e.g. "World Health Organization".
- year: a number, e.g. 2020
- pages: e.g. 45-67
- url: starts with https://
- everything else: plain text (report_number, site_name, place, ...)

Keep replies short.
"""

# What the chat tools need to remember while the chat is running.
CHAT_STATE = {
    "numbers": {},  # Reference number shown to the student -> entry id.
    "user_text": "",  # Everything the student has typed, to check edits against.
    "style": "apa",  # Style of the last generated list.
}


def typed_by_student(text):
    """True if every word and number in text appears in what the student typed.

    This is a simple code check that the agent is not inventing values.
    """
    return words(text) <= words(CHAT_STATE["user_text"])


def print_side_by_side(old, new):
    """Print the old and new reference next to each other in two columns."""
    width = shutil.get_terminal_size((100, 24)).columns
    column = max(25, (width - 3) // 2)
    left = textwrap.wrap(old, column) or [""]
    right = textwrap.wrap(new, column) or [""]

    print()
    print("OLD".ljust(column) + " | NEW")
    print("-" * column + "-+-" + "-" * column)
    for old_line, new_line in itertools.zip_longest(left, right, fillvalue=""):
        print(old_line.ljust(column) + " | " + new_line)
    print()


def chat_entry(number):
    """Return (id, entry with overrides applied) for a reference number."""
    ref_id = CHAT_STATE["numbers"].get(number)
    if ref_id is None:
        return None, None
    entry = next(e for e in load_library() if e["id"] == ref_id)
    return ref_id, apply_overrides(entry, load_overrides())


def numbered_list():
    """The reference list with the numbers the student sees."""
    lines = []
    for number, ref_id in CHAT_STATE["numbers"].items():
        _, entry = chat_entry(number)
        lines.append(f"{number}. {format_reference(entry, CHAT_STATE['style'])}")
    return "\n".join(lines)


def text_result(text):
    """Build a normal (successful) tool result."""
    return {"content": [{"type": "text", "text": text}]}


@tool("list_references", "Show the numbered reference list.", {})
async def list_references(args):
    """Chat tool: show the numbered list."""
    return text_result(numbered_list())


@tool(
    "get_reference",
    "Show every field of one reference, and which required fields are missing.",
    {"number": int},
)
async def get_reference(args):
    """Chat tool: show one reference's fields."""
    ref_id, entry = chat_entry(args["number"])
    if entry is None:
        return error_result(f"There is no reference {args['number']}. Call list_references.")
    fields = {field: entry.get(field, "not stated") for field in CITATION_FIELDS}
    missing = missing_fields(entry, CHAT_STATE["style"])
    # The status is worked out here by code, never by the model.
    status, warnings = verify(entry, load_overrides().get(ref_id, {}))
    return text_result(
        f"Reference {args['number']} (id {ref_id}):\n{json.dumps(fields, indent=2, ensure_ascii=False)}\n"
        f"Missing required fields: {', '.join(missing) or 'none'}\n"
        f"Status (set by code): {status}\n"
        "Warnings:\n" + ("\n".join(f"- {w}" for w in warnings) or "- none")
    )


@tool(
    "edit_reference",
    "Change fields of one reference. Saves to refs/overrides.json, re-generates "
    "the list, and shows the student the old and new reference. Only use "
    "values the student typed.",
    {
        "type": "object",
        "properties": {
            "number": {"type": "integer", "description": "reference number from the list"},
            "changes": {
                "type": "object",
                "description": 'field -> new value, e.g. {"type": "book-chapter", "pages": "45-67"}',
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["number", "changes"],
    },
)
async def edit_reference(args):
    """Chat tool: save changes for one reference and show old vs new."""
    ref_id = CHAT_STATE["numbers"].get(args["number"])
    if ref_id is None:
        return error_result(f"There is no reference {args['number']}. Call list_references.")
    changes = args.get("changes") or {}
    if not changes:
        return error_result("No changes given.")

    # Code check against guessing: every value (except the type and
    # "not stated") must be made of words the student actually typed.
    not_typed = [
        field for field, text in changes.items()
        if field != "type" and text != "not stated" and not typed_by_student(str(text))
    ]
    if not_typed:
        return error_result(
            f"Not saved. The student did not give these values: {', '.join(not_typed)}. "
            "Ask the student for them instead of guessing."
        )

    try:
        old, new, missing = apply_edit(ref_id, changes, CHAT_STATE["style"], show=False)
    except ValueError as err:
        return error_result(f"Not saved. {err}")

    print_side_by_side(old, new)
    note = f"Still missing: {', '.join(missing)}. Ask the student for these." if missing else "Nothing missing."
    return text_result(f"Saved to refs/overrides.json and re-generated {OUTPUT_PATH.name}. {note}")


# The chat's tools, in their own in-process MCP server named "refs".
REFS_SERVER = create_sdk_mcp_server(name="refs", tools=[list_references, get_reference, edit_reference])
REFS_TOOLS = ["mcp__refs__list_references", "mcp__refs__get_reference", "mcp__refs__edit_reference"]


async def run_chat():
    """Refs chat: a multi-turn conversation for fixing references."""
    # 1. Number the references from the last generated list.
    library = load_library()
    if not library:
        print("No references yet. Run first: python agent.py refs --input refs.txt")
        return
    last_run = load_json(LAST_RUN_PATH, {"style": "apa", "ids": [e["id"] for e in library]})
    CHAT_STATE["style"] = last_run["style"]

    overrides = load_overrides()
    by_id = {entry["id"]: entry for entry in library}
    entries = [apply_overrides(by_id[i], overrides) for i in last_run["ids"] if i in by_id]
    # Numbers are fixed for the whole chat, even if an edit changes the sort order.
    CHAT_STATE["numbers"] = {n: e["id"] for n, e in enumerate(sorted(entries, key=sort_key), start=1)}

    print(f"References ({STYLES[CHAT_STATE['style']]}):\n")
    print(numbered_list())
    print('\nSay what to change, e.g. "change reference 4 to a book chapter". Type "quit" to stop.')

    # 2. Configure the agent: no built-in tools at all, only the three refs tools.
    options = ClaudeAgentOptions(
        model="claude-opus-5-5",
        system_prompt=CHAT_PROMPT,
        tools=[],  # No Read/Write/Bash: it can only change references via edit_reference.
        mcp_servers={"refs": REFS_SERVER},
        allowed_tools=REFS_TOOLS,
        cwd=str(PROJECT_DIR),
    )

    # 3. ClaudeSDKClient keeps one session open, so the agent remembers
    #    earlier messages (e.g. its own question and the student's answer).
    async with ClaudeSDKClient(options=options) as client:
        while True:
            try:
                # input() blocks, so run it in a thread to keep the client running.
                text = (await asyncio.to_thread(input, "\nyou> ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in ("quit", "exit"):
                break
            if not text:
                continue

            CHAT_STATE["user_text"] += "\n" + text  # Remembered for typed_by_student().
            await client.query(text)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"\nagent> {block.text}")
                        elif isinstance(block, ToolUseBlock):
                            print(f"[tool] {block.name.removeprefix('mcp__refs__')}")


if __name__ == "__main__":
    # "refs" as the first argument switches to refs mode; otherwise paper mode.
    if len(sys.argv) > 1 and sys.argv[1] == "refs":
        run_refs(sys.argv[2:])
    else:
        asyncio.run(main())
