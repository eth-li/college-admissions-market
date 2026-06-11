.PHONY: setup dev seed backend frontend clean

VENV      = .venv
PYTHON    = $(VENV)/bin/python
PIP       = $(VENV)/bin/pip
UVICORN   = $(VENV)/bin/uvicorn

# ── First-time setup ──────────────────────────────────────────────────────────
setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r market/requirements.txt
	$(PIP) install -r model/requirements.txt
	cd frontend && npm install
	@echo ""
	@echo "Setup complete. Run 'make dev' to start."

# ── Run everything (one terminal) ─────────────────────────────────────────────
dev:
	@chmod +x start.sh && ./start.sh

# ── Wipe DB and re-seed, then start ───────────────────────────────────────────
seed-dev:
	@chmod +x start.sh && ./start.sh --seed

# ── Seed only (no server start) ───────────────────────────────────────────────
seed:
	source $(VENV)/bin/activate && python seed.py

# ── Run services individually ─────────────────────────────────────────────────
backend:
	source $(VENV)/bin/activate && uvicorn market.api.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	rm -rf $(VENV)
	rm -rf frontend/node_modules frontend/.next
	rm -f market.db
