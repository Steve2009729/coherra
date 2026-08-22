"use client";

import { usePrivy } from "@privy-io/react-auth";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck, Wallet, LogIn, LogOut, LayoutDashboard, FileText, Activity } from "lucide-react";

export function Navbar() {
  const pathname = usePathname();
  const { authenticated, ready, user, login, logout } = usePrivy();

  const primaryWallet = user?.wallet?.address;
  const userEmail = user?.email?.address;

  const truncateAddr = (addr: string) =>
    `${addr.slice(0, 6)}...${addr.slice(-4)}`;

  return (
    <header className="sticky top-0 z-50 backdrop-blur-md bg-slate-950/80 border-b border-slate-800/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand Logo */}
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-purple-600 to-pink-500 p-0.5 shadow-lg shadow-indigo-500/20 group-hover:shadow-indigo-500/40 transition-all">
            <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
              <ShieldCheck className="w-5 h-5 text-indigo-400 group-hover:scale-110 transition-transform" />
            </div>
          </div>
          <div className="flex flex-col">
            <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-indigo-300 bg-clip-text text-transparent">
              Coherra
            </span>
            <span className="text-[10px] uppercase font-mono tracking-widest text-indigo-400 font-semibold -mt-1">
              Memory Audit
            </span>
          </div>
        </Link>

        {/* Navigation Links */}
        <nav className="hidden md:flex items-center gap-1 bg-slate-900/60 p-1.5 rounded-full border border-slate-800/60">
          <Link
            href="/"
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all ${
              pathname === "/"
                ? "bg-indigo-600/90 text-white shadow-md shadow-indigo-600/20"
                : "text-slate-400 hover:text-white hover:bg-slate-800/50"
            }`}
          >
            Home
          </Link>
          <Link
            href="/dashboard"
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all flex items-center gap-1.5 ${
              pathname === "/dashboard"
                ? "bg-indigo-600/90 text-white shadow-md shadow-indigo-600/20"
                : "text-slate-400 hover:text-white hover:bg-slate-800/50"
            }`}
          >
            <LayoutDashboard className="w-4 h-4" />
            Dashboard
          </Link>
          <Link
            href="/audit"
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all flex items-center gap-1.5 ${
              pathname === "/audit"
                ? "bg-indigo-600/90 text-white shadow-md shadow-indigo-600/20"
                : "text-slate-400 hover:text-white hover:bg-slate-800/50"
            }`}
          >
            <Activity className="w-4 h-4" />
            Audit
          </Link>
          <Link
            href="/docs"
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all flex items-center gap-1.5 ${
              pathname === "/docs"
                ? "bg-indigo-600/90 text-white shadow-md shadow-indigo-600/20"
                : "text-slate-400 hover:text-white hover:bg-slate-800/50"
            }`}
          >
            <FileText className="w-4 h-4" />
            Docs
          </Link>
        </nav>

        {/* Auth / Account Controls */}
        <div className="flex items-center gap-3">
          {ready && authenticated ? (
            <div className="flex items-center gap-2">
              {primaryWallet && (
                <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs font-mono text-indigo-300">
                  <Wallet className="w-3.5 h-3.5 text-indigo-400" />
                  {truncateAddr(primaryWallet)}
                </div>
              )}
              <button
                onClick={logout}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-200 hover:text-white text-sm font-medium transition-all border border-slate-700/50"
              >
                <LogOut className="w-4 h-4" />
                Disconnect
              </button>
            </div>
          ) : (
            <button
              onClick={login}
              className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white text-sm font-medium shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 transition-all"
            >
              <LogIn className="w-4 h-4" />
              Sign In
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
