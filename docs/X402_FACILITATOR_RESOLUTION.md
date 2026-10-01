# Coherra x402 Facilitator Architecture Resolution

## 1. Summary of Resolution
**Decision**: Coherra uses direct on-chain JSON-RPC verification against Base mainnet nodes. **No third-party CDP facilitator API key is required.**

## 2. Technical Architecture & Analysis
- **Payment Settlement**: When a client executes a 0.015 USDC micropayment on Base Mainnet (Chain ID 8453), the transaction is signed via Privy/viem and broadcasted to the Base network.
- **On-Chain Receipt Verification**:
  - The backend (`coherra.x402:verify_payment_onchain`) queries standard Ethereum JSON-RPC (`eth_getTransactionReceipt`) across resilient Base endpoints (`https://mainnet.base.org`, `https://developer-access-mainnet.base.org`, `https://1rpc.io/base`).
  - Verifies execution status (`status: 0x1`).
  - Inspects ERC-20 `Transfer(address,address,uint256)` event logs to verify the payee recipient (`0x1BFAe4EE12c8f2bF17B8EEb8Ea0BcB32AdbB240B`) and transfer value ($\ge 15,000$ units / 0.015 USDC).
  - Enforces thread-safe replay attack protection.
- **Benefits**:
  - Zero external third-party API dependencies or rate limits.
  - Zero risk of vendor lock-in or custodian downtime.
  - Fully sovereign, verifiable, and trustless on-chain operation.
