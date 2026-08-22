"""Coherra onboarding + migration layer (Feature A, Phase 2).

Imports messy JSON exports from other tools, categorizes them via Claude Haiku
(or a rule-based fallback), writes them through the existing Coherra schema,
audits the result, and surfaces a summary.

Public entry points:
    parse_import(raw)            → list[dict]    raw key/value pairs
    categorize_batch(records)    → list[dict]    enriched with category/name/confidence
    write_records(records)       → dict          {written, errors}
    audit_and_repair(names)      → dict          {issues_found, auto_cleaned, flagged}
    onboard(import_data)         → dict          full pipeline summary
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any

from .client import open_client


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ImportParseError(Exception):
    """Raised when a specific record in the import data is malformed.

    Attributes:
        record_index: Which record (0-based) failed, or -1 for top-level errors.
        field:        Which field was problematic (e.g. "value", "key", "root").
        reason:       Human-readable explanation of why it failed.
    """

    def __init__(self, record_index: int, field: str, reason: str) -> None:
        self.record_index = record_index
        self.field = field
        self.reason = reason
        if record_index >= 0:
            msg = f"Record {record_index}: field '{field}' — {reason}"
        else:
            msg = f"Import error (field '{field}'): {reason}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Step 1: JSON Import Parser
# ---------------------------------------------------------------------------

def _stringify(v: Any) -> str:
    """Coerce a value to a string representation suitable for storage."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return ""
    # For complex types, serialize to JSON
    return json.dumps(v, ensure_ascii=False)


def _clean_key(raw: str) -> str:
    """Normalize a raw key into a clean entity-name-style string."""
    # Replace common separators with underscores
    s = re.sub(r"[\s./\-]+", "_", raw.strip())
    # Remove non-alphanumeric except underscore
    s = re.sub(r"[^a-zA-Z0-9_]", "", s)
    return s.lower().strip("_") or "unnamed"


def parse_import(raw: Any) -> list[dict[str, str]]:
    """Parse a generic JSON export into a list of {raw_key, raw_value} pairs.

    Handles four common shapes:
      1. Flat dict:   {"key": "value", ...}
      2. List of dicts: [{"key": "...", "value": "..."}, ...]
                    or  [{"name": "...", "content": "..."}, ...]
      3. Nested dict: {"section": {"key": "value", ...}, ...}
      4. List of strings: ["fact 1", "fact 2", ...]

    Raises ImportParseError with the specific record index and reason on failure.
    """
    if raw is None:
        raise ImportParseError(-1, "root", "Input is null/None — expected a dict or list")

    if isinstance(raw, str):
        # Try to parse as JSON string
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ImportParseError(-1, "root", f"Input is not valid JSON: {e}")

    records: list[dict[str, str]] = []

    if isinstance(raw, dict):
        if not raw:
            raise ImportParseError(-1, "root", "Input dict is empty — nothing to import")
        # Check if this is a nested dict (values are all dicts → shape 3)
        # vs a flat dict (values are primitives → shape 1)
        nested_count = sum(1 for v in raw.values() if isinstance(v, dict))
        if nested_count > 0 and nested_count >= len(raw) / 2:
            # Shape 3: Nested dict — flatten
            idx = 0
            for section, inner in raw.items():
                if isinstance(inner, dict):
                    for k, v in inner.items():
                        val_str = _stringify(v)
                        if not val_str:
                            raise ImportParseError(
                                idx, "value",
                                f"Empty value for key '{section}/{k}'"
                            )
                        records.append({
                            "raw_key": f"{_clean_key(section)}_{_clean_key(k)}",
                            "raw_value": val_str,
                        })
                        idx += 1
                elif inner is not None:
                    # Mixed: some top-level values aren't dicts — treat as flat
                    val_str = _stringify(inner)
                    if val_str:
                        records.append({
                            "raw_key": _clean_key(section),
                            "raw_value": val_str,
                        })
                    idx += 1
        else:
            # Shape 1: Flat dict
            for idx, (k, v) in enumerate(raw.items()):
                val_str = _stringify(v)
                if not val_str:
                    raise ImportParseError(
                        idx, "value",
                        f"Empty value for key '{k}'"
                    )
                records.append({
                    "raw_key": _clean_key(k),
                    "raw_value": val_str,
                })

    elif isinstance(raw, list):
        if not raw:
            raise ImportParseError(-1, "root", "Input list is empty — nothing to import")

        for idx, item in enumerate(raw):
            if isinstance(item, str):
                # Shape 4: List of strings
                stripped = item.strip()
                if not stripped:
                    raise ImportParseError(
                        idx, "value",
                        "Empty string at this position — every record needs content"
                    )
                records.append({
                    "raw_key": f"imported_fact_{idx}",
                    "raw_value": stripped,
                })
            elif isinstance(item, dict):
                # Shape 2: List of dicts — try common key/value field names
                key_candidates = ["key", "name", "title", "label", "id", "entity"]
                val_candidates = ["value", "content", "data", "text", "body", "description"]

                found_key = None
                found_val = None

                for kc in key_candidates:
                    if kc in item and item[kc] is not None:
                        found_key = str(item[kc]).strip()
                        break

                for vc in val_candidates:
                    if vc in item and item[vc] is not None:
                        found_val = _stringify(item[vc]).strip()
                        break

                # If we couldn't find standard fields, try to use the first
                # two string fields as key/value
                if found_key is None or found_val is None:
                    str_fields = [
                        (k, v) for k, v in item.items()
                        if isinstance(v, (str, int, float, bool))
                    ]
                    if len(str_fields) >= 2 and found_key is None and found_val is None:
                        found_key = str(str_fields[0][1]).strip()
                        found_val = _stringify(str_fields[1][1]).strip()
                    elif len(str_fields) == 1 and found_val is None:
                        # Single field — use field name as key, field value as value
                        found_key = found_key or _clean_key(str_fields[0][0])
                        found_val = _stringify(str_fields[0][1]).strip()

                if not found_key:
                    raise ImportParseError(
                        idx, "key",
                        f"Could not find a key field in record. "
                        f"Expected one of: {key_candidates}. "
                        f"Got fields: {list(item.keys())}"
                    )
                if not found_val:
                    raise ImportParseError(
                        idx, "value",
                        f"Could not find a value field in record with key='{found_key}'. "
                        f"Expected one of: {val_candidates}. "
                        f"Got fields: {list(item.keys())}"
                    )

                records.append({
                    "raw_key": _clean_key(found_key),
                    "raw_value": found_val,
                })
            else:
                raise ImportParseError(
                    idx, "type",
                    f"Expected a string or dict at this position, "
                    f"got {type(item).__name__}: {repr(item)[:100]}"
                )
    else:
        raise ImportParseError(
            -1, "root",
            f"Expected a dict or list at top level, got {type(raw).__name__}"
        )

    if not records:
        raise ImportParseError(-1, "root", "No records could be extracted from the input")

    return records


# ---------------------------------------------------------------------------
# Step 2: Categorization
# ---------------------------------------------------------------------------

# Categories that match the existing Coherra schema
_KNOWN_CATEGORIES = {"preference", "people", "projects", "facts"}

# Keyword → category mapping for rule-based fallback
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "preference": [
        "prefer", "favorite", "fav", "like", "style", "theme", "editor",
        "font", "color", "mode", "format", "tool", "framework", "language",
        "lang", "ide", "workflow", "habit", "setting",
    ],
    "people": [
        "person", "name", "team", "lead", "manager", "engineer", "developer",
        "colleague", "friend", "boss", "mentor", "role", "title", "job",
        "contact", "email", "phone", "member", "coworker",
    ],
    "projects": [
        "project", "repo", "repository", "codebase", "app", "service",
        "deadline", "sprint", "milestone", "status", "version", "deploy",
        "release", "branch", "feature", "task", "ticket", "jira", "trello",
    ],
    "facts": [
        "fact", "info", "timezone", "location", "city", "country",
        "birthday", "joined", "started", "date", "number", "address",
        "note", "remember", "learned",
    ],
}


def _fallback_categorize_one(raw_key: str, raw_value: str) -> dict[str, Any]:
    """Rule-based categorization fallback when Haiku is unavailable."""
    combined = f"{raw_key} {raw_value}".lower()

    best_cat = "facts"  # default
    best_score = 0

    for cat, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_cat = cat

    # Confidence: higher if we matched more keywords
    confidence = min(0.5 + (best_score * 0.1), 0.8)

    return {
        "category": best_cat,
        "clean_name": raw_key,
        "value": raw_value,
        "confidence": round(confidence, 2),
        "source": "migrated",
    }


def _gemini_categorize_batch(records: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Categorize records via Gemini in batches.

    Raises ImportError if google-generativeai is not installed.
    Raises RuntimeError if GEMINI_API_KEY / GOOGLE_API_KEY is not set.
    """
    import google.generativeai as genai  # noqa: F811 — lazy import, optional dep

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    BATCH_SIZE = 20
    results: list[dict[str, Any]] = []

    for batch_start in range(0, len(records), BATCH_SIZE):
        batch = records[batch_start:batch_start + BATCH_SIZE]

        records_json = json.dumps(
            [{"index": i, "raw_key": r["raw_key"], "raw_value": r["raw_value"]}
             for i, r in enumerate(batch)],
            indent=2,
        )

        prompt = f"""You are a data categorization engine for a structured memory system.

For each record below, assign:
- **category**: one of "preference", "people", "projects", "facts"
  - "preference" = user preferences, settings, tool choices, styles
  - "people" = person names, roles, team members, contacts
  - "projects" = project names, repos, deadlines, statuses, versions
  - "facts" = general facts, dates, locations, numbers, miscellaneous info
- **clean_name**: a clean, lowercase, underscore_separated entity name (e.g. "favorite_language", "team_lead_name")
- **value**: the cleaned/normalized value (fix obvious typos, standardize capitalization, but preserve meaning)
- **confidence**: 0.0-1.0 how confident you are in this categorization
  - 1.0 = clearly fits one category
  - 0.7-0.9 = likely fits but could be ambiguous
  - 0.3-0.6 = vague or unclear statement
  - 0.0-0.3 = very uncertain, possibly garbage

Respond with ONLY a JSON array matching the input indices. No markdown formatting, no explanation.

Input records:
{records_json}

Output format (JSON array):
[
  {{"index": 0, "category": "...", "clean_name": "...", "value": "...", "confidence": 0.85}},
  ...
]"""

        response = model.generate_content(prompt)
        response_text = (response.text or "").strip()

        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            ).strip()

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            for r in batch:
                results.append(_fallback_categorize_one(r["raw_key"], r["raw_value"]))
            continue

        result_map: dict[int, dict] = {}
        for item in parsed:
            if isinstance(item, dict) and "index" in item:
                result_map[item["index"]] = item

        for i, r in enumerate(batch):
            if i in result_map:
                cat_result = result_map[i]
                category = cat_result.get("category", "facts")
                if category not in _KNOWN_CATEGORIES:
                    category = "facts"
                results.append({
                    "category": category,
                    "clean_name": _clean_key(cat_result.get("clean_name", r["raw_key"])),
                    "value": cat_result.get("value", r["raw_value"]),
                    "confidence": max(0.0, min(1.0, float(cat_result.get("confidence", 0.5)))),
                    "source": "migrated",
                })
            else:
                results.append(_fallback_categorize_one(r["raw_key"], r["raw_value"]))

    return results


def categorize_batch(records: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Categorize imported records, using Gemini if available, else rule-based fallback.

    Args:
        records: list of {"raw_key": str, "raw_value": str} from parse_import.

    Returns:
        list of {"category", "clean_name", "value", "confidence", "source"} dicts.
    """
    try:
        return _gemini_categorize_batch(records)
    except ImportError:
        pass  # google-generativeai not installed
    except RuntimeError:
        pass  # API key not set
    except Exception:
        pass  # API error — fall back gracefully

    return [_fallback_categorize_one(r["raw_key"], r["raw_value"]) for r in records]


# ---------------------------------------------------------------------------
# Step 3: Write Records
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_records(categorized: list[dict[str, Any]]) -> dict[str, Any]:
    """Write categorized records to Sibyl Memory using the Coherra schema.

    Each record is written with the standard body shape:
        {value, confidence, source, created_at, updated_at, version}

    Args:
        categorized: list from categorize_batch().

    Returns:
        {"written": int, "errors": list[str], "entities": list[tuple[str,str]]}
    """
    client = open_client()
    now = _iso_now()
    written = 0
    errors: list[str] = []
    entities: list[tuple[str, str]] = []

    for i, rec in enumerate(categorized):
        category = rec["category"]
        name = rec["clean_name"]
        value = rec["value"]
        confidence = rec.get("confidence")
        source = rec.get("source", "migrated")

        body = {
            "value": value,
            "confidence": confidence,
            "source": source,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }

        try:
            client.set_entity(category, name, body)
            entities.append((category, name))
            written += 1
        except Exception as e:
            errors.append(f"Record {i} ({category}/{name}): {e}")

    return {"written": written, "errors": errors, "entities": entities}


# ---------------------------------------------------------------------------
# Step 4: Audit and Repair
# ---------------------------------------------------------------------------

def audit_and_repair(
    imported_names: set[str],
) -> dict[str, Any]:
    """Run the audit engine and apply safe repairs, then summarize.

    Args:
        imported_names: set of "category/name" strings for the newly imported
                        entities, used to filter the summary to only imported issues.

    Returns:
        {
            "issues_found": int,        # total issues involving imported entities
            "auto_cleaned": int,        # duplicates + stale auto-repaired
            "flagged_for_review": int,  # contradictions left for manual resolution
            "all_issues": list[dict],   # full issue list for display
        }
    """
    from .audit import run_audit
    from .repair import apply_safe_repairs

    # Run full audit (checks cross-entity relationships)
    audit_result = run_audit()
    all_issues = audit_result.get("issues_found", [])

    # Filter to issues that involve at least one imported entity
    import_issues = []
    for issue in all_issues:
        addr_a = f"{issue.get('category', '')}/{issue.get('name', '')}"
        addr_b = issue.get("related_entity", "")
        if addr_a in imported_names or addr_b in imported_names:
            import_issues.append(issue)

    # Count contradictions (flagged for review, never auto-resolved)
    contradictions = [i for i in import_issues if i.get("severity") == "contradiction"]

    # Apply safe repairs (stale + duplicates only)
    repair_results = apply_safe_repairs()
    safe_fixed = sum(1 for r in repair_results if r.get("ok"))

    # Count how many of the safe fixes were for imported entities
    # We re-check because apply_safe_repairs works on ALL issues, not just imported
    import_fixed = 0
    for r in repair_results:
        if not r.get("ok"):
            continue
        # Check if this repair involved an imported entity
        iid = r.get("issue_id", "")
        for issue in import_issues:
            if issue.get("id") == iid and issue.get("severity") != "contradiction":
                import_fixed += 1
                break

    return {
        "issues_found": len(import_issues),
        "auto_cleaned": import_fixed,
        "flagged_for_review": len(contradictions),
        "all_issues": import_issues,
    }


# ---------------------------------------------------------------------------
# Step 5: Top-Level Orchestrator
# ---------------------------------------------------------------------------

def onboard(import_data: Any) -> dict[str, Any]:
    """Full onboarding pipeline: parse → categorize → write → audit → repair → summary.

    Args:
        import_data: Raw JSON data (dict, list, or JSON string).

    Returns:
        {
            "ok": True,
            "imported": int,            # records successfully written
            "auto_cleaned": int,        # issues auto-repaired (duplicates + stale)
            "flagged_for_review": int,  # contradictions needing manual resolution
            "write_errors": list[str],  # any write failures
            "issues": list[dict],       # detailed issue list
        }
    """
    # 1. Parse
    records = parse_import(import_data)

    # 2. Categorize
    categorized = categorize_batch(records)

    # 3. Write
    write_result = write_records(categorized)
    imported_names = {f"{cat}/{name}" for cat, name in write_result["entities"]}

    # 4. Audit and repair
    ar_result = audit_and_repair(imported_names)

    return {
        "ok": True,
        "imported": write_result["written"],
        "auto_cleaned": ar_result["auto_cleaned"],
        "flagged_for_review": ar_result["flagged_for_review"],
        "write_errors": write_result["errors"],
        "issues": ar_result["all_issues"],
    }
