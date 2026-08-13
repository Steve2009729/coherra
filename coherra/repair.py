"""Coherra repair engine v1.

Public entry points:
    apply_repair(issue_id, action, *, value=None) -> dict
    apply_safe_repairs() -> list[dict]

Repair actions by severity:

  stale
    "archive"   — memory_forget(reason="stale, not refreshed by repair")
    "refresh"   — rewrite the entity with updated_at = now, version bumped
                  (caller confirms the fact is still accurate)

  duplicate
    "merge"     — keep the higher-confidence / more-complete entry,
                  archive the other with reason="duplicate of <kept>"

  contradiction
    "keep_a"    — archive the related_entity, keep the primary (category/name)
    "keep_b"    — archive the primary, keep the related_entity
    "merge_manual" — caller supplies correct value; both old entries are
                     archived and a new canonical entity is written to the
                     primary (category/name) with the supplied value

Every repair:
  1. Applies the memory_forget / memory_remember calls.
  2. Writes a coherra_repair journal event (permanent, append-only).
  3. Returns a summary dict.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .client import open_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_last_audit(client: Any) -> dict[str, Any]:
    result = client.get_state("coherra:last_audit")
    if result is None:
        return {}
    return result.get("body", result) or {}


def _find_issue(client: Any, issue_id: str) -> dict[str, Any] | None:
    """Look up one issue by its id from the last audit result."""
    audit = _get_last_audit(client)
    for issue in audit.get("issues_found", []):
        if issue.get("id") == issue_id:
            return issue
    return None


def _get_entity(client: Any, category: str, name: str) -> dict[str, Any] | None:
    """Fetch one entity; return None if not found."""
    try:
        return client.get_entity(category, name)
    except Exception:
        return None


def _parse_ref(ref: str) -> tuple[str, str]:
    """Split 'category/name' into (category, name).  Raises ValueError if malformed."""
    parts = ref.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid entity reference: {ref!r} (expected 'category/name')")
    return parts[0], parts[1]


def _bump_body(old_body: dict[str, Any], now: str) -> dict[str, Any]:
    """Return a copy of old_body with updated_at=now and version incremented."""
    new = dict(old_body)
    new["updated_at"] = now
    new["version"] = int(old_body.get("version", 1)) + 1
    return new


def _log_repair(
    client: Any,
    *,
    issue_id: str,
    severity: str,
    action_taken: str,
    before: dict[str, Any],
    after: dict[str, Any] | None,
    timestamp: str,
) -> None:
    """Append a permanent coherra_repair journal entry."""
    body = {
        "issue_id":     issue_id,
        "severity":     severity,
        "action_taken": action_taken,
        "before":       before,
        "after":        after,
        "timestamp":    timestamp,
    }
    try:
        client.write_event(acted={"kind": "coherra_repair", "body": body})
    except Exception:
        pass  # journal write failure must never abort the repair itself


def _summary(
    issue_id: str,
    severity: str,
    action_taken: str,
    archived: list[str],
    written: list[str],
) -> dict[str, Any]:
    return {
        "ok":           True,
        "issue_id":     issue_id,
        "severity":     severity,
        "action_taken": action_taken,
        "archived":     archived,
        "written":      written,
    }


# ---------------------------------------------------------------------------
# Per-severity repair implementations
# ---------------------------------------------------------------------------

def _repair_stale(
    client: Any,
    issue: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    category = issue["category"]
    name     = issue["name"]
    issue_id = issue["id"]
    now      = _iso_now()

    entity = _get_entity(client, category, name)
    before = {"category": category, "name": name, "body": entity.get("body") if entity else None}

    if action == "archive":
        if entity is None:
            # Entity already archived (e.g. by a prior contradiction repair) — idempotent.
            return _summary(issue_id, "stale", "archive (already gone)", [f"{category}/{name}"], [])
        client.archive_entity(category, name, reason="stale, not refreshed by coherra repair")
        after = None
        _log_repair(client, issue_id=issue_id, severity="stale",
                    action_taken="archive", before=before, after=after, timestamp=now)
        return _summary(issue_id, "stale", "archive", [f"{category}/{name}"], [])

    if action == "refresh":
        if entity is None:
            raise ValueError(f"Entity {category}/{name} not found; cannot refresh.")
        old_body = entity.get("body") or {}
        new_body = _bump_body(old_body, now)
        client.set_entity(category, name, new_body)
        after = {"category": category, "name": name, "body": new_body}
        _log_repair(client, issue_id=issue_id, severity="stale",
                    action_taken="refresh", before=before, after=after, timestamp=now)
        return _summary(issue_id, "stale", "refresh", [], [f"{category}/{name}"])

    raise ValueError(f"Unknown action for stale issue: {action!r}. Valid: archive, refresh")


def _repair_duplicate(
    client: Any,
    issue: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    if action != "merge":
        raise ValueError(f"Unknown action for duplicate issue: {action!r}. Valid: merge")

    category  = issue["category"]
    name_a    = issue["name"]
    ref_b     = issue.get("related_entity", "")
    issue_id  = issue["id"]
    now       = _iso_now()

    cat_b, name_b = _parse_ref(ref_b)

    entity_a = _get_entity(client, category, name_a)
    entity_b = _get_entity(client, cat_b, name_b)

    body_a = (entity_a or {}).get("body") or {}
    body_b = (entity_b or {}).get("body") or {}

    # Keep the entry with higher confidence; fall back to entity_a
    conf_a = body_a.get("confidence") or 0.0
    conf_b = body_b.get("confidence") or 0.0

    if conf_b > conf_a:
        kept_cat, kept_name, kept_body = cat_b, name_b, body_b
        drop_cat, drop_name            = category, name_a
    else:
        kept_cat, kept_name, kept_body = category, name_a, body_a
        drop_cat, drop_name            = cat_b, name_b

    before = {
        "a": {"category": category,  "name": name_a, "body": body_a},
        "b": {"category": cat_b,     "name": name_b, "body": body_b},
    }

    client.archive_entity(
        drop_cat, drop_name,
        reason=f"duplicate of {kept_cat}/{kept_name}; merged by coherra repair",
    )

    after = {"kept": f"{kept_cat}/{kept_name}", "archived": f"{drop_cat}/{drop_name}"}
    _log_repair(client, issue_id=issue_id, severity="duplicate",
                action_taken="merge", before=before, after=after, timestamp=now)

    return _summary(issue_id, "duplicate", "merge",
                    [f"{drop_cat}/{drop_name}"],
                    [f"{kept_cat}/{kept_name} (unchanged)"])


def _repair_contradiction(
    client: Any,
    issue: dict[str, Any],
    action: str,
    value: Any = None,
) -> dict[str, Any]:
    valid_actions = ("keep_a", "keep_b", "merge_manual")
    if action not in valid_actions:
        raise ValueError(
            f"Unknown action for contradiction issue: {action!r}. "
            f"Valid: {', '.join(valid_actions)}"
        )

    category  = issue["category"]
    name_a    = issue["name"]
    ref_b     = issue.get("related_entity", "")
    issue_id  = issue["id"]
    now       = _iso_now()

    cat_b, name_b = _parse_ref(ref_b)

    entity_a = _get_entity(client, category, name_a)
    entity_b = _get_entity(client, cat_b,    name_b)

    body_a = (entity_a or {}).get("body") or {}
    body_b = (entity_b or {}).get("body") or {}

    before = {
        "a": {"category": category, "name": name_a, "body": body_a},
        "b": {"category": cat_b,    "name": name_b, "body": body_b},
    }

    if action == "keep_a":
        client.archive_entity(
            cat_b, name_b,
            reason=f"contradicted by {category}/{name_a}; resolved by coherra repair",
        )
        after = {"kept": f"{category}/{name_a}", "archived": f"{cat_b}/{name_b}"}
        _log_repair(client, issue_id=issue_id, severity="contradiction",
                    action_taken="keep_a", before=before, after=after, timestamp=now)
        return _summary(issue_id, "contradiction", "keep_a",
                        [f"{cat_b}/{name_b}"], [f"{category}/{name_a} (unchanged)"])

    if action == "keep_b":
        client.archive_entity(
            category, name_a,
            reason=f"contradicted by {cat_b}/{name_b}; resolved by coherra repair",
        )
        after = {"kept": f"{cat_b}/{name_b}", "archived": f"{category}/{name_a}"}
        _log_repair(client, issue_id=issue_id, severity="contradiction",
                    action_taken="keep_b", before=before, after=after, timestamp=now)
        return _summary(issue_id, "contradiction", "keep_b",
                        [f"{category}/{name_a}"], [f"{cat_b}/{name_b} (unchanged)"])

    # merge_manual — caller supplies the correct value
    if value is None:
        raise ValueError(
            "merge_manual requires a 'value' argument with the correct canonical value."
        )

    # Archive both old entries
    client.archive_entity(
        category, name_a,
        reason=f"merged by coherra repair (contradiction with {cat_b}/{name_b})",
    )
    client.archive_entity(
        cat_b, name_b,
        reason=f"merged by coherra repair (contradiction with {category}/{name_a})",
    )

    # Write the canonical replacement at the primary (category/name_a) address
    merged_body = {
        "value":      value,
        "confidence": max(
            body_a.get("confidence") or 0.0,
            body_b.get("confidence") or 0.0,
        ),
        "source":     "coherra_repair",
        "created_at": body_a.get("created_at") or now,
        "updated_at": now,
        "version":    max(
            int(body_a.get("version", 1)),
            int(body_b.get("version", 1)),
        ) + 1,
    }
    client.set_entity(category, name_a, merged_body)

    after = {
        "canonical": f"{category}/{name_a}",
        "archived":  [f"{category}/{name_a} (old)", f"{cat_b}/{name_b}"],
        "value":     value,
    }
    _log_repair(client, issue_id=issue_id, severity="contradiction",
                action_taken="merge_manual", before=before, after=after, timestamp=now)

    return _summary(issue_id, "contradiction", "merge_manual",
                    [f"{category}/{name_a} (old)", f"{cat_b}/{name_b}"],
                    [f"{category}/{name_a} (canonical, value={value!r})"])


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def apply_repair(
    issue_id: str,
    action: str,
    *,
    value: Any = None,
) -> dict[str, Any]:
    """Apply one repair to a specific issue.

    Args:
        issue_id: The 10-char hex id from the audit issue list.
        action:   The repair action to apply.
                    stale:         "archive" | "refresh"
                    duplicate:     "merge"
                    contradiction: "keep_a" | "keep_b" | "merge_manual"
        value:    Required only for contradiction/merge_manual — the
                  correct canonical value to write.

    Returns:
        {ok, issue_id, severity, action_taken, archived, written}

    Raises:
        KeyError  if the issue_id is not found in the last audit.
        ValueError if the action is invalid for the severity.
    """
    client = open_client()
    issue  = _find_issue(client, issue_id)
    if issue is None:
        raise KeyError(
            f"Issue {issue_id!r} not found in last audit. "
            "Run `coherra scan` to refresh, then retry."
        )

    severity = issue.get("severity", "")

    if severity == "stale":
        return _repair_stale(client, issue, action)
    if severity == "duplicate":
        return _repair_duplicate(client, issue, action)
    if severity == "contradiction":
        return _repair_contradiction(client, issue, action, value=value)

    raise ValueError(f"Unknown issue severity: {severity!r}")


def apply_safe_repairs() -> list[dict[str, Any]]:
    """Auto-apply all safe repairs from the last audit.

    Safe = stale→archive and duplicate→merge only.
    Contradictions are NEVER auto-resolved.

    Returns a list of repair summary dicts (one per fix applied).
    """
    client   = open_client()
    audit    = _get_last_audit(client)
    issues   = audit.get("issues_found", [])
    results: list[dict[str, Any]] = []

    for issue in issues:
        severity = issue.get("severity", "")
        iid      = issue.get("id", "")
        try:
            if severity == "stale":
                results.append(apply_repair(iid, "archive"))
            elif severity == "duplicate":
                results.append(apply_repair(iid, "merge"))
            # contradictions: skip silently
        except Exception as exc:
            results.append({
                "ok":       False,
                "issue_id": iid,
                "severity": severity,
                "error":    str(exc),
            })

    return results
