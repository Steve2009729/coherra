# Coherra Credential Sourcing Architecture & User Scoping

## 1. Context & Architecture (Track 2 vs. Track 1)

Coherra operates across two distinct modes of operation:

### Track 2: Local Sibyl Memory Audit via x402 Micropayments
- **Storage Location**: The user's Sibyl Memory database (`~/.sibyl-memory/memory.db`) or local filesystem / MCP server.
- **Credential Scope**: 
  - When a user signs into Coherra with Privy (`privy:did:...`), their `privy_user_id` and connected wallet address (`0x...`) are bound to the session.
  - On `/audit`, the user specifies their memory target (`db_path`, default: `~/.sibyl-memory/memory.db`, or remote MCP tenant identifier).
  - The frontend sends `POST /audit` with:
    ```json
    {
      "credentials": {
        "db_path": "~/.sibyl-memory/memory.db"
      },
      "privy_user_id": "did:privy:...",
      "wallet_address": "0x123..."
    }
    ```
  - **Ephemeral Execution**: The backend (`coherra.http_server:run_ephemeral_audit`) spins up a temporary `MemoryClient`, loads and audits the entities, computes health score and conflict issues, and immediately purges credentials and closes storage handles via Python `gc.collect()`.
  - **User History Scoping**: The verified audit record is inserted into `audit_history` in Postgres with foreign key `privy_user_id`. The user's dashboard (`/dashboard`) queries `/audit-history/{privy_user_id}` so that only the authenticated user can view their historical audits.

### Track 1: Hosted Multi-LLM Chat Memory Isolation
- **Storage Location**: Hosted multi-tenant PostgreSQL (`coherra.storage_pg:PostgresStorageAdapter`).
- **Isolation Guarantee**: Each tenant is strictly isolated by `tenant_id` (`privy_user_id`), enforced by `UNIQUE(tenant_id, category, name)` and per-query tenant filtering.
