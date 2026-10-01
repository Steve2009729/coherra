"""Coherra Track 1 — Multi-Model Chat Backend & Tool Loop.

Supports 4 LLM providers:
  1. Google Gemini (Flash-Lite / Flash 2.5) via `GEMINI_API_KEY`
  2. OpenAI ("Luna" / GPT-4o-mini) via `OPENAI_API_KEY`
  3. xAI Grok (Grok 4.3 / Grok-2) via `XAI_API_KEY`
  4. Anthropic Claude (Haiku 4.5 / 3.5 Haiku) via `ANTHROPIC_API_KEY`

Unified Tools:
  - `create_memory`: Creates a new memory store for the tenant if none exists.
  - `remember`: Stores an entity (category, name, value) in the tenant's memory.
  - `run_audit`: Gated by x402 payment (0.015 USDC on Base). Triggers memory audit.
  - `list_issues`: Lists issues found from the last audit.
  - `apply_repair`: Applies a repair to a detected issue.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

import httpx

from .audit import run_audit
from .repair import apply_repair
from .storage_pg import PostgresStorageAdapter, create_tenant, tenant_exists
from .x402 import build_402_payload, get_payout_address, verify_payment_onchain

# ---------------------------------------------------------------------------
# Tool Specifications
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "create_memory",
        "description": "Initialize and provision a memory storage instance for this user account if they don't have one yet.",
        "parameters": {
            "type": "object",
            "properties": {
                "initial_note": {
                    "type": "string",
                    "description": "Optional initial note or description for the memory store.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "remember",
        "description": "Store a user preference, project detail, personal fact, or rule in persistent memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Entity category, e.g. 'preference', 'projects', 'people', 'facts'.",
                },
                "name": {
                    "type": "string",
                    "description": "Unique key or name for this memory fact (e.g. 'editor', 'language', 'theme').",
                },
                "value": {
                    "type": "string",
                    "description": "The value or content to remember.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score from 0.0 to 1.0 (defaults to 1.0).",
                },
                "source": {
                    "type": "string",
                    "description": "Source of this information (e.g. 'chat', 'user_explicit').",
                },
            },
            "required": ["category", "name", "value"],
        },
    },
    {
        "name": "run_audit",
        "description": "Run a comprehensive Coherra health audit across the user's stored memories to detect contradictions, duplicates, and stale facts. (Requires 0.015 USDC payment proof on Base).",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Optional reason or scope for running the audit.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "list_issues",
        "description": "List existing audit issues (contradictions, duplicates, staleness) currently recorded for this user.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional category filter.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "apply_repair",
        "description": "Fix or resolve an audit issue by applying an action (e.g. 'keep_newer', 'archive', 'set_value', 'delete').",
        "parameters": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "The unique identifier of the issue to repair.",
                },
                "action": {
                    "type": "string",
                    "description": "Repair action to apply: 'keep_newer', 'archive_older', 'update', 'delete', 'archive'.",
                },
                "value": {
                    "type": "string",
                    "description": "Optional value if the action requires updating or setting a specific value.",
                },
            },
            "required": ["issue_id", "action"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool Execution Engine
# ---------------------------------------------------------------------------

def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    tenant_id: str,
    adapter: PostgresStorageAdapter,
    payment_proof: str | None = None,
) -> dict[str, Any]:
    """Execute one of the 5 memory tools against the tenant's PostgresStorageAdapter."""
    if tool_name == "create_memory":
        existed = adapter.tenant_exists()
        if not existed:
            adapter.create_tenant()
            msg = "You didn't have a memory yet, so I just created one for you — this is where everything from here on will be stored."
            return {"status": "created", "tenant_id": tenant_id, "message": msg}
        return {"status": "already_exists", "tenant_id": tenant_id, "message": "Memory store is already active for this account."}

    elif tool_name == "remember":
        if not adapter.tenant_exists():
            adapter.create_tenant()

        cat = args.get("category", "facts")
        name = args.get("name", "fact")
        val = args.get("value", "")
        conf = float(args.get("confidence", 1.0))
        src = args.get("source", "chat")

        body = {
            "value": val,
            "confidence": conf,
            "source": src,
            "tier": "ACTIVE",
        }
        adapter.set_entity(category=cat, name=name, body=body)
        return {
            "status": "success",
            "action": "remembered",
            "category": cat,
            "name": name,
            "value": val,
            "message": f"Remembered {cat}/{name} = '{val}'.",
        }

    elif tool_name == "run_audit":
        try:
            payout_addr = get_payout_address()
        except ValueError:
            payout_addr = "0x0000000000000000000000000000000000000000"

        # Check payment proof
        if not payment_proof:
            challenge = build_402_payload(payout_addr, detail="Valid 0.015 USDC payment proof on Base required to run an audit.")
            return {
                "requires_payment": True,
                "status_code": 402,
                "challenge": challenge,
                "message": "A payment of 0.015 USDC on Base is required to run a comprehensive memory audit.",
            }

        verified, reason = verify_payment_onchain(payment_proof, payout_addr)
        if not verified:
            challenge = build_402_payload(payout_addr, detail=f"Payment verification failed: {reason}")
            return {
                "requires_payment": True,
                "status_code": 402,
                "challenge": challenge,
                "message": f"Payment verification failed: {reason}",
            }

        # Payment verified — run the actual audit
        audit_res = run_audit(client=adapter)
        adapter.set_state("last_audit", audit_res)
        return {
            "requires_payment": False,
            "status": "success",
            "health_score": audit_res.get("health_score"),
            "issues_count": len(audit_res.get("issues_found", [])),
            "issues_found": audit_res.get("issues_found", []),
            "timestamp": audit_res.get("timestamp"),
            "message": f"Audit complete. Health Score: {audit_res.get('health_score')}/100 with {len(audit_res.get('issues_found', []))} issue(s) detected.",
        }

    elif tool_name == "list_issues":
        last_audit = adapter.get_state("last_audit")
        if isinstance(last_audit, dict) and "issues_found" in last_audit:
            issues = last_audit["issues_found"]
            cat = args.get("category")
            if cat:
                issues = [i for i in issues if i.get("category") == cat]
            return {"status": "success", "issues": issues, "count": len(issues)}
        else:
            # Run lightweight scan on entities
            audit_res = run_audit(client=adapter)
            adapter.set_state("last_audit", audit_res)
            issues = audit_res.get("issues_found", [])
            return {"status": "success", "issues": issues, "count": len(issues)}

    elif tool_name == "apply_repair":
        issue_id = args.get("issue_id", "")
        action = args.get("action", "")
        val = args.get("value")
        res = apply_repair(issue_id=issue_id, action=action, value=val, client=adapter)
        return {"status": "success", "action": action, "issue_id": issue_id, "result": res}

    else:
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}


# ---------------------------------------------------------------------------
# LLM Providers (Gemini, OpenAI Luna, Grok, Claude)
# ---------------------------------------------------------------------------

def _normalize_model_name(model_str: str) -> str:
    m = model_str.lower()
    if "gemini" in m:
        return "gemini"
    elif "openai" in m or "luna" in m or "gpt" in m or "chatgpt" in m:
        return "openai"
    elif "grok" in m or "xai" in m:
        return "grok"
    elif "claude" in m or "anthropic" in m or "haiku" in m:
        return "claude"
    return "gemini"


def _call_gemini_api(
    api_key: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call Google Gemini REST API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"

    # Convert tool definitions to Gemini functionDeclarations
    func_declarations = []
    for t in tools:
        func_declarations.append({
            "name": t["name"],
            "description": t["description"],
            "parameters": t.get("parameters", {"type": "object", "properties": {}}),
        })

    # Convert messages
    contents = []
    for m in messages:
        role = "user" if m.get("role") in ("user", "system") else "model"
        parts = []
        if "content" in m and m["content"]:
            parts.append({"text": m["content"]})
        if "tool_calls" in m:
            for tc in m["tool_calls"]:
                parts.append({
                    "functionCall": {
                        "name": tc["name"],
                        "args": tc.get("arguments", {}),
                    }
                })
        if "tool_response" in m:
            parts.append({
                "functionResponse": {
                    "name": m.get("tool_name", "tool"),
                    "response": {"result": m["tool_response"]},
                }
            })
        if parts:
            contents.append({"role": role, "parts": parts})

    body: dict[str, Any] = {"contents": contents}
    if func_declarations:
        body["tools"] = [{"functionDeclarations": func_declarations}]

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    # Parse response
    candidates = data.get("candidates", [])
    if not candidates:
        return {"text": "I didn't receive a response.", "tool_calls": []}

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    text_parts = []
    tool_calls = []

    for p in parts:
        if "text" in p:
            text_parts.append(p["text"])
        if "functionCall" in p:
            fc = p["functionCall"]
            tool_calls.append({
                "name": fc.get("name"),
                "arguments": fc.get("args", {}),
            })

    return {
        "text": "\n".join(text_parts).strip(),
        "tool_calls": tool_calls,
    }


def _call_openai_compatible_api(
    base_url: str,
    api_key: str,
    model_name: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call an OpenAI-compatible endpoint (used for OpenAI Luna & xAI Grok)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    openai_tools = [{"type": "function", "function": t} for t in tools]

    formatted_msgs = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        item: dict[str, Any] = {"role": role, "content": content}
        if "tool_calls" in m:
            item["tool_calls"] = [
                {
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("arguments", {})),
                    },
                }
                for i, tc in enumerate(m["tool_calls"])
            ]
        if role == "tool":
            item["tool_call_id"] = m.get("tool_call_id", "call_0")
        formatted_msgs.append(item)

    payload: dict[str, Any] = {
        "model": model_name,
        "messages": formatted_msgs,
    }
    if openai_tools:
        payload["tools"] = openai_tools

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    choice = data.get("choices", [{}])[0]
    msg = choice.get("message", {})
    text = msg.get("content") or ""

    tool_calls = []
    for tc in msg.get("tool_calls", []):
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except Exception:
            args = {}
        tool_calls.append({
            "name": fn.get("name"),
            "arguments": args,
            "id": tc.get("id"),
        })

    return {"text": text, "tool_calls": tool_calls}


def _call_claude_api(
    api_key: str,
    model_name: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call Anthropic Claude Messages API."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    claude_tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]

    formatted_msgs = []
    system_prompt = "You are Coherra, an intelligent hosted memory and knowledge assistant with access to persistent memory tools."
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            system_prompt = m.get("content", system_prompt)
            continue
        content = m.get("content", "")
        formatted_msgs.append({"role": role if role in ("user", "assistant") else "user", "content": content})

    payload: dict[str, Any] = {
        "model": model_name,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": formatted_msgs,
    }
    if claude_tools:
        payload["tools"] = claude_tools

    with httpx.Client(timeout=30.0) as client:
        resp = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    text_parts = []
    tool_calls = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "name": block.get("name"),
                "arguments": block.get("input", {}),
                "id": block.get("id"),
            })

    return {"text": "\n".join(text_parts).strip(), "tool_calls": tool_calls}


# ---------------------------------------------------------------------------
# Fallback / Simulated Intelligence for Offline & Tests
# ---------------------------------------------------------------------------

def _heuristic_tool_call(message: str, tenant_id: str, adapter: PostgresStorageAdapter) -> tuple[list[dict[str, Any]], str]:
    """Pattern match user intent to trigger tool calls when live LLM keys are absent."""
    m = message.lower().strip()
    tool_calls = []
    reply = ""

    # 1. Create memory
    if "create memory" in m or "start memory" in m or "init memory" in m:
        tool_calls.append({"name": "create_memory", "arguments": {}})
        reply = "I've checked and initialized your personal memory space."

    # 2. Remember / Store
    elif "remember" in m or "save" in m or "store" in m or "my favorite" in m or "i prefer" in m:
        # Simple extraction: "remember that my editor is VSCode" or "remember preference/editor=VSCode"
        cat = "preference"
        name = "info"
        val = message

        match_key_val = re.search(
            r"(?:that\s+)?(?:my\s+)?(?:favorite\s+|preferred\s+)?([a-zA-Z0-9_\-\/]+)\s+(?:is|to be|=|:)\s+([a-zA-Z0-9_\-\.\s\+]+)",
            message,
            re.IGNORECASE,
        )
        if match_key_val:
            raw_key = match_key_val.group(1).lower().strip()
            raw_val = match_key_val.group(2).strip()
            if "/" in raw_key:
                cat, name = raw_key.split("/", 1)
            else:
                name = raw_key
                if name in ("editor", "language", "theme", "test_framework", "code_style"):
                    cat = "preference"
                elif name in ("lead", "engineer", "title", "role"):
                    cat = "people"
                elif name in ("project", "repo", "deadline"):
                    cat = "projects"
                else:
                    cat = "facts"
            val = raw_val
        else:
            name = "custom_note"
            val = message

        tool_calls.append({
            "name": "remember",
            "arguments": {"category": cat, "name": name, "value": val, "confidence": 1.0, "source": "chat"},
        })
        reply = f"I have saved that to your memory under **{cat}/{name}**."

    # 3. Audit
    elif "audit" in m or "scan" in m or "health" in m or "check memory" in m:
        tool_calls.append({"name": "run_audit", "arguments": {}})
        reply = "I will run an audit across your memories."

    # 4. List issues
    elif "issues" in m or "conflicts" in m or "duplicates" in m or "stale" in m:
        tool_calls.append({"name": "list_issues", "arguments": {}})
        reply = "Here are the issues detected in your memory:"

    # 5. Apply repair
    elif "repair" in m or "fix" in m or "resolve" in m:
        match_fix = re.search(r"(?:repair|fix|resolve)\s+([a-zA-Z0-9_\-]+)(?:\s+with\s+action\s+([a-zA-Z0-9_\-]+))?", message, re.IGNORECASE)
        issue_id = match_fix.group(1) if match_fix else "issue_1"
        action = match_fix.group(2) if match_fix and match_fix.group(2) else "archive"
        tool_calls.append({
            "name": "apply_repair",
            "arguments": {"issue_id": issue_id, "action": action},
        })
        reply = f"Applying repair `{action}` to issue `{issue_id}`."

    else:
        # Default conversational reply
        if not adapter.tenant_exists():
            tool_calls.append({"name": "create_memory", "arguments": {}})
            reply = "Welcome to Coherra! I've set up your memory store. How can I help you manage your knowledge today?"
        else:
            reply = f"I'm listening! You can ask me to remember facts, inspect your memory, or run an audit."

    return tool_calls, reply


# ---------------------------------------------------------------------------
# Main Chat Dispatcher & Tool Calling Loop
# ---------------------------------------------------------------------------

def handle_chat(
    tenant_id: str,
    model: str,
    message: str,
    history: list[dict[str, Any]] | None = None,
    payment_proof: str | None = None,
    adapter: PostgresStorageAdapter | None = None,
    dsn: str | None = None,
) -> dict[str, Any]:
    """Execute multi-model chat interaction with tool execution for a tenant.

    Returns:
        {
            "ok": True,
            "model": model,
            "message": "Assistant reply text",
            "tool_calls": [ { "name": ..., "arguments": ..., "result": ... } ],
            "requires_payment": bool,
            "challenge": dict | None,
            "payment_status": str | None,
        }
    """
    if adapter is None:
        adapter = PostgresStorageAdapter(tenant_id=tenant_id, dsn=dsn)

    norm_model = _normalize_model_name(model)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    xai_key = os.environ.get("XAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    msgs: list[dict[str, Any]] = []
    if history:
        for h in history:
            msgs.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    msgs.append({"role": "user", "content": message})

    executed_tools = []
    requires_payment = False
    payment_challenge = None
    assistant_reply = ""

    # 1. Attempt live model invocation if API key is present
    try:
        if norm_model == "gemini" and gemini_key:
            res = _call_gemini_api(gemini_key, msgs, TOOL_DEFINITIONS)
            assistant_reply = res.get("text", "")
            tool_calls = res.get("tool_calls", [])

        elif norm_model == "openai" and openai_key:
            res = _call_openai_compatible_api("https://api.openai.com/v1", openai_key, "gpt-4o-mini", msgs, TOOL_DEFINITIONS)
            assistant_reply = res.get("text", "")
            tool_calls = res.get("tool_calls", [])

        elif norm_model == "grok" and xai_key:
            res = _call_openai_compatible_api("https://api.x.ai/v1", xai_key, "grok-2", msgs, TOOL_DEFINITIONS)
            assistant_reply = res.get("text", "")
            tool_calls = res.get("tool_calls", [])

        elif norm_model == "claude" and anthropic_key:
            res = _call_claude_api(anthropic_key, "claude-3-5-haiku-20241022", msgs, TOOL_DEFINITIONS)
            assistant_reply = res.get("text", "")
            tool_calls = res.get("tool_calls", [])

        else:
            # Simulated fallback for offline test / development mode
            tool_calls, assistant_reply = _heuristic_tool_call(message, tenant_id, adapter)

    except Exception as err:
        # Graceful fallback to heuristic if live network fails or key is invalid
        tool_calls, assistant_reply = _heuristic_tool_call(message, tenant_id, adapter)
        if not assistant_reply:
            assistant_reply = f"(Running in offline/test mode): {err}"

    # 2. Execute any requested tools
    for tc in tool_calls:
        t_name = tc.get("name")
        t_args = tc.get("arguments", {})
        tool_result = execute_tool(
            tool_name=t_name,
            args=t_args,
            tenant_id=tenant_id,
            adapter=adapter,
            payment_proof=payment_proof,
        )

        executed_tools.append({
            "name": t_name,
            "arguments": t_args,
            "result": tool_result,
        })

        if tool_result.get("requires_payment"):
            requires_payment = True
            payment_challenge = tool_result.get("challenge")
            assistant_reply = tool_result.get("message", "Payment required to proceed with memory audit.")

        elif t_name == "create_memory" and tool_result.get("status") == "created":
            assistant_reply = tool_result.get("message", assistant_reply)

        elif t_name == "remember" and tool_result.get("status") == "success":
            assistant_reply = tool_result.get("message", assistant_reply)

        elif t_name == "run_audit" and tool_result.get("status") == "success":
            assistant_reply = tool_result.get("message", assistant_reply)

    return {
        "ok": True,
        "model": model,
        "message": assistant_reply,
        "tool_calls": executed_tools,
        "requires_payment": requires_payment,
        "challenge": payment_challenge,
        "payment_status": "verified" if (payment_proof and not requires_payment) else ("required" if requires_payment else None),
    }
