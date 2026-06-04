"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getPortfolio } from "@/lib/api";
import { getUserId } from "@/lib/user";
import type { Portfolio, PositionSummary } from "@/lib/types";

function PnlCell({ value }: { value: number }) {
  return (
    <span className={`font-semibold tabular-nums ${value >= 0 ? "text-yes" : "text-no"}`}>
      {value >= 0 ? "+" : ""}${value.toFixed(2)}
    </span>
  );
}

function PositionRow({ pos }: { pos: PositionSummary }) {
  return (
    <tr className="border-t border-surface-3 hover:bg-surface-2/50 transition-colors">
      <td className="px-5 py-3.5">
        <Link href={`/markets/${pos.market_id}`}
          className="font-medium text-gray-100 hover:text-indigo-400 transition-colors">
          {pos.school}
        </Link>
        <span className="ml-2 text-xs text-muted">{pos.round}</span>
      </td>
      <td className="px-5 py-3.5 text-right">
        {pos.yes_shares > 0.001 ? (
          <span className="text-yes tabular-nums">{pos.yes_shares.toFixed(2)}</span>
        ) : <span className="text-muted">—</span>}
      </td>
      <td className="px-5 py-3.5 text-right">
        {pos.no_shares > 0.001 ? (
          <span className="text-no tabular-nums">{pos.no_shares.toFixed(2)}</span>
        ) : <span className="text-muted">—</span>}
      </td>
      <td className="px-5 py-3.5 text-right tabular-nums text-gray-300">
        {Math.round(pos.current_price * 100)}¢
      </td>
      <td className="px-5 py-3.5 text-right tabular-nums text-gray-300">
        ${pos.current_value.toFixed(2)}
      </td>
      <td className="px-5 py-3.5 text-right">
        <PnlCell value={pos.unrealized_pnl} />
      </td>
      <td className="px-5 py-3.5">
        <span className={pos.status === "open" ? "badge-open" : pos.status === "closed" ? "badge-closed" : "badge-resolved"}>
          {pos.status}
        </span>
      </td>
    </tr>
  );
}

export default function PortfolioPage() {
  const router = useRouter();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const userId = getUserId();
    if (!userId) { router.push("/login"); return; }
    getPortfolio(userId)
      .then(setPortfolio)
      .catch(() => router.push("/login"))
      .finally(() => setLoading(false));
  }, [router]);

  if (loading || !portfolio) {
    return (
      <div className="flex justify-center py-20">
        <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const { user, balance, positions, unrealized_value } = portfolio;
  const totalValue = balance + Math.max(0, unrealized_value);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Portfolio</h1>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card p-5">
          <p className="text-xs uppercase tracking-widest text-muted mb-1">Cash balance</p>
          <p className="text-3xl font-bold tabular-nums">${balance.toFixed(2)}</p>
        </div>
        <div className="card p-5">
          <p className="text-xs uppercase tracking-widest text-muted mb-1">Unrealised P&L</p>
          <p className={`text-3xl font-bold tabular-nums ${unrealized_value >= 0 ? "text-yes" : "text-no"}`}>
            {unrealized_value >= 0 ? "+" : ""}${unrealized_value.toFixed(2)}
          </p>
        </div>
        <div className="card p-5">
          <p className="text-xs uppercase tracking-widest text-muted mb-1">Est. total value</p>
          <p className="text-3xl font-bold tabular-nums">${totalValue.toFixed(2)}</p>
        </div>
      </div>

      {/* User ID */}
      <div className="card px-5 py-3 flex items-center justify-between text-xs">
        <span className="text-muted">User ID (use to sign in)</span>
        <span className="font-mono text-gray-400 select-all">{user.id}</span>
      </div>

      {/* Positions */}
      {positions.length === 0 ? (
        <div className="card p-12 text-center space-y-3">
          <p className="text-muted">No positions yet.</p>
          <Link href="/" className="btn-primary inline-flex">Browse markets</Link>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-surface-3">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">
              Positions ({positions.length})
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-widest text-muted">
                  <th className="px-5 py-3 text-left font-medium">School</th>
                  <th className="px-5 py-3 text-right font-medium">Yes shares</th>
                  <th className="px-5 py-3 text-right font-medium">No shares</th>
                  <th className="px-5 py-3 text-right font-medium">Price</th>
                  <th className="px-5 py-3 text-right font-medium">Value</th>
                  <th className="px-5 py-3 text-right font-medium">P&L</th>
                  <th className="px-5 py-3 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => <PositionRow key={pos.market_id} pos={pos} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
