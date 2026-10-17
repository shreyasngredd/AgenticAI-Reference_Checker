"""The Field setting: journal lists per field, read from config/fields.json.

This file has no Streamlit code. It reads the file, checks it has the shape
of specs/goal-spec.md section 7.3, and gives the dropdown's options and a
field's ISSNs. If the file is missing or broken, only "All fields" is
offered, with a warning; the file is never written.
"""

import json
import re
from pathlib import Path

PROJECT_FIELDS_PATH = Path(__file__).resolve().parent / "config" / "fields.json"
FIELDS_PATH = PROJECT_FIELDS_PATH  # The file read; tests point it at a temporary copy.
ALL_FIELDS = "All fields"
ISSN_PATTERN = re.compile(r"\d{4}-\d{3}[\dX]")  # NNNN-NNNC, C a digit or X.


def problem_with(data):
    """Why the file's contents don't have the shape of section 7.3, or None if they do."""
    if not isinstance(data, dict) or not data:
        return "it must be a JSON object with at least one field"
    for field, journals in data.items():
        if not isinstance(journals, list) or not journals:
            return f"field '{field}' has no journals"
        for journal in journals:
            if not isinstance(journal, dict):
                return f"a journal in '{field}' is not an object"
            name = journal.get("name")
            if not isinstance(name, str) or not name.strip():
                return f"a journal in '{field}' has no name"
            issns = journal.get("issn")
            if not isinstance(issns, list) or not issns:
                return f"'{name}' has no ISSNs"
            for issn in issns:
                if not isinstance(issn, str) or not ISSN_PATTERN.fullmatch(issn):
                    return f"'{name}' has a badly written ISSN: {issn!r}"
    return None


def load_fields():
    """Read the field lists. Returns ({field: [journals]}, None) or ({}, warning).

    The file is read again on every call, so an edit takes effect on the next
    message. A broken file is not used at all (no partial use).
    """
    try:
        data = json.loads(FIELDS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        reason = "file not found"
    except (OSError, UnicodeDecodeError) as err:
        reason = f"could not be read: {err}"
    except json.JSONDecodeError as err:
        reason = f"not valid JSON: {err}"
    else:
        reason = problem_with(data)
        if reason is None:
            return data, None
    return {}, f"Field lists unavailable (config/fields.json: {reason}). Using {ALL_FIELDS}."


def field_options():
    """The dropdown's options, "All fields" first, and the warning (or None)."""
    data, warning = load_fields()
    return [ALL_FIELDS] + list(data), warning


def field_issns(field):
    """Every ISSN of every journal in `field`, in the file's order.

    Returns None for "All fields", a field no longer in the file, or a broken
    file: all of these mean "search everything".
    """
    data, _ = load_fields()
    if field not in data:
        return None
    issns = []
    for journal in data[field]:
        issns += [issn for issn in journal["issn"] if issn not in issns]
    return issns
