"""
automation/diagnostics.py
==========================
Permanent, always-on failure diagnostics for portal automation. There is no
test harness for this app — every bug so far has been diagnosed from live
log pastes and user-described screen behaviour, which is slow and often
ambiguous (e.g. "Income Tax Returns" not appearing could mean it's missing
from the DOM, present but invisible, or present but not receiving the
hover). This module captures hard evidence automatically at the moment of
failure instead of relying on the user to notice and describe it.

Usage: call capture_failure(page, log_callback, tag) from an except block
right where a step fails. It never raises — a diagnostics failure must
never mask or replace the real error being handled.
"""
import os
from datetime import datetime

from config import _app_dir

_DEBUG_DIR = os.path.join(_app_dir(), "debug")


async def capture_failure(page, log_callback, tag: str) -> None:
    """Save a screenshot and full-page HTML snapshot to the debug folder,
    named with a timestamp + tag so multiple failures don't overwrite each
    other. Logs the saved paths so they show up in the run log the user
    already pastes back. Best-effort — swallows its own errors."""
    try:
        os.makedirs(_DEBUG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)
        base = os.path.join(_DEBUG_DIR, f"{stamp}_{safe_tag}")

        png_path = base + ".png"
        try:
            await page.screenshot(path=png_path, full_page=True)
        except Exception as e:
            png_path = None
            if log_callback:
                log_callback(f"[Diag] Screenshot failed for {tag}: {e}")

        html_path = base + ".html"
        try:
            html = await page.content()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception as e:
            html_path = None
            if log_callback:
                log_callback(f"[Diag] HTML dump failed for {tag}: {e}")

        if log_callback:
            saved = [p for p in (png_path, html_path) if p]
            if saved:
                log_callback(f"[Diag] Saved failure diagnostics for '{tag}': {', '.join(saved)}")
    except Exception as e:
        if log_callback:
            try:
                log_callback(f"[Diag] Diagnostics capture failed for {tag}: {e}")
            except Exception:
                pass
