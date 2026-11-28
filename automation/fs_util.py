"""
automation/fs_util.py
=====================
Shared "is this document already downloaded?" rule (F-14 / #14).

Every ITD portal downloader builds a deterministic output path before it
touches the portal. Issued documents are immutable (26AS/168 for a closed
year, a challan identified by its CIN, a filed return identified by its
Acknowledgement Number, an intimation by its date), so a non-empty file at
that path can be trusted as already downloaded. Checking it locally — before
clicking the portal — is exactly the diff-fetch behaviour e-Proceedings has
shipped since F-2, extended to every other flow.

Keep this module dependency-free (no Playwright, no Qt) so it can be unit
tested on its own.
"""
import os


def is_present(path: str) -> bool:
    """True when `path` exists and is a non-empty file."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def skip_missing_required(path: str, log=None, label: str = "") -> bool:
    """Return True when `path` is already present (caller should skip the
    portal download). Logs a one-line note when a `log` callable is given."""
    if not is_present(path):
        return False
    if log:
        name = os.path.basename(path)
        what = f"{label} " if label else ""
        log(f"[Skip] {what}already present: {name}")
    return True
