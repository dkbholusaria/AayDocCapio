"""F-17 / B-101 — theme contrast and token-usage guarantees."""

import re
from pathlib import Path

import pytest

from themes import THEMES, contrast_checks, contrast_ratio

_HEX = re.compile(r"(?<!&)#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?\b")


def _unexplained_hex_literals(path: Path) -> list[str]:
    """Raw hex colours are only allowed on lines explicitly marked as
    intentional (e.g. provider brand colours)."""
    findings = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "intentional" in line.lower():
            continue
        if _HEX.search(line):
            findings.append(f"{path}:{number}: {line.strip()}")
    return findings


def test_no_unexplained_hardcoded_colours_in_ui():
    findings = []
    for path in (Path("app.py"), Path("ui/dialogs.py")):
        findings.extend(_unexplained_hex_literals(path))
    assert not findings, "Hardcoded UI colours bypass ThemeColors:\n" + "\n".join(findings)


@pytest.mark.parametrize("theme_name", sorted(THEMES))
def test_theme_colour_pairs_meet_wcag_aa(theme_name):
    theme = THEMES[theme_name]
    failures = [
        f"{label}: {fg} on {bg} = {contrast_ratio(fg, bg):.2f}:1 "
        f"(needs {required}:1)"
        for label, fg, bg, required in contrast_checks(theme)
        if contrast_ratio(fg, bg) < required
    ]
    assert not failures, "\n".join(failures)


def test_contrast_ratio_known_values():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, rel=1e-3)
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0, rel=1e-3)
    assert contrast_ratio("#2563EB", "#FFFFFF") > 5.0
