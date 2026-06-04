import Link from "next/link";
import type { Market } from "@/lib/types";

export default function MarketCard({ market }: { market: Market }) {
  const yesPct = Math.round(market.current_price * 100);
  const noPct = 100 - yesPct;

  return (
    <Link href={`/markets/${market.id}`} className="block group">
      <div className="card p-5 hover:border-surface-3/80 hover:bg-surface-2/40 transition-all duration-150 cursor-pointer h-full flex flex-col gap-4">

        {/* Header row */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] uppercase tracking-widest text-muted font-medium mb-1">
              {market.round}
            </p>
            <h3 className="text-sm font-semibold text-gray-100 leading-snug line-clamp-2 group-hover:text-white transition-colors">
              {market.school} admission
            </h3>
          </div>
          <span className={market.status === "open" ? "badge-open" : market.status === "closed" ? "badge-closed" : "badge-resolved"}>
            {market.status}
          </span>
        </div>

        {/* Price display */}
        <div className="flex gap-2">
          <div className="flex-1 rounded-lg bg-yes-dim border border-yes/20 px-3 py-2.5 text-center">
            <p className="text-[10px] uppercase tracking-widest text-yes/70 mb-0.5">Yes</p>
            <p className="text-xl font-bold text-yes tabular-nums">{yesPct}¢</p>
          </div>
          <div className="flex-1 rounded-lg bg-no-dim border border-no/20 px-3 py-2.5 text-center">
            <p className="text-[10px] uppercase tracking-widest text-no/70 mb-0.5">No</p>
            <p className="text-xl font-bold text-no tabular-nums">{noPct}¢</p>
          </div>
        </div>

        {/* Progress bar */}
        <div className="h-1 w-full rounded-full bg-no-dim overflow-hidden">
          <div
            className="h-full rounded-full bg-yes transition-all"
            style={{ width: `${yesPct}%` }}
          />
        </div>

        {/* Footer stats */}
        <div className="flex items-center justify-between text-[11px] text-muted">
          <span>${market.total_volume.toFixed(0)} vol</span>
          <span>{market.trade_count} trades</span>
          {market.ml_prob !== null && market.price_change !== null && (
            <span className={market.price_change >= 0 ? "text-yes" : "text-no"}>
              {market.price_change >= 0 ? "▲" : "▼"} {Math.abs(Math.round(market.price_change * 100))}pp vs ML
            </span>
          )}
        </div>

        {market.status === "resolved" && market.outcome && (
          <div className={`rounded-lg px-3 py-2 text-center text-xs font-semibold ${
            market.outcome === "admitted" ? "bg-yes-dim text-yes" : "bg-no-dim text-no"
          }`}>
            {market.outcome === "admitted" ? "✓ Admitted" : "✗ Rejected"}
          </div>
        )}
      </div>
    </Link>
  );
}
