"""Coherra MCP server.

Exposes Coherra's own tools to any MCP-compatible agent (Claude Code,
Codex CLI, Cursor, etc.).  Runs over stdio transport, same as sibyl-memory-mcp.

Checkpoint 1 tools:
  - coherra_remember   structured entity write (wraps memory_remember)

Checkpoint 2 tools:
  - coherra_recall     read one Coherra entity by (category, name)
  - coherra_list       list Coherra entities, optionally filtered by category

Checkpoint 3 tools:
  - coherra_audit        run a full audit and return health score + issues

Checkpoint 4 tools:
  - coherra_repair       apply one repair to a specific issue
  - coherra_repair_safe  batch-apply all safe (non-contradiction) repairs

Phase 2 — Feature A tools:
  - coherra_onboard      import JSON data, categorize, write, audit, repair
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, NoReturn

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from sibyl_memory_client.exceptions import (
    CapExceededError,
    NotFoundError,
    TierGateError,
    TierVerificationError,
    ValidationError,
)

from .client import open_client


# ---------------------------------------------------------------------------
# Error mapping (mirrors sibyl_memory_mcp._err)
# ---------------------------------------------------------------------------

def _err(e: Exception) -> NoReturn:
    """Map an SDK exception to a ToolError (isError=true in the MCP envelope).

    The structured JSON payload lets agents parse error/code/recovery
    programmatically, same contract as sibyl-memory-mcp.
    """
    cls = type(e).__name__
    payload: dict[str, Any] = {"ok": False, "error": cls, "message": str(e)}

    if isinstance(e, CapExceededError):
        payload["code"] = "CAP_EXCEEDED"
        payload["recovery"] = "Run `sibyl upgrade` to lift the 5 MB free-tier cap."
        payload["upgrade_url"] = getattr(
            e, "upgrade_url", "https://sibyllabs.org/plugin/upgrade"
        )
    elif isinstance(e, TierGateError):
        payload["code"] = "TIER_GATED"
        payload["recovery"] = "This feature requires a paid tier. Run `sibyl upgrade`."
    elif isinstance(e, TierVerificationError):
        payload["code"] = "TIER_VERIFICATION_FAILED"
        payload["recovery"] = (
            "The server couldn't verify your tier. Check connectivity and try again."
        )
    elif isinstance(e, NotFoundError):
        payload["code"] = "NOT_FOUND"
    elif isinstance(e, ValidationError):
        payload["code"] = "VALIDATION_ERROR"
    else:
        payload.setdefault("code", "ERROR")

    raise ToolError(json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_body(
    value: Any,
    confidence: float | None,
    source: str | None,
    now: str,
) -> dict[str, Any]:
    """Build the Coherra structured entity body.

    Shape (from blueprint §2):
        {
            "value":      <the fact>,
            "confidence": 0.0-1.0 | null,
            "source":     "conversation|tool|inference" | null,
            "created_at": "<iso ts>",
            "updated_at": "<iso ts>",
            "version":    1
        }

    created_at and updated_at are both set to `now` on first write; the
    repair engine (checkpoint 2) will increment version and update
    updated_at on rewrites.
    """
    return {
        "value": value,
        "confidence": confidence,
        "source": source,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def build_server() -> FastMCP:
    """Build and return the Coherra MCP server."""
    mcp = FastMCP("coherra")

    # ------------------------------------------------------------------
    # coherra_remember
    # ------------------------------------------------------------------

    @mcp.tool()
    def coherra_remember(
        category: str,
        name: str,
        value: Any,
        confidence: float | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Store a structured fact in Sibyl Memory using Coherra's schema.

        Wraps `memory_remember` with a versioned body shape so all Coherra
        entities are uniform and auditable.

        Args:
            category:   Logical grouping, e.g. "people", "projects", "prefs".
            name:       Unique-within-category key, e.g. "alice", "acme-deal".
            value:      The fact to store — any JSON-serialisable value.
            confidence: Optional float 0.0–1.0 expressing certainty.
            source:     Optional provenance tag: "conversation", "tool",
                        "inference", etc.

        Returns:
            {"ok": True, "category": ..., "name": ...} on success.
        """
        try:
            now = _iso_now()
            body = _build_body(value, confidence, source, now)
            client = open_client()
            client.set_entity(category, name, body)
            return {"ok": True, "category": category, "name": name}
        except Exception as e:
            _err(e)

    # ------------------------------------------------------------------
    # coherra_recall
    # ------------------------------------------------------------------

    @mcp.tool()
    def coherra_recall(category: str, name: str) -> dict[str, Any]:
        """Fetch a single Coherra entity by (category, name).

        Returns the full entity including the structured Coherra body
        (value, confidence, source, created_at, updated_at, version).
        Raises a NOT_FOUND error if the entity does not exist.

        Args:
            category: The category the entity was stored under.
            name:     The unique-within-category key.

        Returns:
            {"ok": True, "category": ..., "name": ..., "body": {...}}
        """
        try:
            client = open_client()
            entity = client.get_entity(category, name)
            # entity shape from SDK: {id, tenant_id, category, name,
            # status, body, created_at, updated_at}
            return {
                "ok": True,
                "category": entity.get("category", category),
                "name": entity.get("name", name),
                "body": entity.get("body"),
                "updated_at": entity.get("updated_at"),
            }
        except Exception as e:
            _err(e)

    # ------------------------------------------------------------------
    # coherra_list
    # ------------------------------------------------------------------

    @mcp.tool()
    def coherra_list(
        category: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List entities managed by Coherra, optionally filtered by category.

        Returns entities most-recently-updated first.  Each result includes
        the structured Coherra body so the caller can inspect value,
        confidence, source, and timestamps without a separate recall call.

        Args:
            category: Optional category filter.  Omit to list all categories.
            limit:    Maximum entities to return (default 50, max 200).

        Returns:
            {"ok": True, "category": ..., "count": N, "results": [...]}
        """
        try:
            client = open_client()
            safe_limit = min(max(limit, 1), 200)
            entities = client.list_entities(category=category, limit=safe_limit)
            # Slim each row to the fields callers care about; body stays intact
            # so the audit engine can read Coherra-structured fields directly.
            results = [
                {
                    "category": e.get("category"),
                    "name": e.get("name"),
                    "body": e.get("body"),
                    "updated_at": e.get("updated_at"),
                }
                for e in entities
            ]
            return {
                "ok": True,
                "category": category,
                "count": len(results),
                "results": results,
            }
        except Exception as e:
            _err(e)

    # ------------------------------------------------------------------
    # coherra_audit
    # ------------------------------------------------------------------

    @mcp.tool()
    def coherra_audit() -> dict[str, Any]:
        """Run a full Coherra memory audit and return the results.

        Scans all entities in Sibyl Memory for three classes of drift:
          - contradiction  two names that likely refer to the same fact
                           but carry different values
          - duplicate      two entities in the same category with nearly
                           identical values
          - stale          an entity whose body.updated_at exceeds the
                           per-category threshold from coherra:config

        Side-effects:
          - Seeds coherra:config with default thresholds if absent
          - Writes results to coherra:last_audit (memory_set_state)
          - Appends a coherra_scan journal event (memory_record_event)

        Returns:
            {
                "ok": True,
                "timestamp":    "<iso now>",
                "health_score": 0-100,
                "entity_count": N,
                "issue_count":  N,
                "issues_found": [ {severity, category, name, detail, ...} ]
            }
        """
        try:
            from .audit import run_audit
            result = run_audit()
            return {
                "ok": True,
                **result,
                "issue_count": len(result.get("issues_found", [])),
            }
        except Exception as e:
            _err(e)

    # ------------------------------------------------------------------
    # coherra_repair
    # ------------------------------------------------------------------

    @mcp.tool()
    def coherra_repair(
        issue_id: str,
        action: str,
        value: Any = None,
    ) -> dict[str, Any]:
        """Apply one repair to a flagged issue from the last audit.

        Actions by severity:
          stale:          "archive" — forget the entity
                          "refresh" — bump updated_at to now (fact still true)
          duplicate:      "merge"   — keep higher-confidence entry, archive the other
          contradiction:  "keep_a"  — keep primary (category/name), archive related
                          "keep_b"  — keep related_entity, archive primary
                          "merge_manual" — archive both, write new canonical entity
                                          at primary address using supplied `value`

        Args:
            issue_id: 10-char hex id from coherra_audit issues_found list.
            action:   Repair action string (see above).
            value:    Required only for contradiction/merge_manual — the
                      correct canonical value to write.

        Returns:
            {ok, issue_id, severity, action_taken, archived, written}
        """
        try:
            from .repair import apply_repair
            return apply_repair(issue_id, action, value=value)
        except (KeyError, ValueError) as e:
            raise ToolError(json.dumps({
                "ok": False, "code": "REPAIR_ERROR",
                "error": type(e).__name__, "message": str(e),
            }))
        except Exception as e:
            _err(e)

    # ------------------------------------------------------------------
    # coherra_repair_safe
    # ------------------------------------------------------------------

    @mcp.tool()
    def coherra_repair_safe() -> dict[str, Any]:
        """Batch-apply all safe repairs from the last audit.

        Auto-applies:
          - stale   → archive   (entity is old, remove it)
          - duplicate → merge   (keep higher-confidence copy, archive the other)

        Contradictions are NEVER auto-resolved — they require explicit human
        choice via coherra_repair with keep_a / keep_b / merge_manual.

        Returns:
            {ok, fixed_count, skipped_contradictions, results: [...]}
        """
        try:
            from .repair import apply_safe_repairs
            results = apply_safe_repairs()
            ok_count   = sum(1 for r in results if r.get("ok"))
            fail_count = sum(1 for r in results if not r.get("ok"))
            return {
                "ok":                      True,
                "fixed_count":             ok_count,
                "failed_count":            fail_count,
                "results":                 results,
            }
        except Exception as e:
            _err(e)

    # ------------------------------------------------------------------
    # coherra_onboard  (Phase 2 — Feature A)
    # ------------------------------------------------------------------

    @mcp.tool()
    def coherra_onboard(import_data: dict) -> dict[str, Any]:
        """Import JSON data from another tool into Coherra.

        Runs the full onboarding pipeline:
          1. Parse the JSON into individual records
          2. Categorize each record (category, name, confidence)
          3. Write to Sibyl Memory using the Coherra schema
          4. Audit for contradictions, duplicates, staleness
          5. Auto-repair safe issues (duplicates + stale)
          6. Flag contradictions for manual review

        Args:
            import_data: A dict or list representing the JSON export.
                         Accepts flat dicts, nested dicts, lists of dicts
                         (with key/value fields), or lists of strings.

        Returns:
            {
                "ok": True,
                "imported": N,            # records written
                "auto_cleaned": X,        # safe issues fixed
                "flagged_for_review": Y,  # contradictions needing manual fix
            }
        """
        try:
            from .onboard import onboard, ImportParseError
            result = onboard(import_data)
            return {
                "ok": True,
                "imported": result["imported"],
                "auto_cleaned": result["auto_cleaned"],
                "flagged_for_review": result["flagged_for_review"],
                "write_errors": result.get("write_errors", []),
                "issues": [
                    {
                        "severity": i.get("severity"),
                        "category": i.get("category"),
                        "name": i.get("name"),
                        "detail": i.get("detail"),
                    }
                    for i in result.get("issues", [])
                ],
            }
        except ImportParseError as e:
            raise ToolError(json.dumps({
                "ok": False,
                "code": "IMPORT_PARSE_ERROR",
                "record_index": e.record_index,
                "field": e.field,
                "message": str(e),
            }))
        except Exception as e:
            _err(e)

    return mcp


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_stdio() -> None:
    """Start the Coherra MCP server on stdio transport."""
    build_server().run()
