# Data: `make data` downloads the 4.6 GB bundle and extracts it into data/ (see README).
# Development: run `make backend` and `make frontend` in two terminals,
# then open http://localhost:5173.
# Demo: `make demo` builds the UI and serves everything from one process
# at http://localhost:8000.

.PHONY: setup data data-bundle splat-setup backend frontend build demo check depth-cache

setup:
	cd backend && uv sync
	cd frontend && npm install

data:
	scripts/sync_data.sh

data-bundle:
	scripts/bundle_data.sh $(TAG)

# Optional: the Gaussian splat view. Installs Depth Anything 3 in its own
# environment and downloads its 6.8 GB checkpoint into data/models/da3.
splat-setup:
	cd tools/da3 && uv sync
	scripts/fetch_da3.sh

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

demo: build
	cd backend && uv run uvicorn app.main:app --port 8000

check:
	cd frontend && npx vue-tsc --noEmit

depth-cache:
	cd backend && uv run python -m app.precompute_depth
