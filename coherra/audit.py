"""Coherra audit engine v1.

Single public entry point:  run_audit() -> dict

Three checks (in order of severity):
  1. contradiction  — two entity names that likely refer to the same real-world
                      fact but carry different values.  Detected via normalised
                      name similarity (token overlap + edit distance).
  2. duplicate      — two entities in the same category whose values are
                      nearly identical after normalisation.
  3. stale          — an entity whose body.updated_at is older than the
                      per-category threshold stored in coherra:config.

Health score (0–100):
    start at 100, subtract per issue:
        contradiction  -10
        duplicate       -5
        stale           -2
    floor at 0.

Persistence after every scan:
    memory_set_state("coherra:last_audit", result_dict)
    memory_record_event(kind="coherra_scan", body=result_dict)
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .client import open_client

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
    "staleness_thresholds": {
        # days before an entity is considered stale, keyed by category
        "preference": 30,
        "people":     90,
        "projects":   90,
        "facts":      365,
        # catch-all for any category not listed above
        "_default":   60,
    },
    "auto_repair_safe": False,
}

# Contradiction detector tuning
_CONTRADICTION_EDIT_DIST_THRESHOLD = 4   # max Levenshtein distance between normalised names
_CONTRADICTION_OVERLAP_THRESHOLD   = 0.6 # min Jaccard token overlap

# Short stopword list for the shared-token check — generic words that appear
# in many key names and don't signal same-subject by themselves.
_NAME_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "my", "your", "our",
    "is", "are", "was", "be", "new", "old", "best", "preferred",
    "current", "active", "main", "default",
    # structural key-name words — these appear in many unrelated keys
    "team", "style", "type", "mode", "info", "data", "name",
    "time", "date", "flag", "list", "item", "note", "notes",
    "project", "projects", "user", "profile", "contact", "contacts",
    "export", "fact", "facts", "random", "app", "choice", "order",
    "setting", "settings", "config", "detail", "details",
})

# Duplicate detector tuning
_DUPLICATE_VALUE_SIMILARITY = 0.85       # min normalised string similarity

# Scoring weights
_SCORE_PENALTY = {"contradiction": 10, "duplicate": 5, "stale": 2}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_config(client: Any) -> dict[str, Any]:
    """Read coherra:config from state; seed defaults if absent."""
    result = client.get_state("coherra:config")
    if result is None:
        client.set_state("coherra:config", _DEFAULT_CONFIG)
        return _DEFAULT_CONFIG
    body = result.get("body", result)
    # Merge: any key missing from stored config falls back to the default
    merged = dict(_DEFAULT_CONFIG)
    merged.update(body)
    thresholds = dict(_DEFAULT_CONFIG["staleness_thresholds"])
    thresholds.update(body.get("staleness_thresholds", {}))
    merged["staleness_thresholds"] = thresholds
    return merged


def _staleness_days(category: str, thresholds: dict[str, int]) -> int:
    return thresholds.get(category, thresholds.get("_default", 60))


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^a-z0-9\s]")


def _normalise(text: str) -> str:
    """Lowercase, strip accents, remove punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def _normalise_name(name: str) -> str:
    """Normalise an entity name: split on underscores/hyphens then normalise."""
    name = name.replace("_", " ").replace("-", " ")
    return _normalise(name)


def _tokens(text: str) -> set[str]:
    return set(text.split())


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union)


def _levenshtein(s: str, t: str) -> int:
    """Standard DP Levenshtein distance."""
    m, n = len(s), len(t)
    if m < n:
        s, t, m, n = t, s, n, m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if s[i - 1] == t[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def _token_prefix_match(toks_short: set[str], toks_long: set[str]) -> bool:
    """Return True if every token in the shorter set is a prefix of some
    token in the longer set, AND every token in the longer set is covered
    by some token in the shorter set.

    Handles abbreviation pairs like {"fav","lang"} vs {"favorite","language"}:
      "fav" is a prefix of "favorite", "lang" is a prefix of "language".
    Requires min token length of 3 to avoid spurious matches on very short words.
    """
    if not toks_short or not toks_long:
        return False
    short, long_ = (toks_short, toks_long) if len(toks_short) <= len(toks_long) else (toks_long, toks_short)
    if len(short) != len(long_):
        return False  # must be 1-to-1 to avoid over-matching
    # Each token in short must be a prefix (len>=3) of exactly one token in long
    long_list = list(long_)
    used: set[int] = set()
    for s in short:
        if len(s) < 3:
            return False
        matched = False
        for idx, l in enumerate(long_list):
            if idx not in used and l.startswith(s):
                used.add(idx)
                matched = True
                break
        if not matched:
            return False
    return True


def _names_likely_same_fact(norm_a: str, norm_b: str) -> bool:
    """Return True if two normalised names probably refer to the same subject."""
    if norm_a == norm_b:
        return True
    toks_a = _tokens(norm_a)
    toks_b = _tokens(norm_b)
    # Jaccard overlap on tokens
    if _jaccard(toks_a, toks_b) >= _CONTRADICTION_OVERLAP_THRESHOLD:
        return True
    # Edit distance on the full normalised string
    if _levenshtein(norm_a, norm_b) <= _CONTRADICTION_EDIT_DIST_THRESHOLD:
        return True
    # One is a substring of the other (handles "fav lang" ⊂ "favorite language")
    if norm_a in norm_b or norm_b in norm_a:
        return True
    # Abbreviation match: every token in the shorter name is a prefix of the
    # corresponding token in the longer name (fav→favorite, lang→language)
    if _token_prefix_match(toks_a, toks_b):
        return True
    # Shared substantive token: at least one non-stopword token appears in both
    # (catches "alex role" ∩ "alex job title" = {"alex"},
    #          "lead engineer" ∩ "team lead"  = {"lead"})
    content_a = toks_a - _NAME_STOPWORDS
    content_b = toks_b - _NAME_STOPWORDS
    if len(content_a) >= 1 and len(content_b) >= 1:
        shared = content_a & content_b
        # Require shared token length >= 4 to avoid matching on short noise words
        if any(len(t) >= 4 for t in shared):
            return True
    return False


def _value_similarity(a: Any, b: Any) -> float:
    """Normalised string similarity between two values (0.0–1.0).

    Uses the ratio of the longest common subsequence length to the max length.
    Fast enough for O(n²) over hundreds of entities.
    """
    sa = _normalise(str(a))
    sb = _normalise(str(b))
    if sa == sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    # LCS via DP (bounded; values are short strings in practice)
    m, n = len(sa), len(sb)
    # cap at 400 chars to keep O(m*n) reasonable
    sa, sb = sa[:400], sb[:400]
    m, n = len(sa), len(sb)
    prev = [0] * (n + 1)
    best = 0
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if sa[i - 1] == sb[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
            else:
                curr[j] = 0
        prev = curr
    # Use longest common substring ratio (stricter than LCS subsequence)
    ratio = (2 * best) / (m + n)
    return ratio


def _values_differ(a: Any, b: Any) -> bool:
    """Return True when two values are clearly different (not just reformatted)."""
    sa = _normalise(str(a))
    sb = _normalise(str(b))
    return sa != sb


# ---------------------------------------------------------------------------
# Issue ID — stable, short, content-addressed
# ---------------------------------------------------------------------------

def _issue_id(severity: str, category: str, name: str, detail: str) -> str:
    raw = f"{severity}:{category}:{name}:{detail}"
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_days(ts: str | None) -> float | None:
    dt = _parse_iso(ts)
    if dt is None:
        return None
    delta = datetime.now(timezone.utc) - dt
    return delta.total_seconds() / 86400


# ---------------------------------------------------------------------------
# Entity fetching
# ---------------------------------------------------------------------------

def _fetch_all_entities(client: Any) -> list[dict[str, Any]]:
    """Collect every entity across all categories (up to 200 per call).

    list_entities(category=None) returns all categories in one shot when
    the SDK supports it.  We use limit=200 which is the SDK max.
    """
    rows = client.list_entities(category=None, limit=200)
    # Each row: {id, tenant_id, category, name, status, body, created_at, updated_at}
    # Keep only active (non-archived) entities.
    # status=None means the SDK didn't set it — treat as active.
    return [r for r in rows if r.get("status") in (None, "active")]


# ---------------------------------------------------------------------------
# Check 1: Staleness
# ---------------------------------------------------------------------------

def _check_staleness(
    entities: list[dict[str, Any]],
    thresholds: dict[str, int],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for e in entities:
        category = e.get("category", "")
        name = e.get("name", "")
        body = e.get("body") or {}
        # Use body.updated_at (Coherra's semantic timestamp), fall back to
        # the SDK's updated_at (row write time) only if body timestamp absent.
        updated_at = body.get("updated_at") or e.get("updated_at")
        age = _age_days(updated_at)
        if age is None:
            continue
        threshold = _staleness_days(category, thresholds)
        if age > threshold:
            detail = (
                f"last updated {int(age)} days ago "
                f"(threshold: {threshold} days for '{category}')"
            )
            issues.append({
                "id": _issue_id("stale", category, name, detail),
                "severity": "stale",
                "category": category,
                "name": name,
                "detail": detail,
                "age_days": round(age, 1),
                "threshold_days": threshold,
                "updated_at": updated_at,
            })
    return issues


# ---------------------------------------------------------------------------
# Check 2: Duplicates
# ---------------------------------------------------------------------------

def _check_duplicates(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag entity pairs in the same category whose values are nearly identical."""
    # Group by category
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for e in entities:
        cat = e.get("category", "")
        by_cat.setdefault(cat, []).append(e)

    issues: list[dict[str, Any]] = []
    seen_pairs: set[frozenset[str]] = set()

    for cat, members in by_cat.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                name_a = a.get("name", "")
                name_b = b.get("name", "")
                val_a = (a.get("body") or {}).get("value", "")
                val_b = (b.get("body") or {}).get("value", "")

                pair_key = frozenset([f"{cat}/{name_a}", f"{cat}/{name_b}"])
                if pair_key in seen_pairs:
                    continue

                sim = _value_similarity(val_a, val_b)
                if sim >= _DUPLICATE_VALUE_SIMILARITY:
                    seen_pairs.add(pair_key)
                    detail = (
                        f"'{name_a}' and '{name_b}' in category '{cat}' "
                        f"have near-identical values (similarity {sim:.0%})"
                    )
                    issues.append({
                        "id": _issue_id("duplicate", cat, name_a, name_b),
                        "severity": "duplicate",
                        "category": cat,
                        "name": name_a,
                        "related_entity": f"{cat}/{name_b}",
                        "detail": detail,
                        "similarity": round(sim, 3),
                        "value_a": val_a,
                        "value_b": val_b,
                    })
    return issues


# ---------------------------------------------------------------------------
# Check 3: Contradictions
# ---------------------------------------------------------------------------

def _check_contradictions(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag entity pairs whose normalised names suggest the same subject but
    whose values differ.

    Checks all pairs (same category OR cross-category) because name-drift
    is common across categories.
    """
    issues: list[dict[str, Any]] = []
    seen_pairs: set[frozenset[str]] = set()

    for i in range(len(entities)):
        for j in range(i + 1, len(entities)):
            a, b = entities[i], entities[j]
            cat_a, cat_b = a.get("category", ""), b.get("category", "")
            name_a, name_b = a.get("name", ""), b.get("name", "")

            # Skip pairs already flagged as duplicates (same value)
            val_a = (a.get("body") or {}).get("value", "")
            val_b = (b.get("body") or {}).get("value", "")
            if not _values_differ(val_a, val_b):
                continue

            norm_a = _normalise_name(name_a)
            norm_b = _normalise_name(name_b)
            if not _names_likely_same_fact(norm_a, norm_b):
                continue

            pair_key = frozenset([f"{cat_a}/{name_a}", f"{cat_b}/{name_b}"])
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            detail = (
                f"'{cat_a}/{name_a}' = {val_a!r} "
                f"contradicts '{cat_b}/{name_b}' = {val_b!r} "
                f"(names are likely the same subject)"
            )
            issues.append({
                "id": _issue_id("contradiction", cat_a, name_a, f"{cat_b}/{name_b}"),
                "severity": "contradiction",
                "category": cat_a,
                "name": name_a,
                "related_entity": f"{cat_b}/{name_b}",
                "detail": detail,
                "value_a": val_a,
                "value_b": val_b,
            })
    return issues


# ---------------------------------------------------------------------------
# Health score
# ---------------------------------------------------------------------------

def _compute_health(issues: list[dict[str, Any]]) -> int:
    score = 100
    for issue in issues:
        score -= _SCORE_PENALTY.get(issue["severity"], 0)
    return max(0, score)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_audit(client: Any = None) -> dict[str, Any]:
    """Run a full Coherra audit.

    Args:
        client: Optional storage client.  When ``None`` (default), uses the
                local Sibyl MemoryClient via ``open_client()`` (Track 2).
                Pass a ``PostgresStorageAdapter`` instance for Track 1.

    Returns a result dict:
        {
            "timestamp":    "<iso now>",
            "health_score": 0-100,
            "issues_found": [ {severity, category, name, detail, ...} ],
            "entity_count": N,
        }

    Side-effects:
        - Reads / seeds coherra:config
        - Writes coherra:last_audit state
        - Appends a coherra_scan journal event
    """
    if client is None:
        client = open_client()
    config = _load_config(client)
    thresholds = config.get("staleness_thresholds", _DEFAULT_CONFIG["staleness_thresholds"])

    entities = _fetch_all_entities(client)

    # Run all three checks; order matters for the final list (contradiction first)
    contradiction_issues = _check_contradictions(entities)
    duplicate_issues     = _check_duplicates(entities)
    staleness_issues     = _check_staleness(entities, thresholds)

    all_issues = contradiction_issues + duplicate_issues + staleness_issues
    health = _compute_health(all_issues)
    now = _iso_now()

    result: dict[str, Any] = {
        "timestamp":    now,
        "health_score": health,
        "issues_found": all_issues,
        "entity_count": len(entities),
    }

    # Persist — set_state is an upsert; write_event is append-only
    client.set_state("coherra:last_audit", result)
    client.write_event(
        acted={"kind": "coherra_scan", "body": result},
    )

    return result
