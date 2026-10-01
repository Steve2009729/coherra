"""Coherra HTTP Server — x402 Payment-Gated Memory Audit Service.

Serves `POST /audit` over HTTP:
  1. Abuse Guards: Rate limiting per IP + max 1MB payload body limit.
  2. x402 Payment Gate: Requires verified Base Sepolia payment proof (0.015 USDC).
     Responds 402 Payment Required with challenge parameters if unverified.
  3. Ephemeral Caller Account Audit: Instantiates temporary MemoryClient using
     caller's supplied credentials, runs run_audit(), returns JSON result, and
     immediately discards credentials from memory.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import time
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import uvicorn

from sibyl_memory_client import DEFAULT_TENANT, MemoryClient
from .audit import _check_contradictions, _check_duplicates, _check_staleness, _compute_health, _fetch_all_entities, _iso_now, _load_config
from .x402 import build_402_payload, get_payout_address, verify_payment_onchain

# ---------------------------------------------------------------------------
# Constants & Settings
# ---------------------------------------------------------------------------

MAX_BODY_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB
RATE_LIMIT_REQUESTS = 10               # max requests per window
RATE_LIMIT_WINDOW_SEC = 60.0          # window duration in seconds


# ---------------------------------------------------------------------------
# Rate Limiting & Body Size Middleware
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding-window in-memory rate limiter per IP address."""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, window_sec: float = RATE_LIMIT_WINDOW_SEC) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self.history: dict[str, list[float]] = {}

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        cutoff = now - self.window_sec
        timestamps = [ts for ts in self.history.get(client_ip, []) if ts > cutoff]

        if len(timestamps) >= self.max_requests:
            self.history[client_ip] = timestamps
            return False

        timestamps.append(now)
        self.history[client_ip] = timestamps
        return True


_global_rate_limiter = RateLimiter()


class AbuseGuardMiddleware(BaseHTTPMiddleware):
    """Enforces max body size limit (1MB) and rate limits (10 req/min per IP)."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # 1. Rate Limit Check
        client_ip = request.client.host if request.client else "unknown"
        if not _global_rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                {"ok": False, "error": "Too Many Requests", "message": "Rate limit exceeded. Max 10 requests per minute."},
                status_code=429,
            )

        # 2. Content Length / Body Size Check
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_SIZE_BYTES:
            return JSONResponse(
                {"ok": False, "error": "Payload Too Large", "message": "Request body exceeds 1 MB limit."},
                status_code=413,
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Ephemeral Caller Client Audit Runner
# ---------------------------------------------------------------------------

def run_ephemeral_audit(creds: dict[str, Any]) -> dict[str, Any]:
    """Run audit against caller-supplied credentials without persisting them.

    Accepts credentials dict containing db_path, tenant_id, session_token, etc.
    Instantiates an ephemeral MemoryClient, runs audit, and cleans up.
    """
    db_path = creds.get("db_path") or creds.get("memory_db") or creds.get("db")
    if not db_path:
        # Fall back to caller's custom tenant or temporary path
        raise ValueError("Missing 'db_path' in credentials payload.")

    client = None
    try:
        client = MemoryClient.local(
            str(db_path),
            tenant_id=creds.get("tenant_id") or creds.get("account_id") or DEFAULT_TENANT,
            account_id=creds.get("account_id"),
            session_token=creds.get("session_token"),
            tier=creds.get("tier", "free"),
        )

        config = _load_config(client)
        thresholds = config.get("staleness_thresholds", {})
        entities = _fetch_all_entities(client)

        contradiction_issues = _check_contradictions(entities)
        duplicate_issues = _check_duplicates(entities)
        staleness_issues = _check_staleness(entities, thresholds)

        all_issues = contradiction_issues + duplicate_issues + staleness_issues
        health = _compute_health(all_issues)
        now = _iso_now()

        result = {
            "timestamp": now,
            "health_score": health,
            "issues_found": all_issues,
            "entity_count": len(entities),
            "ephemeral": True,
        }
        return result
    finally:
        # Explicit ephemeral cleanup
        if client is not None:
            try:
                getattr(client.storage, "close", lambda: None)()
            except Exception:
                pass
            client = None
        creds.clear()
        gc.collect()


# ---------------------------------------------------------------------------
# POST /audit Endpoint Handler
# ---------------------------------------------------------------------------

async def handle_audit(request: Request) -> Response:
    """HTTP route handler for POST /audit."""
    if request.method != "POST":
        return JSONResponse({"ok": False, "error": "Method Not Allowed"}, status_code=405)

    # Read payout address from environment
    try:
        payout_address = get_payout_address()
    except ValueError as err:
        return JSONResponse(
            {"ok": False, "error": "Server Configuration Error", "message": str(err)},
            status_code=500,
        )

    # Extract payment proof header (X-Payment or X-Payment-Proof or Authorization)
    proof_header = (
        request.headers.get("x-payment")
        or request.headers.get("x-payment-proof")
        or request.headers.get("authorization")
    )

    # 1. Payment Check: If no proof, return 402
    if not proof_header:
        payload_402 = build_402_payload(payout_address)
        accepts_0 = payload_402["accepts"][0]
        headers_402 = {
            "X-Payment-Required": f'amount="{accepts_0["amount"]} USDC", payee="{payout_address}", network="{accepts_0["network"]}", chain_id="{accepts_0["chain_id"]}"'
        }
        return JSONResponse(payload_402, status_code=402, headers=headers_402)

    # 2. Verify payment on-chain
    verified, msg = verify_payment_onchain(proof_header, payout_address)
    if not verified:
        payload_402 = build_402_payload(payout_address, detail=f"Payment verification failed: {msg}")
        return JSONResponse(payload_402, status_code=402)

    # 3. Read body & audit caller's memory
    try:
        raw_body = await request.body()
        if len(raw_body) > MAX_BODY_SIZE_BYTES:
            return JSONResponse(
                {"ok": False, "error": "Payload Too Large", "message": "Request body exceeds 1 MB limit."},
                status_code=413,
            )

        data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        creds = data.get("credentials") or data

        if not isinstance(creds, dict) or not creds:
            return JSONResponse(
                {"ok": False, "error": "Bad Request", "message": "Request body must include caller credentials object (e.g. {'credentials': {'db_path': '...'}})"},
                status_code=400,
            )

        privy_user_id = data.get("privy_user_id") or (creds.get("privy_user_id") if isinstance(creds, dict) else None)
        wallet_address = data.get("wallet_address") or (creds.get("wallet_address") if isinstance(creds, dict) else None)

        audit_result = run_ephemeral_audit(creds)

        # If privy_user_id provided, record to audit_history DB
        if privy_user_id:
            try:
                from .db import record_audit_history
                from .x402 import parse_payment_proof
                tx_hash = parse_payment_proof(proof_header)
                record_audit_history(
                    privy_user_id=privy_user_id,
                    health_score=audit_result.get("health_score", 100),
                    issues_found=audit_result.get("issues_found", []),
                    wallet_address=wallet_address,
                    payment_tx_hash=tx_hash,
                )
            except Exception as e:
                pass  # DB persistence failure must not fail audit response

        return JSONResponse({"ok": True, "payment_status": "verified", "payment_detail": msg, **audit_result})

    except json.JSONDecodeError as e:
        return JSONResponse({"ok": False, "error": "Invalid JSON", "message": str(e)}, status_code=400)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": "Invalid Credentials", "message": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Internal Error", "message": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Link Wallet & Fetch Audit History Handlers
# ---------------------------------------------------------------------------

async def handle_link_wallet(request: Request) -> Response:
    """HTTP route handler for POST /link-wallet."""
    if request.method != "POST":
        return JSONResponse({"ok": False, "error": "Method Not Allowed"}, status_code=405)

    try:
        raw_body = await request.body()
        data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        privy_user_id = data.get("privy_user_id")
        wallet_address = data.get("wallet_address")
        email = data.get("email")

        if not privy_user_id or not wallet_address:
            return JSONResponse(
                {"ok": False, "error": "Bad Request", "message": "Requires 'privy_user_id' and 'wallet_address' in JSON body."},
                status_code=400,
            )

        from .db import link_wallet
        res = link_wallet(privy_user_id=privy_user_id, wallet_address=wallet_address, email=email)
        return JSONResponse({"ok": True, **res})
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Internal Error", "message": str(e)}, status_code=500)


async def handle_get_audit_history(request: Request) -> Response:
    """HTTP route handler for GET /audit-history/{privy_user_id}."""
    privy_user_id = request.path_params.get("privy_user_id")
    if not privy_user_id:
        return JSONResponse({"ok": False, "error": "Bad Request", "message": "Missing privy_user_id parameter"}, status_code=400)

    try:
        from .db import get_audit_history
        history = get_audit_history(privy_user_id)
        return JSONResponse({"ok": True, "privy_user_id": privy_user_id, "count": len(history), "history": history})
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Internal Error", "message": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /chat Endpoint Handler (Track 1 Multi-Model Chat)
# ---------------------------------------------------------------------------

async def handle_chat_endpoint(request: Request) -> Response:
    """HTTP route handler for POST /chat."""
    if request.method != "POST":
        return JSONResponse({"ok": False, "error": "Method Not Allowed"}, status_code=405)

    try:
        raw_body = await request.body()
        data = json.loads(raw_body.decode("utf-8")) if raw_body else {}

        tenant_id = data.get("tenant_id") or data.get("privy_user_id") or "default"
        model = data.get("model", "gemini")
        message = data.get("message", "")
        history = data.get("history", [])
        
        # Payment proof can come from header or body
        payment_proof = (
            request.headers.get("x-payment")
            or request.headers.get("x-payment-proof")
            or request.headers.get("authorization")
            or data.get("payment_proof")
        )

        if not message and not data.get("tool_calls"):
            return JSONResponse(
                {"ok": False, "error": "Bad Request", "message": "Missing 'message' in chat request."},
                status_code=400,
            )

        from .chat import handle_chat
        res = handle_chat(
            tenant_id=tenant_id,
            model=model,
            message=message,
            history=history,
            payment_proof=payment_proof,
        )
        return JSONResponse(res)

    except json.JSONDecodeError as e:
        return JSONResponse({"ok": False, "error": "Invalid JSON", "message": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": "Internal Error", "message": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Health & Root Handlers
# ---------------------------------------------------------------------------

async def handle_health(request: Request) -> Response:
    """HTTP route handler for GET /health and GET /."""
    return JSONResponse({
        "ok": True,
        "service": "coherra-backend",
        "status": "healthy",
        "version": "0.1.0",
        "network": "base-mainnet",
        "chain_id": 8453,
    })


# ---------------------------------------------------------------------------
# Application Factory & Main Entry Point
# ---------------------------------------------------------------------------

from starlette.middleware.cors import CORSMiddleware


def create_app() -> Starlette:
    routes = [
        Route("/", handle_health, methods=["GET"]),
        Route("/health", handle_health, methods=["GET"]),
        Route("/audit", handle_audit, methods=["POST"]),
        Route("/chat", handle_chat_endpoint, methods=["POST"]),
        Route("/link-wallet", handle_link_wallet, methods=["POST"]),
        Route("/audit-history/{privy_user_id}", handle_get_audit_history, methods=["GET"]),
    ]

    # Configure CORS origins from environment or default to wildcard
    allowed_origins_env = os.environ.get("COHERRA_ALLOWED_ORIGINS", "*")
    if allowed_origins_env == "*":
        allowed_origins = ["*"]
    else:
        allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True if allowed_origins != ["*"] else False,
        ),
        Middleware(AbuseGuardMiddleware),
    ]
    return Starlette(debug=False, routes=routes, middleware=middleware)


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Coherra x402 HTTP Audit Server")
    default_host = os.environ.get("HOST", "0.0.0.0")
    default_port = int(os.environ.get("PORT", "8080"))
    parser.add_argument("--host", default=default_host, help=f"Host to bind (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port to bind (default: {default_port})")
    args = parser.parse_args()

    print(f"Starting Coherra x402 HTTP server on {args.host}:{args.port}...")
    uvicorn.run("coherra.http_server:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()

