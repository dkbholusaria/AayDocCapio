"""GST portal automation (captcha reading + login).

Runtime imports stay light: the captcha module uses onnxruntime and ddddocr,
never torch. See Documentation/ADR-gst-captcha.md.
"""

from automation.gst.captcha import solve, should_submit  # noqa: F401
from automation.gst.login import login_gst  # noqa: F401

__all__ = ["solve", "should_submit", "login_gst"]
