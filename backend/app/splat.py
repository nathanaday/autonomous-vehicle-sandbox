"""Gaussian splats from Depth Anything 3, built by a subprocess.

DA3 lives in its own environment under tools/da3 (it pins numpy<2). This
module launches `uv run splat_export.py` there, tails its progress file, and
serves the finished PLY and stats. Results are cached per keyframe and
options under the splat cache directory.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = ROOT / "tools" / "da3"


class SplatBuilder:
    def __init__(self, cache_dir: Path, model_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir = Path(model_dir)
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return (self.model_dir / "model.safetensors").exists() and (TOOL_DIR / "splat_export.py").exists()

    def info(self) -> dict:
        return {
            "model_dir": str(self.model_dir),
            "available": self.available,
            "tool": str(TOOL_DIR / "splat_export.py"),
        }

    @staticmethod
    def key(sample_token: str, views: int, posed: bool) -> str:
        return f"{sample_token[:12]}_v{views}_{'posed' if posed else 'unposed'}"

    def status(self, sample_token: str, views: int, posed: bool) -> dict:
        key = self.key(sample_token, views, posed)
        meta = self.cache_dir / f"{key}.json"
        if meta.exists():
            return {**json.loads(meta.read_text()), "key": key, "state": "ready"}
        with self._lock:
            job = self._jobs.get(key)
            if job is None:
                job = {"state": "running", "progress": 0.0, "message": "starting", "log": []}
                self._jobs[key] = job
                threading.Thread(target=self._run, args=(key, sample_token, views, posed), daemon=True).start()
            elif job["state"] == "running":
                self._refresh(key, job)
            elif job["state"] == "error":
                # report the failure once, then let the next request try again
                self._jobs.pop(key, None)
        return {"key": key, **{k: v for k, v in job.items() if k != "log"}, "tail": job["log"][-3:]}

    def ply_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.ply"

    # ----- subprocess ---------------------------------------------------

    def _refresh(self, key: str, job: dict) -> None:
        p = self.cache_dir / f"{key}.progress.json"
        if p.exists():
            try:
                job.update(json.loads(p.read_text()))
            except json.JSONDecodeError:
                pass  # partially written; next poll gets it

    def _run(self, key: str, sample_token: str, views: int, posed: bool) -> None:
        job = self._jobs[key]
        cmd = [
            "uv", "run", "--project", str(TOOL_DIR), "python", str(TOOL_DIR / "splat_export.py"),
            "--sample", sample_token, "--out", str(self.cache_dir), "--key", key,
            "--views", str(views), "--model", str(self.model_dir),
        ]
        if not posed:
            cmd.append("--unposed")
        t0 = time.time()
        try:
            proc = subprocess.Popen(cmd, cwd=TOOL_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    job["log"].append(line[-300:])
                    job["log"] = job["log"][-60:]
            code = proc.wait()
        except Exception as e:
            job["state"] = "error"
            job["message"] = f"{type(e).__name__}: {e}"
            return
        if code != 0 or not (self.cache_dir / f"{key}.json").exists():
            job["state"] = "error"
            errors = [l for l in job["log"] if "Error" in l or "error" in l]
            job["message"] = (errors[-1] if errors else job["log"][-1] if job["log"] else f"exit code {code}")[:300]
            return
        job["seconds"] = round(time.time() - t0, 1)
        with self._lock:
            self._jobs.pop(key, None)
        (self.cache_dir / f"{key}.progress.json").unlink(missing_ok=True)
