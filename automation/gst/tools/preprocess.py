"""Input pipeline shared by training and inference (must stay in sync with
``automation/gst/captcha.render4``)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

W, H = 182, 50


def to_tensor(png):
    im = Image.open(io.BytesIO(png)) if isinstance(png, (bytes, bytearray)) else png
    a = np.asarray(im.convert("RGB").resize((W, H), Image.LANCZOS)).astype(np.float32)
    gray = a.mean(axis=2)
    return np.stack([
        1.0 - gray / 255.0,
        (gray < 45).astype(np.float32),
        (gray < gray.mean() * 0.72).astype(np.float32),
        ((a[..., 0] > 150) & (a[..., 1] < 100) & (a[..., 2] < 100)).astype(np.float32),
    ], axis=0)
