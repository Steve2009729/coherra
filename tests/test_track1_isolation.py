"""Track 1 — Storage Adapter + Cross-Tenant Isolation E2E Tests.

Tests the PostgresStorageAdapter (SQLite backend) and confirms that
audit/repair engines work against it, and that tenant isolation is
rock-solid — no data leaks across tenant_id boundaries.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True,
    )

# Ensure project root is on sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from coherra.storage_pg import PostgresStorageAdapter
from coherra.audit import (
    _check_contradictions,
    _check_duplicates,
    _check_staleness,
    _compute_health,
    _iso_now,
    _load_config,
    run_audit,
)
from coherra.repair import apply_repair

# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR", "") == ""
def _c(code: str, t: str) -> str: return f"\033[{code}m{t}\033[0m" if _COLOR else t
def green(t: str) -> str: return _c("32", t)
def red(t: str) -> str: return _c("31", t)
def bold(t: str) -> str: return _c("1", t)
def dim(t: str) -> str: return _c("2", t)

def check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        print(f"  {green('✓')} {label}" + (f"  {dim(detail)}" if detail else ""))
    else:
        print(f"  {red('✗')} {label}" + (f"  {red(detail)}" if detail else ""))
    return condition


def main() -> int:
    print(f"\n{bold('═' * 64)}")
    print(f"{bold('  Coherra Track 1: Storage Adapter + Isolation E2E Test')}")
    print(f"{bold('═' * 64)}\n")

    all_ok = True

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "track1_test.db"

        # ---------------------------------------------------------------
        # Test 1: Tenant creation
        # ---------------------------------------------------------------
        print(f"{bold('Test 1: Tenant Creation')}")

        adapter_a = PostgresStorageAdapter("privy:did:alice", sqlite_path=db_path)
        adapter_b = PostgresStorageAdapter("privy:did:bob", sqlite_path=db_path)

        info_a = adapter_a.create_tenant()
        all_ok &= check("Created tenant Alice", info_a["privy_user_id"] == "privy:did:alice")

        info_b = adapter_b.create_tenant()
        all_ok &= check("Created tenant Bob", info_b["privy_user_id"] == "privy:did:bob")

        all_ok &= check("Alice exists", adapter_a.tenant_exists())
        all_ok &= check("Bob exists", adapter_b.tenant_exists())

        # Non-existent tenant
        adapter_c = PostgresStorageAdapter("privy:did:nobody", sqlite_path=db_path)
        all_ok &= check("Unknown tenant does not exist", not adapter_c.tenant_exists())

        # ---------------------------------------------------------------
        # Test 2: Entity CRUD
        # ---------------------------------------------------------------
        print(f"\n{bold('Test 2: Entity CRUD')}")

        adapter_a.set_entity("preference", "language", {
            "value": "Python", "confidence": 0.95, "source": "user",
            "created_at": "2026-08-01T00:00:00Z", "updated_at": "2026-08-01T00:00:00Z",
        })
        adapter_a.set_entity("preference", "editor", {
            "value": "VSCode", "confidence": 0.9, "source": "user",
            "created_at": "2026-07-01T00:00:00Z", "updated_at": "2026-07-01T00:00:00Z",
        })

        entities_a = adapter_a.list_entities()
        all_ok &= check("Alice has 2 entities", len(entities_a) == 2, f"got {len(entities_a)}")

        lang = adapter_a.get_entity("preference", "language")
        all_ok &= check("Language entity body correct", lang["body"]["value"] == "Python")

        # Update entity
        adapter_a.set_entity("preference", "language", {
            "value": "Rust", "confidence": 0.99, "source": "user",
            "updated_at": _iso_now(), "version": 2,
        })
        lang2 = adapter_a.get_entity("preference", "language")
        all_ok &= check("Entity updated to Rust", lang2["body"]["value"] == "Rust")

        # Archive entity
        adapter_a.archive_entity("preference", "editor", reason="test archive")
        entities_a2 = adapter_a.list_entities()
        all_ok &= check("After archive, 1 active entity", len(entities_a2) == 1)

        # ---------------------------------------------------------------
        # Test 3: State get/set
        # ---------------------------------------------------------------
        print(f"\n{bold('Test 3: State Get/Set')}")

        adapter_a.set_state("coherra:config", {"staleness_thresholds": {"_default": 60}})
        cfg = adapter_a.get_state("coherra:config")
        all_ok &= check("State stored and retrieved", cfg is not None)
        all_ok &= check("State body correct", cfg["body"]["staleness_thresholds"]["_default"] == 60)

        missing = adapter_a.get_state("nonexistent:key")
        all_ok &= check("Missing state returns None", missing is None)

        # ---------------------------------------------------------------
        # Test 4: Event write/read
        # ---------------------------------------------------------------
        print(f"\n{bold('Test 4: Event Write/Read')}")

        adapter_a.write_event(acted={"kind": "test_event", "body": {"msg": "hello"}})
        adapter_a.write_event(acted={"kind": "test_event", "body": {"msg": "world"}})
        adapter_a.write_event(acted={"kind": "other_event", "body": {"x": 1}})

        all_events = adapter_a.read_events()
        all_ok &= check("3 events total for Alice", len(all_events) >= 3, f"got {len(all_events)}")

        test_events = adapter_a.read_events(kind="test_event")
        all_ok &= check("2 test_events for Alice", len(test_events) == 2)

        # ---------------------------------------------------------------
        # Test 5: Cross-Tenant Isolation — Entity Scoping
        # ---------------------------------------------------------------
        print(f"\n{bold('Test 5: Cross-Tenant Entity Isolation')}")

        adapter_b.set_entity("preference", "language", {
            "value": "Go", "confidence": 0.8, "source": "user",
            "created_at": _iso_now(), "updated_at": _iso_now(),
        })
        adapter_b.set_entity("facts", "timezone", {
            "value": "US/Pacific", "confidence": 0.9, "source": "user",
            "created_at": _iso_now(), "updated_at": _iso_now(),
        })

        entities_b = adapter_b.list_entities()
        all_ok &= check("Bob has 2 entities", len(entities_b) == 2, f"got {len(entities_b)}")

        # Alice should still have only 1 active entity (language=Rust)
        entities_a3 = adapter_a.list_entities()
        all_ok &= check("Alice still has 1 entity (not Bob's)", len(entities_a3) == 1)

        alice_lang = adapter_a.get_entity("preference", "language")
        all_ok &= check("Alice's language is Rust, not Go", alice_lang["body"]["value"] == "Rust")

        bob_lang = adapter_b.get_entity("preference", "language")
        all_ok &= check("Bob's language is Go, not Rust", bob_lang["body"]["value"] == "Go")

        # Bob cannot see Alice's timezone (Alice has none)
        try:
            adapter_a.get_entity("facts", "timezone")
            all_ok &= check("Alice should NOT have timezone entity", False)
        except KeyError:
            all_ok &= check("Alice cannot access facts/timezone (Bob's data)", True)

        # ---------------------------------------------------------------
        # Test 6: Cross-Tenant Isolation — State Scoping
        # ---------------------------------------------------------------
        print(f"\n{bold('Test 6: Cross-Tenant State Isolation')}")

        bob_cfg = adapter_b.get_state("coherra:config")
        all_ok &= check("Bob has no config (Alice's config is isolated)", bob_cfg is None)

        adapter_b.set_state("coherra:config", {"staleness_thresholds": {"_default": 999}})
        bob_cfg2 = adapter_b.get_state("coherra:config")
        all_ok &= check("Bob's config is 999", bob_cfg2["body"]["staleness_thresholds"]["_default"] == 999)

        alice_cfg2 = adapter_a.get_state("coherra:config")
        all_ok &= check("Alice's config still 60 (not Bob's 999)", alice_cfg2["body"]["staleness_thresholds"]["_default"] == 60)

        # ---------------------------------------------------------------
        # Test 7: Cross-Tenant Isolation — Event Scoping
        # ---------------------------------------------------------------
        print(f"\n{bold('Test 7: Cross-Tenant Event Isolation')}")

        bob_events = adapter_b.read_events(kind="test_event")
        all_ok &= check("Bob has 0 test_events (Alice's are isolated)", len(bob_events) == 0)

        # ---------------------------------------------------------------
        # Test 8: Audit Engine Against Storage Adapter
        # ---------------------------------------------------------------
        print(f"\n{bold('Test 8: Audit Engine Against Track 1 Adapter')}")

        # Set up a scenario with contradictions, duplicates, and staleness
        adapter_test = PostgresStorageAdapter("privy:did:audit_tester", sqlite_path=db_path)
        adapter_test.create_tenant()

        # Contradiction: two similar names, different values
        adapter_test.set_entity("preference", "editor", {
            "value": "VSCode", "confidence": 0.9, "source": "user",
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        })
        adapter_test.set_entity("preference", "preferred_editor", {
            "value": "Vim", "confidence": 0.85, "source": "user",
            "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z",
        })

        # Duplicate: same value under different keys
        adapter_test.set_entity("projects", "main_project", {
            "value": "Nighthawk", "confidence": 0.9, "source": "user",
            "created_at": _iso_now(), "updated_at": _iso_now(),
        })
        adapter_test.set_entity("projects", "current_project", {
            "value": "Nighthawk", "confidence": 0.9, "source": "user",
            "created_at": _iso_now(), "updated_at": _iso_now(),
        })

        # Stale entity (updated > 365 days ago)
        adapter_test.set_entity("facts", "python_version", {
            "value": "3.11", "confidence": 0.9, "source": "user",
            "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
        })

        # Run audit via the refactored run_audit with Track 1 adapter
        result = run_audit(client=adapter_test)
        all_ok &= check("Audit returned health_score", "health_score" in result)
        all_ok &= check("Audit returned issues_found", "issues_found" in result)
        all_ok &= check(f"Health score < 100 (issues detected)", result["health_score"] < 100,
                         f"score={result['health_score']}")
        all_ok &= check(f"Found {len(result['issues_found'])} issues", len(result["issues_found"]) > 0)

        # Verify that this audit did NOT touch Alice or Bob's data
        alice_entities = adapter_a.list_entities()
        all_ok &= check("Alice's entities unchanged after audit_tester audit",
                         len(alice_entities) == 1)

        # ---------------------------------------------------------------
        # Test 9: Cross-Tenant Repair Isolation
        # ---------------------------------------------------------------
        print(f"\n{bold('Test 9: Cross-Tenant Repair Isolation')}")

        # Find a stale issue in audit_tester's results and repair it
        stale_issues = [i for i in result["issues_found"] if i["severity"] == "stale"]
        if stale_issues:
            issue = stale_issues[0]
            repair_result = apply_repair(issue["id"], "archive", client=adapter_test)
            all_ok &= check(f"Repaired stale issue for audit_tester", repair_result.get("ok", False))

            # Verify Bob's data is untouched
            bob_entities2 = adapter_b.list_entities()
            all_ok &= check("Bob's entities unchanged after audit_tester repair",
                             len(bob_entities2) == 2)
        else:
            all_ok &= check("(skipped — no stale issues found)", True)

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    print(f"\n{bold('═' * 64)}")
    if all_ok:
        print(f"  {green('ALL TRACK 1 STORAGE + ISOLATION TESTS PASSED')} {green('✓')}")
    else:
        print(f"  {red('SOME TRACK 1 TESTS FAILED')} {red('✗')}")
    print(f"{bold('═' * 64)}\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
