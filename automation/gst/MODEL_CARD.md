# GST captcha model — model card

`model.onnx` is a 6-head digit classifier (one 10-way head per character
position) for the login captcha on `services.gst.gov.in`.

## Files

| File | Purpose |
|---|---|
| `model.onnx` | Inference model used by `automation/gst/captcha.py` (~6.7 MB, opset 17) |
| `tools/model.py` | The network definition (PyTorch, 1.68 M parameters) |
| `tools/train.py` | Trainer + ONNX exporter |
| `tools/synth.py` | Synthetic captcha generator covering the three observed styles |
| `tools/preprocess.py` | Input pipeline (must match `captcha.render4`) |

## Input

`float32[1, 4, 50, 182]` — the captcha resized to 182×50 with four channels:
inverted greyscale, absolute dark mask (`gray < 45`), relative dark mask
(`gray < mean × 0.72`), red strike-through mask (R>150, G<100, B<100).

## Output

Six `float32[1, 10]` logits (`d0` … `d5`), one per digit; softmax per head.

## Training data

* Synthetic images from `tools/synth.py` — randomised fonts, sizes, rotation,
  overlap, stroke weight, grid pitch, red-line placement, and the three observed
  style regimes (`light`, `bold`, `hard`).
* Real captchas harvested from logins during development, labelled only by
  accepted logins (a captcha the portal accepted is by definition correct) and
  by high-agreement OCR consensus. No third-party captcha dataset was used.

## Measured accuracy (development machine, CPU)

* 67 / 74 exact (6 digits) on the full real labelled set, **100 % precision on
  the 67 images the ensemble chose to submit**.
* 68 / 74 on the CNN alone.
* Live portal: 12 / 12 logins cleared the captcha (average 2.8 captcha reads) in
  the final measurement run; a real account login succeeded on the first
  submitted code.

Captcha styles change. When the portal changes its rendering, the expected
behaviour is a drop in the CNN's confidence — which the solver turns into a
refresh rather than a wrong submit — and new labels can be harvested with
`tools/train.py --labels`.

## Licensing

The model and training tooling are part of this repository and covered by its
AGPL-3.0-or-later licence. The OCR reader used alongside it, `ddddocr`, is MIT;
`onnxruntime` is MIT. No code or weights from unlicensed captcha repositories
were used.
