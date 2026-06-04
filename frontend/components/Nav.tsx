"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { getUserId, clearUserId } from "@/lib/user";
import { getUser } from "@/lib/api";

export default function Nav() {
  const [username, setUsername] = useState<string | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const pathname = usePathname();

  useEffect(() => {
    const id = getUserId();
    if (!id) return;
    getUser(id)
      .then((u) => { setUsername(u.username); setBalance(u.balance); })
      .catch(() => { clearUserId(); });
  }, [pathname]);

  const navLink = (href: string, label: string) => (
    <Link
      href={href}
      className={`text-sm font-medium transition-colors ${
        pathname === href
          ? "text-gray-100"
          : "text-muted hover:text-gray-100"
      }`}
    >
      {label}
    </Link>
  );

  return (
    <header className="sticky top-0 z-50 border-b border-surface-3 bg-surface/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 h-14">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <span className="text-base font-bold tracking-tight text-gray-100">
            Admissions<span className="text-indigo-400">Market</span>
          </span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-5 flex-1">
          {navLink("/", "Markets")}
          {navLink("/markets/new", "Create")}
          {username && navLink("/portfolio", "Portfolio")}
        </nav>

        {/* Right side */}
        <div className="flex items-center gap-3 shrink-0">
          {username ? (
            <>
              {balance !== null && (
                <span className="text-sm font-semibold text-gray-100 tabular-nums">
                  ${balance.toFixed(2)}
                </span>
              )}
              <span className="text-sm text-muted">{username}</span>
              <button
                onClick={() => { clearUserId(); setUsername(null); setBalance(null); }}
                className="text-xs text-muted hover:text-gray-300 transition-colors"
              >
                Sign out
              </button>
            </>
          ) : (
            <Link href="/login" className="btn-primary text-xs px-3 py-1.5">
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
