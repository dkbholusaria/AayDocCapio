# v1.7.2 Release Metadata Plan

## Summary
Prepare AayDocCapio release metadata for v1.7.2 after AIS Excel workbook fixes.

## Changes
- Bump `version.py` and `pyproject.toml` to `1.7.2`.
- Add v1.7.2 release notes to `CHANGELOG.md` and `Documentation/CHANGELOG.md`.
- Update `README.md` and `Documentation/README.md` badges and What's New copy.
- Update `docs/index.html` release/version/download metadata and What's New content.
- Verify live version and stale version references.

## Verification
- `.venv/bin/python -c "from version import __version__; print(__version__)"`
- `rg` checks for stale `1.6.3`, `1.6.4`, `v1.6.3`, and `v1.6.4` references in release-facing files.
