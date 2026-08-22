"use client";

import { useState } from "react";
import { FileText, Cpu, ShieldCheck, Zap, Lock, Terminal, Copy, Check, Code2 } from "lucide-react";
import { PageTransition } from "@/components/motion/PageTransition";
import { FadeInUp } from "@/components/motion/FadeInUp";
import { StaggerContainer, StaggerItem } from "@/components/motion/StaggerContainer";

export default function DocsPage() {
  const [copied, setCopied] = useState<string | null>(null);

  const copyToClipboard = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopied(id);
    setTimeout(() => setCopied(null), 2000);
  };

  const mcpConfigSnippet = `{
  "mcpServers": {
    "coherra": {
      "command": "python",
      "args": ["-m", "coherra"],
      "env": {
        "SIBYL_MEMORY_DB": "~/.sibyl-memory/memory.db"
      }
    }
  }
}`;

  const httpApiSnippet = `POST /audit HTTP/1.1
Host: 127.0.0.1:8080
Content-Type: application/json
X-Payment: 0x4a9b2c7e1f8d3a6e9f5b2c8d1e4a7b3c6f9e2d5a8b1c4e7f3a6b9c2d5e8f1a4

{
  "credentials": {
    "db_path": "~/.sibyl-memory/memory.db"
  },
  "privy_user_id": "privy:did:12345"
}`;

  return (
    <PageTransition>
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-12">
        <FadeInUp>
          <div className="space-y-3 text-center sm:text-left border-b border-slate-800 pb-6">
            <h1 className="text-3xl font-extrabold text-white flex items-center justify-center sm:justify-start gap-3">
              <FileText className="w-8 h-8 text-indigo-400" />
              Coherra Documentation
            </h1>
            <p className="text-slate-400 text-sm">
              Complete reference for CLI commands, Model Context Protocol (MCP) server integration, and x402 HTTP API.
            </p>
          </div>
        </FadeInUp>

        <StaggerContainer className="space-y-8">
          {/* 1. Overview */}
          <StaggerItem>
            <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 space-y-4">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <Cpu className="w-5 h-5 text-indigo-400" />
                1. System Overview
              </h2>
              <p className="text-slate-300 text-sm leading-relaxed">
                Coherra audits and repairs memory drift in Sibyl Memory databases. It categorizes entities across `preference`, `people`, `projects`, and `facts`, detects contradictions via token overlap and Jaccard similarity, and safe-repairs duplicate keys and stale entries.
              </p>
            </div>
          </StaggerItem>

          {/* 2. CLI Commands */}
          <StaggerItem>
            <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 space-y-4">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <Terminal className="w-5 h-5 text-purple-400" />
                2. CLI Reference
              </h2>
              <div className="bg-slate-950 p-5 rounded-2xl border border-slate-800 font-mono text-xs text-slate-300 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-slate-900">
                  <span className="text-indigo-400 font-bold">coherra scan</span>
                  <span className="text-slate-400">Run a full memory health scan &amp; compute health score</span>
                </div>
                <div className="flex items-center justify-between pb-2 border-b border-slate-900">
                  <span className="text-indigo-400 font-bold">coherra issues</span>
                  <span className="text-slate-400">List all detected contradictions, duplicates, and stale facts</span>
                </div>
                <div className="flex items-center justify-between pb-2 border-b border-slate-900">
                  <span className="text-indigo-400 font-bold">coherra fix --all</span>
                  <span className="text-slate-400">Apply non-destructive safe repairs to duplicates and stale entries</span>
                </div>
                <div className="flex items-center justify-between pb-2 border-b border-slate-900">
                  <span className="text-indigo-400 font-bold">coherra onboard --import &lt;file.json&gt;</span>
                  <span className="text-slate-400">Import &amp; Gemini-categorize legacy memory exports</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-indigo-400 font-bold">coherra serve [--port 8080]</span>
                  <span className="text-slate-400">Launch x402 HTTP server with Base mainnet micropayment gate</span>
                </div>
              </div>
            </div>
          </StaggerItem>

          {/* 3. MCP Server Configuration */}
          <StaggerItem>
            <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Code2 className="w-5 h-5 text-pink-400" />
                  3. MCP Server Integration
                </h2>
                <button
                  onClick={() => copyToClipboard(mcpConfigSnippet, "mcp")}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-mono text-indigo-300 flex items-center gap-1.5 transition-all"
                >
                  {copied === "mcp" ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied === "mcp" ? "Copied" : "Copy JSON"}
                </button>
              </div>
              <p className="text-slate-300 text-sm">
                Add Coherra as a native MCP server tool to your Claude Desktop or Antigravity AI assistant:
              </p>
              <pre className="bg-slate-950 p-5 rounded-2xl border border-slate-800 font-mono text-xs text-indigo-300 overflow-x-auto">
                {mcpConfigSnippet}
              </pre>
            </div>
          </StaggerItem>

          {/* 4. x402 HTTP API */}
          <StaggerItem>
            <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Lock className="w-5 h-5 text-emerald-400" />
                  4. x402 HTTP API Reference
                </h2>
                <button
                  onClick={() => copyToClipboard(httpApiSnippet, "http")}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-mono text-indigo-300 flex items-center gap-1.5 transition-all"
                >
                  {copied === "http" ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied === "http" ? "Copied" : "Copy HTTP"}
                </button>
              </div>
              <p className="text-slate-300 text-sm leading-relaxed">
                Requests to <code className="text-indigo-400 bg-slate-950 px-2 py-0.5 rounded">POST /audit</code> without an <code className="text-amber-400 bg-slate-950 px-2 py-0.5 rounded">X-Payment</code> header return HTTP 402 with Base mainnet (Chain ID 8453) USDC payment instructions.
              </p>
              <pre className="bg-slate-950 p-5 rounded-2xl border border-slate-800 font-mono text-xs text-emerald-300 overflow-x-auto">
                {httpApiSnippet}
              </pre>
            </div>
          </StaggerItem>
        </StaggerContainer>
      </div>
    </PageTransition>
  );
}
