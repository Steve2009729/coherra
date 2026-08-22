"""Coherra x402 payment gate module — Base mainnet.

Implements the x402 Payment Required specification:
  - 402 challenge response construction
  - On-chain transaction settlement verification against Base mainnet RPC
  - Replay prevention for transaction hashes
  - Dynamic payout address resolution from COHERRA_PAYOUT_ADDRESS env var
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_MAINNET_CHAIN_ID = 8453
BASE_MAINNET_RPC_URL = (
    os.environ.get("BASE_MAINNET_RPC_URL")
    or os.environ.get("BASE_RPC_URL")
    or "https://mainnet.base.org"
)
BASE_MAINNET_USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
DEFAULT_PRICE_USDC = "0.015"
DEFAULT_PRICE_RAW = "15000"  # 6 decimals -> 0.015 USDC = 15000 units

# ERC-20 Transfer topic: Transfer(address,address,uint256)
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Replay protection set (in-memory, thread-safe)
_USED_TX_LOCK = threading.Lock()
_USED_TX_HASHES: set[str] = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_payout_address() -> str:
    """Return the recipient payout address from COHERRA_PAYOUT_ADDRESS env var.

    Raises ValueError if the env var is missing or not a valid Ethereum address.
    """
    addr = os.environ.get("COHERRA_PAYOUT_ADDRESS", "").strip()
    if not addr:
        raise ValueError(
            "COHERRA_PAYOUT_ADDRESS environment variable is not set. "
            "Set it to your wallet address before starting the x402 server."
        )
    if not re.match(r"^0x[a-fA-F0-9]{40}$", addr):
        raise ValueError(
            f"COHERRA_PAYOUT_ADDRESS={addr!r} is not a valid 20-byte hex Ethereum address."
        )
    return addr


def build_402_payload(
    payout_address: str,
    detail: str = "",
) -> dict[str, Any]:
    """Construct the x402 JSON challenge response body."""
    return {
        "x402": True,
        "version": "1.0",
        "error": "Payment Required",
        "detail": detail or "Valid x402 payment proof on Base mainnet required to access POST /audit",
        "accepts": [
            {
                "scheme": "exact",
                "network": "base",
                "chain_id": BASE_MAINNET_CHAIN_ID,
                "asset": "USDC",
                "contract_address": BASE_MAINNET_USDC_CONTRACT,
                "amount": DEFAULT_PRICE_USDC,
                "amount_raw": DEFAULT_PRICE_RAW,
                "payee": payout_address,
                "rpc_url": BASE_MAINNET_RPC_URL,
            }
        ],
    }


def parse_payment_proof(raw_proof: str | dict) -> str | None:
    """Extract a 66-character 0x-prefixed transaction hash from raw proof input."""
    if isinstance(raw_proof, dict):
        raw_proof = raw_proof.get("tx_hash") or raw_proof.get("proof") or raw_proof.get("transaction_hash") or ""
    if not isinstance(raw_proof, str):
        return None

    raw_proof = raw_proof.strip()

    # If it's a JSON string, try parsing
    if raw_proof.startswith("{"):
        try:
            data = json.loads(raw_proof)
            if isinstance(data, dict):
                return parse_payment_proof(data)
        except json.JSONDecodeError:
            pass

    # Extract 0x-prefixed or bare 64-char hex string
    match = re.search(r"(?:0x)?[a-fA-F0-9]{64}", raw_proof)
    if match:
        val = match.group(0).lower()
        if not val.startswith("0x"):
            val = "0x" + val
        return val
    return None


def verify_payment_onchain(
    proof_header: str | dict,
    payout_address: str,
    rpc_url: str = BASE_MAINNET_RPC_URL,
) -> tuple[bool, str]:
    """Verify an x402 transaction proof against the Base mainnet blockchain.

    Checks:
      1. Valid 66-char transaction hash present.
      2. Transaction hash has not been previously used (replay protection).
      3. Transaction exists on Base mainnet and status == 0x1 (successful).
      4. Log contains ERC-20 Transfer event (or direct value transfer) matching
         payout_address and amount >= required minimum (15,000 units / 0.015 USDC).

    Returns:
        (True, "success message") or (False, "error explanation")
    """
    tx_hash = parse_payment_proof(proof_header)
    if not tx_hash:
        return False, "Malformed payment proof: missing 66-character 0x-prefixed transaction hash."

    # Check replay protection
    with _USED_TX_LOCK:
        if tx_hash in _USED_TX_HASHES:
            return False, f"Replay rejected: transaction hash {tx_hash} has already been used."

    # List of RPC endpoints with fallback for network resilience
    rpc_endpoints = [rpc_url]
    for alt in ("https://developer-access-mainnet.base.org", "https://1rpc.io/base"):
        if alt not in rpc_endpoints:
            rpc_endpoints.append(alt)

    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getTransactionReceipt",
        "params": [tx_hash],
        "id": 1,
    }

    rpc_result = None
    last_err = ""
    for r_url in rpc_endpoints:
        try:
            response = httpx.post(r_url, json=payload, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if "result" in data or "error" in data:
                    rpc_result = data
                    break
        except Exception as e:
            last_err = str(e)
            continue

    if not rpc_result:
        return False, f"RPC connection error to Base mainnet ({rpc_url}): {last_err or 'Network unreachable'}"

    if "error" in rpc_result:
        return False, f"RPC error: {rpc_result['error']}"

    receipt = rpc_result.get("result")
    if not receipt:
        return False, f"Transaction {tx_hash} not found on Base mainnet chain."

    # Check status (0x1 = success)
    status = receipt.get("status")
    if status != "0x1":
        return False, f"Transaction {tx_hash} failed or was reverted on-chain (status={status})."

    # Verify payout recipient and amount
    # Case A: ERC-20 USDC Transfer event log
    target_payee_hex = payout_address.lower().replace("0x", "").zfill(64)
    min_amount_raw = int(DEFAULT_PRICE_RAW)

    verified = False
    logs = receipt.get("logs", [])

    for log in logs:
        topics = log.get("topics", [])
        if not topics or topics[0].lower() != ERC20_TRANSFER_TOPIC:
            continue
        if len(topics) >= 3:
            to_topic = topics[2].lower().replace("0x", "")
            if to_topic == target_payee_hex:
                # Value is stored in log data
                data_hex = log.get("data", "0x0").replace("0x", "")
                val = int(data_hex, 16) if data_hex else 0
                if val >= min_amount_raw:
                    verified = True
                    break

    # Case B: Direct ETH transfer fallback if ERC-20 log not matched
    if not verified:
        # Query transaction details for ETH transfer
        tx_payload = {
            "jsonrpc": "2.0",
            "method": "eth_getTransactionByHash",
            "params": [tx_hash],
            "id": 2,
        }
        try:
            tx_resp = httpx.post(rpc_url, json=tx_payload, timeout=10.0).json()
            tx_data = tx_resp.get("result") or {}
            tx_to = (tx_data.get("to") or "").lower()
            tx_val = int(tx_data.get("value", "0x0"), 16)

            if tx_to == payout_address.lower() and tx_val > 0:
                verified = True
        except Exception:
            pass

    if not verified:
        return False, (
            f"Transaction {tx_hash} cleared on-chain, but did not transfer >= {DEFAULT_PRICE_USDC} USDC "
            f"(or native value) to payee address {payout_address}."
        )

    # Record used hash in replay protection
    with _USED_TX_LOCK:
        _USED_TX_HASHES.add(tx_hash)

    return True, f"Payment verified on Base mainnet (tx={tx_hash[:10]}...)."
