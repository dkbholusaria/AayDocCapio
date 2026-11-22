"""Synthetic GST captcha generator — training data for automation/gst/model.onnx.

This is development tooling only; the app never imports it. It reproduces the
three styles that every live captcha read needs to survive:

``light``  thin condensed digits, ~6 px woven grid, 19-22 px pitch.
``bold``   heavy digits, 8-10 px grid, 26-29 px pitch, strong overlap.
``hard``   6 px hand-drawn wobbly grid, two red lines (3-4 px and 1-2 px), very
           large bold digits with a soft grey/tan drop shadow (seen 2026-11-21).

Fonts are discovered from the system; whichever bold/condensed faces exist are
used. Rendering is deliberately random across size, rotation, stroke weight,
overlap and line placement so the model generalises instead of memorising one
screenshot batch.

API: ``gen_one(rng, style=None) -> (PIL.Image 182x50, "123456")``.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 182, 50

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
    "/usr/share/fonts/truetype/lato/Lato-Black.ttf",
    "/usr/share/fonts/truetype/lato/Lato-Heavy.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _available_fonts() -> list:
    found = []
    for path in _FONT_CANDIDATES:
        try:
            ImageFont.truetype(path, 20)
        except Exception:
            continue
        found.append(path)
    return found or list(_FONT_CANDIDATES[:1])


FONT_PATHS = _available_fonts()
_FONT_CACHE: dict = {}


def _font(path, size):
    key = (path, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(path, size)
    return _FONT_CACHE[key]


STYLES = {
    "light": dict(
        pitch=(19.0, 22.0), height=(36.0, 44.0), aspect=(0.46, 0.62),
        grid=(6, 6), stroke=(0.85, 1.10), bg=(170, 245), shadow=False, n_red=1,
    ),
    "bold": dict(
        pitch=(25.0, 28.5), height=(42.0, 48.0), aspect=(0.42, 0.58),
        grid=(8, 10), stroke=(1.0, 1.45), bg=(175, 235), shadow=False, n_red=1,
    ),
    "hard": dict(
        pitch=(22.5, 27.0), height=(35.0, 43.0), aspect=(0.55, 0.78),
        grid=(6, 6), stroke=(1.05, 1.50), bg=(115, 252), shadow=True, n_red=2,
    ),
}


def _background(rng, grid_pitch):
    """Grey gradient with a black woven grid, a faint checker and a border."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    angle = rng.uniform(0, 2 * np.pi)
    proj = (xx / (W - 1)) * np.cos(angle) + (yy / (H - 1)) * np.sin(angle)
    lo, hi = rng.uniform(45, 85), rng.uniform(185, 250)
    if rng.random() < 0.5:
        lo, hi = hi, lo
    span = (proj - proj.min()) / max(proj.max() - proj.min(), 1e-6)
    base = lo + span * (hi - lo) + rng.normal(0, 3.0, (H, W))
    arr = np.repeat(np.clip(base, 40, 252)[..., None], 3, axis=2)
    im = Image.fromarray(arr.astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(im)
    jitter = 0.55 if grid_pitch <= 6 else 0.30
    for x in range(0, W, grid_pitch):
        pts = [(x + rng.uniform(-jitter, jitter), y) for y in range(0, H, 4)]
        pts.append((x + rng.uniform(-jitter, jitter), H - 1))
        draw.line(pts, fill=(0, 0, 0))
    for y in range(0, H, grid_pitch):
        pts = [(x, y + rng.uniform(-jitter, jitter)) for x in range(0, W, 4)]
        pts.append((W - 1, y + rng.uniform(-jitter, jitter)))
        draw.line(pts, fill=(0, 0, 0))
    for cy in range(0, H, grid_pitch):
        for cx in range(0, W, grid_pitch):
            if ((cx // grid_pitch) + (cy // grid_pitch)) & 1:
                a2 = np.asarray(im).astype(np.int16)
                y0, y1 = cy + 1, min(cy + grid_pitch, H)
                x0, x1 = cx + 1, min(cx + grid_pitch, W)
                if y1 > y0 and x1 > x0:
                    a2[y0:y1, x0:x1] -= int(rng.integers(8, 26))
                im = Image.fromarray(np.clip(a2, 0, 255).astype(np.uint8))
    ImageDraw.Draw(im).rectangle([0, 0, W - 1, H - 1], outline=(0, 0, 0))
    return im


def _glyphs(rng, code, style):
    path = FONT_PATHS[int(rng.integers(len(FONT_PATHS)))]
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    target_h = rng.uniform(*style["height"])
    target_w = target_h * rng.uniform(*style["aspect"])
    font = _font(path, 90)
    out = []
    for ch in code:
        box = probe.textbbox((0, 0), ch, font=font)
        gw, gh = box[2] - box[0], box[3] - box[1]
        tmp = Image.new("RGBA", (gw + 10, gh + 10), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((5 - box[0], 5 - box[1]), ch, font=font,
                                 fill=(8, 8, 8, 255))
        tmp = tmp.crop(tmp.getbbox())
        w = max(2, int(round(target_w * rng.uniform(0.9, 1.1))))
        tmp = tmp.resize((w, max(2, int(round(target_h)))), Image.LANCZOS)
        stroke = rng.uniform(*style["stroke"])
        if stroke > 1.08:
            tmp = tmp.filter(ImageFilter.MaxFilter(3))
        elif stroke < 0.92:
            tmp = tmp.filter(ImageFilter.MinFilter(3))
        out.append(tmp)
    return out


def _compose(rng, glyphs, style):
    pad = 16
    size = (W + 2 * pad, H + 2 * pad)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    pitch = rng.uniform(*style["pitch"])
    x0 = float(pad) + glyphs[0].width / 2 + rng.uniform(0, 6)
    top = rng.uniform(0.5, 4.0)
    for i, glyph in enumerate(glyphs):
        rotated = glyph.rotate(rng.uniform(-11, 11), resample=Image.BICUBIC, expand=True)
        px = int(round(x0 + i * pitch - rotated.width / 2))
        py = int(round(pad + top + rng.uniform(-2.0, 2.0)
                       - (rotated.height - glyph.height) / 2))
        layer.alpha_composite(rotated, (px, py))
    box = layer.getbbox()
    if box is None:
        return layer
    ink_w, ink_h = box[2] - box[0], box[3] - box[1]
    left = rng.uniform(3, 10)
    if ink_w + left > W - 2:
        left = max(2.0, (W - ink_w) / 2.0)
    dx = int(round(left - box[0]))
    dy = int(round((H - ink_h) / 2.0 - box[1])) if ink_h > H else int(round(
        rng.uniform(0, 2) - box[1]))
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.alpha_composite(layer, (16 + dx, 16 + dy))
    return out


def _red_line(draw, rng, width=None, y0=None, slope=None):
    start = rng.uniform(2, H - 3) if y0 is None else y0
    grad = rng.uniform(-0.18, 0.18) if slope is None else slope
    width = int(rng.integers(2, 6)) if width is None else width
    phase = rng.uniform(0, 2 * np.pi)
    amp = rng.uniform(0.4, 2.4)
    pts = []
    for x in range(0, W, 2):
        y = start + grad * x + amp * np.sin(x / 13.0 + phase)
        if 0 <= y <= H - 1:
            pts.append((x, y))
    if len(pts) >= 2:
        draw.line(pts, fill=(int(rng.integers(200, 256)), 0, 0), width=width)


def gen_one(rng, style=None):
    if style is None:
        roll = rng.random()
        style = "light" if roll < 0.2 else ("bold" if roll < 0.55 else "hard")
    st = STYLES[style]
    code = "".join(str(int(d)) for d in rng.integers(0, 10, 6))
    grid = int(rng.integers(st["grid"][0], st["grid"][1] + 1))
    im = _background(rng, grid)
    layer = _compose(rng, _glyphs(rng, code, st), st).crop((16, 16, 16 + W, 16 + H))
    if st["shadow"]:
        dx, dy = int(rng.integers(3, 9)), int(rng.integers(2, 7))
        shadow = layer.filter(ImageFilter.GaussianBlur(rng.uniform(1.2, 3.2)))
        alpha = shadow.getchannel("A").point(lambda v: int(v * rng.uniform(0.35, 0.6)))
        if rng.random() < 0.35:
            colour = (int(rng.integers(150, 185)), int(rng.integers(110, 145)),
                      int(rng.integers(75, 115)))
        else:
            colour = (int(rng.integers(60, 120)),) * 3
        shadow = Image.new("RGBA", shadow.size, colour + (0,))
        shadow.putalpha(alpha)
        base = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        base.alpha_composite(shadow, (dx, dy))
        base.alpha_composite(layer)
        layer = base
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    draw = ImageDraw.Draw(im)
    if st["n_red"] >= 2:
        _red_line(draw, rng, width=int(rng.integers(2, 5)),
                  y0=rng.uniform(2, H * 0.5), slope=rng.uniform(-0.10, 0.10))
        _red_line(draw, rng, width=int(rng.integers(1, 3)),
                  y0=rng.uniform(H * 0.25, H - 3), slope=rng.uniform(-0.10, 0.10))
    else:
        _red_line(draw, rng)
    return im, code


if __name__ == "__main__":
    import csv
    import os
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "synth_out"
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        image, code = gen_one(rng)
        name = f"syn_{i:05d}.png"
        image.save(os.path.join(out_dir, name))
        rows.append([name, code])
    with open(os.path.join(out_dir, "labels.csv"), "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["filename", "label"])
        writer.writerows(rows)
    print(f"wrote {n} images to {out_dir}")
