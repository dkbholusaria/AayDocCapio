"""Train the 6-head captcha CNN and export automation/gst/model.onnx.

Development tooling only. Requires PyTorch (CPU is fine) which is NOT a runtime
dependency of the app — the app loads the exported ONNX file with onnxruntime.

    python tools/train.py [epochs] [steps_per_epoch] [batch] [labels.csv ...]

Every labels CSV must have ``filename,label`` columns; paths are resolved
relative to the CSV. Mixing several CSVs lets you combine real labelled captures
with synthetic sets. Input pipeline lives in ``preprocess.py`` and is identical
to ``automation/gst/captcha.render4``.

Output: ``build/model.pt`` (checkpoint) and ``automation/gst/model.onnx`` when
``--export`` is passed.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import preprocess  # noqa: E402
import synth  # noqa: E402
from model import CaptchaNet  # noqa: E402

BUILD = os.path.join(HERE, "build")
APP_MODEL = os.path.join(HERE, "..", "model.onnx")


class SynthDataset(Dataset):
    def __init__(self, length, seed=0):
        self.length = length
        self.seed = seed

    def __len__(self):
        return self.length

    def __getitem__(self, i):
        rng = np.random.default_rng((self.seed, i))
        image, code = synth.gen_one(rng)
        x = preprocess.to_tensor(image)
        y = np.array([int(c) for c in code], dtype=np.int64)
        return torch.from_numpy(x), torch.from_numpy(y)


class FileDataset(Dataset):
    def __init__(self, rows, repeat=1):
        self.rows = rows * repeat

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        path, label = self.rows[i]
        with open(path, "rb") as fh:
            x = preprocess.to_tensor(fh.read())
        return torch.from_numpy(x), torch.tensor([int(c) for c in label])


def load_csvs(paths):
    rows = []
    for path in paths:
        base = os.path.dirname(os.path.abspath(path))
        for r in csv.DictReader(open(path, newline="")):
            p = r["filename"]
            if not os.path.isabs(p):
                p = os.path.join(base, p)
            if os.path.exists(p) and len(r.get("label", "")) == 6:
                rows.append((p, r["label"]))
    return rows


def augment(x):
    b = x.shape[0]
    dx = torch.randint(-3, 4, (b,))
    dy = torch.randint(-2, 3, (b,))
    out = torch.empty_like(x)
    for i in range(b):
        out[i] = torch.roll(x[i], shifts=(int(dy[i]), int(dx[i])), dims=(1, 2))
    out = (out * (0.85 + 0.3 * torch.rand(b, 1, 1, 1)).clamp(0.7, 1.25)).clamp(0, 1)
    if torch.rand(1).item() < 0.3:
        out = out.clamp(1e-4, 1.0) ** (0.85 + 0.3 * torch.rand(1))
    return out


def evaluate(model, loader):
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for x, y in loader:
            logits = model(x)
            pred = torch.stack([l.argmax(1) for l in logits], 1)
            correct += (pred == y).all(1).sum().item()
            total += len(y)
    return correct / max(1, total)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epochs", nargs="?", type=int, default=8)
    ap.add_argument("steps", nargs="?", type=int, default=320)
    ap.add_argument("batch", nargs="?", type=int, default=64)
    ap.add_argument("--labels", nargs="*", default=[])
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--out", default=APP_MODEL)
    args = ap.parse_args()

    torch.manual_seed(0)
    os.makedirs(BUILD, exist_ok=True)
    real = load_csvs(args.labels)
    print(f"labelled samples: {len(real)}", flush=True)
    val_rows, trn_rows = [], list(real)
    if real:
        order = np.random.default_rng(0).permutation(len(real))
        n_val = max(1, len(real) // 5)
        val_rows = [real[i] for i in order[:n_val]]
        trn_rows = [real[i] for i in order[n_val:]]

    trn_syn = SynthDataset(args.steps * args.batch, seed=1)
    val_syn = SynthDataset(512, seed=2)
    trn_loader = DataLoader(trn_syn, batch_size=args.batch, num_workers=2,
                            prefetch_factor=4, persistent_workers=True)
    real_loader = real_iter = None
    if trn_rows:
        real_loader = DataLoader(FileDataset(trn_rows, repeat=40),
                                 batch_size=args.batch, shuffle=True)
        real_iter = iter(real_loader)

    model = CaptchaNet()
    print(f"params: {sum(p.numel() for p in model.parameters())/1e6:.2f}M", flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=3e-3, total_steps=args.epochs * args.steps, pct_start=0.15)

    best = -1.0
    for epoch in range(1, args.epochs + 1):
        model.train()
        t0 = time.time()
        run = 0.0
        k = 0
        for k, (x, y) in enumerate(trn_loader):
            if k >= args.steps:
                break
            if real_iter is not None and k % 4 == 3:
                try:
                    rx, ry = next(real_iter)
                except StopIteration:
                    real_iter = iter(real_loader)
                    rx, ry = next(real_iter)
                half = args.batch // 2
                x = torch.cat([x[:half], rx[:half]], 0)
                y = torch.cat([y[:half], ry[:half]], 0)
            x = augment(x)
            logits = model(x)
            loss = sum(F.cross_entropy(logits[i], y[:, i]) for i in range(6)) / 6
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            run += loss.item()
        syn_acc = evaluate(model, DataLoader(val_syn, batch_size=128))
        real_acc = evaluate(model, DataLoader(FileDataset(val_rows), batch_size=32)) \
            if val_rows else 0.0
        print(f"epoch {epoch}: loss {run/max(1,k+1):.4f} synth={syn_acc:.3f} "
              f"real={real_acc:.3f} ({time.time()-t0:.0f}s)", flush=True)
        score = 0.6 * syn_acc + 0.4 * real_acc
        if score >= best:
            best = score
            torch.save({"model": model.state_dict()}, os.path.join(BUILD, "model.pt"))

    if args.export:
        ckpt = torch.load(os.path.join(BUILD, "model.pt"), map_location="cpu")
        model.load_state_dict(ckpt["model"])
        model.eval()
        torch.onnx.export(model, torch.randn(1, 4, 50, 182), args.out,
                          input_names=["input"],
                          output_names=[f"d{i}" for i in range(6)],
                          opset_version=17, do_constant_folding=True, dynamo=False)
        print(f"exported {args.out}")


if __name__ == "__main__":
    main()
