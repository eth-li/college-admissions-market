"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { getMarket, listTrades } from "@/lib/api";
import type { Market, Trade } from "@/lib/types";
import TradePanel from "@/components/TradePanel";

function ProbBar({ prob }: { prob: number }) {
  const pct = Math.round(prob * 100);
  return (
    <div className="space-y-2">
      <div className="flex justify-between items-end">
        <div>
          <span className="text-4xl font-bold text-yes tabular-nums">{pct}¢</span>
          <span className="text-sm text-muted ml-2">chance of admission</span>
        </div>
        <div className="text-right">
          <span className="text-2xl font-bold text-no tabular-nums">{100 - pct}¢</span>
          <span className="text-sm text-muted ml-2">No</span>
        </div>
      </div>
      <div className="h-2 w-full rounded-full bg-no-dim overflow-hidden">
        <div className="h-full rounded-full bg-yes transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function MarketPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [market, setMarket] = useState<Market | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    getMarket(id).then(setMarket).catch(() => null);
    listTrades(id).then(setTrades).catch(() => null);
  }, [id]);

  useEffect(() => {
    setLoading(true);
    Promise.all([getMarket(id), listTrades(id)])
      .then(([m, t]) => { setMarket(m); setTrades(t); })
      .catch(() => router.push("/"))
      .finally(() => setLoading(false));
  }, [id, router]);

  if (loading || !market) {
    return (
      <div className="flex justify-center py-20">
        <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <Link href="/" className="hover:text-gray-300 transition-colors">Markets</Link>
        <span>/</span>
        <span className="text-gray-400">{market.school}</span>
      </div>

      {/* Hero card */}
      <div className="card p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1 min-w-0">
            <p className="text-xs uppercase tracking-widest text-muted font-medium">
              {market.round} · College Admissions
            </p>
            <h1 className="text-2xl font-bold text-gray-100 leading-tight">
              Will this student be admitted to {market.school}?
            </h1>
          </div>
          <span className={`shrink-0 ${market.status === "open" ? "badge-open" : market.status === "closed" ? "badge-closed" : "badge-resolved"}`}>
            {market.status}
          </span>
        </div>

        <ProbBar prob={market.current_price} />

        {/* Stats row */}
        <div className="flex gap-6 pt-1 text-sm">
          <div>
            <p className="text-muted text-xs uppercase tracking-wide">Volume</p>
            <p className="font-semibold tabular-nums">${market.total_volume.toFixed(0)}</p>
          </div>
          <div>
            <p className="text-muted text-xs uppercase tracking-wide">Trades</p>
            <p className="font-semibold tabular-nums">{market.trade_count}</p>
          </div>
          {market.ml_prob !== null && (
            <div>
              <p className="text-muted text-xs uppercase tracking-wide">ML baseline</p>
              <p className="font-semibold tabular-nums">
                {Math.round(market.ml_prob * 100)}¢
                {market.price_change !== null && (
                  <span className={`ml-1.5 text-xs ${market.price_change >= 0 ? "text-yes" : "text-no"}`}>
                    {market.price_change >= 0 ? "+" : ""}{Math.round(market.price_change * 100)}pp
                  </span>
                )}
              </p>
            </div>
          )}
          {market.b !== undefined && (
            <div>
              <p className="text-muted text-xs uppercase tracking-wide">Max house loss</p>
              <p className="font-semibold tabular-nums">${market.max_loss.toFixed(0)}</p>
            </div>
          )}
        </div>

        {market.status === "resolved" && market.outcome && (
          <div className={`rounded-xl px-5 py-3 text-sm font-semibold flex items-center gap-2 ${
            market.outcome === "admitted" ? "bg-yes-dim text-yes border border-yes/30" : "bg-no-dim text-no border border-no/30"
          }`}>
            {market.outcome === "admitted" ? "✓" : "✗"} Outcome: {market.outcome}
          </div>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        {/* Left column */}
        <div className="space-y-5">
          {/* Student profile */}
          {(market.gpa_uw || market.sat || market.act) && (
            <div className="card p-5">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-muted mb-4">
                Student profile
              </h2>
              <div className="grid grid-cols-3 gap-4">
                {market.gpa_uw && (
                  <div className="rounded-lg bg-surface-2 px-4 py-3 text-center">
                    <p className="text-xs text-muted mb-1">GPA (UW)</p>
                    <p className="text-lg font-bold tabular-nums">{market.gpa_uw.toFixed(2)}</p>
                  </div>
                )}
                {market.sat && (
                  <div className="rounded-lg bg-surface-2 px-4 py-3 text-center">
                    <p className="text-xs text-muted mb-1">SAT</p>
                    <p className="text-lg font-bold tabular-nums">{market.sat}</p>
                  </div>
                )}
                {market.act && (
                  <div className="rounded-lg bg-surface-2 px-4 py-3 text-center">
                    <p className="text-xs text-muted mb-1">ACT</p>
                    <p className="text-lg font-bold tabular-nums">{market.act}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* LLM assessment */}
          {(market.extracurriculars || market.llm_summary) && (
            <div className="card p-5 space-y-4">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">
                Extracurricular profile
              </h2>
              {market.llm_score !== null && (
                <div className="flex items-center gap-3">
                  <div className="flex gap-1">
                    {Array.from({ length: 10 }).map((_, i) => (
                      <div
                        key={i}
                        className={`h-2 w-4 rounded-sm ${
                          i < Math.round(market.llm_score!) ? "bg-indigo-500" : "bg-surface-3"
                        }`}
                      />
                    ))}
                  </div>
                  <span className="text-sm font-semibold tabular-nums text-gray-200">
                    {market.llm_score.toFixed(1)}<span className="text-muted font-normal">/10</span>
                  </span>
                </div>
              )}
              {market.llm_summary && (
                <p className="text-sm text-gray-300 leading-relaxed">{market.llm_summary}</p>
              )}
              {market.extracurriculars && (
                <details className="group">
                  <summary className="cursor-pointer text-xs text-muted hover:text-gray-300 transition-colors select-none">
                    Show full profile
                  </summary>
                  <p className="mt-2 text-sm text-gray-400 leading-relaxed whitespace-pre-wrap">
                    {market.extracurriculars}
                  </p>
                </details>
              )}
            </div>
          )}

          {/* Trade feed */}
          <div className="card overflow-hidden">
            <div className="px-5 py-4 border-b border-surface-3">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">
                Activity
              </h2>
            </div>
            {trades.length === 0 ? (
              <p className="px-5 py-8 text-sm text-muted text-center">
                No trades yet. Be the first.
              </p>
            ) : (
              <div className="divide-y divide-surface-3">
                {trades.map((t) => {
                  const priceDelta = ((t.price_after - t.price_before) * 100).toFixed(1);
                  const positive = t.price_after >= t.price_before;
                  return (
                    <div key={t.id} className="px-5 py-3 flex items-center justify-between text-sm">
                      <div className="flex items-center gap-3">
                        <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ${
                          t.side === "yes" ? "bg-yes-dim text-yes" : "bg-no-dim text-no"
                        }`}>
                          {t.action === "buy" ? "↑" : "↓"} {t.side.toUpperCase()}
                        </span>
                        <span className="text-gray-300 tabular-nums">
                          {t.shares.toFixed(2)} shares
                        </span>
                        <span className="text-muted tabular-nums">
                          @ {(Math.abs(t.cost / t.shares) * 100).toFixed(1)}¢
                        </span>
                      </div>
                      <div className="text-right">
                        <span className={`text-xs tabular-nums ${positive ? "text-yes" : "text-no"}`}>
                          {positive ? "+" : ""}{priceDelta}pp
                        </span>
                        <p className="text-[11px] text-muted">
                          {new Date(t.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right column */}
        <div className="lg:sticky lg:top-20 self-start">
          <TradePanel market={market} onTraded={refresh} />
        </div>
      </div>
    </div>
  );
}
