export interface User {
  id: string;
  username: string;
  email: string;
  balance: number;
  created_at: string;
}

export interface Market {
  id: string;
  creator_id: string;
  school: string;
  round: string;
  current_price: number;
  ml_prob: number | null;
  price_change: number | null;
  b: number;
  max_loss: number;
  status: "open" | "closed" | "resolved";
  outcome: "admitted" | "rejected" | null;
  gpa_uw:      number | null;
  gpa_w:       number | null;
  sat:         number | null;
  act:         number | null;
  gender:      string | null;
  race:        string | null;
  income_ord:  number | null;
  flair_field: string | null;
  extracurriculars: string | null;
  llm_score:   number | null;
  llm_summary: string | null;
  trade_count: number;
  total_volume: number;
  created_at: string;
  resolved_at: string | null;
}

export interface Trade {
  id: string;
  market_id: string;
  user_id: string;
  side: "yes" | "no";
  action: "buy" | "sell";
  shares: number;
  cost: number;
  price_before: number;
  price_after: number;
  created_at: string;
}

export interface PriceQuote {
  side: "yes" | "no";
  shares: number;
  cost: number;
  price_before: number;
  price_after: number;
  avg_price: number;
}

export interface Position {
  market_id: string;
  user_id: string;
  yes_shares: number;
  no_shares: number;
  cost_basis: number;
  current_price: number;
  current_value: number;
  unrealized_pnl: number;
}

export interface PositionSummary {
  market_id: string;
  school: string;
  round: string;
  status: string;
  current_price: number;
  yes_shares: number;
  no_shares: number;
  cost_basis: number;
  current_value: number;
  unrealized_pnl: number;
}

export interface Portfolio {
  user: User;
  balance: number;
  positions: PositionSummary[];
  unrealized_value: number;
}

