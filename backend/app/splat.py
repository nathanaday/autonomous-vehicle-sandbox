"""Gaussian splats from Depth Anything 3, built by a subprocess.

DA3 lives in its own environment under tools/da3 (it pins numpy<2). This
module launches `uv run splat_export.py` there for a list of keyframes, tails
its progress file, and serves the finished PLY and stats. Results are cached
per keyframe and options under the splat cache directory.

Builds start only when asked. Reading a status never starts one, and at most
one exporter process runs at a time: each load of the 6.8 GB model costs
several GB of memory, and playback once started one per keyframe.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = ROOT / "tools" / "da3"

ACTIVE_STATES = ("running", "cancelling")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def splat_key(sample_token: str, views: int, posed: bool) -> str:
    return f"{sample_token[:12]}_v{views}_{'posed' if posed else 'unposed'}"


class BuildBusy(Exception):
    pass


class SplatBuilder:
    def __init__(self, cache_dir: Path, model_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir = Path(model_dir)
        self._job: dict | None = None  # the running job, or the last one until the next starts
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._clean_up_previous_run()

    @property
    def available(self) -> bool:
        return (self.model_dir / "model.safetensors").exists() and (TOOL_DIR / "splat_export.py").exists()

    def info(self) -> dict:
        return {
            "model_dir": str(self.model_dir),
            "available": self.available,
            "tool": str(TOOL_DIR / "splat_export.py"),
            "job": self.job_status(),
        }

    # ----- reading ------------------------------------------------------

    def ply_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.ply"

    def _meta(self, key: str) -> dict | None:
        path = self.cache_dir / f"{key}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def sample_status(self, sample_token: str, views: int, posed: bool) -> dict:
        """The finished splat's stats, or where the keyframe stands: 'running'
        (being built now), 'queued' (later in the running job), 'missing'."""
        key = splat_key(sample_token, views, posed)
        meta = self._meta(key)
        if meta is not None:
            return {**meta, "key": key, "state": "ready"}
        job = self.job_status()
        if job and job["state"] in ACTIVE_STATES and key in job["keys"]:
            state = "running" if job["current"] and job["current"]["key"] == key else "queued"
            return {"key": key, "state": state, "progress": job["progress"], "message": job["message"]}
        return {"key": key, "state": "missing"}

    def scene_status(self, scene_token: str, sample_tokens: list[str], views: int, posed: bool) -> dict:
        keyframes = []
        for tok in sample_tokens:
            key = splat_key(tok, views, posed)
            keyframes.append({"token": tok, "key": key, "ready": (self.cache_dir / f"{key}.json").exists()})
        return {
            "scene_token": scene_token,
            "views": views,
            "posed": posed,
            "keyframes": keyframes,
            "n_ready": sum(k["ready"] for k in keyframes),
            "n_total": len(keyframes),
            "job": self.job_status(),
        }

    def job_status(self) -> dict | None:
        with self._lock:
            job = self._job
            if job is None:
                return None
            if job["state"] in ACTIVE_STATES:
                self._refresh(job)
                job["seconds"] = round(time.time() - job["started"], 1)
            public = {k: v for k, v in job.items() if k not in ("log", "started")}
            public["tail"] = job["log"][-3:]
            return public

    # ----- building -----------------------------------------------------

    def build(self, label: str, scene_token: str, sample_tokens: list[str], views: int, posed: bool) -> None:
        """Build every keyframe in the list that is not cached, in order, in one
        exporter process. Raises BuildBusy while another build runs."""
        with self._lock:
            if self._job and self._job["state"] in ACTIVE_STATES:
                raise BuildBusy(self._job["label"])
            todo = [tok for tok in sample_tokens if not (self.cache_dir / f"{splat_key(tok, views, posed)}.json").exists()]
            job = {
                "id": self._next_id,
                "label": label,
                "scene_token": scene_token,
                "views": views,
                "posed": posed,
                "keys": [splat_key(tok, views, posed) for tok in todo],
                "state": "running" if todo else "done",
                "total": len(todo),
                "index": 0,
                "current": None,
                "progress": 0.0 if todo else 1.0,
                "message": "starting" if todo else "nothing to build",
                "log": [],
                "started": time.time(),
                "seconds": 0.0,
            }
            self._next_id += 1
            self._job = job
            if todo:
                threading.Thread(target=self._run, args=(job, todo), daemon=True).start()

    def cancel(self) -> bool:
        with self._lock:
            job, proc = self._job, self._proc
            if not job or job["state"] != "running" or proc is None:
                return False
            job["state"] = "cancelling"
            job["message"] = "stopping"
        os.killpg(proc.pid, signal.SIGTERM)  # uv and the python it started
        return True

    def _clean_up_previous_run(self) -> None:
        """A backend restart (uvicorn --reload does one on every edit) leaves
        the exporter of an unfinished build running on its own. Stop it, then
        drop the progress files it and any crashed run left behind."""
        for pid_file in self.cache_dir.glob("job-*.pid"):
            try:
                pid = int(pid_file.read_text())
                cmdline = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
                if "splat_export.py" in cmdline:
                    os.killpg(pid, signal.SIGTERM)
            except (ValueError, ProcessLookupError, PermissionError):
                pass
            pid_file.unlink(missing_ok=True)
        for stale in self.cache_dir.glob("*.progress.json"):
            stale.unlink()

    def _refresh(self, job: dict) -> None:
        p = self.cache_dir / f"job-{job['id']}.progress.json"
        if p.exists():
            try:
                job.update(json.loads(p.read_text()))
            except json.JSONDecodeError:
                pass  # partially written; next poll gets it

    def _run(self, job: dict, sample_tokens: list[str]) -> None:
        progress = self.cache_dir / f"job-{job['id']}.progress.json"
        cmd = [
            "uv", "run", "--project", str(TOOL_DIR), "python", str(TOOL_DIR / "splat_export.py"),
            "--samples", *sample_tokens, "--out", str(self.cache_dir), "--progress", str(progress),
            "--views", str(job["views"]), "--model", str(self.model_dir),
        ]
        if not job["posed"]:
            cmd.append("--unposed")
        pid_file = self.cache_dir / f"job-{job['id']}.pid"
        try:
            proc = subprocess.Popen(cmd, cwd=TOOL_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    start_new_session=True)
            pid_file.write_text(str(proc.pid))
            with self._lock:
                self._proc = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                line = ANSI.sub("", line).rstrip()
                if line:
                    job["log"].append(line[-300:])
                    job["log"] = job["log"][-60:]
            code = proc.wait()
        except Exception as e:
            code = -1
            job["log"].append(f"{type(e).__name__}: {e}")
        with self._lock:
            self._proc = None
            self._refresh(job)
            job["seconds"] = round(time.time() - job["started"], 1)
            job["current"] = None
            built = 0
            for k in job["keys"]:
                if (self.cache_dir / f"{k}.json").exists():
                    built += 1
                else:  # a stopped exporter can leave a half-written keyframe behind
                    for ext in ("ply", "npz"):
                        (self.cache_dir / f"{k}.{ext}").unlink(missing_ok=True)
            job["index"] = built
            if job["state"] == "cancelling":
                job["state"] = "cancelled"
                job["message"] = f"stopped after {built} of {job['total']} keyframes"
            elif code != 0 or built < job["total"]:
                job["state"] = "error"
                errors = [l for l in job["log"] if "Error" in l or "error" in l]
                job["message"] = (errors[-1] if errors else job["log"][-1] if job["log"] else f"exit code {code}")[:300]
            else:
                job["state"] = "done"
                job["progress"] = 1.0
                job["message"] = f"built {built} keyframes in {job['seconds']:.0f} s"
        progress.unlink(missing_ok=True)
        pid_file.unlink(missing_ok=True)
