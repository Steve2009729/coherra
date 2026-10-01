/**
 * Coherra API Client.
 * Communicates with the Coherra x402 Python Backend API server.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_COHERRA_API_URL || "http://127.0.0.1:8080";

export interface AuditIssue {
  id: string;
  severity: "contradiction" | "duplicate" | "stale";
  category: string;
  name: string;
  detail: string;
  value_a?: string;
  value_b?: string;
  related_entity?: string;
}

export interface AuditHistoryRecord {
  id: number;
  privy_user_id: string;
  wallet_address?: string;
  health_score: number;
  issues_found: AuditIssue[];
  payment_tx_hash?: string;
  created_at: string;
}

export interface AuditResponse {
  ok: boolean;
  status?: number;
  detail?: string;
  payment_status?: string;
  payment_detail?: string;
  timestamp?: string;
  health_score?: number;
  issues_found?: AuditIssue[];
  entity_count?: number;
  ephemeral?: boolean;
  error?: string;
  message?: string;
  x402?: boolean;
  accepts?: Array<{
    scheme: string;
    network: string;
    chain_id: number;
    asset: string;
    contract_address: string;
    amount: string;
    payee: string;
  }>;
}

export interface LinkWalletResponse {
  ok: boolean;
  wallet_address?: string;
  privy_user_id?: string;
  linked_at?: string;
  error?: string;
  message?: string;
}

export interface AuditHistoryResponse {
  ok: boolean;
  privy_user_id?: string;
  count?: number;
  history?: AuditHistoryRecord[];
  error?: string;
  message?: string;
}

/**
 * Link a user's wallet address with their Privy user ID on the backend.
 */
export async function linkWallet(
  privyUserId: string,
  walletAddress: string,
  email?: string
): Promise<LinkWalletResponse> {
  try {
    const res = await fetch(`${API_BASE_URL}/link-wallet`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        privy_user_id: privyUserId,
        wallet_address: walletAddress,
        email,
      }),
    });
    return await res.json();
  } catch (err: any) {
    return { ok: false, error: "Network Error", message: err.message };
  }
}

/**
 * Fetch audit history for a Privy user ID.
 */
export async function fetchAuditHistory(privyUserId: string): Promise<AuditHistoryResponse> {
  try {
    const res = await fetch(`${API_BASE_URL}/audit-history/${encodeURIComponent(privyUserId)}`, {
      method: "GET",
      headers: { "Accept": "application/json" },
    });
    return await res.json();
  } catch (err: any) {
    return { ok: false, error: "Network Error", message: err.message };
  }
}

/**
 * Trigger an audit against the Python backend with optional x402 payment proof header.
 */
export async function triggerAudit(
  credentials: Record<string, any>,
  privyUserId?: string,
  walletAddress?: string,
  paymentProofTxHash?: string
): Promise<AuditResponse> {
  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (paymentProofTxHash) {
      headers["X-Payment"] = paymentProofTxHash;
    }

    const payload = {
      credentials,
      privy_user_id: privyUserId,
      wallet_address: walletAddress,
    };

    const res = await fetch(`${API_BASE_URL}/audit`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (res.status === 402) {
      return { ok: false, status: 402, ...data } as any;
    }
    return data;
  } catch (err: any) {
    return { ok: false, error: "Network Error", message: err.message };
  }
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatResponse {
  ok: boolean;
  model?: string;
  message?: string;
  tool_calls?: Array<{
    name: string;
    arguments: Record<string, any>;
    result: Record<string, any>;
  }>;
  requires_payment?: boolean;
  challenge?: {
    x402: boolean;
    version: string;
    error: string;
    detail: string;
    accepts: Array<{
      scheme: string;
      network: string;
      chain_id: number;
      asset: string;
      contract_address: string;
      amount: string;
      amount_raw: string;
      payee: string;
      rpc_url: string;
    }>;
  };
  payment_status?: string;
  error?: string;
}

/**
 * Send a chat message to the Coherra Track 1 multi-model backend.
 */
export async function sendChatMessage(params: {
  tenantId: string;
  model: string;
  message: string;
  history?: ChatMessage[];
  paymentProof?: string;
}): Promise<ChatResponse> {
  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (params.paymentProof) {
      headers["X-Payment"] = params.paymentProof;
    }

    const res = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        tenant_id: params.tenantId,
        model: params.model,
        message: params.message,
        history: params.history || [],
        payment_proof: params.paymentProof,
      }),
    });

    const data = await res.json();
    return data;
  } catch (err: any) {
    return { ok: false, error: "Network Error", message: err.message };
  }
}

