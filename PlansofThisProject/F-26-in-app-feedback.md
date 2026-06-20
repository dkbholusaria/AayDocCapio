# F-26: In-app bug report and feature request flow

GitHub issue: https://github.com/dkbholusaria/AayDocCapio/issues/34

## Goal

Let users report bugs or request new features from inside AayDocCapio without
storing GitHub credentials in the desktop app.

## Plan

1. Add GitHub issue templates:
   - `.github/ISSUE_TEMPLATE/bug_report.yml`
   - `.github/ISSUE_TEMPLATE/feature_request.yml`
   - `.github/ISSUE_TEMPLATE/config.yml`

2. Add an app entry point:
   - Add `Help -> Report Bug / Request Feature...`.
   - Show a small choice dialog with `Report Bug` and `Request Feature`.
   - Open the selected GitHub issue form in the default browser.

3. Privacy behavior:
   - Warn users not to include passwords, PANs, or taxpayer data.
   - Do not send logs or client data automatically.

4. Documentation:
   - Update `README.md`, `Documentation/README.md`, and
     `Documentation/CONTRIBUTING.md`.
   - Add the flow to the offline user manual FAQ.
   - Add `F-26` to `Documentation/ISSUES_BACKLOG.md`.

5. Verification:
   - Run `.venv/bin/python -m py_compile app.py`.
   - Check `git diff --check`.
   - Verify the GitHub issue template files are present.

## Decision

Blank GitHub issues are disabled. Users must choose one of the structured
templates to keep project intake clean.
