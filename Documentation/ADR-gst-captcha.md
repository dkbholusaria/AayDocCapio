# ADR — GST portal captcha reading and login (2026-11-21)

## Context

The GST turnover reconciliation work needs a login on `services.gst.gov.in`.
That login is protected by a 6-digit captcha image and was the blocker.

Research (recorded on `dkbholusaria/AayDocCapio#92`) established:

* The captcha lives at `/services/captcha?rnd=…` and is shown as `#imgCaptcha`.
  Reading the image through `fetch(img.src)` returns a **different** captcha
  than the one displayed; only a screenshot of the element matches what the
  server expects.
* The rendering changes. Three styles were seen within 24 hours: thin digits on
  a 6 px grid, heavy digits on an 8–10 px grid, and a "hard" variant with a
  hand-drawn 6 px wobbly grid, two red lines and a soft drop shadow.
* Pointing the image at a new `?rnd=` rotates the server-side expected code, so
  refreshing is a cheap, safe retry.
* After a rejected captcha the portal clears the username and password inputs.
* Error text is the verdict: `Enter valid Letters shown` means the captcha was
  wrong; `Invalid Username or Password` means the captcha was accepted.

## Decision

1. Use **several independent readers** and submit only on agreement:
   a locally trained CNN, `ddddocr` on two threshold renders, and a
   `ddddocr` majority vote over six renders.
2. Ship the CNN as **ONNX** and run it with `onnxruntime`. PyTorch stays a
   development-only dependency of `automation/gst/tools/`: it is ~700 MB and
   has no place in a desktop app install.
3. Refresh the captcha instead of guessing when no reader combination agrees.
4. Keep the flow in `automation/gst/login.py` as async Playwright code, matching
   `automation/auth.py` conventions, so a future UI stage can call it directly.

## Alternatives considered

* **Only `ddddocr`** — simplest, but its accuracy on newly-changed styles is not
  enough on its own; it also cannot express per-digit confidence.
* **A paid/remote captcha service** — rejected: sends taxpayer-adjacent traffic
  to a third party and adds a per-login cost.
* **Copying an unlicensed GST captcha repo** — rejected: no licence, so
  incompatible with this AGPL project.

## Consequences

* New runtime dependencies: `ddddocr` (MIT), `onnxruntime` (MIT).
* The model must be retrained when the portal changes style; the trainer and
  generator are in the repo, and labels are harvested from accepted logins.
* If a GST account requires an OTP after the password, login must pause for the
  user. `login_gst()` reports `reason: "otp"` and returns; wiring a prompt is a
  UI follow-up.

## Privacy

No GST password is logged or persisted outside the encrypted vault. Captcha
answers are only held in memory for the submit, and the account name is read
from the welcome page solely to confirm the right login.
