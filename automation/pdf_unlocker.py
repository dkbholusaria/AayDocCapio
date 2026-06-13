"""
automation/pdf_unlocker.py
==========================
Strip the owner/user password from a downloaded AIS or TIS PDF.

IT Department PDF password conventions (as of mid-2026)
--------------------------------------------------------
  Form 26AS   : DOB in DDMMYYYY format               (e.g. 01011990)
  AIS (PDF)   : lowercase PAN + DOB DDMMYYYY          (e.g. abcde1234f01011990)
  TIS (PDF)   : same as AIS (lowercase PAN + DDMMYYYY)

We try multiple DOB formats (DDMMYYYY, DDMMYY, DD/MM/YYYY) × PAN variants
(lowercase, none, uppercase) so the caller doesn't need to know the exact format.

We try every plausible combination so the caller doesn't have to know
which document uses which format.

Implementation
--------------
Uses `pikepdf` — Python bindings for the qpdf library.
Install:  pip install pikepdf
If pikepdf is absent the function logs a friendly message and leaves the
encrypted file untouched (download is NOT considered a failure).
"""

import os
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Password candidate generation (mirrors unlocker.js from the Electron project)
# ---------------------------------------------------------------------------

def _dob_variants(dob: str) -> list[str]:
    """
    Return all plausible DOB string formats from a vault-stored DD-MM-YYYY value.
    """
    variants = []
    try:
        parts = dob.strip().split("-")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            dd, mm, yyyy = parts[0], parts[1], parts[2]
            yy = yyyy[-2:]
            variants = [
                dd + mm + yyyy,        # DDMMYYYY  — most common
                dd + mm + yy,          # DDMMYY    — 2-digit year variant
                dd + "/" + mm + "/" + yyyy,  # DD/MM/YYYY — slash variant
            ]
    except Exception:
        pass
    return variants


def password_candidates(pan: str, dob: str) -> list[str]:
    """
    Build the ordered list of password strings to try against a PDF.

    :param pan: PAN number (any case — we normalise internally)
    :param dob: Date of birth in DD-MM-YYYY format (from the vault)
    :returns:   De-duplicated list of candidate passwords
    """
    dob_fmts = _dob_variants(dob)
    if not dob_fmts:
        return []

    PAN = (pan or "").strip().upper()
    pan_ = (pan or "").strip().lower()

    seen: set[str] = set()
    candidates: list[str] = []

    # Primary DOB format (DDMMYYYY) tried first with all PAN variants,
    # then additional DOB formats as fallbacks.
    for dob_fmt in dob_fmts:
        for pwd in [
            pan_ + dob_fmt,   # lowercase PAN + DOB  (AIS/TIS confirmed format)
            dob_fmt,          # DOB only             (26AS)
            PAN + dob_fmt,    # uppercase PAN + DOB  (fallback)
        ]:
            if pwd and pwd not in seen:
                seen.add(pwd)
                candidates.append(pwd)

    return candidates


# ---------------------------------------------------------------------------
# Core unlock logic
# ---------------------------------------------------------------------------

def unlock_pdf(
    file_path: str,
    pan: str,
    dob: str,
    log=None,
) -> dict:
    """
    Attempt to remove the PDF password from *file_path* in-place.

    :param file_path: Absolute path to the PDF file.
    :param pan:       PAN number of the assessee.
    :param dob:       Date of birth in DD-MM-YYYY format (vault format).
    :param log:       Optional callable for status messages (e.g. a GUI log fn).
    :returns: dict with keys:
              ``unlocked`` (bool)
              ``password`` (str, only when unlocked=True)
              ``reason``   (str, only when unlocked=False) —
                           one of 'file-missing', 'pikepdf-missing',
                           'not-encrypted', 'no-dob',
                           'no-password-matched'
    """

    def _log(msg: str):
        if log:
            log(msg)
        logger.debug(msg)

    # ------------------------------------------------------------------
    # Guard: file must exist
    # ------------------------------------------------------------------
    if not os.path.exists(file_path):
        _log(f"[PDF Unlock] File not found: {file_path}")
        return {"unlocked": False, "reason": "file-missing"}

    filename = os.path.basename(file_path)

    # ------------------------------------------------------------------
    # Guard: pikepdf must be importable
    # ------------------------------------------------------------------
    try:
        import pikepdf
    except ImportError:
        _log(
            f"[PDF Unlock] pikepdf not installed — leaving {filename} encrypted.\n"
            "  Install it with:  pip install pikepdf"
        )
        return {"unlocked": False, "reason": "pikepdf-missing"}

    # ------------------------------------------------------------------
    # Guard: is the PDF actually encrypted?
    # ------------------------------------------------------------------
    try:
        # Opening without a password succeeds for unencrypted files.
        with pikepdf.open(file_path) as pdf:
            _log(f"[PDF Unlock] {filename} is not encrypted — nothing to do.")
            return {"unlocked": False, "reason": "not-encrypted"}
    except pikepdf.PasswordError:
        pass   # encrypted — fall through to brute-force the password
    except Exception as e:
        _log(f"[PDF Unlock] Could not open {filename}: {e}")
        return {"unlocked": False, "reason": f"open-error: {e}"}

    # ------------------------------------------------------------------
    # Build candidate list
    # ------------------------------------------------------------------
    candidates = password_candidates(pan, dob)
    if not candidates:
        _log(
            f"[PDF Unlock] No DOB stored for PAN {pan} — "
            f"leaving {filename} encrypted."
        )
        return {"unlocked": False, "reason": "no-dob"}

    # ------------------------------------------------------------------
    # Try each candidate
    # ------------------------------------------------------------------
    tmp_path = file_path + ".unlocked.tmp"
    _log(f"[PDF Unlock] Trying {len(candidates)} password candidates for {filename}…")

    for i, pwd in enumerate(candidates, 1):
        _log(f"[PDF Unlock] Candidate {i}/{len(candidates)}…")
        try:
            with pikepdf.open(file_path, password=pwd) as pdf:
                pdf.save(tmp_path)
            # Success — replace original
            os.replace(tmp_path, file_path)
            _log(f"[PDF Unlock] Unlocked {filename} with candidate {i} ✓")
            return {"unlocked": True, "password": pwd}
        except pikepdf.PasswordError:
            continue       # wrong password — try next
        except Exception as e:
            _log(f"[PDF Unlock] Unexpected error for {filename}: {e}")
            break

    # Cleanup temp if left over
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except Exception:
        pass

    _log(
        f"[PDF Unlock] None of the {len(candidates)} password candidates "
        f"matched {filename}."
    )
    return {"unlocked": False, "reason": "no-password-matched"}


# ---------------------------------------------------------------------------
# Convenience: unlock a whole folder
# ---------------------------------------------------------------------------

def unlock_pdfs_in_dir(
    directory: str,
    pan: str,
    dob: str,
    log=None,
    glob_pattern: str = "*.pdf",
) -> list[dict]:
    """
    Unlock every PDF in *directory* that matches *glob_pattern*.

    :returns: List of result dicts (one per file attempted), each containing
              ``file``, ``unlocked``, and either ``password`` or ``reason``.
    """
    import glob

    results = []
    pdf_files = sorted(glob.glob(os.path.join(directory, glob_pattern)))

    if not pdf_files:
        if log:
            log(f"[PDF Unlock] No PDFs found in {directory}")
        return results

    for pdf_file in pdf_files:
        result = unlock_pdf(pdf_file, pan=pan, dob=dob, log=log)
        result["file"] = pdf_file
        results.append(result)

    return results
