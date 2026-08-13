"""Coherra demo seed — a believable AI coding assistant's memory after months of use.

Usage:
    python -m coherra.seed            # write demo data (idempotent)
    python -m coherra.seed --demo     # wipe ALL coherra entities first, then reload
    python -m coherra.seed --verify   # list what's currently in each category

The story
---------
Alex is a software engineer.  Over the past few months an AI coding assistant
has been accumulating facts about Alex in Sibyl Memory — preferences, project
state, team info, decisions.  The assistant stored facts at different times,
sometimes using slightly different key names for the same concept.  The result
is a memory that's mostly right but riddled with the kind of quiet drift that
builds up in any real long-running agent:

  CONTRADICTION 1 (editor wars, relatable)
    preference/editor           = "VSCode"   ← what the agent noted 2 months ago
    preference/preferred_editor = "Vim"      ← what Alex said last week

  CONTRADICTION 2 (job title changed)
    people/alex_role            = "Senior Engineer"   ← onboarding note
    people/alex_job_title       = "Staff Engineer"    ← noted after promotion

  DUPLICATE 1 (project name, two spellings)
    projects/main_project       = "Nighthawk"
    projects/current_project    = "Nighthawk"

  DUPLICATE 2 (team lead, two keys)
    people/team_lead            = "Jordan"
    people/lead_engineer        = "Jordan"

  STALE 1 (old Python version — 95 days ago)
    facts/python_version        = "3.11"   ← set when project started

  STALE 2 (old deadline — 120 days ago, long past)
    projects/deadline           = "2026-04-30"

  STALE 3 (old test framework preference — 80 days ago)
    preference/test_framework   = "unittest"

  CLEAN (fresh, correct, non-conflicting)
    preference/language         = "Python"
    preference/code_style       = "black + ruff"
    preference/review_style     = "thorough, with inline comments"
    projects/repo               = "github.com/alex/nighthawk"
    projects/status             = "active"
    facts/joined_team           = "2025-01-15"
    facts/timezone              = "Europe/Warsaw"
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from coherra.client import open_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_ago(days: int) -> str:
    ts = datetime.now(timezone.utc) - timedelta(days=days)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _body(
    value: Any,
    *,
    confidence: float = 0.9,
    source: str = "conversation",
    days_old: int | None = None,
    version: int = 1,
) -> dict[str, Any]:
    ts = _iso_ago(days_old) if days_old else _iso_now()
    return {
        "value":      value,
        "confidence": confidence,
        "source":     source,
        "created_at": ts,
        "updated_at": ts,
        "version":    version,
    }


def _w(client: Any, category: str, name: str, b: dict[str, Any], tag: str) -> None:
    client.set_entity(category, name, b)
    age = ""
    ts = b.get("updated_at", "")
    if ts:
        try:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            d  = (datetime.now(timezone.utc) - dt).days
            age = f"  [{d}d old]" if d > 0 else ""
        except ValueError:
            pass
    print(f"  [{tag:<14s}]  {category}/{name} = {b['value']!r}{age}")


# ---------------------------------------------------------------------------
# Wipe helpers
# ---------------------------------------------------------------------------

_DEMO_CATEGORIES = ("preference", "projects", "people", "facts")


def _wipe(client: Any) -> None:
    """Archive every active entity in the demo categories."""
    wiped = 0
    for cat in _DEMO_CATEGORIES:
        try:
            rows = client.list_entities(category=cat, limit=200)
        except Exception:
            rows = []
        for row in rows:
            if row.get("status") not in (None, "active"):
                continue
            try:
                client.archive_entity(cat, row["name"],
                                      reason="wiped by coherra seed --demo")
                wiped += 1
            except Exception:
                pass
    # Also clear the last_audit state so the demo starts fresh
    try:
        client.set_state("coherra:last_audit", {
            "timestamp": _iso_now(),
            "health_score": 100,
            "issues_found": [],
            "entity_count": 0,
            "note": "reset by coherra seed --demo",
        })
    except Exception:
        pass
    print(f"  Wiped {wiped} existing entities across {_DEMO_CATEGORIES}.")


# ---------------------------------------------------------------------------
# Demo dataset
# ---------------------------------------------------------------------------

def seed_demo(client: Any) -> None:
    print("\n── CONTRADICTIONS ─────────────────────────────────────────────────────")
    print("   (same real-world fact, two different keys, conflicting values)\n")

    # C1: Editor wars — VSCode vs Vim
    _w(client, "preference", "editor",
       _body("VSCode", confidence=0.85, source="inference", days_old=62),
       "CONTRADICTION")
    _w(client, "preference", "preferred_editor",
       _body("Vim",    confidence=0.95, source="conversation", days_old=7),
       "CONTRADICTION")

    # C2: Job title — promotion not propagated
    _w(client, "people", "alex_role",
       _body("Senior Engineer", confidence=0.9, source="conversation", days_old=180),
       "CONTRADICTION")
    _w(client, "people", "alex_job_title",
       _body("Staff Engineer",  confidence=0.95, source="conversation", days_old=14),
       "CONTRADICTION")

    print("\n── DUPLICATES ─────────────────────────────────────────────────────────")
    print("   (same value stored under two slightly different keys)\n")

    # D1: Project name spelled two ways
    _w(client, "projects", "main_project",
       _body("Nighthawk", confidence=1.0, source="conversation"),
       "DUPLICATE")
    _w(client, "projects", "current_project",
       _body("Nighthawk", confidence=0.95, source="inference"),
       "DUPLICATE")

    # D2: Team lead stored twice
    _w(client, "people", "team_lead",
       _body("Jordan", confidence=1.0, source="conversation"),
       "DUPLICATE")
    _w(client, "people", "lead_engineer",
       _body("Jordan", confidence=0.9, source="tool"),
       "DUPLICATE")

    print("\n── STALE ───────────────────────────────────────────────────────────────")
    print("   (facts that haven't been refreshed — probably outdated)\n")

    # S1: Python version — set at project start, 95 days ago
    _w(client, "facts", "python_version",
       _body("3.11", confidence=0.8, source="tool", days_old=95),
       "STALE (95d)")

    # S2: Old sprint deadline, 120 days in the past
    _w(client, "projects", "deadline",
       _body("2026-04-30", confidence=1.0, source="conversation", days_old=120),
       "STALE (120d)")

    # S3: Test framework preference, 80 days old
    _w(client, "preference", "test_framework",
       _body("unittest", confidence=0.7, source="inference", days_old=80),
       "STALE (80d)")

    print("\n── CLEAN ───────────────────────────────────────────────────────────────")
    print("   (fresh, correct, no conflicts — audit should leave these alone)\n")

    _w(client, "preference", "language",
       _body("Python",                        confidence=1.0, source="conversation"),
       "CLEAN")
    _w(client, "preference", "code_style",
       _body("black + ruff",                  confidence=1.0, source="conversation"),
       "CLEAN")
    _w(client, "preference", "review_style",
       _body("thorough, with inline comments", confidence=0.9, source="conversation"),
       "CLEAN")
    _w(client, "projects", "repo",
       _body("github.com/alex/nighthawk",     confidence=1.0, source="tool"),
       "CLEAN")
    _w(client, "projects", "status",
       _body("active",                        confidence=1.0, source="tool"),
       "CLEAN")
    _w(client, "facts", "joined_team",
       _body("2025-01-15",                    confidence=1.0, source="conversation"),
       "CLEAN")
    _w(client, "facts", "timezone",
       _body("Europe/Warsaw",                 confidence=1.0, source="conversation"),
       "CLEAN")

    print()


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def verify(client: Any) -> None:
    print("\nVerifying demo data in Sibyl Memory:")
    total = 0
    for cat in _DEMO_CATEGORIES:
        rows = client.list_entities(category=cat, limit=50)
        active = [r for r in rows if r.get("status") in (None, "active")]
        names  = [r.get("name") for r in active]
        print(f"  {cat:12s}  {len(active):2d} entities: {names}")
        total += len(active)
    print(f"\n  Total active: {total}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(demo: bool = False) -> None:
    client = open_client()

    if demo:
        print("coherra seed --demo: wiping existing demo data…")
        _wipe(client)
        print()

    print("Writing Coherra demo dataset (Alex the coding assistant's memory)…")
    seed_demo(client)
    verify(client)
    print("Done.  Run: coherra scan")


if __name__ == "__main__":
    demo_flag = "--demo" in sys.argv
    main(demo=demo_flag)
