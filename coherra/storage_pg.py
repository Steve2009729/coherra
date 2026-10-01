"""Coherra Track 1 — Postgres multi-tenant storage adapter.

Provides a `PostgresStorageAdapter` that exposes the same read/write surface
the existing audit and repair engines use on the Sibyl `MemoryClient`:
    list_entities, get_entity, set_entity, archive_entity,
    get_state, set_state, write_event, read_events.

Backed by **one shared Postgres database** with tenant isolation enforced by:
    1. Every query is scoped to `tenant_id`.
    2. `UNIQUE(tenant_id, category, name)` prevents cross-tenant overwrites.

When `POSTGRES_URL` / `DATABASE_URL` is set, uses **psycopg v3**.
Falls back to an in-process **SQLite** engine for offline development and
testing — the adapter interface is identical either way.
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
# Schema DDL (dialect-agnostic SQL, valid for both PG and SQLite)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    privy_user_id  TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id             INTEGER PRIMARY KEY {autoincrement},
    tenant_id      TEXT    NOT NULL REFERENCES tenants(privy_user_id),
    category       TEXT    NOT NULL,
    name           TEXT    NOT NULL,
    tier           TEXT    NOT NULL DEFAULT 'HOT',
    value          TEXT,
    confidence     REAL,
    source         TEXT,
    status         TEXT    NOT NULL DEFAULT 'active',
    body           TEXT,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, category, name)
);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY {autoincrement},
    tenant_id      TEXT    NOT NULL REFERENCES tenants(privy_user_id),
    kind           TEXT    NOT NULL,
    body           TEXT,
    category       TEXT,
    name           TEXT,
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS states (
    tenant_id      TEXT    NOT NULL REFERENCES tenants(privy_user_id),
    key            TEXT    NOT NULL,
    value          TEXT,
    updated_at     TEXT    NOT NULL,
    PRIMARY KEY (tenant_id, key)
);
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _get_dsn() -> str | None:
    """Return a Postgres DSN from env, or None → use SQLite fallback."""
    return (
        os.environ.get("POSTGRES_URL")
        or os.environ.get("DATABASE_URL")
        or None
    )


# ---------------------------------------------------------------------------
# Backend abstraction (Postgres vs SQLite)
# ---------------------------------------------------------------------------

class _SqliteBackend:
    """SQLite-backed storage for local / offline / testing."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".sibyl-memory" / "coherra_track1.db"
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        ddl = _SCHEMA_SQL.replace("{autoincrement}", "AUTOINCREMENT")
        with self._lock:
            conn = sqlite3.connect(str(self._path))
            conn.row_factory = sqlite3.Row
            try:
                for stmt in ddl.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(stmt)
                conn.commit()
            finally:
                conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def execute(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(sql, params)
                if sql.strip().upper().startswith("SELECT"):
                    return [dict(r) for r in cur.fetchall()]
                conn.commit()
                return [{"lastrowid": cur.lastrowid, "rowcount": cur.rowcount}]
            finally:
                conn.close()

    def close(self) -> None:
        pass


class _PostgresBackend:
    """Live Postgres backend via psycopg v3."""

    def __init__(self, dsn: str) -> None:
        import psycopg  # noqa: late import, only when PG is actually used
        self._dsn = dsn
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        import psycopg
        ddl = _SCHEMA_SQL.replace("{autoincrement}", "GENERATED BY DEFAULT AS IDENTITY")
        with psycopg.connect(self._dsn) as conn:
            for stmt in ddl.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> list[dict]:
        import psycopg
        # Translate SQLite-style ? placeholders to %s for psycopg
        sql = sql.replace("?", "%s")
        with self._lock:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    if cur.description:
                        cols = [d.name for d in cur.description]
                        return [dict(zip(cols, row)) for row in cur.fetchall()]
                    conn.commit()
                    return [{"rowcount": cur.rowcount}]

    def close(self) -> None:
        pass


def _make_backend(dsn: str | None = None, sqlite_path: str | Path | None = None) -> _SqliteBackend | _PostgresBackend:
    """Factory: choose backend from explicit DSN, env, or SQLite fallback."""
    raw_dsn = dsn or _get_dsn()
    if raw_dsn:
        if raw_dsn.startswith("postgresql://") or raw_dsn.startswith("postgres://"):
            return _PostgresBackend(raw_dsn)
        elif raw_dsn.startswith("sqlite:///"):
            path = raw_dsn[len("sqlite:///"):]
            return _SqliteBackend(path or sqlite_path)
    return _SqliteBackend(sqlite_path)


# ---------------------------------------------------------------------------
# PostgresStorageAdapter — the public class used by chat / audit / repair
# ---------------------------------------------------------------------------

class PostgresStorageAdapter:
    """Multi-tenant storage adapter for Track 1.

    Drop-in replacement for `MemoryClient` as far as the audit and repair
    engines are concerned — they call `.list_entities()`, `.get_entity()`,
    `.set_entity()`, `.archive_entity()`, `.get_state()`, `.set_state()`,
    `.write_event()`, and `.read_events()`.

    Parameters
    ----------
    tenant_id : str
        The Privy user ID that scopes every query.
    dsn : str | None
        Explicit Postgres DSN.  Omit to read from POSTGRES_URL / DATABASE_URL
        env vars, or fall back to a local SQLite file.
    sqlite_path : str | Path | None
        Explicit SQLite file path (only used when no DSN is resolved).
    """

    def __init__(
        self,
        tenant_id: str,
        dsn: str | None = None,
        sqlite_path: str | Path | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self._tenant_id = tenant_id
        self.dsn = dsn
        self._backend = _make_backend(dsn=dsn, sqlite_path=sqlite_path)
        # Alias so existing code that accesses `client.storage` can call
        # `.close()` without crashing:
        self.storage = self._backend

    # -- tenant management ---------------------------------------------------

    def create_tenant(self) -> dict[str, Any]:
        """Ensure the tenant row exists. Idempotent."""
        now = _iso_now()
        existing = self._backend.execute(
            "SELECT privy_user_id, created_at FROM tenants WHERE privy_user_id = ?",
            (self._tenant_id,),
        )
        if existing:
            return existing[0]
        self._backend.execute(
            "INSERT INTO tenants (privy_user_id, created_at) VALUES (?, ?)",
            (self._tenant_id, now),
        )
        return {"privy_user_id": self._tenant_id, "created_at": now}

    def tenant_exists(self) -> bool:
        rows = self._backend.execute(
            "SELECT 1 FROM tenants WHERE privy_user_id = ?",
            (self._tenant_id,),
        )
        return bool(rows)

    # -- entities ------------------------------------------------------------

    def list_entities(
        self,
        category: str | None = None,
        *,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, tenant_id, category, name, status, body, "
            "created_at, updated_at FROM entities WHERE tenant_id = ?"
        )
        params: list[Any] = [self._tenant_id]
        if category is not None:
            sql += " AND category = ?"
            params.append(category)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        else:
            sql += " AND status = 'active'"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = self._backend.execute(sql, tuple(params))
        return [self._row_to_entity(r) for r in rows]

    def get_entity(self, category: str, name: str) -> dict[str, Any]:
        rows = self._backend.execute(
            "SELECT id, tenant_id, category, name, status, body, "
            "created_at, updated_at FROM entities "
            "WHERE tenant_id = ? AND category = ? AND name = ? AND status = 'active'",
            (self._tenant_id, category, name),
        )
        if not rows:
            raise KeyError(f"entity {category}/{name} not found for tenant {self._tenant_id}")
        return self._row_to_entity(rows[0])

    def set_entity(self, category: str, name: str, body: dict[str, Any] | Any) -> None:
        now = _iso_now()
        body_json = _json_dumps(body)
        value = body.get("value") if isinstance(body, dict) else None
        confidence = body.get("confidence") if isinstance(body, dict) else None
        source = body.get("source") if isinstance(body, dict) else None
        tier = body.get("tier", "HOT") if isinstance(body, dict) else "HOT"
        version = int(body.get("version", 1)) if isinstance(body, dict) else 1

        # Ensure tenant exists
        self.create_tenant()

        # Check if entity exists
        existing = self._backend.execute(
            "SELECT id FROM entities WHERE tenant_id = ? AND category = ? AND name = ?",
            (self._tenant_id, category, name),
        )
        if existing:
            self._backend.execute(
                "UPDATE entities SET body = ?, value = ?, confidence = ?, "
                "source = ?, tier = ?, status = 'active', "
                "updated_at = ?, version = ? "
                "WHERE tenant_id = ? AND category = ? AND name = ?",
                (body_json, str(value) if value is not None else None,
                 confidence, source, tier, now, version,
                 self._tenant_id, category, name),
            )
        else:
            self._backend.execute(
                "INSERT INTO entities "
                "(tenant_id, category, name, tier, value, confidence, source, "
                "status, body, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)",
                (self._tenant_id, category, name, tier,
                 str(value) if value is not None else None,
                 confidence, source, body_json, now, now, version),
            )

    def archive_entity(self, category: str, name: str, reason: str | None = None) -> None:
        now = _iso_now()
        self._backend.execute(
            "UPDATE entities SET status = 'archived', tier = 'ARCHIVE', "
            "updated_at = ? WHERE tenant_id = ? AND category = ? AND name = ?",
            (now, self._tenant_id, category, name),
        )
        # Log the archive as an event
        self.write_event(acted={
            "kind": "entity_archived",
            "body": {"category": category, "name": name, "reason": reason},
        })

    # -- state ---------------------------------------------------------------

    def get_state(self, key: str) -> dict[str, Any] | None:
        rows = self._backend.execute(
            "SELECT value, updated_at FROM states "
            "WHERE tenant_id = ? AND key = ?",
            (self._tenant_id, key),
        )
        if not rows:
            return None
        raw = rows[0].get("value") or rows[0].get("VALUE") or None
        return {"body": _json_loads(raw), "updated_at": rows[0].get("updated_at")}

    def set_state(self, key: str, value: Any) -> None:
        now = _iso_now()
        self.create_tenant()
        val_json = _json_dumps(value)
        # Upsert
        existing = self._backend.execute(
            "SELECT 1 FROM states WHERE tenant_id = ? AND key = ?",
            (self._tenant_id, key),
        )
        if existing:
            self._backend.execute(
                "UPDATE states SET value = ?, updated_at = ? "
                "WHERE tenant_id = ? AND key = ?",
                (val_json, now, self._tenant_id, key),
            )
        else:
            self._backend.execute(
                "INSERT INTO states (tenant_id, key, value, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (self._tenant_id, key, val_json, now),
            )

    # -- events --------------------------------------------------------------

    def write_event(self, acted: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if acted is None:
            return
        now = _iso_now()
        kind = acted.get("kind", "unknown")
        body = acted.get("body")
        category = acted.get("category") or (body.get("category") if isinstance(body, dict) else None)
        name_ = acted.get("name") or (body.get("name") if isinstance(body, dict) else None)
        self.create_tenant()
        self._backend.execute(
            "INSERT INTO events (tenant_id, kind, body, category, name, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self._tenant_id, kind, _json_dumps(body), category, name_, now),
        )

    def read_events(self, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT id, tenant_id, kind, body, category, name, created_at FROM events WHERE tenant_id = ?"
        params: list[Any] = [self._tenant_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = self._backend.execute(sql, tuple(params))
        return [
            {
                "id": r["id"],
                "tenant_id": r["tenant_id"],
                "kind": r["kind"],
                "body": _json_loads(r.get("body")),
                "category": r.get("category"),
                "name": r.get("name"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # -- internal helpers ----------------------------------------------------

    @staticmethod
    def _row_to_entity(row: dict[str, Any]) -> dict[str, Any]:
        body = _json_loads(row.get("body"))
        val = row.get("value")
        conf = row.get("confidence")
        src = row.get("source")
        tier = row.get("tier")
        if isinstance(body, dict):
            val = body.get("value", val)
            conf = body.get("confidence", conf)
            src = body.get("source", src)
            tier = body.get("tier", tier)
        return {
            "id": row.get("id"),
            "tenant_id": row.get("tenant_id"),
            "category": row.get("category"),
            "name": row.get("name"),
            "status": row.get("status"),
            "value": val,
            "confidence": conf,
            "source": src,
            "tier": tier,
            "body": body,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def init_db(dsn: str | None = None, sqlite_path: str | Path | None = None) -> None:
    """Initialize schema on the target database."""
    _make_backend(dsn=dsn, sqlite_path=sqlite_path)


def create_tenant(tenant_id: str, dsn: str | None = None, sqlite_path: str | Path | None = None) -> dict[str, Any]:
    """Create or ensure a tenant exists."""
    adapter = PostgresStorageAdapter(tenant_id=tenant_id, dsn=dsn, sqlite_path=sqlite_path)
    return adapter.create_tenant()


def tenant_exists(tenant_id: str, dsn: str | None = None, sqlite_path: str | Path | None = None) -> bool:
    """Check if a tenant exists."""
    adapter = PostgresStorageAdapter(tenant_id=tenant_id, dsn=dsn, sqlite_path=sqlite_path)
    return adapter.tenant_exists()

