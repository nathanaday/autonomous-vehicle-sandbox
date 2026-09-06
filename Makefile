# Data: `make data` downloads the 5 GB dataset bundle into data/ (see README).
# `make data-depth` and `make data-splat` add the optional bundles that unlock
# the Depth Anything, fused mesh and Gaussian splat views.
# Development: run `make backend` and `make frontend` in two terminals,
# then open http://localhost:5173.
# Demo: `make demo` builds the UI and serves everything from one process
# at http://localhost:8000.

.PHONY: setup data data-depth data-splat data-all data-bundle splat-setup backend frontend build demo check depth-cache

setup:
	cd backend && uv sync
	cd frontend && npm install

data:
	scripts/sync_data.sh dataset

data-depth:
	scripts/sync_data.sh depth

data-splat:
	scripts/sync_data.sh splat

data-all:
	scripts/sync_data.sh dataset depth splat

# Pack data/ for a release: make data-bundle TAG=data-v3 BUNDLES="depth splat"
data-bundle:
	scripts/bundle_data.sh $(TAG) $(BUNDLES)

# The splat bundle plus the Depth Anything 3 environment for building new
# splats. Viewing cached splats needs only the bundle.
splat-setup: data-splat
	cd tools/da3 && uv sync

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
