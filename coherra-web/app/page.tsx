"use client";

import Link from "next/link";
import {
  ShieldCheck,
  Cpu,
  ArrowRight,
  Activity,
  Zap,
  Lock,
  Database,
  CheckCircle2,
  AlertTriangle,
  Layers,
  Sparkles,
  Terminal,
} from "lucide-react";
import { FadeInUp } from "@/components/motion/FadeInUp";
import { StaggerContainer, StaggerItem } from "@/components/motion/StaggerContainer";
import { PageTransition } from "@/components/motion/PageTransition";

export default function HomePage() {
  return (
    <PageTransition>
      <div className="relative overflow-hidden pt-12 pb-24 space-y-32">
        {/* Background Ambient Glows */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-7xl h-96 bg-gradient-to-b from-indigo-950/40 via-purple-950/20 to-transparent blur-3xl -z-10 pointer-events-none" />
        <div className="absolute top-1/4 right-10 w-96 h-96 bg-indigo-600/10 rounded-full blur-3xl -z-10 pointer-events-none animate-pulse" />
        <div className="absolute top-1/3 left-10 w-96 h-96 bg-purple-600/10 rounded-full blur-3xl -z-10 pointer-events-none animate-pulse" style={{ animationDelay: "2s" }} />

        {/* Hero Section */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-4xl mx-auto space-y-8 pt-8">
            <FadeInUp delay={0.1}>
              <div className="inline-flex items-center gap-2.5 px-4 py-2 rounded-full bg-slate-900/90 border border-indigo-500/40 text-indigo-300 text-xs font-semibold tracking-wide uppercase shadow-lg shadow-indigo-950/50 relative group">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                <Cpu className="w-3.5 h-3.5 text-indigo-400" />
                <span>Base Mainnet x402 Micropayments</span>
                <span className="px-2 py-0.5 rounded-md bg-indigo-600/30 text-[10px] font-mono font-bold text-indigo-200">
                  0.015 USDC / audit
                </span>
              </div>
            </FadeInUp>

            <FadeInUp delay={0.2}>
              <h1 className="text-4xl sm:text-7xl font-extrabold tracking-tight text-white leading-tight">
                Continuous Drift Audit &amp; Safe Repair for{" "}
                <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                  AI Memory Stores
                </span>
              </h1>
            </FadeInUp>

            <FadeInUp delay={0.3}>
              <p className="text-lg sm:text-xl text-slate-300 max-w-2xl mx-auto leading-relaxed font-normal">
                Detect contradictory facts, prune duplicate keys, and refresh stale entities in Sibyl Memory before model output quality degrades.
              </p>
            </FadeInUp>

            <FadeInUp delay={0.4}>
              <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-4">
                <Link
                  href="/audit"
                  className="w-full sm:w-auto px-8 py-4 rounded-2xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-semibold shadow-xl shadow-indigo-600/30 hover:shadow-indigo-600/50 flex items-center justify-center gap-2 transition-all transform hover:-translate-y-0.5 text-base"
                >
                  <Activity className="w-5 h-5" />
                  Launch Live Audit Flow
                  <ArrowRight className="w-4 h-4 ml-1" />
                </Link>
                <Link
                  href="/docs"
                  className="w-full sm:w-auto px-8 py-4 rounded-2xl bg-slate-900/90 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 text-slate-200 font-semibold flex items-center justify-center gap-2 transition-all text-base"
                >
                  <Terminal className="w-5 h-5 text-purple-400" />
                  View CLI &amp; MCP Docs
                </Link>
              </div>
            </FadeInUp>
          </div>
        </div>

        {/* Problem vs Solution Section */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <FadeInUp>
            <div className="p-8 sm:p-12 rounded-3xl bg-slate-900/40 border border-slate-800/80 backdrop-blur-xl grid grid-cols-1 md:grid-cols-2 gap-8">
              <div className="space-y-4">
                <div className="w-10 h-10 rounded-xl bg-rose-950/80 border border-rose-800/60 flex items-center justify-center text-rose-400">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <h2 className="text-2xl font-bold text-white">The Memory Drift Problem</h2>
                <p className="text-slate-400 text-sm leading-relaxed">
                  As AI assistants converse over months, memory stores accumulate conflicting facts, duplicated entity keys, and outdated preferences. Standard retrieval injects contradictory context directly into prompts, leading to agent hallucinations.
                </p>
              </div>

              <div className="space-y-4">
                <div className="w-10 h-10 rounded-xl bg-emerald-950/80 border border-emerald-800/60 flex items-center justify-center text-emerald-400">
                  <CheckCircle2 className="w-5 h-5" />
                </div>
                <h2 className="text-2xl font-bold text-white">The Coherra Solution</h2>
                <p className="text-slate-400 text-sm leading-relaxed">
                  Coherra runs multi-pass scans to flag contradictions for human review while auto-repairing stale and duplicate records. Payment is handled on-chain via light x402 Base HTTP headers.
                </p>
              </div>
            </div>
          </FadeInUp>
        </div>

        {/* Feature Grid with Staggered Cascades */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <FadeInUp>
            <div className="text-center space-y-3 mb-16">
              <h2 className="text-3xl sm:text-4xl font-bold text-white">
                Engineered for Autonomous Memory Maintenance
              </h2>
              <p className="text-slate-400 max-w-xl mx-auto text-sm">
                Four core modules designed for agentic workflows, MCP tools, and HTTP micro-services.
              </p>
            </div>
          </FadeInUp>

          <StaggerContainer className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <StaggerItem>
              <div className="p-8 rounded-2xl bg-slate-900/60 border border-slate-800 backdrop-blur-sm hover:border-indigo-500/50 transition-all hover:shadow-xl hover:shadow-indigo-500/10 group h-full flex flex-col justify-between">
                <div className="space-y-4">
                  <div className="w-12 h-12 rounded-xl bg-indigo-950 border border-indigo-800/60 flex items-center justify-center group-hover:scale-110 transition-transform">
                    <Database className="w-6 h-6 text-indigo-400" />
                  </div>
                  <h3 className="text-lg font-bold text-white">Sibyl-Native Storage</h3>
                  <p className="text-slate-400 text-xs leading-relaxed">
                    Direct integration with Sibyl Memory schema. Inspects entity categories (`preference`, `people`, `projects`, `facts`).
                  </p>
                </div>
              </div>
            </StaggerItem>

            <StaggerItem>
              <div className="p-8 rounded-2xl bg-slate-900/60 border border-slate-800 backdrop-blur-sm hover:border-purple-500/50 transition-all hover:shadow-xl hover:shadow-purple-500/10 group h-full flex flex-col justify-between">
                <div className="space-y-4">
                  <div className="w-12 h-12 rounded-xl bg-purple-950 border border-purple-800/60 flex items-center justify-center group-hover:scale-110 transition-transform">
                    <ShieldCheck className="w-6 h-6 text-purple-400" />
                  </div>
                  <h3 className="text-lg font-bold text-white">Multi-Severity Scans</h3>
                  <p className="text-slate-400 text-xs leading-relaxed">
                    Calculates health score (0-100), categorizes issues into Contradictions, Duplicates, and Stale entries.
                  </p>
                </div>
              </div>
            </StaggerItem>

            <StaggerItem>
              <div className="p-8 rounded-2xl bg-slate-900/60 border border-slate-800 backdrop-blur-sm hover:border-pink-500/50 transition-all hover:shadow-xl hover:shadow-pink-500/10 group h-full flex flex-col justify-between">
                <div className="space-y-4">
                  <div className="w-12 h-12 rounded-xl bg-pink-950 border border-pink-800/60 flex items-center justify-center group-hover:scale-110 transition-transform">
                    <Lock className="w-6 h-6 text-pink-400" />
                  </div>
                  <h3 className="text-lg font-bold text-white">x402 Payment Gate</h3>
                  <p className="text-slate-400 text-xs leading-relaxed">
                    Base mainnet USDC payment challenge (0.015 USDC). Instant RPC verification with replay protection.
                  </p>
                </div>
              </div>
            </StaggerItem>

            <StaggerItem>
              <div className="p-8 rounded-2xl bg-slate-900/60 border border-slate-800 backdrop-blur-sm hover:border-emerald-500/50 transition-all hover:shadow-xl hover:shadow-emerald-500/10 group h-full flex flex-col justify-between">
                <div className="space-y-4">
                  <div className="w-12 h-12 rounded-xl bg-emerald-950 border border-emerald-800/60 flex items-center justify-center group-hover:scale-110 transition-transform">
                    <Layers className="w-6 h-6 text-emerald-400" />
                  </div>
                  <h3 className="text-lg font-bold text-white">Onboarding &amp; Migration</h3>
                  <p className="text-slate-400 text-xs leading-relaxed">
                    Imports generic JSON exports, uses Gemini to categorize entities, and scopes initial audit/repair pass.
                  </p>
                </div>
              </div>
            </StaggerItem>
          </StaggerContainer>
        </div>

        {/* CTA Section */}
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <FadeInUp>
            <div className="p-10 sm:p-16 rounded-3xl bg-gradient-to-r from-indigo-900/40 via-purple-900/40 to-slate-900 border border-indigo-500/30 text-center space-y-6 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-64 h-64 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
              <h2 className="text-3xl sm:text-4xl font-extrabold text-white">
                Ready to Repair Your Agent Memory?
              </h2>
              <p className="text-slate-300 max-w-xl mx-auto text-sm sm:text-base">
                Sign in with Privy, connect your Web3 wallet, and trigger an automated audit against your Sibyl Memory database.
              </p>
              <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-4">
                <Link
                  href="/audit"
                  className="w-full sm:w-auto px-8 py-4 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-semibold shadow-xl shadow-indigo-600/30 transition-all flex items-center justify-center gap-2"
                >
                  <Sparkles className="w-5 h-5 text-amber-300" />
                  Start Auditing Now
                </Link>
              </div>
            </div>
          </FadeInUp>
        </div>
      </div>
    </PageTransition>
  );
}
