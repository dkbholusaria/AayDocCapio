"""Unit tests for the GST captcha solver (no network, no live portal)."""
import io
import os
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.gst import captcha
from automation.gst.login import classify_error, mask


def _png(w=182, h=50):
    img = Image.new("RGB", (w, h), (200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_render4_shape_and_range():
    x = captcha.render4(_png())
    assert x.shape == (4, 50, 182)
    assert x.dtype == np.float32
    assert x.min() >= 0.0 and x.max() <= 1.0


def test_render_thr_is_png():
    data = captcha.render_thr(_png(), thr=45)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    im = Image.open(io.BytesIO(data))
    # border cropped (1 px each side) then upscaled 4x
    assert im.size == (180 * 4, 48 * 4)


def _result(**kw):
    base = {"code": "", "confidence": "none", "cnn": "", "cnn_min": 0.0,
            "t45": "", "t60": "", "vote": "", "agreement": 0.0, "n_votes": 0}
    base.update(kw)
    return base


def test_should_submit_requires_code_and_confidence():
    assert not captcha.should_submit(_result())
    assert not captcha.should_submit(_result(code="123456", confidence="low"))
    assert not captcha.should_submit(_result(confidence="high"))
    assert captcha.should_submit(_result(code="123456", confidence="high"))
    assert captcha.should_submit(_result(code="123456", confidence="medium"))


def test_solve_prefers_consensus_vote(monkeypatch):
    monkeypatch.setattr(captcha, "cnn_read", lambda png: ("111111", 0.99))
    monkeypatch.setattr(captcha, "_ocr_read", lambda data: "")
    monkeypatch.setattr(captcha, "vote",
                        lambda png: ("222222", 1.0, ["222222"] * 6))
    r = captcha.solve(_png())
    assert r["code"] == "222222"
    assert r["reason"] == "vote-strong"
    assert captcha.should_submit(r)


def test_solve_refuses_on_conflict(monkeypatch):
    monkeypatch.setattr(captcha, "cnn_read", lambda png: ("333333", 0.2))
    values = iter(["123456", "654321"])
    monkeypatch.setattr(captcha, "_ocr_read", lambda data: next(values))
    monkeypatch.setattr(captcha, "vote", lambda png: ("", 0.0, [""] * 6))
    r = captcha.solve(_png())
    assert r["code"] == ""
    assert r["reason"] == "t45-t60-conflict"
    assert not captcha.should_submit(r)


def test_solve_unreadable(monkeypatch):
    monkeypatch.setattr(captcha, "cnn_read", lambda png: ("", 0.0))
    monkeypatch.setattr(captcha, "_ocr_read", lambda data: "")
    monkeypatch.setattr(captcha, "vote", lambda png: ("", 0.0, [""] * 6))
    r = captcha.solve(_png())
    assert r["code"] == ""
    assert r["reason"] == "unreadable"


@pytest.mark.parametrize("text,verdict", [
    ("Enter valid Letters shown", "wrong"),
    ("Invalid Username or Password. Please try again.", "credentials"),
    ("Enter the OTP sent to your registered mobile", "otp"),
    ("Something unexpected", "unknown"),
    ("", "unknown"),
])
def test_classify_error(text, verdict):
    assert classify_error(text) == verdict


def test_mask_never_leaks_username():
    assert mask("GSTLOGIN01") == "GST***"
    assert mask("ab") == "***"
    assert mask("") == "***"


def test_import_does_not_pull_in_torch():
    code = ("import sys; import automation.gst.captcha, automation.gst.login; "
            "print('torch' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
