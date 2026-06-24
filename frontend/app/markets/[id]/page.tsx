"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { getMarket, listTrades } from "@/lib/api";
import type { Market, Trade } from "@/lib/types";
import TradePanel from "@/components/TradePanel";

// Published acceptance rates (Class of 2028 / latest available)
const ACCEPTANCE_RATES: Record<string, number> = {
  "MIT": 0.037,
  "Stanford": 0.036,
  "Harvard": 0.032,
  "Yale": 0.045,
  "Columbia": 0.040,
  "Princeton": 0.047,
  "UC Berkeley": 0.117,
  "UNC Chapel Hill": 0.190,
  "Duke": 0.063,
  "Johns Hopkins": 0.069,
  "Northwestern": 0.067,
  "USC": 0.120,
  "Caltech": 0.030,
  "UPenn": 0.056,
  "Brown": 0.057,
  "Dartmouth": 0.057,
  "Cornell": 0.089,
  "Vanderbilt": 0.073,
  "Rice": 0.082,
  "Notre Dame": 0.127,
};

function getAcceptanceRate(school: string): number | null {
  for (const [key, rate] of Object.entries(ACCEPTANCE_RATES)) {
    if (school.toLowerCase().includes(key.toLowerCase()) ||
        key.toLowerCase().includes(school.toLowerCase())) {
      return rate;
    }
  }
  return null;
}

const INCOME_LABELS = ["Low income", "Lower-middle", "Middle", "Upper-middle", "Upper", "High income"];

const FLAIR_LABELS: Record<string, string> = {
  "STEM":    "STEM",
  "Art_Hum": "Arts & Humanities",
  "SocSci":  "Social Science",
  "Bus_Fin": "Business / Finance",
};

// ── Price history chart ────────────────────────────────────────────────────────

function PriceChart({ market, trades }: { market: Market; trades: Trade[] }) {
  const acceptanceRate = getAcceptanceRate(market.school);

  // Build chronological data points: [timestamp_ms, probability]
  const points: [number, number][] = [];
  if (market.ml_prob !== null) {
    points.push([new Date(market.created_at).getTime(), market.ml_prob]);
  }
  const sorted = [...trades].reverse();
  for (const t of sorted) {
    points.push([new Date(t.created_at).getTime(), t.price_after]);
  }
  if (points.length === 0) return null;

  const W = 800, H = 160;
  const PAD = { top: 14, right: 16, bottom: 28, left: 44 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  const xMin = points[0][0];
  const xMax = points.length > 1 ? points[points.length - 1][0] : xMin + 1;
  const xRange = xMax - xMin;

  const xScale = (t: number) => PAD.left + ((t - xMin) / xRange) * chartW;
  const yScale = (p: number) => PAD.top + (1 - p) * chartH;

  const linePts = points.map(([t, p]) => `${xScale(t).toFixed(1)},${yScale(p).toFixed(1)}`).join(" ");

  // Closed area path for gradient fill
  const areaPath = `M ${xScale(points[0][0]).toFixed(1)} ${yScale(points[0][1]).toFixed(1)} ` +
    points.slice(1).map(([t, p]) => `L ${xScale(t).toFixed(1)} ${yScale(p).toFixed(1)}`).join(" ") +
    ` L ${xScale(points[points.length - 1][0]).toFixed(1)} ${(PAD.top + chartH).toFixed(1)}` +
    ` L ${xScale(points[0][0]).toFixed(1)} ${(PAD.top + chartH).toFixed(1)} Z`;

  const yTicks = [0, 0.25, 0.5, 0.75, 1];

  // X-axis: format timestamps
  const fmtTime = (ms: number) => {
    const d = new Date(ms);
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  };
  const xTicks = points.length > 1
    ? [points[0][0], points[Math.floor(points.length / 2)][0], points[points.length - 1][0]]
    : [points[0][0]];

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">Chance of admission over time</h2>
        <div className="flex items-center gap-4 text-[11px] text-muted">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-4 h-0.5 bg-yes" />
            Market
          </span>
          {market.ml_prob !== null && (
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-4 border-t border-dashed border-indigo-400" />
              ML baseline
            </span>
          )}
          {acceptanceRate !== null && (
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-4 border-t border-dashed border-orange-400" />
              Published rate
            </span>
          )}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Grid lines */}
        {yTicks.map((p) => (
          <g key={p}>
            <line x1={PAD.left} y1={yScale(p)} x2={W - PAD.right} y2={yScale(p)}
              stroke="#1e1e2e" strokeWidth="1" />
            <text x={PAD.left - 6} y={yScale(p) + 4} textAnchor="end"
              fontSize="10" fill="#6b7280">{Math.round(p * 100)}%</text>
          </g>
        ))}

        {/* X-axis labels */}
        {xTicks.map((t, i) => (
          <text key={i} x={xScale(t)} y={H - 4} textAnchor="middle"
            fontSize="10" fill="#6b7280">{fmtTime(t)}</text>
        ))}

        {/* ML baseline */}
        {market.ml_prob !== null && (
          <line x1={PAD.left} y1={yScale(market.ml_prob)} x2={W - PAD.right} y2={yScale(market.ml_prob)}
            stroke="#818cf8" strokeWidth="1" strokeDasharray="5,3" opacity="0.6" />
        )}

        {/* Published acceptance rate */}
        {acceptanceRate !== null && (
          <>
            <line x1={PAD.left} y1={yScale(acceptanceRate)} x2={W - PAD.right} y2={yScale(acceptanceRate)}
              stroke="#fb923c" strokeWidth="1" strokeDasharray="5,3" opacity="0.7" />
            <text x={W - PAD.right + 2} y={yScale(acceptanceRate) + 4}
              fontSize="9" fill="#fb923c" opacity="0.8">{Math.round(acceptanceRate * 100)}%</text>
          </>
        )}

        {/* Area fill */}
        {points.length > 1 && (
          <path d={areaPath} fill="url(#areaGrad)" />
        )}

        {/* Price line */}
        <polyline points={linePts} fill="none" stroke="#22c55e" strokeWidth="2" strokeLinejoin="round" />

        {/* Current price dot */}
        <circle
          cx={xScale(points[points.length - 1][0])}
          cy={yScale(points[points.length - 1][1])}
          r="3.5" fill="#22c55e"
        />
      </svg>
    </div>
  );
}

// ── Prob bar ───────────────────────────────────────────────────────────────────

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

// ── Stat tile ──────────────────────────────────────────────────────────────────

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg bg-surface-2 px-4 py-3 text-center">
      <p className="text-xs text-muted mb-1">{label}</p>
      <p className="text-lg font-bold tabular-nums">{value}</p>
    </div>
  );
}

// ── LLM summary bullets ────────────────────────────────────────────────────────

function LlmBullets({ summary }: { summary: string }) {
  // Supports new format ("• Point\n• Point") and old paragraph format
  let bullets: string[];
  if (summary.includes("•") || summary.includes("\n")) {
    bullets = summary.split("\n").map(s => s.replace(/^•\s*/, "").trim()).filter(Boolean);
  } else {
    bullets = summary.split(/\.\s+/).map(s => s.replace(/\.$/, "").trim()).filter(Boolean);
  }
  return (
    <ul className="space-y-1.5">
      {bullets.map((b, i) => (
        <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
          <span className="mt-1 shrink-0 w-1.5 h-1.5 rounded-full bg-indigo-400" />
          {b}
        </li>
      ))}
    </ul>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

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

  const acceptanceRate = getAcceptanceRate(market.school);

  // Build profile stat tiles — only non-null values
  const profileStats: { label: string; value: string | number }[] = [];
  if (market.gpa_uw != null) profileStats.push({ label: "GPA (UW)", value: market.gpa_uw.toFixed(2) });
  if (market.gpa_w  != null) profileStats.push({ label: "GPA (W)",  value: market.gpa_w.toFixed(2) });
  if (market.sat    != null) profileStats.push({ label: "SAT",       value: market.sat });
  if (market.act    != null) profileStats.push({ label: "ACT",       value: market.act });

  const profileMeta: { label: string; value: string }[] = [];
  profileMeta.push({ label: "Round", value: market.round });
  if (market.gender)      profileMeta.push({ label: "Gender",    value: market.gender });
  if (market.race)        profileMeta.push({ label: "Race/Eth.", value: market.race });
  if (market.income_ord != null) profileMeta.push({ label: "Income",  value: INCOME_LABELS[market.income_ord] ?? String(market.income_ord) });
  if (market.flair_field) profileMeta.push({ label: "Field",     value: FLAIR_LABELS[market.flair_field] ?? market.flair_field });

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
        <div className="flex flex-wrap gap-6 pt-1 text-sm">
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
          {acceptanceRate !== null && (
            <div>
              <p className="text-muted text-xs uppercase tracking-wide">Published rate</p>
              <p className="font-semibold tabular-nums text-orange-400">{(acceptanceRate * 100).toFixed(1)}%</p>
            </div>
          )}
          <div>
            <p className="text-muted text-xs uppercase tracking-wide">Max house loss</p>
            <p className="font-semibold tabular-nums">${market.max_loss.toFixed(0)}</p>
          </div>
        </div>

        {market.status === "resolved" && market.outcome && (
          <div className={`rounded-xl px-5 py-3 text-sm font-semibold flex items-center gap-2 ${
            market.outcome === "admitted"
              ? "bg-yes-dim text-yes border border-yes/30"
              : "bg-no-dim text-no border border-no/30"
          }`}>
            {market.outcome === "admitted" ? "✓" : "✗"} Outcome: {market.outcome}
          </div>
        )}
      </div>

      {/* Price chart */}
      <PriceChart market={market} trades={trades} />

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        {/* Left column */}
        <div className="space-y-5">

          {/* Student profile */}
          {(profileStats.length > 0 || profileMeta.length > 0) && (
            <div className="card p-5 space-y-4">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">
                Student profile
              </h2>
              {profileStats.length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {profileStats.map(({ label, value }) => (
                    <StatTile key={label} label={label} value={value} />
                  ))}
                </div>
              )}
              {profileMeta.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {profileMeta.map(({ label, value }) => (
                    <div key={label} className="rounded-full bg-surface-2 px-3 py-1 text-xs flex items-center gap-1.5">
                      <span className="text-muted">{label}:</span>
                      <span className="text-gray-200 font-medium">{value}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Extracurricular profile */}
          {(market.extracurriculars || market.llm_summary || market.llm_score !== null) && (
            <div className="card p-5 space-y-4">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">
                Extracurricular profile
              </h2>

              {/* Score bar */}
              {market.llm_score !== null && (
                <div className="flex items-center gap-3">
                  <div className="flex gap-1">
                    {Array.from({ length: 10 }).map((_, i) => (
                      <div key={i} className={`h-2 w-4 rounded-sm ${
                        i < Math.round(market.llm_score!) ? "bg-indigo-500" : "bg-surface-3"
                      }`} />
                    ))}
                  </div>
                  <span className="text-sm font-semibold tabular-nums text-gray-200">
                    {market.llm_score.toFixed(1)}<span className="text-muted font-normal">/10</span>
                  </span>
                </div>
              )}

              {/* AI summary as bullets */}
              {market.llm_summary && <LlmBullets summary={market.llm_summary} />}

              {/* Raw extracurriculars — no dropdown */}
              {market.extracurriculars && (
                <div className="pt-1 border-t border-surface-3">
                  <p className="text-xs text-muted uppercase tracking-wide mb-2">Full profile</p>
                  <p className="text-sm text-gray-400 leading-relaxed whitespace-pre-wrap">
                    {market.extracurriculars}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Activity feed */}
          <div className="card overflow-hidden">
            <div className="px-5 py-4 border-b border-surface-3">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">Activity</h2>
            </div>
            {trades.length === 0 ? (
              <p className="px-5 py-8 text-sm text-muted text-center">No trades yet. Be the first.</p>
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
                        <span className="text-gray-300 tabular-nums">{t.shares.toFixed(2)} shares</span>
                        <span className="text-muted tabular-nums">@ {(Math.abs(t.cost / t.shares) * 100).toFixed(1)}¢</span>
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
