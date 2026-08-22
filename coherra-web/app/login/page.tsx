"use client";

import { usePrivy } from "@privy-io/react-auth";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ShieldCheck, LogIn, Sparkles, Wallet, Mail, ArrowRight } from "lucide-react";
import { PageTransition } from "@/components/motion/PageTransition";
import { FadeInUp } from "@/components/motion/FadeInUp";

export default function LoginPage() {
  const { ready, authenticated, login } = usePrivy();
  const router = useRouter();

  useEffect(() => {
    if (ready && authenticated) {
      router.push("/dashboard");
    }
  }, [ready, authenticated, router]);

  return (
    <PageTransition>
      <div className="min-h-[80vh] flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <FadeInUp>
            <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 shadow-2xl backdrop-blur-xl space-y-8 text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-indigo-600 to-purple-600 p-0.5 mx-auto shadow-xl shadow-indigo-500/20">
                <div className="w-full h-full bg-slate-950 rounded-[14px] flex items-center justify-center">
                  <ShieldCheck className="w-8 h-8 text-indigo-400" />
                </div>
              </div>

              <div className="space-y-2">
                <h1 className="text-2xl font-bold text-white tracking-tight">
                  Welcome to Coherra
                </h1>
                <p className="text-sm text-slate-400">
                  Sign in with Email, Google, or Web3 Wallet to manage your memory audits and view past history.
                </p>
              </div>

              <div className="space-y-3 pt-2">
                <button
                  onClick={login}
                  disabled={!ready}
                  className="w-full py-3.5 px-6 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-semibold shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 transition-all flex items-center justify-center gap-2 group disabled:opacity-50"
                >
                  <LogIn className="w-5 h-5" />
                  Sign In with Privy
                  <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                </button>
              </div>

              <div className="pt-4 border-t border-slate-800/80 flex items-center justify-center gap-6 text-xs text-slate-400">
                <span className="flex items-center gap-1.5">
                  <Mail className="w-3.5 h-3.5 text-indigo-400" /> Passwordless
                </span>
                <span className="flex items-center gap-1.5">
                  <Wallet className="w-3.5 h-3.5 text-purple-400" /> Embedded Wallet
                </span>
                <span className="flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-pink-400" /> Base Mainnet
                </span>
              </div>
            </div>
          </FadeInUp>
        </div>
      </div>
    </PageTransition>
  );
}
