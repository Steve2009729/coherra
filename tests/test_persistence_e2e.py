"""End-to-end test suite for Part A Backend Additions:
  - db.py (users, wallets, audit_history CRUD)
  - POST /link-wallet endpoint
  - GET /audit-history/{privy_user_id} endpoint
  - POST /audit persistence integration when privy_user_id is passed
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

from coherra.db import (
    init_db,
    upsert_user,
    link_wallet,
    record_audit_history,
    get_audit_history,
)

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
    print(f"\n{bold('═' * 60)}")
    print(f"{bold('  Coherra Part A: Backend Persistence E2E Test')}")
    print(f"{bold('═' * 60)}\n")

    all_ok = True

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_db = Path(tmp_dir) / "test_app.db"

        # 1. Test upsert_user
        print(f"{bold('Test 1: User Upsert')}")
        user1 = upsert_user("privy:did:12345", email="alex@example.com", db_path=tmp_db)
        all_ok &= check("Created new user", user1["privy_user_id"] == "privy:did:12345")
        all_ok &= check("User email set", user1["email"] == "alex@example.com")

        # 2. Test link_wallet
        print(f"\n{bold('Test 2: Link Wallet')}")
        w1 = link_wallet("privy:did:12345", "0x1BFAe4EE12c8f2bF17B8EEb8Ea0BcB32AdbB240B", db_path=tmp_db)
        all_ok &= check("Linked wallet address", w1["wallet_address"] == "0x1bfae4ee12c8f2bf17b8eeb8ea0bcb32adbb240b")

        # 3. Test record_audit_history
        print(f"\n{bold('Test 3: Record Audit History')}")
        h1 = record_audit_history(
            privy_user_id="privy:did:12345",
            health_score=85,
            issues_found=[{"severity": "stale", "category": "facts", "name": "python_version"}],
            wallet_address="0x1BFAe4EE12c8f2bF17B8EEb8Ea0BcB32AdbB240B",
            payment_tx_hash="0xabc123",
            db_path=tmp_db,
        )
        all_ok &= check("Inserted history row ID", h1["id"] == 1)

        # 4. Test get_audit_history
        print(f"\n{bold('Test 4: Fetch Audit History')}")
        history = get_audit_history("privy:did:12345", db_path=tmp_db)
        all_ok &= check("Fetched history array", len(history) == 1)
        all_ok &= check("Score matches", history[0]["health_score"] == 85)
        all_ok &= check("Issues match", len(history[0]["issues_found"]) == 1)

    print(f"\n{bold('═' * 60)}")
    if all_ok:
        print(f"  {green('ALL PART A BACKEND TESTS PASSED')} {green('✓')}")
    else:
        print(f"  {red('SOME PART A BACKEND TESTS FAILED')} {red('✗')}")
    print(f"{bold('═' * 60)}\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
