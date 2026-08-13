"""Coherra client — authenticated MemoryClient factory.

Replicates the credential-loading and caching pattern from sibyl_memory_mcp/server.py
(_load_credentials, _open_client, _build_client) so Coherra authenticates
against the same local Sibyl account without duplicating the credential file.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from sibyl_memory_client import DEFAULT_TENANT, MemoryClient

# ---------------------------------------------------------------------------
# Paths — honour the same env-var overrides as sibyl_memory_mcp so all Sibyl
# tools point at the same DB and credentials file.
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path(os.environ.get(
    "SIBYL_MEMORY_DB",
    Path.home() / ".sibyl-memory" / "memory.db",
))
DEFAULT_CRED_PATH = Path(os.environ.get(
    "SIBYL_CREDENTIALS",
    Path.home() / ".sibyl-memory" / "credentials.json",
))


# ---------------------------------------------------------------------------
# Credential loading (mirrors sibyl_memory_mcp SEC-4 / SEC-11 hardening)
# ---------------------------------------------------------------------------

def _load_credentials() -> dict[str, Any]:
    """Read credentials.json if present. Missing/symlink/bad-parse = free tier.

    Security notes (matching sibyl_memory_mcp):
      - Symlinks are refused (SEC-11) — treated as absent.
      - Any I/O or JSON parse error is silently swallowed; caller gets {}.
    """
    if not DEFAULT_CRED_PATH.exists():
        return {}
    if DEFAULT_CRED_PATH.is_symlink():
        return {}
    try:
        return json.loads(DEFAULT_CRED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Cached MemoryClient (mirrors sibyl_memory_mcp P-H1)
# ---------------------------------------------------------------------------

_client_lock = threading.Lock()
_client_cache: dict[str, Any] = {
    "client": None,
    "creds_mtime": None,
    "creds_path_exists": False,
}


def _credentials_mtime() -> float | None:
    """Return mtime of credentials.json if present and not a symlink, else None."""
    try:
        if DEFAULT_CRED_PATH.exists() and not DEFAULT_CRED_PATH.is_symlink():
            return DEFAULT_CRED_PATH.stat().st_mtime
    except OSError:
        pass
    return None


def _build_client() -> MemoryClient:
    """Construct a fresh MemoryClient bound to the local DB and credentials.

    Tenant resolution ladder (mirrors sibyl_memory_mcp Contract T):
        credentials.tenant_id → credentials.account_id → DEFAULT_TENANT

    The ~/.sibyl-memory/ directory is created at mode 0o700 on first use
    (mirrors sibyl_memory_mcp R30).
    """
    creds = _load_credentials()
    parent = DEFAULT_DB_PATH.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(parent, 0o700)
    except OSError:
        pass

    return MemoryClient.local(
        str(DEFAULT_DB_PATH),
        tenant_id=creds.get("tenant_id") or creds.get("account_id") or DEFAULT_TENANT,
        account_id=creds.get("account_id"),
        session_token=creds.get("session_token"),
        tier=creds.get("tier", "free"),
        # Pass the HMAC-signed claim only when a signature is present;
        # matches sibyl_memory_mcp Contract PII — required for signature
        # verification even though it carries PII fields.
        credentials_claim={
            "account_id": creds.get("account_id"),
            "tenant_id": creds.get("tenant_id"),
            "tier": creds.get("tier"),
            "email": creds.get("email"),
            "wallet": creds.get("wallet"),
            "issued_at": creds.get("issued_at"),
            "schema_version": creds.get("schema_version", 1),
        } if creds.get("signature") else None,
        credentials_signature=creds.get("signature"),
    )


def open_client() -> MemoryClient:
    """Return a cached MemoryClient; rebuild only when credentials.json changes.

    Thread-safe.  Drop-in equivalent of sibyl_memory_mcp._open_client().
    """
    with _client_lock:
        cur_mtime = _credentials_mtime()
        cur_exists = DEFAULT_CRED_PATH.exists()
        client: MemoryClient | None = _client_cache["client"]
        cached_mtime = _client_cache["creds_mtime"]
        cached_exists = _client_cache["creds_path_exists"]

        if (
            client is None
            or cur_mtime != cached_mtime
            or cur_exists != cached_exists
        ):
            old = client
            client = _build_client()
            # Close the old storage before swapping to avoid stranded SQLite
            # connections (mirrors sibyl_memory_mcp R26).
            if old is not None:
                try:
                    getattr(old.storage, "close", lambda: None)()
                except Exception:
                    pass
            _client_cache["client"] = client
            _client_cache["creds_mtime"] = cur_mtime
            _client_cache["creds_path_exists"] = cur_exists

        return client
