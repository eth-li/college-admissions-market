"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createUser, loginUser } from "@/lib/api";
import { setUserId } from "@/lib/user";

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"register" | "login">("register");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setUsername(""); setEmail(""); setPassword(""); setError(null);
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const user = await createUser(username, email, password);
      setUserId(user.id);
      router.push("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const user = await loginUser(username, password);
      setUserId(user.id);
      router.push("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm pt-8">
      {/* Logo */}
      <div className="text-center mb-8">
        <h1 className="text-2xl font-bold text-gray-100">
          Admissions<span className="text-indigo-400">Market</span>
        </h1>
        <p className="text-sm text-muted mt-1">Prediction markets for college admissions</p>
      </div>

      {/* Tabs */}
      <div className="flex rounded-xl overflow-hidden border border-surface-3 bg-surface-2 p-0.5 gap-0.5 mb-6">
        {(["register", "login"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); reset(); }}
            className={`flex-1 py-2 rounded-lg text-sm font-semibold transition-all ${
              tab === t ? "bg-surface text-gray-100 shadow-sm" : "text-muted hover:text-gray-300"
            }`}
          >
            {t === "register" ? "Register" : "Sign in"}
          </button>
        ))}
      </div>

      {tab === "register" ? (
        <form onSubmit={handleRegister} className="card p-6 space-y-4">
          <div>
            <label className="label">Username</label>
            <input className="input" value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="yourname" minLength={3} maxLength={64} required />
          </div>
          <div>
            <label className="label">Email</label>
            <input type="email" className="input" value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com" required />
          </div>
          <div>
            <label className="label">Password</label>
            <input type="password" className="input" value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min 6 characters" minLength={6} required />
          </div>
          {error && (
            <div className="rounded-lg bg-no-dim border border-no/30 px-4 py-2.5 text-sm text-no">
              {error}
            </div>
          )}
          <button type="submit" disabled={loading} className="btn-primary w-full py-2.5">
            {loading ? "Creating account…" : "Register — start with $1,000"}
          </button>
          <p className="text-center text-xs text-muted">
            Virtual credits only. No real money involved.
          </p>
        </form>
      ) : (
        <form onSubmit={handleLogin} className="card p-6 space-y-4">
          <div>
            <label className="label">Username</label>
            <input className="input" value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="yourname" required />
          </div>
          <div>
            <label className="label">Password</label>
            <input type="password" className="input" value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your password" required />
          </div>
          {error && (
            <div className="rounded-lg bg-no-dim border border-no/30 px-4 py-2.5 text-sm text-no">
              {error}
            </div>
          )}
          <button type="submit" disabled={loading} className="btn-primary w-full py-2.5">
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      )}
    </div>
  );
}
