"""Depth Anything V2 inference. Predictions go to the depth cache as float16
arrays at half the model input resolution, keyed by sample_data token; the
viewer's backend/app/depth.py reads them and fits them to the lidar."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from PIL import Image

from depth_anything_v2.dpt import DepthAnythingV2

MODEL_CONFIGS = {
    "vits": {"encoder": "vits", "features": 64, "out_channels": [48, 96, 192, 384]},
    "vitb": {"encoder": "vitb", "features": 128, "out_channels": [96, 192, 384, 768]},
    "vitl": {"encoder": "vitl", "features": 256, "out_channels": [256, 512, 1024, 1024]},
}

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def pick_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def input_size(width: int, height: int, short_side: int = 518) -> tuple[int, int]:
    """Official preprocessing: scale so the short side is 518, round both sides
    to a multiple of the 14 px patch."""
    scale = short_side / min(width, height)
    w = int(round(width * scale / 14)) * 14
    h = int(round(height * scale / 14)) * 14
    return w, h


class DepthPredictor:
    def __init__(self, checkpoint: Path, encoder: str = "vitb"):
        self.device = pick_device()
        model = DepthAnythingV2(**MODEL_CONFIGS[encoder])
        model.load_state_dict(torch.load(Path(checkpoint), map_location="cpu"))
        self.model = model.to(self.device).eval()

    def predict(self, image_path: Path) -> np.ndarray:
        """Relative inverse depth, (h/2, w/2) float32."""
        img = Image.open(image_path).convert("RGB")
        w, h = input_size(*img.size)
        x = np.asarray(img.resize((w, h), Image.BICUBIC), dtype=np.float32) / 255.0
        x = (x - IMAGENET_MEAN) / IMAGENET_STD
        t = torch.from_numpy(x.transpose(2, 0, 1)).unsqueeze(0).to(self.device)
        with torch.no_grad():
            pred = self.model(t)  # (1, h, w)
            pred = torch.nn.functional.interpolate(
                pred.unsqueeze(1), size=(h // 2, w // 2), mode="bilinear", align_corners=False
            ).squeeze()
        return pred.float().cpu().numpy()


def save_prediction(path: Path, pred: np.ndarray) -> None:
    """Write then rename, so a reader never sees a partial file."""
    tmp = path.with_suffix(".tmp.npy")
    np.save(tmp, pred.astype(np.float16))
    tmp.replace(path)
