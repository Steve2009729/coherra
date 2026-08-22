"use client";

import { usePrivy, useWallets } from "@privy-io/react-auth";
import { useState } from "react";
import { encodeFunctionData, parseUnits } from "viem";
import {
  Activity,
  ShieldCheck,
  Zap,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Lock,
  ExternalLink,
  Wallet,
  ArrowRight,
  Sparkles,
  CreditCard,
} from "lucide-react";
import { PageTransition } from "@/components/motion/PageTransition";
import { FadeInUp } from "@/components/motion/FadeInUp";
import { StaggerContainer, StaggerItem } from "@/components/motion/StaggerContainer";
import { triggerAudit, AuditResponse } from "@/lib/api";

const erc20Abi = [
  {
    name: "transfer",
    type: "function",
    inputs: [
      { name: "to", type: "address" },
      { name: "value", type: "uint256" },
    ],
    outputs: [{ name: "", type: "bool" }],
    stateMutability: "nonpayable",
  },
] as const;

export default function AuditPage() {
  const { ready, authenticated, user, connectWallet, login } = usePrivy();
  const { wallets } = useWallets();

  const [dbPath, setDbPath] = useState("~/.sibyl-memory/memory.db");
  const [txHash, setTxHash] = useState("");
  const [loading, setLoading] = useState(false);
  const [paying, setPaying] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState<string | null>(null);
  const [result, setResult] = useState<AuditResponse | null>(null);

  const primaryWallet = user?.wallet?.address;
  const privyUserId = user?.id;

  const handleRunAudit = async (customTxHash?: string) => {
    setLoading(true);
    setResult(null);
    try {
      const proofToUse = customTxHash !== undefined ? customTxHash : txHash.trim();
      const res = await triggerAudit(
        { db_path: dbPath },
        privyUserId,
        primaryWallet,
        proofToUse || undefined
      );
      setResult(res);
    } catch (err: any) {
      setResult({ ok: false, error: "Client Error", message: err.message });
    } finally {
      setLoading(false);
    }
  };

  /**
   * Triggers real on-chain USDC payment on Base mainnet via connected Privy wallet.
   */
  const handlePayOnChain = async () => {
    if (!authenticated) {
      login();
      return;
    }

    if (!wallets || wallets.length === 0) {
      connectWallet();
      return;
    }

    const activeWallet =
      wallets.find((w) => w.address.toLowerCase() === primaryWallet?.toLowerCase()) ||
      wallets[0];

    if (!activeWallet) {
      setPaymentStatus("No active wallet connected");
      return;
    }

    const challenge = result?.accepts?.[0];
    const payeeAddress = challenge?.payee || "0x1BFAe4EE12c8f2bF17B8EEb8Ea0BcB32AdbB240B";
    const usdcContract = challenge?.contract_address || "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
    const amountStr = challenge?.amount || "0.015";

    setPaying(true);
    setPaymentStatus("Preparing on-chain USDC transfer transaction...");

    try {
      // 0.015 USDC with 6 decimals = 15000 units
      const amountUnits = parseUnits(amountStr, 6);
      const calldata = encodeFunctionData({
        abi: erc20Abi,
        functionName: "transfer",
        args: [payeeAddress as `0x${string}`, amountUnits],
      });

      setPaymentStatus("Requesting signature from Privy wallet...");
      const provider = await activeWallet.getEthereumProvider();
      const realTxHash = (await provider.request({
        method: "eth_sendTransaction",
        params: [
          {
            from: activeWallet.address,
            to: usdcContract,
            data: calldata,
            value: "0x0",
          },
        ],
      })) as string;

      setPaymentStatus(`Transaction broadcasted: ${realTxHash}. Retrying audit with payment proof...`);
      setTxHash(realTxHash);

      // Retry audit with real transaction hash proof
      await handleRunAudit(realTxHash);
    } catch (err: any) {
      console.error("On-chain payment failed:", err);
      setPaymentStatus(`Payment Error: ${err.message || err}`);
    } finally {
      setPaying(false);
    }
  };

  return (
    <PageTransition>
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-8">
        <FadeInUp>
          <div className="space-y-2 text-center sm:text-left">
            <h1 className="text-3xl font-extrabold text-white flex items-center justify-center sm:justify-start gap-3">
              <Activity className="w-8 h-8 text-indigo-400" />
              Memory Audit &amp; Repair Console
            </h1>
            <p className="text-slate-400 text-sm">
              Execute live memory scans against your Sibyl Memory database using Base mainnet x402 USDC micropayments.
            </p>
          </div>
        </FadeInUp>

        {/* Auth / Wallet Banner */}
        {ready && (!authenticated || !primaryWallet) && (
          <FadeInUp delay={0.05}>
            <div className="p-4 rounded-2xl bg-indigo-950/40 border border-indigo-800/80 flex items-center justify-between gap-4 text-xs text-indigo-200">
              <div className="flex items-center gap-2">
                <Wallet className="w-4 h-4 text-indigo-400" />
                <span>
                  {!authenticated
                    ? "Sign in with Privy to associate your audit history with your account."
                    : "Connect a Web3 wallet to sign on-chain x402 micropayments."}
                </span>
              </div>
              <button
                onClick={() => (!authenticated ? login() : connectWallet())}
                className="px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold transition-all whitespace-nowrap"
              >
                {!authenticated ? "Sign In" : "Connect Wallet"}
              </button>
            </div>
          </FadeInUp>
        )}

        {/* Audit Request Form */}
        <FadeInUp delay={0.1}>
          <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 space-y-6">
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                  Sibyl Memory Database Path
                </label>
                <input
                  type="text"
                  value={dbPath}
                  onChange={(e) => setDbPath(e.target.value)}
                  className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-800 text-white font-mono text-sm focus:outline-none focus:border-indigo-500 transition-colors"
                  placeholder="~/.sibyl-memory/memory.db"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                  X-Payment Proof Header (Optional / Tx Hash)
                </label>
                <input
                  type="text"
                  value={txHash}
                  onChange={(e) => setTxHash(e.target.value)}
                  className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-800 text-white font-mono text-sm focus:outline-none focus:border-indigo-500 transition-colors"
                  placeholder="0x... (Leave empty to trigger HTTP 402 challenge)"
                />
              </div>
            </div>

            <button
              onClick={() => handleRunAudit()}
              disabled={loading || paying}
              className="w-full py-4 px-6 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-semibold shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 transition-all flex items-center justify-center gap-2 disabled:opacity-50 text-base"
            >
              {loading ? (
                <>
                  <RefreshCw className="w-5 h-5 animate-spin" />
                  Running Ephemeral Audit...
                </>
              ) : (
                <>
                  <Zap className="w-5 h-5" />
                  Execute POST /audit Request
                </>
              )}
            </button>
          </div>
        </FadeInUp>

        {/* Audit Response Payload / Payoff View */}
        {result && (
          <FadeInUp delay={0.2}>
            <div className="space-y-6">
              {result.status === 402 || result.x402 ? (
                /* HTTP 402 Payment Challenge Card */
                <div className="p-8 rounded-3xl bg-amber-950/40 border border-amber-800/80 space-y-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 text-amber-400 font-bold text-lg">
                      <Lock className="w-6 h-6" />
                      HTTP 402 Payment Required
                    </div>
                    <span className="px-3 py-1 rounded-full bg-amber-900/60 text-amber-300 font-mono text-xs font-semibold">
                      Base Mainnet (8453)
                    </span>
                  </div>

                  <p className="text-slate-300 text-sm leading-relaxed">
                    {result.detail || result.message || "Payment required to execute memory audit engine."}
                  </p>

                  {result.accepts && result.accepts.length > 0 && (
                    <div className="p-5 rounded-2xl bg-slate-950/80 border border-amber-900/60 font-mono text-xs space-y-2">
                      <div className="text-amber-300 font-semibold uppercase tracking-wider mb-2">
                        x402 Challenge Parameters
                      </div>
                      <div className="flex justify-between py-1 border-b border-slate-900 text-slate-300">
                        <span>Required Amount:</span>
                        <span className="text-emerald-400 font-bold">{result.accepts[0].amount} USDC</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-slate-900 text-slate-300">
                        <span>Target Network:</span>
                        <span className="text-white">{result.accepts[0].network} (Chain ID: {result.accepts[0].chain_id})</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-slate-900 text-slate-300">
                        <span>USDC Contract:</span>
                        <span className="text-indigo-300 truncate max-w-[200px]">{result.accepts[0].contract_address}</span>
                      </div>
                      <div className="flex justify-between py-1 text-slate-300">
                        <span>Payout Address:</span>
                        <span className="text-purple-300 truncate max-w-[200px]">{result.accepts[0].payee}</span>
                      </div>
                    </div>
                  )}

                  {paymentStatus && (
                    <div className="p-3 rounded-xl bg-slate-950 border border-amber-900/60 text-xs font-mono text-amber-300 flex items-center gap-2">
                      {paying && <RefreshCw className="w-4 h-4 animate-spin text-amber-400 shrink-0" />}
                      <span>{paymentStatus}</span>
                    </div>
                  )}

                  <div className="pt-2 flex flex-col sm:flex-row items-center gap-3">
                    <button
                      onClick={handlePayOnChain}
                      disabled={paying || loading}
                      className="w-full sm:w-auto px-6 py-3.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold text-sm transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/30 disabled:opacity-50"
                    >
                      <CreditCard className="w-4 h-4" />
                      {paying ? "Processing Payment..." : `Pay ${result.accepts?.[0]?.amount || "0.015"} USDC On-Chain & Execute Audit`}
                    </button>
                  </div>
                </div>
              ) : result.ok ? (
                /* Successful Audit Payoff View */
                <div className="p-8 rounded-3xl bg-slate-900/90 border border-slate-800 space-y-6 shadow-2xl">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-800">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 rounded-2xl bg-emerald-950 border border-emerald-800/80 flex items-center justify-center text-emerald-400">
                        <CheckCircle2 className="w-7 h-7" />
                      </div>
                      <div>
                        <h2 className="text-xl font-bold text-white">Memory Audit Verified</h2>
                        <p className="text-xs text-slate-400 font-mono">
                          Payment Status: {result.payment_status} | Ephemeral Exec: {String(result.ephemeral)}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <div className="text-right">
                        <div className="text-xs text-slate-400 uppercase font-semibold">Health Score</div>
                        <div
                          className={`text-2xl font-black ${
                            (result.health_score ?? 100) >= 80
                              ? "text-emerald-400"
                              : (result.health_score ?? 100) >= 60
                              ? "text-amber-400"
                              : "text-rose-400"
                          }`}
                        >
                          {result.health_score}/100
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 font-mono text-xs">
                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
                      <span className="text-slate-400 uppercase text-[10px]">Entities Audited</span>
                      <p className="text-lg font-bold text-white">{result.entity_count}</p>
                    </div>

                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
                      <span className="text-slate-400 uppercase text-[10px]">Issues Flagged</span>
                      <p className="text-lg font-bold text-amber-400">{result.issues_found?.length || 0}</p>
                    </div>

                    <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-1 col-span-2 sm:col-span-1">
                      <span className="text-slate-400 uppercase text-[10px]">Audit Timestamp</span>
                      <p className="text-xs font-bold text-indigo-300 truncate">
                        {new Date(result.timestamp || Date.now()).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>

                  {/* Issues Detail */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                      Detected Memory Issues ({result.issues_found?.length || 0})
                    </h3>
                    {result.issues_found && result.issues_found.length > 0 ? (
                      <StaggerContainer className="space-y-3">
                        {result.issues_found.map((issue, idx) => (
                          <StaggerItem key={idx}>
                            <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs space-y-2">
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-white text-sm">
                                  {issue.category}/{issue.name}
                                </span>
                                <span
                                  className={`px-2.5 py-0.5 rounded-md font-bold uppercase text-[10px] ${
                                    issue.severity === "contradiction"
                                      ? "bg-rose-950 text-rose-400 border border-rose-800"
                                      : issue.severity === "duplicate"
                                      ? "bg-amber-950 text-amber-400 border border-amber-800"
                                      : "bg-indigo-950 text-indigo-400 border border-indigo-800"
                                  }`}
                                >
                                  {issue.severity}
                                </span>
                              </div>
                              <p className="text-slate-300">{issue.detail}</p>
                            </div>
                          </StaggerItem>
                        ))}
                      </StaggerContainer>
                    ) : (
                      <div className="p-6 text-center text-emerald-400 text-sm bg-emerald-950/30 rounded-2xl border border-emerald-800/60">
                        <CheckCircle2 className="w-8 h-8 mx-auto mb-2" />
                        Memory database clean! All entity relationships are consistent.
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                /* Failure Error Display */
                <div className="p-6 rounded-2xl bg-rose-950/40 border border-rose-800 text-rose-300 space-y-2">
                  <div className="flex items-center gap-2 font-bold">
                    <AlertCircle className="w-5 h-5" />
                    Audit Execution Error
                  </div>
                  <p className="text-sm">{result.message || result.error}</p>
                </div>
              )}
            </div>
          </FadeInUp>
        )}
      </div>
    </PageTransition>
  );
}
