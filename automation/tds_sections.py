"""
automation/tds_sections.py
==========================
Offline catalogue of the TDS/TCS section codes offered by the e-Pay Tax
wizard for "Other than Company Deductee(s)" + "Resident Deductee(s)" under
the Income-tax Act, 2025.

Captured verbatim from the live portal on 2026-11-20 (Tax Year 2026-27) —
see PlansofThisProject/F-4_evidence/. The portal remains the source of
truth: the generator matches by numeric code against the live dropdown and
fails that row with a clear reason if a code is no longer offered, rather
than silently submitting the wrong section.
"""
import os
import re

_DATA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data",
    "tds_sections_other_than_company_resident.txt")

# Option text looks like:
#   "Payment of Employees other than Government Employees - 392 - 1002"
# The last "- NNNN" token is the section code.
_LINE_RE = re.compile(r"^(.*?)\s*-\s*(\d{4})$")


def load_sections(path: str = None) -> list:
    sections = []
    with open(path or _DATA_FILE, encoding="utf-8") as fh:
        for line in fh:
            label = line.strip()
            if not label:
                continue
            m = _LINE_RE.match(label)
            if not m:
                continue
            sections.append({"code": m.group(2), "label": m.group(1).strip()})
    return sections


SECTIONS = load_sections()


def section_by_code(code) -> dict | None:
    code = str(code).strip()
    for s in SECTIONS:
        if s["code"] == code:
            return s
    return None


def description_for(code) -> str:
    s = section_by_code(code)
    return s["label"] if s else ""
