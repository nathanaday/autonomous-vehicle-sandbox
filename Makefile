# Viewing: `make setup`, `make data` (the dataset bundle) plus `make data-depth`,
# `make data-fusion`, `make data-splat`, `make data-gs3d` for the precomputed
# results of each view, `make data-occ3d` for the Occ3D labels, then `make backend` and `make frontend` in two
# terminals (or `make demo`).
# Computing: `make compute-setup` once, then `make compute SCENES="scene-0061"`.
# Training splats needs a CUDA machine: `make gs3d-export`, then `make
# gs3d-push gs3d-setup gs3d-train gs3d-pull` with GS3D_HOST=user@host.

.PHONY: setup data data-depth data-fusion data-splat data-gs3d data-occ3d data-all data-bundle compute-setup models compute backend frontend build demo check \
	gs3d-export gs3d-push gs3d-setup gs3d-train gs3d-log gs3d-pull

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

data-gs3d:
	scripts/sync_data.sh gs3d

data-occ3d:
	scripts/sync_data.sh occ3d

data-all:
	scripts/sync_data.sh dataset depth fusion splat gs3d occ3d

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

# ----- trained Gaussian splats: export here, train on a CUDA machine -----
# make gs3d-export SCENES="scene-0061" [GS3D_ARGS="--sweeps"]   writes data/gs3d/<scene>_<kf|sweeps>_m1
# make gs3d-push GS3D_HOST=ubuntu@1.2.3.4    copies compute/gs3d and data/gs3d to ~/av-gs3d on the machine
# make gs3d-setup GS3D_HOST=...              clones and builds the official trainer there, once
# make gs3d-train GS3D_HOST=... EXPORT=scene-0061_kf_m1 [GS3D_TRAIN_ARGS="--no-depth"]   starts a run in the background
# make gs3d-log GS3D_HOST=...                follows the runs' logs
# make gs3d-pull GS3D_HOST=...               fetches the results into data/cache/gs3d
GS3D_HOST ?=
GS3D_REMOTE ?= av-gs3d
GS3D_ARGS ?=
GS3D_TRAIN_ARGS ?=
EXPORT ?= $(firstword $(SCENES))_kf_m1

gs3d-export:
	uv run --project backend python compute/gs3d/export.py $(foreach s,$(SCENES),--scene $(s)) $(GS3D_ARGS)

gs3d-push:
	@test -n "$(GS3D_HOST)" || { echo "set GS3D_HOST=user@host"; exit 1; }
	ssh $(GS3D_HOST) 'mkdir -p $(GS3D_REMOTE)/export'
	rsync -az --progress --exclude __pycache__ compute/gs3d/ $(GS3D_HOST):$(GS3D_REMOTE)/gs3d/
	rsync -az --progress data/gs3d/ $(GS3D_HOST):$(GS3D_REMOTE)/export/

gs3d-setup:
	@test -n "$(GS3D_HOST)" || { echo "set GS3D_HOST=user@host"; exit 1; }
	ssh -t $(GS3D_HOST) 'bash $(GS3D_REMOTE)/gs3d/setup_remote.sh'

gs3d-train:
	@test -n "$(GS3D_HOST)" || { echo "set GS3D_HOST=user@host"; exit 1; }
	ssh $(GS3D_HOST) 'cd $(GS3D_REMOTE) && mkdir -p runs && nohup .venv/bin/python gs3d/train.py $(addprefix export/,$(EXPORT)) $(GS3D_TRAIN_ARGS) > runs/train.log 2>&1 < /dev/null & echo "started; make gs3d-log to follow"'

gs3d-log:
	@test -n "$(GS3D_HOST)" || { echo "set GS3D_HOST=user@host"; exit 1; }
	ssh $(GS3D_HOST) 'tail -n 30 -f $(GS3D_REMOTE)/runs/train.log'

gs3d-pull:
	@test -n "$(GS3D_HOST)" || { echo "set GS3D_HOST=user@host"; exit 1; }
	mkdir -p data/cache/gs3d
	rsync -az --progress $(GS3D_HOST):$(GS3D_REMOTE)/cache/gs3d/ data/cache/gs3d/

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
