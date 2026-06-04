"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createMarket } from "@/lib/api";
import { getUserId } from "@/lib/user";
import type { CreateMarketPayload } from "@/lib/types";

const ROUNDS = ["RD", "EA", "ED", "REA", "Rolling", "QB"] as const;

export default function NewMarketPage() {
  const router = useRouter();
  const [form, setForm] = useState<CreateMarketPayload>({ school: "", round: "RD", b: 100 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof CreateMarketPayload>(key: K, raw: string) {
    setForm((prev) => {
      const numFields: (keyof CreateMarketPayload)[] = ["gpa_uw", "gpa_w", "sat", "act", "income_ord", "b"];
      const value = numFields.includes(key) ? (raw === "" ? undefined : Number(raw)) : (raw || undefined);
      return { ...prev, [key]: value };
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const userId = getUserId();
    if (!userId) { setError("Sign in to create a market."); return; }
    setLoading(true);
    setError(null);
    try {
      const market = await createMarket(form, userId);
      router.push(`/markets/${market.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create market.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 text-xs text-muted mb-3">
          <Link href="/" className="hover:text-gray-300 transition-colors">Markets</Link>
          <span>/</span>
          <span className="text-gray-400">Create</span>
        </div>
        <h1 className="text-2xl font-bold text-gray-100">Create a market</h1>
        <p className="text-sm text-muted mt-1">
          The ML model will set the opening probability from your student stats.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-5">
        {/* School */}
        <div className="card p-5 space-y-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">
            Application
          </h2>
          <div>
            <label className="label">School *</label>
            <input
              className="input"
              value={form.school}
              onChange={(e) => setForm((p) => ({ ...p, school: e.target.value }))}
              placeholder="e.g. Harvard, Stanford University"
              required minLength={2} maxLength={128}
            />
          </div>
          <div>
            <label className="label">Application round</label>
            <div className="flex gap-2 flex-wrap">
              {ROUNDS.map((r) => (
                <button
                  type="button"
                  key={r}
                  onClick={() => setForm((p) => ({ ...p, round: r }))}
                  className={`px-4 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                    form.round === r
                      ? "bg-indigo-600 border-indigo-600 text-white"
                      : "border-surface-3 bg-surface-2 text-muted hover:text-gray-300 hover:border-surface-3"
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Student stats */}
        <div className="card p-5 space-y-4">
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">
              Student stats
            </h2>
            <p className="text-xs text-muted mt-0.5">Optional — all fields improve the ML prediction.</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">GPA (unweighted)</label>
              <input type="number" className="input" step="0.01" min="0" max="4.0" placeholder="3.90"
                onChange={(e) => set("gpa_uw", e.target.value)} />
            </div>
            <div>
              <label className="label">GPA (weighted)</label>
              <input type="number" className="input" step="0.01" min="0" max="5.5" placeholder="4.50"
                onChange={(e) => set("gpa_w", e.target.value)} />
            </div>
            <div>
              <label className="label">SAT</label>
              <input type="number" className="input" min="400" max="1600" step="10" placeholder="1500"
                onChange={(e) => set("sat", e.target.value)} />
            </div>
            <div>
              <label className="label">ACT</label>
              <input type="number" className="input" min="1" max="36" placeholder="34"
                onChange={(e) => set("act", e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Gender</label>
              <select className="input" defaultValue="" onChange={(e) => set("gender", e.target.value)}>
                <option value="">—</option>
                <option>Male</option>
                <option>Female</option>
                <option>Other</option>
              </select>
            </div>
            <div>
              <label className="label">Income bracket (0–5)</label>
              <input type="number" className="input" min="0" max="5" placeholder="2"
                onChange={(e) => set("income_ord", e.target.value)} />
            </div>
          </div>

          <div>
            <label className="label">Intended field</label>
            <select className="input" defaultValue="" onChange={(e) => set("flair_field", e.target.value)}>
              <option value="">—</option>
              <option value="STEM">STEM</option>
              <option value="Art_Hum">Art / Humanities</option>
              <option value="SocSci">Social Sciences</option>
              <option value="Bus_Fin">Business / Finance</option>
            </select>
          </div>
        </div>

        {/* Advanced */}
        <div className="card p-5 space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">
            Market settings
          </h2>
          <div>
            <label className="label">
              Liquidity parameter (b)
              <span className="normal-case tracking-normal font-normal text-muted ml-1">
                — higher = less price impact, more house risk
              </span>
            </label>
            <input type="number" className="input" min="10" max="10000" value={form.b}
              onChange={(e) => set("b", e.target.value)} />
            <p className="mt-1.5 text-[11px] text-muted">
              Max house loss: ${((form.b ?? 100) * Math.log(2)).toFixed(0)}
            </p>
          </div>
        </div>

        {error && (
          <div className="rounded-lg bg-no-dim border border-no/30 px-4 py-3 text-sm text-no">
            {error}
          </div>
        )}

        <button type="submit" disabled={loading || !form.school} className="btn-primary w-full py-3">
          {loading ? "Creating…" : "Create market"}
        </button>
      </form>
    </div>
  );
}
