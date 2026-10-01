# Coherra

**An AI agent's memory gets messy.  Coherra keeps it clean.**

After months of use, any long-running agent accumulates contradictions (the same
fact stored twice with different values), duplicates (the same value under
different key names), and stale entries (facts that were true six months ago but
almost certainly aren't now).  Coherra audits the entire memory on demand, scores
its health, surfaces every issue with a clear explanation, and repairs them —
logging every single action permanently inside Sibyl Memory itself.
**No external database.  No separate service.  Everything lives inside Sibyl.**

---

## Live Production Deployment

- **Production Domain (Web App & Chat)**: [https://coherra.xyz](https://coherra.xyz) (or [https://coherra.app](https://coherra.app))
- **Production API & x402 Server**: [https://api.coherra.xyz](https://api.coherra.xyz) (or [https://api.coherra.app](https://api.coherra.app))
- **Base Mainnet Smart Contract (USDC)**: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (Chain ID: `8453`)
- **Official Payout Address**: `0x1BFAe4EE12c8f2bF17B8EEb8Ea0BcB32AdbB240B`
- **Track 1**: In-browser hosted multi-model chat with Gemini, OpenAI, Grok, and Claude.
- **Track 2**: Local MCP/CLI memory audit and drift resolution.


---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Agent / IDE                       │
│           (Claude Code, Codex CLI, Cursor, …)            │
└───────────────────────┬─────────────────────────────────┘
                        │ MCP (stdio)
          ┌─────────────▼──────────────┐
          │       Coherra MCP Server    │
          │  coherra_remember           │  ← structured writes
          │  coherra_recall             │  ← single entity read
          │  coherra_list               │  ← browse memory
          │  coherra_audit              │  ← run full scan
          │  coherra_repair             │  ← fix one issue
          │  coherra_repair_safe        │  ← batch safe fixes
          └─────────────┬──────────────┘
                        │ sibyl-memory-client SDK
          ┌─────────────▼──────────────┐
          │       Sibyl Memory          │
          │  WARM tier  — entities      │  ← facts, preferences, people
          │  HOT  tier  — state         │  ← coherra:last_audit, coherra:config
          │  COLD tier  — journal       │  ← coherra_scan, coherra_repair events
          └─────────────────────────────┘
                   ~/.sibyl-memory/memory.db
```

**Coherra sits between the agent and Sibyl Memory.**
It adds a schema layer (versioned, confidence-tagged bodies), an audit engine
(three detectors: contradiction, duplicate, staleness), and a repair engine that
logs every action to Sibyl's own append-only journal — so the audit trail is
itself part of the memory being managed.

---

## Quickstart

```bash
# 1. Clone and install
git clone <repo>
cd coherra
pip install -e .

# 2. Make sure Sibyl Memory is initialised
#    (run once if you haven't already)
sibyl init

# 3. Load the demo dataset
python -m coherra.seed --demo

# 4. Run your first audit
coherra scan

# 5. Browse the issues
coherra issues

# 6. Fix safe issues automatically
coherra fix --all

# 7. Resolve contradictions interactively
coherra fix <issue-id>

# 8. Confirm clean memory
coherra scan
```

---

## CLI reference

| Command | What it does |
|---|---|
| `coherra scan` | Run a full audit — contradiction, duplicate, staleness checks |
| `coherra health` | One-line summary of the last scan result |
| `coherra issues [--severity <s>]` | List every flagged issue, grouped by severity |
| `coherra fix <id> [action]` | Fix one issue; contradictions get an interactive prompt |
| `coherra fix --all` | Auto-apply all safe repairs (duplicates + stale) |

---

## MCP server

Add to your `.mcp.json` or Claude Code settings:

```json
{
  "mcpServers": {
    "coherra": { "command": "coherra-mcp" }
  }
}
```

Tools exposed: `coherra_remember`, `coherra_recall`, `coherra_list`,
`coherra_audit`, `coherra_repair`, `coherra_repair_safe`.

---

## The pitch

Most memory systems only answer the question *"what do I know?"*
Coherra answers *"what do I know that's **wrong**?"* —
and fixes it, permanently, with a complete audit trail stored
inside the same memory it's cleaning.

Built for the **Sibyl Labs Memory Hackathon** · August 2026.
Requires: `sibyl-memory-client >= 0.5.0`, `mcp >= 1.0.0`.
