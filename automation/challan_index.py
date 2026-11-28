"""
automation/challan_index.py
===========================
Read-only index of challans already saved on disk.

The vault tracks one download status per (client, year, doc type), and the
Generate Challans / Generate TDS Challans flows do not record their artifacts
at all — so the filesystem is the only reliable source for "what challans do I
already have?". This module walks the configured download root and returns one
record per saved PDF/PNG, classified as Paid or Unpaid from the folder it lives
in:

    {PAN|TAN}-{Name}/{AY|TY}_{year}/Tax Challans (Paid)/...
    {PAN|TAN}-{Name}/{AY|TY}_{year}/Tax Challans (Payable)/...

Legacy folder names ("Challans", "Tax Challans", "Tax Challans (Generated)")
are recognised so older installs still show their files.

No Qt, no network, no writes.
"""
import os
import re
from datetime import datetime

from vault import identify_type

# Folder name (lower-case) -> display status. Oldest layouts map to Paid
# because the very first flat "Challans" folder only ever held downloaded
# (already-paid) challans; F-64 later split generated ones out.
_STATUS_FOLDERS = {
    "tax challans (paid)": "Paid",
    "tax challans": "Paid",
    "challans": "Paid",
    "tax challans (payable)": "Unpaid",
    "tax challans (generated)": "Unpaid",
}

_ARTIFACT_EXTS = {".pdf", ".png", ".jpg", ".jpeg"}

_YEAR_SEGMENT_RE = re.compile(r"^(AY|TY)_(\d{4})_(\d{2})$", re.IGNORECASE)
_YEAR_ANY_RE = re.compile(r"\b(AY|TY)[_\s-]?(\d{4})[_\s-](\d{2})\b", re.IGNORECASE)
_YEAR_BARE_RE = re.compile(r"(?<!\d)(\d{4})[_-](\d{2})(?!\d)")


def classify_status(folder_name: str) -> str | None:
    """Return "Paid", "Unpaid", or None for a folder name."""
    return _STATUS_FOLDERS.get((folder_name or "").strip().lower())


def format_size(num_bytes: int) -> str:
    """Human-readable file size (decimal units, matching the rest of the UI)."""
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.0f} {unit}" if n >= 10 else f"{n:.1f} {unit}"
        n /= 1000.0
    return f"{n:.1f} GB"


def parse_year(*texts: str) -> str:
    """Return a display year like "AY 2026-27" from path/filename text.

    Prefers an AY/TY-prefixed token (the folder convention); falls back to a
    bare "2026_27" (portal-downloaded challan filenames). Returns "" when no
    year can be found.
    """
    for text in texts:
        if not text:
            continue
        m = _YEAR_ANY_RE.search(text)
        if m:
            return f"{m.group(1).upper()} {m.group(2)}-{m.group(3)}"
    for text in texts:
        if not text:
            continue
        m = _YEAR_BARE_RE.search(text)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return ""


def _folder_identity(folder_name: str) -> str:
    """Identity is the part before the first "-" in "{PAN|TAN}-{Name}"."""
    head = (folder_name or "").split("-", 1)[0].strip().upper()
    return head if identify_type(head) else ""


def _filename_identity(filename: str) -> str:
    """Downloaded/generated filenames begin with "{PAN|TAN}-"."""
    head = (filename or "").split("-", 1)[0].strip().upper()
    return head if identify_type(head) else ""


def parse_identity(folder_name: str, filename: str = "") -> str:
    """Resolve a client identity from the client folder, then the filename."""
    return _folder_identity(folder_name) or _filename_identity(filename)


def _pretty_slug(slug: str) -> str:
    text = (slug or "").replace("_", " ").strip()
    return re.sub(r"\s+", " ", text)


def _is_generated_name(upper: str) -> bool:
    # Same rule doc_types.match_doc_type uses to tell a payable (generated)
    # challan from a paid one: the year segment is prefixed with AY_/TY_.
    return "-CHALLAN-AY_" in upper or "-CHALLAN-TY_" in upper


def _payment_type(filename: str) -> str:
    stem = os.path.splitext(filename or "")[0]
    parts = stem.split("-")
    upper = stem.upper()
    if "-TDS-CHALLAN-" in upper or "-TDS_CHALLAN-" in upper:
        return "TDS/TCS"
    if _is_generated_name(upper):
        # ...-Challan-{AY|TY}_{year}-{payment_type}-{crn}
        return _pretty_slug(parts[-2]) if len(parts) >= 3 else ""
    # Downloaded paid challan: ...-Challan-{year}-{cin}-{payment_type}
    return _pretty_slug(parts[-1]) if len(parts) >= 2 else ""


def _doc_type(filename: str) -> str:
    upper = (filename or "").upper()
    if "-TDS-CHALLAN-" in upper or "-TDS_CHALLAN-" in upper:
        return "TDS/TCS"
    return "Income Tax"


def scan_saved_challans(root_dir: str, clients=None) -> list[dict]:
    """Walk `root_dir` and return saved challan records, newest first.

    `clients` may be a list of vault client dicts ({"pan", "name"}) or a
    {identity: name} mapping; it is only used to show the current client name.
    """
    if not root_dir or not os.path.isdir(root_dir):
        return []

    if isinstance(clients, dict):
        name_by_id = {str(k).upper(): v for k, v in clients.items()}
    else:
        name_by_id = {
            str(c.get("pan", "")).upper(): c.get("name", "")
            for c in (clients or [])
        }

    records: list[dict] = []
    seen_paths: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        status = classify_status(os.path.basename(dirpath))
        if status is None:
            continue

        rel_parts = os.path.relpath(dirpath, root_dir).split(os.sep)
        client_folder = rel_parts[0] if rel_parts else ""
        # The client folder is only meaningful when the challan folder sits
        # below it; a challan folder directly under the root is still shown.
        if client_folder.casefold() == os.path.basename(dirpath).casefold():
            client_folder = ""

        year = parse_year(*rel_parts[1:], os.path.basename(dirpath))

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _ARTIFACT_EXTS:
                continue
            path = os.path.join(dirpath, filename)
            if path in seen_paths:
                continue
            seen_paths.add(path)
            try:
                stat = os.stat(path)
            except OSError:
                continue

            client_id = parse_identity(client_folder, filename)
            display_id = client_id or client_folder.split("-", 1)[0].strip()
            client_name = name_by_id.get(display_id.upper(), "")
            if not client_name and "-" in client_folder:
                client_name = client_folder.split("-", 1)[1].strip()
            if not client_name and not display_id:
                client_label = os.path.basename(dirpath)
            else:
                client_label = display_id

            file_year = year or parse_year(filename)
            records.append({
                "client_id": display_id,
                "client_name": client_name,
                "client_label": client_label,
                "year": file_year,
                "status": status,
                "doc_type": _doc_type(filename),
                "payment_type": _payment_type(filename),
                "filename": filename,
                "path": path,
                "folder": dirpath,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            })

    records.sort(key=lambda r: r["mtime"], reverse=True)
    return records


def format_timestamp(mtime: float) -> str:
    """Short local timestamp used in the dialog's Date column."""
    try:
        return datetime.fromtimestamp(mtime).strftime("%d-%b-%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return ""
