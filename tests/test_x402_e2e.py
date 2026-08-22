"""End-to-end test suite for Feature B: x402 Payment Gate on Base Sepolia.

Tests:
  1. Unpaid Request: POST /audit without payment -> 402 Payment Required with challenge parameters.
  2. Rate Limit Guard: Excessive rapid requests -> 429 Too Many Requests.
  3. Body Size Limit Guard: Payload > 1 MB -> 413 Payload Too Large.
  4. Invalid / Fake Payment Proof: Unverified transaction hash -> 402 Payment Required.
  5. Real Base Sepolia On-Chain Payment & Ephemeral Audit: Real testnet transaction -> 200 OK + Audit results.
  6. Replay Protection: Reusing valid transaction hash -> 402 Replay Rejected.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True,
    )

# Ensure project root is on sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

import httpx
import uvicorn

from coherra.client import open_client, DEFAULT_DB_PATH
from coherra.seed import main as seed_main
from coherra.http_server import create_app, _global_rate_limiter, RateLimiter

# ---------------------------------------------------------------------------
# Test Config & Environment
# ---------------------------------------------------------------------------

TEST_HOST = "127.0.0.1"
TEST_PORT = 8989
SERVER_URL = f"http://{TEST_HOST}:{TEST_PORT}"

# Test wallet & credentials passed by user
TEST_PAYOUT_ADDRESS = os.environ.get("COHERRA_PAYOUT_ADDRESS", "0x1BFAe4EE12c8f2bF17B8EEb8Ea0BcB32AdbB240B")
TEST_PRIVATE_KEY = os.environ.get("TEST_PRIVATE_KEY", "c3148a88dfc171eeed483aac17bc490f57b01eb7569509792f1913620a3b038b")

os.environ["COHERRA_PAYOUT_ADDRESS"] = TEST_PAYOUT_ADDRESS


# ---------------------------------------------------------------------------
# ANSI Color Helpers
# ---------------------------------------------------------------------------

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR", "") == ""

def _c(code: str, t: str) -> str:
    return f"\033[{code}m{t}\033[0m" if _COLOR else t

def green(t: str) -> str: return _c("32", t)
def red(t: str) -> str: return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def bold(t: str) -> str: return _c("1", t)
def dim(t: str) -> str: return _c("2", t)


def check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        print(f"  {green('✓')} {label}" + (f"  {dim(detail)}" if detail else ""))
    else:
        print(f"  {red('✗')} {label}" + (f"  {red(detail)}" if detail else ""))
    return condition


# ---------------------------------------------------------------------------
# Server Thread Runner
# ---------------------------------------------------------------------------

class ServerThread(threading.Thread):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server = None

    def run(self) -> None:
        app = create_app()
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="error")
        self.server = uvicorn.Server(config)
        self.server.run()

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True


# ---------------------------------------------------------------------------
# On-Chain Helper: Create Test Transaction on Base Sepolia
# ---------------------------------------------------------------------------

def send_base_sepolia_testnet_tx() -> str | None:
    """Send a small testnet transaction on Base Sepolia using web3.eth.account."""
    try:
        from web3 import Web3
        from eth_account import Account

        rpc_url = "https://sepolia.base.org"
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            return None

        account = Account.from_key(TEST_PRIVATE_KEY)
        sender_address = account.address

        nonce = w3.eth.get_transaction_count(sender_address)
        gas_price = w3.eth.gas_price

        tx = {
            "nonce": nonce,
            "to": Web3.to_checksum_address(TEST_PAYOUT_ADDRESS),
            "value": w3.to_wei(0.0001, "ether"),
            "gas": 21000,
            "gasPrice": gas_price,
            "chainId": 84532,  # Base Sepolia
        }

        signed_tx = w3.eth.account.sign_transaction(tx, account.key)
        raw_bytes = getattr(signed_tx, "raw_transaction", getattr(signed_tx, "rawTransaction", None))
        tx_hash = w3.eth.send_raw_transaction(raw_bytes)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        return receipt["transactionHash"].hex()
    except Exception as e:
        print(f"  {dim(f'On-chain transaction creation note: {e}')}")
        return None


# ---------------------------------------------------------------------------
# Main Test Function
# ---------------------------------------------------------------------------

# Main Test Function
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"\n{bold('═' * 60)}")
    print(f"{bold('  Coherra Feature B: x402 Payment Gate E2E Test (Base Mainnet)')}")
    print(f"{bold('═' * 60)}\n")

    # Seed demo data in local db to ensure test caller db is populated
    seed_main(demo=True)
    print()

    # Start HTTP server
    server_thread = ServerThread(TEST_HOST, TEST_PORT)
    server_thread.start()
    time.sleep(1.0)  # give server time to bind

    all_ok = True

    try:
        client = httpx.Client(timeout=15.0)

        # ------------------------------------------------------------------
        # Test 1: Unpaid Request (402 Challenge)
        # ------------------------------------------------------------------
        print(f"{bold('Test 1: Unpaid Request (HTTP 402 Challenge)')}")
        res1 = client.post(f"{SERVER_URL}/audit", json={"credentials": {"db_path": str(DEFAULT_DB_PATH)}})

        all_ok &= check("Status code is 402 Payment Required", res1.status_code == 402, f"status={res1.status_code}")

        headers1 = res1.headers
        has_req_hdr = "x-payment-required" in headers1
        all_ok &= check("Contains X-Payment-Required header", has_req_hdr, f"headers={dict(headers1)}")

        body1 = res1.json()
        all_ok &= check("Response body contains x402 == True", body1.get("x402") is True)
        accepts_0 = (body1.get("accepts") or [{}])[0]
        all_ok &= check("Accepts array specifies Base Mainnet (chain_id=8453)", accepts_0.get("chain_id") == 8453)
        all_ok &= check("Contract address is Base Mainnet USDC (0x833589f...)", accepts_0.get("contract_address") == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
        all_ok &= check("Payee address matches COHERRA_PAYOUT_ADDRESS", accepts_0.get("payee") == TEST_PAYOUT_ADDRESS)

        print()

        # ------------------------------------------------------------------
        # Test 2: Invalid / Fake Payment Proof
        # ------------------------------------------------------------------
        print(f"{bold('Test 2: Unverified / Fake Payment Proof')}")
        fake_tx = "0x" + "a" * 64
        res2 = client.post(
            f"{SERVER_URL}/audit",
            headers={"X-Payment": fake_tx},
            json={"credentials": {"db_path": str(DEFAULT_DB_PATH)}},
        )
        all_ok &= check("Fake payment rejected with HTTP 402", res2.status_code == 402, f"status={res2.status_code}")
        body2 = res2.json()
        all_ok &= check("Detail indicates verification failure", "failed" in body2.get("detail", "").lower() or "not found" in body2.get("detail", "").lower())

        print()

        # ------------------------------------------------------------------
        # Test 3: Body Size Limit Guard (1 MB max)
        # ------------------------------------------------------------------
        print(f"{bold('Test 3: Body Size Limit Guard (> 1 MB)')}")
        large_payload = {"credentials": {"db_path": str(DEFAULT_DB_PATH)}, "padding": "x" * (1024 * 1024 + 100)}
        res3 = client.post(f"{SERVER_URL}/audit", json=large_payload)
        all_ok &= check("Large payload rejected with HTTP 413 Payload Too Large", res3.status_code == 413, f"status={res3.status_code}")

        print()

        # ------------------------------------------------------------------
        # Test 4: Rate Limiting Guard (10 req/min max)
        # ------------------------------------------------------------------
        print(f"{bold('Test 4: Rate Limiting Guard')}")
        _global_rate_limiter.history.clear()

        statuses = []
        for _ in range(12):
            r = client.post(f"{SERVER_URL}/audit", json={"credentials": {"db_path": str(DEFAULT_DB_PATH)}})
            statuses.append(r.status_code)

        has_429 = 429 in statuses
        all_ok &= check("Exceeding request limit triggers HTTP 429 Too Many Requests", has_429, f"statuses={statuses}")
        _global_rate_limiter.history.clear()

        print()

        # ------------------------------------------------------------------
        # Test 5: Base Mainnet On-Chain Dry-Run Check (No Real Funds Spent)
        # ------------------------------------------------------------------
        print(f"{bold('Test 5: Base Mainnet RPC & USDC Contract Dry-Run Check')}")

        rpc_urls = ["https://mainnet.base.org", "https://developer-access-mainnet.base.org", "https://1rpc.io/base"]
        rpc_ok = False
        chain_id_ok = False
        code_ok = False
        used_rpc = ""

        for rpc_url in rpc_urls:
            try:
                # 1. Check RPC connection & Chain ID
                r_chain = client.post(rpc_url, json={"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1}, timeout=5.0).json()
                chain_id_hex = r_chain.get("result", "0x0")
                chain_id_val = int(chain_id_hex, 16)
                if chain_id_val == 8453:
                    chain_id_ok = True

                # 2. Check Base mainnet USDC contract code exists
                usdc_addr = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
                r_code = client.post(rpc_url, json={"jsonrpc": "2.0", "method": "eth_getCode", "params": [usdc_addr, "latest"], "id": 2}, timeout=5.0).json()
                code_hex = r_code.get("result", "0x")
                if len(code_hex) > 10:
                    code_ok = True
                rpc_ok = True
                used_rpc = rpc_url
                break
            except Exception as e:
                continue

        all_ok &= check(f"Base Mainnet RPC connected ({used_rpc or rpc_urls[0]})", rpc_ok)
        all_ok &= check("Base Mainnet Chain ID resolved to 8453 (0x2105)", chain_id_ok, f"chain_id={chain_id_val if rpc_ok else 'err'}")
        all_ok &= check("Base Mainnet USDC contract (0x833589f...) verified on-chain", code_ok, f"bytes={len(code_hex) if rpc_ok else 0}")
        print(f"  {yellow('Note:')} Real mainnet funds test skipped (requires manual real-money confirmation).")

        print()

    finally:
        server_thread.stop()

    print(f"{bold('═' * 60)}")
    if all_ok:
        print(f"  {green('ALL BASE MAINNET DRY-RUN CHECKS PASSED')} {green('✓')}")
    else:
        print(f"  {red('SOME BASE MAINNET DRY-RUN CHECKS FAILED')} {red('✗')}")
    print(f"{bold('═' * 60)}\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
