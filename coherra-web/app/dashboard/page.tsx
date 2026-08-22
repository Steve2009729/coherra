"use client";

import { usePrivy } from "@privy-io/react-auth";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  User,
  Wallet,
  Mail,
  History,
  Activity,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
  ShieldCheck,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { PageTransition } from "@/components/motion/PageTransition";
import { FadeInUp } from "@/components/motion/FadeInUp";
import { StaggerContainer, StaggerItem } from "@/components/motion/StaggerContainer";
import { fetchAuditHistory, linkWallet, AuditHistoryRecord } from "@/lib/api";

export default function DashboardPage() {
  const { ready, authenticated, user, connectWallet } = usePrivy();
  const router = useRouter();

  const [history, setHistory] = useState<AuditHistoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [linking, setLinking] = useState(false);
  const [linkedStatus, setLinkedStatus] = useState<string | null>(null);

  const privyUserId = user?.id;
  const userEmail = user?.email?.address;
  const primaryWallet = user?.wallet?.address;

  // 1. Auth Guard Protection
  useEffect(() => {
    if (ready && !authenticated) {
      router.push("/login");
    }
  }, [ready, authenticated, router]);

  // 2. Link Wallet & Fetch Audit History
  useEffect(() => {
    if (ready && authenticated && privyUserId) {
      if (primaryWallet) {
        setLinking(true);
        linkWallet(privyUserId, primaryWallet, userEmail)
          .then((res) => {
            if (res.ok) setLinkedStatus("Wallet linked on backend");
          })
          .finally(() => setLinking(false));
      }

      setLoading(true);
      fetchAuditHistory(privyUserId)
        .then((res) => {
          if (res.ok && res.history) {
            setHistory(res.history);
          }
        })
        .finally(() => setLoading(false));
    }
  }, [ready, authenticated, privyUserId, primaryWallet, userEmail]);

  if (!ready || !authenticated) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="flex items-center gap-3 text-slate-400">
          <RefreshCw className="w-5 h-5 animate-spin text-indigo-400" />
          <span>Verifying authentication...</span>
        </div>
      </div>
    );
  }

  // Format history for Recharts (oldest to newest for left-to-right trend)
  const chartData = [...history].reverse().map((item, idx) => ({
    run: `#${idx + 1}`,
    score: item.health_score,
    date: new Date(item.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    issues: item.issues_found.length,
  }));

  return (
    <PageTransition>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-10">
        {/* Header */}
        <FadeInUp>
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800">
            <div>
              <h1 className="text-3xl font-extrabold text-white flex items-center gap-3">
                <LayoutDashboard className="w-8 h-8 text-indigo-400" />
                User Dashboard
              </h1>
              <p className="text-slate-400 text-sm mt-1">
                Manage your authenticated account, linked wallets, and view health score trends over time.
              </p>
            </div>
            <button
              onClick={() => {
                if (privyUserId) {
                  setLoading(true);
                  fetchAuditHistory(privyUserId).then((res) => {
                    if (res.history) setHistory(res.history);
                    setLoading(false);
                  });
                }
              }}
              className="self-start md:self-auto px-4 py-2 rounded-xl bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-300 hover:text-white text-sm font-medium transition-all flex items-center gap-2"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin text-indigo-400" : ""}`} />
              Refresh History
            </button>
          </div>
        </FadeInUp>

        {/* Profile & Wallet Details */}
        <FadeInUp delay={0.1}>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="p-6 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                <User className="w-4 h-4 text-indigo-400" />
                Privy DID
              </div>
              <p className="text-sm font-mono text-white truncate font-medium">
                {privyUserId}
              </p>
            </div>

            <div className="p-6 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                <Mail className="w-4 h-4 text-purple-400" />
                Email Address
              </div>
              <p className="text-sm font-medium text-white truncate">
                {userEmail || "No email connected"}
              </p>
            </div>

            <div className="p-6 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                  <Wallet className="w-4 h-4 text-pink-400" />
                  Connected Wallet
                </div>
                {!primaryWallet && (
                  <button
                    onClick={connectWallet}
                    className="text-xs font-semibold text-indigo-400 hover:text-indigo-300 underline"
                  >
                    Connect
                  </button>
                )}
              </div>
              <p className="text-sm font-mono text-white truncate font-medium">
                {primaryWallet || "No wallet connected"}
              </p>
              {linkedStatus && (
                <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                  <CheckCircle2 className="w-3.5 h-3.5" /> {linkedStatus}
                </span>
              )}
            </div>
          </div>
        </FadeInUp>

        {/* Health Score Trend Chart Section */}
        {history.length > 0 && (
          <FadeInUp delay={0.15}>
            <div className="p-6 sm:p-8 rounded-3xl bg-slate-900/80 border border-slate-800 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-indigo-400" />
                  <h2 className="text-lg font-bold text-white">Memory Health Score Trend</h2>
                </div>
                <span className="text-xs text-slate-400 font-mono">
                  Latest Score: {history[0].health_score}/100
                </span>
              </div>

              <div className="h-64 w-full pt-4">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="scoreColor" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#6366f1" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#6366f1" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
                    <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} tickLine={false} />
                    <YAxis domain={[0, 100]} stroke="#94a3b8" fontSize={12} tickLine={false} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#0f172a",
                        borderColor: "#334155",
                        borderRadius: "12px",
                        color: "#fff",
                      }}
                      formatter={(val: any) => [`${val}/100`, "Health Score"]}
                    />
                    <Area
                      type="monotone"
                      dataKey="score"
                      stroke="#818cf8"
                      strokeWidth={3}
                      fillOpacity={1}
                      fill="url(#scoreColor)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </FadeInUp>
        )}

        {/* Audit History Section */}
        <div className="space-y-6">
          <FadeInUp delay={0.2}>
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <History className="w-5 h-5 text-indigo-400" />
                Audit Run History
              </h2>
              <span className="text-xs text-slate-400 font-mono">
                Total Runs: {history.length}
              </span>
            </div>
          </FadeInUp>

          {loading ? (
            <div className="p-12 text-center text-slate-400 bg-slate-900/40 rounded-2xl border border-slate-800">
              <RefreshCw className="w-6 h-6 animate-spin mx-auto text-indigo-400 mb-2" />
              Loading your audit history...
            </div>
          ) : history.length === 0 ? (
            <FadeInUp delay={0.3}>
              <div className="p-12 text-center space-y-4 bg-slate-900/40 rounded-2xl border border-slate-800">
                <ShieldCheck className="w-12 h-12 text-slate-600 mx-auto" />
                <h3 className="text-lg font-semibold text-white">No Audit History Found</h3>
                <p className="text-slate-400 text-sm max-w-md mx-auto">
                  You haven&apos;t run any memory audits yet. Trigger your first x402-gated audit to see persistent results here.
                </p>
                <a
                  href="/audit"
                  className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-sm transition-all"
                >
                  <Activity className="w-4 h-4" /> Run Audit Now
                </a>
              </div>
            </FadeInUp>
          ) : (
            <StaggerContainer className="space-y-4">
              {history.map((item) => (
                <StaggerItem key={item.id}>
                  <div className="p-6 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-slate-700 transition-all space-y-4">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800/60">
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg ${
                            item.health_score >= 80
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800/60"
                              : item.health_score >= 60
                              ? "bg-amber-950 text-amber-400 border border-amber-800/60"
                              : "bg-rose-950 text-rose-400 border border-rose-800/60"
                          }`}
                        >
                          {item.health_score}
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-white">
                            Health Score: {item.health_score}/100
                          </div>
                          <div className="text-xs text-slate-400 font-mono">
                            {new Date(item.created_at).toLocaleString()}
                          </div>
                        </div>
                      </div>

                      {item.payment_tx_hash && (
                        <a
                          href={`https://basescan.org/tx/${item.payment_tx_hash}`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-indigo-300 text-xs font-mono transition-all"
                        >
                          Tx: {item.payment_tx_hash.slice(0, 10)}...
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                    {/* Issues List */}
                    <div className="space-y-2">
                      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                        Issues Involving Memory ({item.issues_found.length})
                      </div>
                      {item.issues_found.length === 0 ? (
                        <div className="text-sm text-emerald-400 flex items-center gap-1.5">
                          <CheckCircle2 className="w-4 h-4" /> All memory facts clean!
                        </div>
                      ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {item.issues_found.slice(0, 4).map((issue, idx) => (
                            <div
                              key={idx}
                              className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/60 text-xs space-y-1"
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-semibold text-white">
                                  {issue.category}/{issue.name}
                                </span>
                                <span className="uppercase text-[10px] font-bold text-amber-400">
                                  {issue.severity}
                                </span>
                              </div>
                              <p className="text-slate-400 truncate">{issue.detail}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </StaggerItem>
              ))}
            </StaggerContainer>
          )}
        </div>
      </div>
    </PageTransition>
  );
}
