# College Admissions Prediction Market

A real-money-style prediction market for college admissions outcomes.  
An XGBoost + Bayesian inference ML model (trained on 12,000+ r/collegeresults posts) seeds opening prices. A Logarithmic Market Scoring Rule (LMSR) market maker handles all trades.

**Stack:** FastAPI · SQLite (dev) / Postgres (prod) · Next.js 14 · Tailwind CSS

---

## Quick start

### 1. Prerequisites

- Python 3.11+
- Node.js 18+
- An `ANTHROPIC_API_KEY` (optional — used for LLM extracurricular scoring; markets still work without it)

### 2. First-time setup

```bash
make setup
```

This creates a Python virtual environment, installs all backend dependencies, and runs `npm install` for the frontend.

### 3. Configure environment

Copy `.env.example` files and fill in values:

```bash
# Backend — create market/.env
ANTHROPIC_API_KEY=sk-ant-...   # optional

# Frontend — already configured in frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 4. Seed the database (optional but recommended)

```bash
make seed
```

Wipes `market.db` and populates it with 10 detailed applicant markets. Each market's opening probability is set by the ML model (and optionally blended with an LLM extracurricular assessment if `ANTHROPIC_API_KEY` is set).

### 5. Start everything

```bash
make dev
```

Launches the backend and frontend in a **single terminal**. Both processes share prefixed log output and are killed together with `Ctrl+C`.

| Service  | URL                                    |
|----------|----------------------------------------|
| Frontend | http://localhost:3000                  |
| Backend  | http://localhost:8000                  |
| API docs | http://localhost:8000/docs (Swagger)   |

To wipe the database and re-seed on start:

```bash
make seed-dev
```

---

## All `make` commands

| Command       | What it does                                      |
|---------------|---------------------------------------------------|
| `make setup`  | Create venv, install Python + Node deps           |
| `make dev`    | Start backend + frontend in one terminal          |
| `make seed-dev` | Seed DB, then start backend + frontend          |
| `make seed`   | Seed DB only (no server)                          |
| `make backend`  | Start backend only                              |
| `make frontend` | Start frontend only                             |
| `make clean`  | Remove venv, node_modules, .next, market.db       |

---

## Project structure

```
college-admissions-market/
├── market/             # FastAPI backend
│   ├── api/            # Routes, schemas, deps
│   ├── core/           # LMSR engine, LLM assessor
│   └── db/             # SQLAlchemy models & session
├── model/              # ML model (XGBoost + Bayesian calibration)
│   └── artifacts/      # Trained model pickle
├── frontend/           # Next.js frontend
│   ├── app/            # Pages (App Router)
│   ├── components/     # MarketCard, TradePanel, Nav
│   └── lib/            # API client, types
├── data/               # Processed applicant data
├── data_collection/    # Reddit scraping scripts
├── seed.py             # Database seeding script
├── start.sh            # One-command launcher
└── Makefile
```

---

## How it works

1. **ML model** — XGBoost trained on GPA, SAT/ACT, gender, income, school selectivity, and application round. Bayesian calibration corrects for r/collegeresults self-selection bias.
2. **LLM assessor** — Claude scores extracurricular activities on a 1–10 scale. The ML probability and LLM score are blended to set the market's opening price.
3. **LMSR market maker** — Every buy/sell is filled instantly at a price derived from the current share quantities. The house subsidises liquidity; maximum loss per market = `b × ln(2)`.
4. **Resolution** — When a decision arrives, the market creator resolves YES or NO. Winning shareholders receive $1.00 per share.

---

## Deploying to Railway (backend) + Vercel (frontend)

### Backend → Railway

1. Push this repo to GitHub.
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select this repo.
3. Railway auto-detects `Procfile` and `requirements.txt` and starts the FastAPI app.
4. Add a **Postgres** database: in your Railway project click **+ New** → **Database** → **PostgreSQL**. Railway automatically sets `DATABASE_URL` in your service — no manual config needed.
5. Add these environment variables in Railway → your service → **Variables**:
   ```
   ANTHROPIC_API_KEY=sk-ant-...     # optional
   FRONTEND_URL=https://your-app.vercel.app   # set after Vercel deploy
   ```
6. In Railway → your service → **Settings** → copy the public domain (e.g. `https://your-api.up.railway.app`). You'll need this for the frontend.

### Frontend → Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New Project** → import the same GitHub repo.
2. When prompted for **Root Directory**, set it to `frontend`.
3. Add this environment variable in Vercel → **Settings** → **Environment Variables**:
   ```
   NEXT_PUBLIC_API_URL=https://your-api.up.railway.app
   ```
4. Deploy. Vercel gives you a URL like `https://your-app.vercel.app`.
5. Go back to Railway and set `FRONTEND_URL=https://your-app.vercel.app` so CORS allows it.

### Seed the production database

Once both services are deployed, seed the Railway Postgres DB from your local machine:

```bash
# Get your Railway DATABASE_URL from the Railway dashboard → Postgres → Connect
DATABASE_URL=postgresql+asyncpg://... python seed.py
```

Or install the [Railway CLI](https://docs.railway.app/guides/cli) and run:

```bash
railway run python seed.py
```

---

## API overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/users` | Create account (returns $1,000 in credits) |
| `GET`  | `/markets` | List all markets |
| `POST` | `/markets` | Create a market (ML sets opening price) |
| `GET`  | `/markets/{id}` | Market detail + current price |
| `POST` | `/markets/{id}/buy` | Buy YES or NO shares |
| `POST` | `/markets/{id}/sell` | Sell shares |
| `POST` | `/markets/{id}/resolve` | Resolve market YES/NO |

Protected endpoints require `X-User-Id: <uuid>` header.  
Full interactive docs: `http://localhost:8000/docs`
