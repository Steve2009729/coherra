"""Coherra App Persistence Layer — SQLite Database for Users, Wallets & Audit History.

Manages `~/.sibyl-memory/coherra_app.db`:
  - `users`: privy_user_id (PK), email, created_at
  - `wallets`: wallet_address (PK), privy_user_id (FK), linked_at
  - `audit_history`: id (PK), privy_user_id, wallet_address, health_score, issues_found (JSON), payment_tx_hash, created_at
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Database Path
# ---------------------------------------------------------------------------

DEFAULT_APP_DB_PATH = Path(os.environ.get(
    "COHERRA_APP_DB",
    Path.home() / ".sibyl-memory" / "coherra_app.db",
))

_db_lock = threading.Lock()


def _get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target_path = Path(db_path) if db_path else DEFAULT_APP_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(str(target_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database tables if they do not exist."""
    with _db_lock:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        privy_user_id TEXT PRIMARY KEY,
                        email TEXT,
                        created_at TEXT NOT NULL
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS wallets (
                        wallet_address TEXT PRIMARY KEY,
                        privy_user_id TEXT NOT NULL,
                        linked_at TEXT NOT NULL,
                        FOREIGN KEY (privy_user_id) REFERENCES users(privy_user_id)
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        privy_user_id TEXT NOT NULL,
                        wallet_address TEXT,
                        health_score INTEGER NOT NULL,
                        issues_found TEXT NOT NULL,
                        payment_tx_hash TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (privy_user_id) REFERENCES users(privy_user_id)
                    );
                """)
        finally:
            conn.close()


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# User & Wallet CRUD
# ---------------------------------------------------------------------------

def upsert_user(
    privy_user_id: str,
    email: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Insert user if absent; update email if supplied."""
    init_db(db_path)
    now = _iso_now()

    with _db_lock:
        conn = _get_connection(db_path)
        try:
            with conn:
                existing = conn.execute(
                    "SELECT privy_user_id, email, created_at FROM users WHERE privy_user_id = ?",
                    (privy_user_id,),
                ).fetchone()

                if existing:
                    if email and existing["email"] != email:
                        conn.execute(
                            "UPDATE users SET email = ? WHERE privy_user_id = ?",
                            (email, privy_user_id),
                        )
                    return {
                        "privy_user_id": privy_user_id,
                        "email": email or existing["email"],
                        "created_at": existing["created_at"],
                    }
                else:
                    conn.execute(
                        "INSERT INTO users (privy_user_id, email, created_at) VALUES (?, ?, ?)",
                        (privy_user_id, email, now),
                    )
                    return {
                        "privy_user_id": privy_user_id,
                        "email": email,
                        "created_at": now,
                    }
        finally:
            conn.close()


def link_wallet(
    privy_user_id: str,
    wallet_address: str,
    email: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Link a wallet address to a privy_user_id."""
    upsert_user(privy_user_id, email=email, db_path=db_path)
    wallet_address = wallet_address.lower().strip()
    now = _iso_now()

    with _db_lock:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wallets (wallet_address, privy_user_id, linked_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(wallet_address) DO UPDATE SET
                        privy_user_id = excluded.privy_user_id,
                        linked_at = excluded.linked_at
                    """,
                    (wallet_address, privy_user_id, now),
                )
                return {
                    "wallet_address": wallet_address,
                    "privy_user_id": privy_user_id,
                    "linked_at": now,
                }
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Audit History CRUD
# ---------------------------------------------------------------------------

def record_audit_history(
    privy_user_id: str,
    health_score: int,
    issues_found: list[dict[str, Any]],
    wallet_address: str | None = None,
    payment_tx_hash: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Record a completed audit run to audit_history."""
    upsert_user(privy_user_id, db_path=db_path)
    now = _iso_now()
    issues_json = json.dumps(issues_found, ensure_ascii=False)
    wallet_clean = wallet_address.lower().strip() if wallet_address else None

    with _db_lock:
        conn = _get_connection(db_path)
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO audit_history
                    (privy_user_id, wallet_address, health_score, issues_found, payment_tx_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (privy_user_id, wallet_clean, health_score, issues_json, payment_tx_hash, now),
                )
                row_id = cursor.lastrowid
                return {
                    "id": row_id,
                    "privy_user_id": privy_user_id,
                    "wallet_address": wallet_clean,
                    "health_score": health_score,
                    "issues_found": issues_found,
                    "payment_tx_hash": payment_tx_hash,
                    "created_at": now,
                }
        finally:
            conn.close()


def get_audit_history(
    privy_user_id: str,
    limit: int = 20,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Fetch past audits for a given privy_user_id, most recent first."""
    init_db(db_path)

    with _db_lock:
        conn = _get_connection(db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, privy_user_id, wallet_address, health_score, issues_found, payment_tx_hash, created_at
                FROM audit_history
                WHERE privy_user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (privy_user_id, max(1, min(limit, 100))),
            ).fetchall()

            history = []
            for r in rows:
                try:
                    issues = json.loads(r["issues_found"])
                except Exception:
                    issues = []
                history.append({
                    "id": r["id"],
                    "privy_user_id": r["privy_user_id"],
                    "wallet_address": r["wallet_address"],
                    "health_score": r["health_score"],
                    "issues_found": issues,
                    "payment_tx_hash": r["payment_tx_hash"],
                    "created_at": r["created_at"],
                })
            return history
        finally:
            conn.close()
