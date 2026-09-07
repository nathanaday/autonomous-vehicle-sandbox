"""Minimal nuScenes reader.

Loads the JSON tables of one split into memory, indexes them by token, and
exposes the geometry needed to put every sensor of a keyframe into one common
frame: the ego vehicle frame at the LIDAR_TOP timestamp of that keyframe.

Frames follow nuScenes conventions: x forward, y left, z up. Quaternions are
[w, x, y, z]. Every 4x4 matrix maps a column vector from the frame named first
to the frame named second, e.g. `sensor_to_ego`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np

TABLES = [
    "scene", "log", "sensor", "calibrated_sensor", "sample", "sample_data",
    "ego_pose", "sample_annotation", "category", "attribute", "visibility",
    "instance", "map",
]

CAMERA_CHANNELS = [
    "CAM_FRONT_LEFT", "CAM_FRONT", "CAM_FRONT_RIGHT",
    "CAM_BACK_LEFT", "CAM_BACK", "CAM_BACK_RIGHT",
]
RADAR_CHANNELS = [
    "RADAR_FRONT_LEFT", "RADAR_FRONT", "RADAR_FRONT_RIGHT",
    "RADAR_BACK_LEFT", "RADAR_BACK_RIGHT",
]
LIDAR_CHANNEL = "LIDAR_TOP"

RADAR_PCD_DTYPE = np.dtype([
    ("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("dyn_prop", "i1"), ("id", "<i2"),
    ("rcs", "<f4"), ("vx", "<f4"), ("vy", "<f4"), ("vx_comp", "<f4"), ("vy_comp", "<f4"),
    ("is_quality_valid", "i1"), ("ambig_state", "i1"), ("x_rms", "i1"), ("y_rms", "i1"),
    ("invalid_state", "i1"), ("pdh0", "i1"), ("vx_rms", "i1"), ("vy_rms", "i1"),
])

RADAR_DYN_PROP = [
    "moving", "stationary", "oncoming", "stationary candidate",
    "unknown", "crossing stationary", "crossing moving", "stopped",
]


def quat_to_mat(q) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def pose_to_mat(record) -> np.ndarray:
    """calibrated_sensor / ego_pose / annotation record -> 4x4 homogeneous."""
    m = np.eye(4)
    m[:3, :3] = quat_to_mat(record["rotation"])
    m[:3, 3] = record["translation"]
    return m


def apply(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Apply a 4x4 to an (N,3) array of points."""
    return pts @ m[:3, :3].T + m[:3, 3]


def yaw_of(m: np.ndarray) -> float:
    return float(np.arctan2(m[1, 0], m[0, 0]))


@dataclass
class Frame:
    """Everything about one keyframe, expressed in the reference ego frame."""

    sample: dict
    ref_to_global: np.ndarray
    lidar_sd: dict
    camera_sds: dict[str, dict]
    radar_sds: dict[str, dict]


class NuScenes:
    def __init__(self, dataroot: Path, version: str = "v1.0-mini"):
        self.dataroot = Path(dataroot)
        self.version = version
        table_dir = self.dataroot / version
        self.table: dict[str, list[dict]] = {
            t: json.loads((table_dir / f"{t}.json").read_text()) for t in TABLES
        }
        self.by_token: dict[str, dict[str, dict]] = {
            t: {r["token"]: r for r in rows} for t, rows in self.table.items()
        }
        self._index()
        self._keep_scenes_on_disk()

    def get(self, table: str, token: str) -> dict:
        return self.by_token[table][token]

    def _index(self) -> None:
        self.channel_of_cs: dict[str, str] = {}
        for cs in self.table["calibrated_sensor"]:
            self.channel_of_cs[cs["token"]] = self.get("sensor", cs["sensor_token"])["channel"]

        self.keyframe_sd: dict[str, dict[str, dict]] = {}
        self.sweep_counts: dict[str, dict[str, int]] = {}
        for sd in self.table["sample_data"]:
            channel = self.channel_of_cs[sd["calibrated_sensor_token"]]
            if sd["is_key_frame"]:
                self.keyframe_sd.setdefault(sd["sample_token"], {})[channel] = sd
            else:
                scene_token = self.get("sample", sd["sample_token"])["scene_token"]
                counts = self.sweep_counts.setdefault(scene_token, {})
                counts[channel] = counts.get(channel, 0) + 1

        self.annotations_of_sample: dict[str, list[dict]] = {}
        for ann in self.table["sample_annotation"]:
            self.annotations_of_sample.setdefault(ann["sample_token"], []).append(ann)

        self.samples_of_scene: dict[str, list[dict]] = {}
        for scene in self.table["scene"]:
            samples = []
            token = scene["first_sample_token"]
            while token:
                sample = self.get("sample", token)
                samples.append(sample)
                token = sample["next"]
            self.samples_of_scene[scene["token"]] = samples

    def _keep_scenes_on_disk(self) -> None:
        """The tables list every scene of the split, but a data bundle may
        carry the files of only a few. Keep the scenes whose keyframes exist."""
        def present(scene: dict) -> bool:
            first = self.samples_of_scene[scene["token"]][0]
            sd = self.keyframe_sd[first["token"]]["CAM_FRONT"]
            return (self.dataroot / sd["filename"]).exists()

        self.table["scene"] = [s for s in self.table["scene"] if present(s)]
        self.by_token["scene"] = {s["token"]: s for s in self.table["scene"]}

    # ----- scenes -------------------------------------------------------

    def scene_summary(self, scene: dict) -> dict:
        log = self.get("log", scene["log_token"])
        samples = self.samples_of_scene[scene["token"]]
        first = samples[0]
        instance_tokens = set()
        category_counts: dict[str, int] = {}
        for s in samples:
            for ann in self.annotations_of_sample.get(s["token"], []):
                instance_tokens.add(ann["instance_token"])
        for tok in instance_tokens:
            inst = self.get("instance", tok)
            name = self.get("category", inst["category_token"])["name"]
            category_counts[name] = category_counts.get(name, 0) + 1
        desc = scene["description"].lower()
        tags = []
        if "night" in desc:
            tags.append("night")
        if "rain" in desc:
            tags.append("rain")
        duration_s = (samples[-1]["timestamp"] - first["timestamp"]) / 1e6
        return {
            "token": scene["token"],
            "name": scene["name"],
            "description": scene["description"],
            "location": log["location"],
            "date_captured": log["date_captured"],
            "vehicle": log["vehicle"],
            "logfile": log["logfile"],
            "nbr_samples": scene["nbr_samples"],
            "duration_s": round(duration_s, 2),
            "first_sample_token": first["token"],
            "thumbnail_sd_token": self.keyframe_sd[first["token"]]["CAM_FRONT"]["token"],
            "tags": tags,
            "nbr_instances": len(instance_tokens),
            "category_counts": dict(sorted(category_counts.items(), key=lambda kv: -kv[1])),
            "sweep_counts": self.sweep_counts.get(scene["token"], {}),
        }

    def scene_detail(self, scene_token: str) -> dict:
        scene = self.get("scene", scene_token)
        summary = self.scene_summary(scene)
        samples = []
        for s in self.samples_of_scene[scene_token]:
            lidar_sd = self.keyframe_sd[s["token"]][LIDAR_CHANNEL]
            pose = self.get("ego_pose", lidar_sd["ego_pose_token"])
            samples.append({
                "token": s["token"],
                "timestamp": s["timestamp"],
                "ego_translation": pose["translation"],
                "ego_rotation": pose["rotation"],
                "nbr_annotations": len(self.annotations_of_sample.get(s["token"], [])),
            })
        first_sample = self.samples_of_scene[scene_token][0]
        sensors = []
        for channel, sd in self.keyframe_sd[first_sample["token"]].items():
            cs = self.get("calibrated_sensor", sd["calibrated_sensor_token"])
            sensor = self.get("sensor", cs["sensor_token"])
            sensors.append({
                "channel": channel,
                "modality": sensor["modality"],
                "translation": cs["translation"],
                "rotation": cs["rotation"],
                "camera_intrinsic": cs["camera_intrinsic"],
                "width": sd["width"],
                "height": sd["height"],
                "fileformat": sd["fileformat"],
            })
        sensors.sort(key=lambda s: (s["modality"], s["channel"]))
        return {**summary, "samples": samples, "sensors": sensors}

    def moving_instances(self, scene_token: str, threshold_m: float = 1.0) -> set[str]:
        """Instances whose annotated position changes by more than the
        threshold over the scene. Parked cars stay; driving cars and walking
        people go."""
        first: dict[str, np.ndarray] = {}
        span: dict[str, float] = {}
        for sample in self.samples_of_scene[scene_token]:
            for ann in self.annotations_of_sample.get(sample["token"], []):
                p = np.array(ann["translation"])
                tok = ann["instance_token"]
                if tok not in first:
                    first[tok] = p
                    span[tok] = 0.0
                else:
                    span[tok] = max(span[tok], float(np.linalg.norm(p - first[tok])))
        return {tok for tok, d in span.items() if d > threshold_m}

    # ----- frames -------------------------------------------------------

    def frame(self, sample_token: str) -> Frame:
        sample = self.get("sample", sample_token)
        sds = self.keyframe_sd[sample_token]
        lidar_sd = sds[LIDAR_CHANNEL]
        ref_to_global = pose_to_mat(self.get("ego_pose", lidar_sd["ego_pose_token"]))
        return Frame(
            sample=sample,
            ref_to_global=ref_to_global,
            lidar_sd=lidar_sd,
            camera_sds={c: sds[c] for c in CAMERA_CHANNELS if c in sds},
            radar_sds={c: sds[c] for c in RADAR_CHANNELS if c in sds},
        )

    def sensor_to_ref(self, frame: Frame, sd: dict) -> np.ndarray:
        """sensor frame at the sensor's own timestamp -> reference ego frame."""
        cs = self.get("calibrated_sensor", sd["calibrated_sensor_token"])
        ego_to_global = pose_to_mat(self.get("ego_pose", sd["ego_pose_token"]))
        return np.linalg.inv(frame.ref_to_global) @ ego_to_global @ pose_to_mat(cs)

    def frame_detail(self, sample_token: str) -> dict:
        frame = self.frame(sample_token)
        sample = frame.sample
        scene = self.get("scene", sample["scene_token"])
        samples = self.samples_of_scene[scene["token"]]
        index = next(i for i, s in enumerate(samples) if s["token"] == sample_token)
        global_to_ref = np.linalg.inv(frame.ref_to_global)
        t0 = sample["timestamp"]

        cameras = []
        for channel, sd in frame.camera_sds.items():
            cs = self.get("calibrated_sensor", sd["calibrated_sensor_token"])
            cam_to_ref = self.sensor_to_ref(frame, sd)
            cameras.append({
                "channel": channel,
                "sd_token": sd["token"],
                "filename": sd["filename"],
                "timestamp": sd["timestamp"],
                "dt_ms": round((sd["timestamp"] - t0) / 1e3, 1),
                "width": sd["width"],
                "height": sd["height"],
                "intrinsic": cs["camera_intrinsic"],
                "translation": cs["translation"],
                "rotation": cs["rotation"],
                "cam_to_ref": cam_to_ref.tolist(),
                "ref_to_cam": np.linalg.inv(cam_to_ref).tolist(),
            })

        radars = []
        for channel, sd in frame.radar_sds.items():
            cs = self.get("calibrated_sensor", sd["calibrated_sensor_token"])
            raw, kept = self.read_radar(frame, sd)
            radars.append({
                "channel": channel,
                "sd_token": sd["token"],
                "filename": sd["filename"],
                "timestamp": sd["timestamp"],
                "dt_ms": round((sd["timestamp"] - t0) / 1e3, 1),
                "translation": cs["translation"],
                "rotation": cs["rotation"],
                "yaw_deg": round(np.degrees(yaw_of(pose_to_mat(cs))), 1),
                "nbr_points_raw": int(raw),
                "nbr_points": int(len(kept)),
            })

        lidar_cs = self.get("calibrated_sensor", frame.lidar_sd["calibrated_sensor_token"])
        lidar_pts = self.read_lidar(frame)
        lidar = {
            "channel": LIDAR_CHANNEL,
            "sd_token": frame.lidar_sd["token"],
            "filename": frame.lidar_sd["filename"],
            "timestamp": frame.lidar_sd["timestamp"],
            "dt_ms": 0.0,
            "translation": lidar_cs["translation"],
            "rotation": lidar_cs["rotation"],
            "nbr_points": int(len(lidar_pts)),
        }

        annotations = []
        for ann in self.annotations_of_sample.get(sample_token, []):
            inst = self.get("instance", ann["instance_token"])
            box_to_ref = global_to_ref @ pose_to_mat(ann)
            annotations.append({
                "token": ann["token"],
                "instance_token": ann["instance_token"],
                "category": self.get("category", inst["category_token"])["name"],
                "attributes": [self.get("attribute", t)["name"] for t in ann["attribute_tokens"]],
                "visibility": self.get("visibility", ann["visibility_token"])["level"],
                "center": box_to_ref[:3, 3].tolist(),
                "size": ann["size"],  # width (y), length (x), height (z)
                "yaw": yaw_of(box_to_ref),
                "num_lidar_pts": ann["num_lidar_pts"],
                "num_radar_pts": ann["num_radar_pts"],
            })

        trajectory = []
        for s in samples:
            sd = self.keyframe_sd[s["token"]][LIDAR_CHANNEL]
            ego_to_global = pose_to_mat(self.get("ego_pose", sd["ego_pose_token"]))
            ego_in_ref = global_to_ref @ ego_to_global
            trajectory.append({
                "token": s["token"],
                "position": ego_in_ref[:3, 3].tolist(),
                "yaw": yaw_of(ego_in_ref),
                "t_s": round((s["timestamp"] - samples[0]["timestamp"]) / 1e6, 3),
            })

        ego_pose = self.get("ego_pose", frame.lidar_sd["ego_pose_token"])
        return {
            "token": sample_token,
            "scene_token": scene["token"],
            "scene_name": scene["name"],
            "index": index,
            "count": len(samples),
            "timestamp": t0,
            "t_s": round((t0 - samples[0]["timestamp"]) / 1e6, 3),
            "prev": sample["prev"] or None,
            "next": sample["next"] or None,
            "ego_pose": {
                "translation": ego_pose["translation"],
                "rotation": ego_pose["rotation"],
                "ref_to_global": frame.ref_to_global.tolist(),
            },
            "cameras": cameras,
            "lidar": lidar,
            "radars": radars,
            "annotations": annotations,
            "trajectory": trajectory,
        }

    # ----- point clouds -------------------------------------------------

    def read_lidar(self, frame: Frame) -> np.ndarray:
        """(N,5) float32: x y z intensity ring, in the reference ego frame."""
        path = self.dataroot / frame.lidar_sd["filename"]
        pts = np.fromfile(path, dtype=np.float32).reshape(-1, 5)
        out = pts.copy()
        out[:, :3] = apply(self.sensor_to_ref(frame, frame.lidar_sd), pts[:, :3])
        return out

    def read_radar(self, frame: Frame, sd: dict) -> tuple[int, np.ndarray]:
        """Returns (raw count, (N,8) float32) with columns
        x y z vx vy rcs dyn_prop channel_index, in the reference ego frame.

        Filtering follows the devkit defaults: invalid_state == 0 and
        ambig_state == 3 (stationary and moving targets that were resolved).
        """
        path = self.dataroot / sd["filename"]
        raw = path.read_bytes()
        header_end = raw.index(b"DATA binary\n") + len(b"DATA binary\n")
        header = raw[:header_end].decode()
        n = int(next(line for line in header.splitlines() if line.startswith("POINTS")).split()[1])
        rec = np.frombuffer(raw, dtype=RADAR_PCD_DTYPE, count=n, offset=header_end)
        keep = (rec["invalid_state"] == 0) & (rec["ambig_state"] == 3)
        rec = rec[keep]
        m = self.sensor_to_ref(frame, sd)
        xyz = apply(m, np.stack([rec["x"], rec["y"], rec["z"]], axis=1).astype(np.float64))
        vel = np.stack([rec["vx_comp"], rec["vy_comp"], np.zeros(len(rec))], axis=1) @ m[:3, :3].T
        out = np.empty((len(rec), 8), dtype=np.float32)
        out[:, :3] = xyz
        out[:, 3:5] = vel[:, :2]
        out[:, 5] = rec["rcs"]
        out[:, 6] = rec["dyn_prop"]
        out[:, 7] = RADAR_CHANNELS.index(self.channel_of_cs[sd["calibrated_sensor_token"]])
        return n, out

    def read_all_radar(self, frame: Frame) -> np.ndarray:
        parts = [self.read_radar(frame, sd)[1] for sd in frame.radar_sds.values()]
        return np.concatenate(parts) if parts else np.empty((0, 8), dtype=np.float32)
