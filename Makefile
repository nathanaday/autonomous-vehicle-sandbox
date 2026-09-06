# Viewing: `make setup`, `make data` (the dataset bundle) plus `make data-depth`,
# `make data-fusion`, `make data-splat` for the precomputed results of each
# view, then `make backend` and `make frontend` in two terminals (or `make demo`).
# Computing: `make compute-setup` once, then `make compute SCENES="scene-0061"`.

.PHONY: setup data data-depth data-fusion data-splat data-all data-bundle compute-setup models compute backend frontend build demo check

SCENES ?= scene-0061 scene-0103 scene-1094
TASK ?= all

setup:
	cd backend && uv sync
	cd frontend && npm install

data:
	scripts/sync_data.sh dataset

data-depth:
	scripts/sync_data.sh depth

data-fusion:
	scripts/sync_data.sh fusion

data-splat:
	scripts/sync_data.sh splat

data-all:
	scripts/sync_data.sh dataset depth fusion splat

# Pack data/ for a release: make data-bundle TAG=data-v3 BUNDLES="depth splat"
data-bundle:
	SCENES="$(SCENES)" scripts/bundle_data.sh $(TAG) $(BUNDLES)

# The compute side: its own environment (torch, open3d, Depth Anything 3) and
# both checkpoints, 7.2 GB. Only needed to compute results, not to view them.
compute-setup: models
	cd compute && uv sync

models:
	scripts/fetch_models.sh

# make compute SCENES="scene-0061 scene-0103" TASK=depth
compute:
	cd compute && uv run python cli.py $(TASK) $(foreach s,$(SCENES),--scene $(s))

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
