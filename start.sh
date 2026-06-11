#!/usr/bin/env bash
# start.sh — launch backend + frontend in one terminal
# Usage: ./start.sh [--seed]
#   --seed   wipe & re-seed the database before starting (runs seed.py)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"

# ── Activate virtual environment ──────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "Virtual environment not found. Run: make setup"
  exit 1
fi
source "$VENV/bin/activate"

# ── Optional seed ─────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--seed" ]]; then
  echo "Seeding database..."
  python seed.py
  echo ""
fi

# ── Cleanup on exit ───────────────────────────────────────────────────────────
cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo "Done."
}
trap cleanup EXIT INT TERM

# ── Backend ───────────────────────────────────────────────────────────────────
echo "[backend]  starting on http://localhost:8000"
uvicorn market.api.main:app --reload --port 8000 2>&1 | sed 's/^/[backend]  /' &
BACKEND_PID=$!

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "[frontend] starting on http://localhost:3000"
(cd "$ROOT/frontend" && npm run dev 2>&1 | sed 's/^/[frontend] /') &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:8000  (API docs: http://localhost:8000/docs)"
echo "  Frontend: http://localhost:3000"
echo ""
echo "  Press Ctrl+C to stop both."
echo ""

# Wait for both processes (Ctrl+C triggers the trap above)
wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
