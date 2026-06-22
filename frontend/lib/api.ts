import type {
  Market,
  Portfolio,
  Position,
  PriceQuote,
  Trade,
  User,
} from "./types";

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");

async function req<T>(
  path: string,
  options: RequestInit & { userId?: string } = {}
): Promise<T> {
  const { userId, ...init } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (userId) headers["X-User-Id"] = userId;

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── Users ──────────────────────────────────────────────────

export const createUser = (username: string, email: string, password: string) =>
  req<User>("/users", {
    method: "POST",
    body: JSON.stringify({ username, email, password }),
  });

export const loginUser = (username: string, password: string) =>
  req<User>("/users/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });

export const getUser = (userId: string) => req<User>(`/users/${userId}`);

export const getPortfolio = (userId: string) =>
  req<Portfolio>(`/users/${userId}/portfolio`);

// ── Markets ────────────────────────────────────────────────

export const listMarkets = (params?: {
  school?: string;
  status?: string;
  skip?: number;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.school) qs.set("school", params.school);
  if (params?.status) qs.set("status", params.status);
  if (params?.skip !== undefined) qs.set("skip", String(params.skip));
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  const query = qs.toString() ? `?${qs}` : "";
  return req<Market[]>(`/markets${query}`);
};

export const getMarket = (marketId: string) =>
  req<Market>(`/markets/${marketId}`);

export const getQuote = (
  marketId: string,
  side: "yes" | "no",
  budget: number
) =>
  req<PriceQuote>(
    `/markets/${marketId}/quote?side=${side}&budget=${budget}`
  );

// ── Trades ─────────────────────────────────────────────────

export const buyShares = (
  marketId: string,
  side: "yes" | "no",
  budget: number,
  userId: string
) =>
  req<Trade>(`/markets/${marketId}/buy`, {
    method: "POST",
    body: JSON.stringify({ side, budget }),
    userId,
  });

export const sellShares = (
  marketId: string,
  side: "yes" | "no",
  shares: number,
  userId: string
) =>
  req<Trade>(`/markets/${marketId}/sell`, {
    method: "POST",
    body: JSON.stringify({ side, shares }),
    userId,
  });

export const listTrades = (marketId: string) =>
  req<Trade[]>(`/markets/${marketId}/trades`);

export const getPosition = (marketId: string, userId: string) =>
  req<Position>(`/markets/${marketId}/positions/${userId}`);
