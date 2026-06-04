"use client";

import { useEffect, useState, useCallback } from "react";
import { buyShares, sellShares, getQuote, getPosition } from "@/lib/api";
import type { Market, PriceQuote, Position } from "@/lib/types";
import { getUserId } from "@/lib/user";

interface Props {
  market: Market;
  onTraded: () => void;
}

type Tab = "buy" | "sell";

export default function TradePanel({ market, onTraded }: Props) {
  const [tab, setTab] = useState<Tab>("buy");
  const [side, setSide] = useState<"yes" | "no">("yes");
  const [amount, setAmount] = useState("");
  const [quote, setQuote] = useState<PriceQuote | null>(null);
  const [position, setPosition] = useState<Position | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const userId = getUserId();

  const refreshPosition = useCallback(() => {
    if (!userId) return;
    getPosition(market.id, userId).then(setPosition).catch(() => null);
  }, [market.id, userId]);

  useEffect(() => { refreshPosition(); }, [refreshPosition]);

  // Debounced quote fetch
  useEffect(() => {
    setQuote(null);
    if (tab !== "buy" || !amount || isNaN(Number(amount)) || Number(amount) <= 0) return;
    const t = setTimeout(() => {
      getQuote(market.id, side, Number(amount)).then(setQuote).catch(() => setQuote(null));
    }, 350);
    return () => clearTimeout(t);
  }, [tab, side, amount, market.id]);

  async function submit() {
    if (!userId) { setError("Sign in to trade."); return; }
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      if (tab === "buy") {
        const t = await buyShares(market.id, side, Number(amount), userId);
        setSuccess(`Bought ${t.shares.toFixed(2)} ${side.toUpperCase()} shares`);
      } else {
        const t = await sellShares(market.id, side, Number(amount), userId);
        setSuccess(`Sold ${t.shares.toFixed(2)} ${side.toUpperCase()} shares for $${Math.abs(t.cost).toFixed(2)}`);
      }
      setAmount("");
      setQuote(null);
      refreshPosition();
      onTraded();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Trade failed.");
    } finally {
      setLoading(false);
    }
  }

  if (!userId) {
    return (
      <div className="card p-5 text-center text-sm text-muted">
        <a href="/login" className="text-indigo-400 hover:text-indigo-300 font-medium">Sign in</a>{" "}
        to trade on this market.
      </div>
    );
  }

  if (market.status !== "open") {
    return (
      <div className="card p-5 text-center text-sm text-muted">
        This market is {market.status}.
      </div>
    );
  }

  const yesPct = Math.round(market.current_price * 100);
  const noPct = 100 - yesPct;
  const ownedYes = position?.yes_shares ?? 0;
  const ownedNo = position?.no_shares ?? 0;

  return (
    <div className="card p-5 space-y-4">
      {/* Buy / Sell tabs */}
      <div className="flex rounded-lg overflow-hidden border border-surface-3 bg-surface-2 p-0.5 gap-0.5">
        {(["buy", "sell"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setAmount(""); setQuote(null); setError(null); setSuccess(null); }}
            className={`flex-1 py-1.5 rounded-md text-sm font-semibold transition-all ${
              tab === t ? "bg-surface text-gray-100 shadow-sm" : "text-muted hover:text-gray-300"
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* YES / NO selector */}
      <div className="flex gap-2">
        <button
          onClick={() => setSide("yes")}
          className={`flex-1 rounded-xl py-3 border-2 transition-all ${
            side === "yes"
              ? "bg-yes-dim border-yes text-yes"
              : "border-surface-3 bg-surface-2 text-muted hover:border-yes/40"
          }`}
        >
          <p className="text-[10px] uppercase tracking-widest mb-0.5 opacity-70">Yes</p>
          <p className="text-2xl font-bold tabular-nums">{yesPct}¢</p>
        </button>
        <button
          onClick={() => setSide("no")}
          className={`flex-1 rounded-xl py-3 border-2 transition-all ${
            side === "no"
              ? "bg-no-dim border-no text-no"
              : "border-surface-3 bg-surface-2 text-muted hover:border-no/40"
          }`}
        >
          <p className="text-[10px] uppercase tracking-widest mb-0.5 opacity-70">No</p>
          <p className="text-2xl font-bold tabular-nums">{noPct}¢</p>
        </button>
      </div>

      {/* Amount */}
      <div>
        <label className="label">
          {tab === "buy" ? "Amount ($)" : `Shares to sell`}
        </label>
        <div className="relative">
          {tab === "buy" && (
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted text-sm">$</span>
          )}
          <input
            type="number"
            min="0"
            step={tab === "buy" ? "1" : "0.01"}
            placeholder={tab === "buy" ? "0.00" : "0.00"}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className={`input ${tab === "buy" ? "pl-7" : ""}`}
          />
        </div>
        {tab === "sell" && (
          <p className="mt-1.5 text-[11px] text-muted">
            You own:{" "}
            <span className="text-yes">{ownedYes.toFixed(2)} YES</span>
            {" · "}
            <span className="text-no">{ownedNo.toFixed(2)} NO</span>
          </p>
        )}
      </div>

      {/* Quote summary */}
      {tab === "buy" && quote && Number(amount) > 0 && (
        <div className="rounded-xl bg-surface-2 border border-surface-3 divide-y divide-surface-3 text-sm overflow-hidden">
          <div className="flex justify-between px-4 py-2.5">
            <span className="text-muted">Shares</span>
            <span className="font-semibold tabular-nums">{quote.shares.toFixed(2)}</span>
          </div>
          <div className="flex justify-between px-4 py-2.5">
            <span className="text-muted">Avg price</span>
            <span className="font-semibold tabular-nums">{(quote.avg_price * 100).toFixed(1)}¢</span>
          </div>
          <div className="flex justify-between px-4 py-2.5">
            <span className="text-muted">Price impact</span>
            <span className={`font-semibold tabular-nums ${side === "yes" ? "text-yes" : "text-no"}`}>
              {(quote.price_before * 100).toFixed(1)}¢ → {(quote.price_after * 100).toFixed(1)}¢
            </span>
          </div>
          <div className="flex justify-between px-4 py-2.5 bg-surface-1">
            <span className="font-semibold text-gray-100">Total cost</span>
            <span className="font-bold text-gray-100 tabular-nums">${quote.cost.toFixed(2)}</span>
          </div>
        </div>
      )}

      {/* Potential return hint */}
      {tab === "buy" && quote && (
        <p className="text-[11px] text-muted text-center">
          Potential return if correct:{" "}
          <span className="text-gray-300 font-medium">
            ${quote.shares.toFixed(2)} ({((quote.shares / quote.cost - 1) * 100).toFixed(0)}% profit)
          </span>
        </p>
      )}

      {error && (
        <div className="rounded-lg bg-no-dim border border-no/30 px-4 py-2.5 text-sm text-no">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg bg-yes-dim border border-yes/30 px-4 py-2.5 text-sm text-yes">
          {success}
        </div>
      )}

      <button
        onClick={submit}
        disabled={loading || !amount || Number(amount) <= 0}
        className={`w-full py-3 rounded-xl text-sm font-bold tracking-wide transition-all ${
          side === "yes"
            ? "bg-yes hover:bg-yes-hover text-white disabled:opacity-40"
            : "bg-no hover:bg-no-hover text-white disabled:opacity-40"
        }`}
      >
        {loading
          ? "Processing…"
          : tab === "buy"
          ? `Buy ${side === "yes" ? "Yes" : "No"}`
          : `Sell ${side === "yes" ? "Yes" : "No"}`}
      </button>
    </div>
  );
}
