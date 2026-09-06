"""Run Depth Anything 3 on the cameras of one nuScenes keyframe and export a
Gaussian splat in the ego frame of that keyframe.

    uv run python splat_export.py --sample <token> --out <dir> [--views 6|18] [--unposed]

Runs in its own environment (see pyproject.toml) because DA3 pins numpy<2.
Only numpy and the JSON tables are shared with the backend, through
backend/app/nuscenes.py.

Outputs, all named <key>.*:
  .ply            3DGS-format Gaussians (Spark, SuperSplat, etc. read it)
  .npz            metric depth, sky mask and confidence per view, float16
  .json           stats: per-view depth error against lidar, pose error when
                  unposed, Gaussian count, timings
  .progress.json  written during the run so the backend can show progress
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # torch and open3d both ship libomp
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np
import torch
from PIL import Image
from plyfile import PlyData, PlyElement

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.nuscenes import CAMERA_CHANNELS, NuScenes, apply  # noqa: E402

DEFAULT_MODEL = ROOT / "data" / "models" / "da3" / "DA3NESTED-GIANT-LARGE-1.1"
DEFAULT_DATAROOT = ROOT / "data" / "nuscenes"

MIN_DEPTH, MAX_DEPTH = 1.0, 80.0


def log(progress_path: Path, p: float, msg: str) -> None:
    progress_path.write_text(json.dumps({"progress": round(p, 3), "message": msg}))
    print(f"[{p * 100:5.1f}%] {msg}", flush=True)


def pick_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


# ----- small quaternion / pose helpers (numpy) ---------------------------


def mat_to_quat_wxyz(R: np.ndarray) -> np.ndarray:
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        return np.array([0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s])
    i = int(np.argmax(np.diag(R)))
    if i == 0:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        return np.array([(R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s])
    if i == 1:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        return np.array([(R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s])
    s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
    return np.array([(R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s])


def quat_mul_wxyz(q: np.ndarray, r: np.ndarray) -> np.ndarray:
    """q (4,) times r (N,4), both wxyz."""
    w1, x1, y1, z1 = q
    w2, x2, y2, z2 = r[:, 0], r[:, 1], r[:, 2], r[:, 3]
    return np.stack([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ], axis=1)


def umeyama(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Similarity (s, R, t) with dst ~ s R src + t."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    cov = xd.T @ xs / len(src)
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1
    R = U @ S @ Vt
    var_s = (xs ** 2).sum() / len(src)
    s = float((D * np.diag(S)).sum() / var_s)
    t = mu_d - s * R @ mu_s
    return s, R, t


def rotation_error_deg(Ra: np.ndarray, Rb: np.ndarray) -> float:
    c = np.clip((np.trace(Ra.T @ Rb) - 1) / 2, -1, 1)
    return float(np.degrees(np.arccos(c)))


# ----- main --------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True, help="nuScenes sample token of the keyframe")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--key", required=True, help="basename for the output files")
    ap.add_argument("--views", type=int, default=6, choices=(6, 18), help="6: this keyframe; 18: with its neighbours")
    ap.add_argument("--unposed", action="store_true", help="let DA3 estimate the camera poses instead of using calibration")
    ap.add_argument("--res", type=int, default=504, help="DA3 processing resolution (long side)")
    ap.add_argument("--scale-mult", type=float, default=0.7, help="multiply every Gaussian's size; below 1 is crisper with more gaps")
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--dataroot", default=str(DEFAULT_DATAROOT))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    progress = out / f"{args.key}.progress.json"
    t_start = time.perf_counter()
    log(progress, 0.02, "loading nuScenes tables")

    nusc = NuScenes(Path(args.dataroot))
    frame = nusc.frame(args.sample)
    sample = frame.sample

    # views: the six cameras of this keyframe, optionally the neighbours too,
    # all expressed in this keyframe's ego frame
    frames = [frame]
    if args.views == 18:
        for tok in (sample["prev"], sample["next"]):
            if tok:
                frames.append(nusc.frame(tok))
    global_to_ref = np.linalg.inv(frame.ref_to_global)

    images, K_in, w2c_in, view_meta = [], [], [], []
    for f in frames:
        f_to_ref = global_to_ref @ f.ref_to_global
        for ch in CAMERA_CHANNELS:
            sd = f.camera_sds[ch]
            cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
            cam_to_ref = f_to_ref @ nusc.sensor_to_ref(f, sd)
            images.append(str(nusc.dataroot / sd["filename"]))
            K_in.append(np.array(cs["camera_intrinsic"], dtype=np.float64))
            w2c_in.append(np.linalg.inv(cam_to_ref))
            view_meta.append({"channel": ch, "sample_token": f.sample["token"], "sd_token": sd["token"]})
    K_in = np.stack(K_in)
    w2c_in = np.stack(w2c_in)

    # ----- model -----
    log(progress, 0.05, "loading Depth Anything 3 (1.4B parameters)")
    from depth_anything_3.api import DepthAnything3

    device = pick_device()
    if device.type == "mps":
        # e3nn's Wigner-D rotation of the SH coefficients builds complex tensors,
        # which MPS cannot do. Run that one step on the CPU.
        import depth_anything_3.model.gs_adapter as gsa

        _rotate_sh = gsa.rotate_sh

        def rotate_sh_cpu(sh, rotations):
            with torch.device("cpu"):
                return _rotate_sh(sh.detach().cpu(), rotations.detach().cpu()).to(sh.device)

        gsa.rotate_sh = rotate_sh_cpu

    t0 = time.perf_counter()
    model = DepthAnything3.from_pretrained(args.model).to(device).eval()
    t_load = time.perf_counter() - t0

    # The nested model computes a sky mask in its metric branch but does not
    # return it. Attach it to the output so sky Gaussians can be dropped.
    nested = model.model
    _handle_sky = nested._handle_sky_regions

    def handle_sky_and_keep_mask(output, metric_output, **kw):
        out = _handle_sky(output, metric_output, **kw)
        out["sky"] = metric_output.sky
        return out

    nested._handle_sky_regions = handle_sky_and_keep_mask

    # Record the camera poses the Gaussian adapter used, so each Gaussian can be
    # mapped from the model's world into ours through its own camera.
    import depth_anything_3.model.gs_adapter as gsa

    adapter_inputs: dict = {}
    _adapter_forward = gsa.GaussianAdapter.forward

    def adapter_forward(self, extrinsics, intrinsics, depths, opacities, raw_gaussians, image_shape,
                        eps=1e-8, gt_extrinsics=None, **kw):
        adapter_inputs["extrinsics"] = extrinsics.detach().float().cpu().numpy()[0]
        return _adapter_forward(self, extrinsics, intrinsics, depths, opacities, raw_gaussians, image_shape,
                                eps, gt_extrinsics, **kw)

    gsa.GaussianAdapter.forward = adapter_forward

    # DA3's forward uses CUDA autocast; on MPS or CPU run in float32 instead.
    def forward_fp32(image, extrinsics=None, intrinsics=None, export_feat_layers=None,
                     infer_gs=False, use_ray_pose=False, ref_view_strategy="saddle_balanced"):
        with torch.inference_mode():
            return model.model(image, extrinsics, intrinsics, export_feat_layers, infer_gs, use_ray_pose, ref_view_strategy)

    if device.type != "cuda":
        model.forward = forward_fp32

    log(progress, 0.15, f"running DA3 on {len(images)} views ({device.type})")
    t0 = time.perf_counter()
    # align_to_input_ext_scale=False: the API would otherwise rescale the metric
    # depth by a similarity fit between predicted and given camera centres. Our
    # six cameras sit within about a metre of each other, so that fit is
    # ill-conditioned (it halved the depth in tests). The metric branch is the
    # better source of scale, so keep it.
    pred = model.inference(
        images,
        extrinsics=None if args.unposed else w2c_in.astype(np.float32),
        intrinsics=None if args.unposed else K_in.astype(np.float32),
        infer_gs=True,
        process_res=args.res,
        align_to_input_ext_scale=False,
    )
    t_infer = time.perf_counter() - t0
    log(progress, 0.75, "aligning Gaussians to the ego frame")

    n, h, w = pred.depth.shape
    K_proc = pred.intrinsics.astype(np.float64)  # (n,3,3) at processed resolution

    # Poses used for export. Posed: our calibration. Unposed: DA3's estimate,
    # anchored so the estimated front camera coincides with the calibrated one;
    # the other five then show how far the estimate drifts. A similarity fit over
    # all six centres would be ill-conditioned for cameras this close together.
    pose_report = None
    if args.unposed:
        ext = pred.extrinsics
        if ext.shape[1] == 3:
            ext = np.concatenate([ext, np.tile([[[0, 0, 0, 1]]], (n, 1, 1))], axis=1)
        c2w_pred = np.linalg.inv(ext)
        c2w_in = np.linalg.inv(w2c_in)
        T = c2w_in[0] @ np.linalg.inv(c2w_pred[0])
        c2w_export = T @ c2w_pred
        pose_report = {
            "anchor": view_meta[0]["channel"],
            "rotation_error_deg": [rotation_error_deg(c2w_export[i, :3, :3], c2w_in[i, :3, :3]) for i in range(n)],
            "position_error_m": [float(np.linalg.norm(c2w_export[i, :3, 3] - c2w_in[i, :3, 3])) for i in range(n)],
        }
    else:
        c2w_export = np.linalg.inv(w2c_in)
    if pred.intrinsics is None:
        raise SystemExit("DA3 returned no intrinsics")

    # ----- Gaussians: re-express in the export frame -----
    # The adapter places Gaussian i at C_model + ray_i * d_i in the any-view
    # model's world. In tests those d_i disagreed with the metric depth map by
    # a factor of 1.4 to 2.5 with a wide spread, while the ray directions matched
    # to a fraction of a degree. So: keep the model's rays, colors, opacities and
    # shapes, but put every Gaussian on the metric depth map along calibrated
    # rays. Positions then agree with the depth we evaluate against lidar.
    g = pred.gaussians
    means = g.means[0].float().cpu().numpy().reshape(n, h, w, 3)
    scales = g.scales[0].float().cpu().numpy().reshape(n, h, w, 3)
    rots = g.rotations[0].float().cpu().numpy().reshape(n, h, w, 4)  # wxyz, model world
    sh_dc = g.harmonics[0][..., 0].float().cpu().numpy().reshape(n, h, w, 3)
    opac = g.opacities[0].float().cpu().numpy().reshape(n, h, w)

    ext_model = adapter_inputs["extrinsics"]
    if ext_model.shape[1] == 3:
        ext_model = np.concatenate([ext_model, np.tile([[[0, 0, 0, 1]]], (n, 1, 1))], axis=1)
    c2w_model = np.linalg.inv(ext_model)

    out_means = np.empty_like(means)
    out_scales = np.empty_like(scales)
    out_rots = np.empty_like(rots)
    depth_final = pred.depth  # (n,h,w) metric z-depth
    for i in range(n):
        C_m, R_m = c2w_model[i, :3, 3], c2w_model[i, :3, :3]
        C_o, R_o = c2w_export[i, :3, 3], c2w_export[i, :3, :3]
        rel = means[i].reshape(-1, 3) - C_m
        dist_m = np.linalg.norm(rel, axis=1) + 1e-9
        ray_cam = (rel @ R_m) / dist_m[:, None]  # unit ray in camera coords, with the head's xy offsets
        z = depth_final[i].reshape(-1)
        ray_z = np.maximum(ray_cam[:, 2], 1e-3)
        pt_cam = ray_cam * (z / ray_z)[:, None]  # metric z-depth along that ray
        out_means[i] = (pt_cam @ R_o.T + C_o).reshape(h, w, 3)
        ratio = np.linalg.norm(pt_cam, axis=1) / dist_m
        out_scales[i] = scales[i] * ratio.reshape(h, w, 1) * args.scale_mult
        q_rel = mat_to_quat_wxyz(R_o @ R_m.T)
        out_rots[i] = quat_mul_wxyz(q_rel, rots[i].reshape(-1, 4)).reshape(h, w, 4)
        good = np.isfinite(ratio) & (z > MIN_DEPTH) & (z < MAX_DEPTH)
        view_meta[i]["model_position_ratio"] = float(np.median(ratio[good])) if good.any() else None

    # ----- prune -----
    keep = np.ones((n, h, w), dtype=bool)
    trim_h, trim_w = int(8 / 256 * h), int(8 / 256 * w)
    keep[:, :trim_h, :] = keep[:, -trim_h:, :] = False
    keep[:, :, :trim_w] = keep[:, :, -trim_w:] = False
    if pred.sky is not None:
        keep &= ~pred.sky
    keep &= (depth_final > MIN_DEPTH) & (depth_final < MAX_DEPTH)
    keep &= opac > 0.02
    n_keep = int(keep.sum())

    # ----- depth against lidar, per view, no fitting -----
    lidar_ref = {f.sample["token"]: nusc.read_lidar(f) for f in frames}
    ref_to_this = {f.sample["token"]: global_to_ref @ f.ref_to_global for f in frames}
    for i, vm in enumerate(view_meta):
        pts = apply(ref_to_this[vm["sample_token"]], lidar_ref[vm["sample_token"]][:, :3])
        cam = apply(np.linalg.inv(c2w_export[i]), pts)
        zc = cam[:, 2]
        ok = (zc > MIN_DEPTH) & (zc < MAX_DEPTH)
        cam, zc = cam[ok], zc[ok]
        K = K_proc[i]
        u = K[0, 0] * cam[:, 0] / zc + K[0, 2]
        v = K[1, 1] * cam[:, 1] / zc + K[1, 2]
        inside = (u >= 0) & (u < w) & (v >= 0) & (v < h)
        u, v, zc = u[inside], v[inside], zc[inside]
        zp = depth_final[i][v.astype(int), u.astype(int)]
        good = np.isfinite(zp) & (zp > 0)
        zc, zp = zc[good], zp[good]
        if len(zc) > 10:
            ratio = np.maximum(zp / zc, zc / zp)
            scale_fit = float(np.median(zc / zp))
            vm["lidar"] = {
                "n": int(len(zc)),
                "abs_rel": float(np.mean(np.abs(zp - zc) / zc)),
                "delta1": float(np.mean(ratio < 1.25)),
                "median_scale_to_lidar": scale_fit,
                "abs_rel_after_scale": float(np.mean(np.abs(zp * scale_fit - zc) / zc)),
            }

    # ----- write -----
    log(progress, 0.9, f"writing {n_keep:,} Gaussians")
    sel = keep.reshape(-1)
    xyz = out_means.reshape(-1, 3)[sel]
    scl = np.log(np.clip(out_scales.reshape(-1, 3)[sel], 1e-6, None))
    rot = out_rots.reshape(-1, 4)[sel]
    dc = sh_dc.reshape(-1, 3)[sel]
    op = opac.reshape(-1)[sel]
    op = np.log(np.clip(op, 1e-5, 1 - 1e-5) / (1 - np.clip(op, 1e-5, 1 - 1e-5)))  # inverse sigmoid
    dtype = [(k, "f4") for k in ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                                   "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]]
    rec = np.empty(len(xyz), dtype=dtype)
    for j, k in enumerate(["x", "y", "z"]):
        rec[k] = xyz[:, j]
    for k in ["nx", "ny", "nz"]:
        rec[k] = 0
    for j in range(3):
        rec[f"f_dc_{j}"] = dc[:, j]
        rec[f"scale_{j}"] = scl[:, j]
    rec["opacity"] = op
    for j in range(4):
        rec[f"rot_{j}"] = rot[:, j]
    PlyData([PlyElement.describe(rec, "vertex")], byte_order="<").write(str(out / f"{args.key}.ply"))

    np.savez_compressed(
        out / f"{args.key}.npz",
        depth=depth_final.astype(np.float16),
        sky=pred.sky if pred.sky is not None else np.zeros_like(depth_final, dtype=bool),
        conf=pred.conf.astype(np.float16) if pred.conf is not None else np.zeros_like(depth_final, dtype=np.float16),
        intrinsics=K_proc.astype(np.float32),
        c2w=c2w_export.astype(np.float32),
    )

    # camera poses in the export frame, for drawing frustums
    for i, vm in enumerate(view_meta):
        vm["c2w"] = c2w_export[i].tolist()

    meta = {
        "key": args.key,
        "sample_token": args.sample,
        "scene_token": sample["scene_token"],
        "model": "Depth Anything 3, nested Giant + metric Large (1.1)",
        "device": device.type,
        "posed": not args.unposed,
        "process_res": [int(w), int(h)],
        "scale_mult": args.scale_mult,
        "views": view_meta,
        "n_views": n,
        "n_gaussians": n_keep,
        "n_gaussians_raw": int(n * h * w),
        "sky_fraction": float(pred.sky.mean()) if pred.sky is not None else None,
        "metric_scale_factor": pred.scale_factor,
        "pose": pose_report,
        "seconds": {"load": round(t_load, 1), "inference": round(t_infer, 1), "total": round(time.perf_counter() - t_start, 1)},
        "ply_bytes": (out / f"{args.key}.ply").stat().st_size,
    }
    (out / f"{args.key}.json").write_text(json.dumps(meta))
    log(progress, 1.0, "done")


if __name__ == "__main__":
    main()
