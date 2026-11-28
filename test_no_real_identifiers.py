"""Guard against real client identifiers or credentials leaking into the repo.

Scans tracked text files for known-bad literals and for PAN/TAN-shaped strings
that are not from the approved placeholder set. Run:

    .venv/bin/pytest test_no_real_identifiers.py
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

TEXT_SUFFIXES = (
    ".py", ".md", ".json", ".html", ".txt", ".yml", ".yaml",
    ".toml", ".iss", ".wxs", ".sh", ".ps1", ".bat", ".command", ".cfg",
)

FORBIDDEN_LITERALS = [
    "adgnito", "adgnito24",
    "Adgnito Pvt Ltd",
    "ADGNITO TECHNOLOGIES",
    "AVQPB4769C",
    "AFBPA8322B",
    "AFCPB9287R",
    "AMRA16635D",
    "Altaf Hussain",
    "Advocate@1234",
    "AAAPT0001A", "AAAPT0002A", "AAAPT0002B", "AAAPT0003A", "AAAPT0003C",
    "FGHIJ5678K", "LMNOP9012Q", "RSTUV3456W", "RTKSG1234R",
    "Priya Mehta", "Rajesh Verma", "Rakesh Gupta", "Rajesh Kumar", "RAJA SOOD",
    "VikasBanga", "Vikas Banga",
    "SecretGst1", "Gst@123",
    "itdpass",
]

PLACEHOLDER_ALLOWLIST = {
    # Synthetic client PANs used in tests/docs
    "AABCP1234F", "AABCP1235G", "AABCP1236H", "AABCP1237J",
    "AAAAA0000A", "BBBBB0000B", "CCCCC0000C", "AAAAA9999A",
    "XXXXX0000A", "XXXXX0000B", "XXXXX0000C", "XXXXX0000D", "XXXXX0000E",
    # Synthetic deductor TANs
    "ABCD12345E", "AMRA12345D",
    # Placeholder used in the live-verification log and mockup export name
    "AAAPL1234C", "AAAPL5678F", "XXDPB9287X",
    # Public corporate/deductor PANs referenced as realistic samples in the mockup
    "AACCH6301G", "AAACG2271J", "AAACV2678L", "AAACC1450B", "AAACN0255D",
    "AAACI1195H", "AAACC1152C", "AAACC3035G", "AAACC6233A", "AADCN9802F",
    "AAECS5981K", "AAACI1314G", "AAATR0090B",
}

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
TAN_RE = re.compile(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b")

SELF = os.path.basename(__file__)
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist"}


def _tracked_files():
    try:
        out = subprocess.run(
            ["git", "-C", REPO_ROOT, "ls-files"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        out = ""
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                out += os.path.relpath(os.path.join(root, name), REPO_ROOT) + "\n"
    return [line.strip() for line in out.splitlines() if line.strip()]


def _iter_text_files():
    for rel in _tracked_files():
        if not rel.lower().endswith(TEXT_SUFFIXES):
            continue
        path = os.path.join(REPO_ROOT, rel)
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                yield rel, fh.read()
        except OSError:
            continue


def _is_binary_garbage_file(rel):
    return rel == SELF


def test_no_known_bad_literals():
    hits = []
    for rel, text in _iter_text_files():
        if _is_binary_garbage_file(rel):
            continue
        low = text.lower()
        for token in FORBIDDEN_LITERALS:
            if token.lower() in low:
                hits.append(f"{rel}: contains {token!r}")
    assert not hits, "Real client identifiers leaked in:\n" + "\n".join(hits)


def test_pan_and_tan_values_are_placeholders():
    hits = []
    for rel, text in _iter_text_files():
        if _is_binary_garbage_file(rel):
            continue
        for match in PAN_RE.findall(text):
            if match not in PLACEHOLDER_ALLOWLIST:
                hits.append(f"{rel}: PAN-like {match!r} not in placeholder allowlist")
        for match in TAN_RE.findall(text):
            if match not in PLACEHOLDER_ALLOWLIST:
                hits.append(f"{rel}: TAN-like {match!r} not in placeholder allowlist")
    assert not hits, "Non-placeholder PAN/TAN values found:\n" + "\n".join(hits)
