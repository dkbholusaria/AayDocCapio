"""
Which statement form applies to a given tax year, and how to fetch it.

    Income Tax Act, 1961  →  Assessment Year (AY)  →  Form 26AS
    Income Tax Act, 2025  →  Tax Year (TY)         →  Form 168

The mapping is derived from the year type rather than stored in
assessment_years.json. That file is copied into the user's data directory on
first run, so anything recorded in it goes stale on upgrade — an installed copy
written before Form 168 existed would keep fetching Form 26AS for a TY year no
matter which version of the app was running.

Adding a form:
    1. Write automation/downloader_<form>.py
    2. Add an entry to FORM_REGISTRY
    3. Add a rule to form_for() if the year → form mapping needs one
"""

from automation.downloader_26as import download_26as
from automation.downloader_168 import download_168

DEFAULT_FORM = "26AS"

FORM_REGISTRY = {
    "26AS": {
        "label": "26AS",
        "act": "Income Tax Act, 1961",
        "download": download_26as,
    },
    "168": {
        "label": "Form 168",
        "act": "Income Tax Act, 2025",
        "download": download_168,
    },
}


def form_for(year_type: str, year: str = "") -> str:
    """Form code for a year. year_type is 'AY' (1961 Act) or 'TY' (2025 Act)."""
    if year_type == "TY":
        return "168"
    return DEFAULT_FORM


def form_spec(form_code: str) -> dict:
    """Registry entry for a form code, falling back to the default form."""
    return FORM_REGISTRY.get(form_code, FORM_REGISTRY[DEFAULT_FORM])
