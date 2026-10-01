"use client";

import { usePrivy, useWallets } from "@privy-io/react-auth";
import { useState, useRef, useEffect } from "react";
import { encodeFunctionData, parseUnits } from "viem";
import {
  Send,
  Sparkles,
  Bot,
  User,
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  RefreshCw,
  Zap,
  CreditCard,
  ChevronDown,
  Layers,
  Database,
  ExternalLink,
  Info,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
import { sendChatMessage, ChatMessage, ChatResponse } from "@/lib/api";

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

interface ChatPanelProps {
  tenantId?: string;
  defaultOpen?: boolean;
}

const MODELS = [
  { id: "gemini", name: "Gemini Flash-Lite 2.5", provider: "Google", badge: "Fast & Cheap", color: "from-blue-500 to-cyan-500" },
  { id: "openai", name: "ChatGPT (Luna / 4o-mini)", provider: "OpenAI", badge: "Balanced", color: "from-emerald-500 to-teal-500" },
  { id: "grok", name: "Grok 4.3", provider: "xAI", badge: "Real-time", color: "from-zinc-400 to-slate-200" },
  { id: "claude", name: "Claude Haiku 4.5", provider: "Anthropic", badge: "Precise", color: "from-amber-500 to-orange-500" },
];

export function ChatPanel({ tenantId, defaultOpen = true }: ChatPanelProps) {
  const { authenticated, user, login, connectWallet } = usePrivy();
  const { wallets } = useWallets();

  const activeTenantId = tenantId || user?.id || "default_user";
  const primaryWallet = user?.wallet?.address;

  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [isMinimized, setIsMinimized] = useState(false);
  const [selectedModel, setSelectedModel] = useState(MODELS[0].id);
  const [inputMessage, setInputMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [paying, setPaying] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState<string | null>(null);

  const [messages, setMessages] = useState<
    Array<{
      id: string;
      role: "user" | "assistant" | "system";
      content: string;
      model?: string;
      toolCalls?: Array<any>;
      requiresPayment?: boolean;
      challenge?: any;
    }>
  >([
    {
      id: "welcome",
      role: "assistant",
      content:
        "👋 Welcome to Coherra Hosted Memory! I can store your preferences, project details, and rules in isolated storage, or audit and heal any conflicts.",
      model: MODELS[0].id,
    },
  ]);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async (customMessage?: string, paymentProof?: string) => {
    const textToSend = customMessage !== undefined ? customMessage : inputMessage.trim();
    if (!textToSend && !paymentProof) return;

    if (!paymentProof) {
      const userMsgId = `user_${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", content: textToSend },
      ]);
      setInputMessage("");
    }

    setLoading(true);

    try {
      const historyPayload: ChatMessage[] = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.content }));

      const res = await sendChatMessage({
        tenantId: activeTenantId,
        model: selectedModel,
        message: textToSend || "Proceed with payment verification",
        history: historyPayload,
        paymentProof,
      });

      const assistantMsgId = `assistant_${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          role: "assistant",
          content: res.message || (res.ok ? "Done." : "An error occurred."),
          model: res.model || selectedModel,
          toolCalls: res.tool_calls,
          requiresPayment: res.requires_payment,
          challenge: res.challenge,
        },
      ]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: `error_${Date.now()}`,
          role: "assistant",
          content: `⚠️ Error: ${err.message || "Failed to reach chat server."}`,
          model: selectedModel,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  /**
   * Inline on-chain x402 payment handling for chat-triggered audits.
   */
  const handleInlinePay = async (challenge: any) => {
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

    const payeeAddress =
      challenge?.accepts?.[0]?.payee || "0x1BFAe4EE12c8f2bF17B8EEb8Ea0BcB32AdbB240B";
    const usdcContract =
      challenge?.accepts?.[0]?.contract_address ||
      "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
    const amountStr = challenge?.accepts?.[0]?.amount || "0.015";

    setPaying(true);
    setPaymentStatus("Preparing on-chain USDC transfer on Base mainnet...");

    try {
      const amountUnits = parseUnits(amountStr, 6);
      const calldata = encodeFunctionData({
        abi: erc20Abi,
        functionName: "transfer",
        args: [payeeAddress as `0x${string}`, amountUnits],
      });

      setPaymentStatus("Requesting wallet signature...");
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

      setPaymentStatus(`Payment broadcasted: ${realTxHash.slice(0, 10)}... Retrying audit...`);

      // Automatically rerun with the real payment proof
      await handleSend("Audit my memory", realTxHash);
    } catch (err: any) {
      console.error("Payment failed:", err);
      setPaymentStatus(`Payment Failed: ${err.message || err}`);
    } finally {
      setPaying(false);
    }
  };

  const currentModelMeta = MODELS.find((m) => m.id === selectedModel) || MODELS[0];

  return (
    <div className="w-full bg-slate-900/90 border border-slate-800 rounded-3xl overflow-hidden shadow-2xl backdrop-blur-xl flex flex-col transition-all duration-300">
      {/* Header Bar */}
      <div className="px-6 py-4 border-b border-slate-800 bg-slate-950/60 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-2xl bg-gradient-to-tr ${currentModelMeta.color} flex items-center justify-center text-white shadow-lg`}>
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-white">Coherra Multi-Model Memory Chat</h2>
              <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                Track 1
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Isolated tenant storage • 4 LLM providers • x402 audit tools
            </p>
          </div>
        </div>

        {/* Model Picker */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="appearance-none bg-slate-900 border border-slate-700 hover:border-slate-600 text-xs text-slate-200 font-medium py-2 pl-3 pr-8 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all cursor-pointer"
            >
              {MODELS.map((m) => (
                <option key={m.id} value={m.id} className="bg-slate-900 text-white">
                  {m.name} ({m.provider})
                </option>
              ))}
            </select>
            <ChevronDown className="w-4 h-4 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 p-6 space-y-4 overflow-y-auto max-h-[480px] min-h-[360px]">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex items-start gap-3 ${m.role === "user" ? "flex-row-reverse" : "flex-row"}`}
          >
            <div
              className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
                m.role === "user"
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-800 border border-slate-700 text-indigo-400"
              }`}
            >
              {m.role === "user" ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
            </div>

            <div
              className={`max-w-[85%] rounded-2xl p-4 text-sm space-y-3 ${
                m.role === "user"
                  ? "bg-indigo-600 text-white shadow-md rounded-tr-none"
                  : "bg-slate-950/70 border border-slate-800 text-slate-200 rounded-tl-none"
              }`}
            >
              <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>

              {/* Tool Execution Badges */}
              {m.toolCalls && m.toolCalls.length > 0 && (
                <div className="space-y-2 pt-2 border-t border-slate-800/80">
                  <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Database className="w-3.5 h-3.5 text-indigo-400" />
                    Tools Executed ({m.toolCalls.length})
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {m.toolCalls.map((tc, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 text-xs font-mono text-indigo-300"
                      >
                        <Zap className="w-3 h-3 text-amber-400" />
                        {tc.name}
                        {tc.result?.status && (
                          <span className="text-[10px] text-emerald-400 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-800/40">
                            {tc.result.status}
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Inline x402 Payment Challenge Card */}
              {m.requiresPayment && m.challenge && (
                <div className="mt-3 p-4 rounded-2xl bg-amber-950/40 border border-amber-800/70 space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-amber-300 font-bold text-xs uppercase tracking-wider">
                      <ShieldAlert className="w-4 h-4 text-amber-400" />
                      x402 Payment Required
                    </div>
                    <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-[11px] font-bold border border-amber-500/40">
                      0.015 USDC • Base
                    </span>
                  </div>

                  <p className="text-xs text-amber-200/90 leading-normal">
                    This audit inspects all stored facts for contradictions, duplicates, and staleness. A 0.015 USDC micropayment on Base mainnet is required.
                  </p>

                  {paymentStatus && (
                    <div className="text-xs font-mono text-amber-300/80 bg-amber-950/80 p-2 rounded-lg border border-amber-900">
                      {paymentStatus}
                    </div>
                  )}

                  <div className="flex flex-wrap gap-2 pt-1">
                    <button
                      onClick={() => handleInlinePay(m.challenge)}
                      disabled={paying}
                      className="px-4 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white text-xs font-bold transition-all shadow-md flex items-center gap-2 disabled:opacity-50 cursor-pointer"
                    >
                      {paying ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          Processing Transfer...
                        </>
                      ) : (
                        <>
                          <CreditCard className="w-3.5 h-3.5" />
                          Pay 0.015 USDC with Privy Wallet
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Prompt Box */}
      <div className="p-4 border-t border-slate-800 bg-slate-950/70 space-y-3">
        {/* Quick Suggestion Chips */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs text-slate-400">
          <span className="shrink-0 text-[11px] text-slate-500 font-medium">Try:</span>
          <button
            onClick={() => handleSend("Remember that my editor is VSCode and preferred language is TypeScript")}
            className="shrink-0 px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-white transition-all text-xs"
          >
            💾 "Remember preference..."
          </button>
          <button
            onClick={() => handleSend("Audit my memory")}
            className="shrink-0 px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-white transition-all text-xs"
          >
            🛡️ "Audit my memory"
          </button>
          <button
            onClick={() => handleSend("Show my memory issues")}
            className="shrink-0 px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-white transition-all text-xs"
          >
            🔍 "Show issues"
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            placeholder={`Message ${currentModelMeta.name}... (e.g. "Remember that project deadline is Oct 15")`}
            disabled={loading}
            className="flex-1 bg-slate-900 border border-slate-800 focus:border-indigo-500 rounded-2xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 transition-all"
          />

          <button
            type="submit"
            disabled={loading || !inputMessage.trim()}
            className="p-3 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-all shadow-lg shadow-indigo-500/20 disabled:opacity-40 disabled:hover:bg-indigo-600 cursor-pointer shrink-0"
          >
            {loading ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
          </button>
        </form>
      </div>
    </div>
  );
}
