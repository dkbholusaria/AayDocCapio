# F-27: DPDP-aligned privacy confirmation in issue templates

GitHub issue: https://github.com/dkbholusaria/AayDocCapio/issues/35

## Goal

Update the mandatory privacy checkbox in GitHub issue templates so reporters
confirm that the issue does not contain personal data or confidential taxpayer
information.

## Plan

1. Update `.github/ISSUE_TEMPLATE/bug_report.yml`.
2. Update `.github/ISSUE_TEMPLATE/feature_request.yml`.
3. Keep the checkbox mandatory in both templates.
4. Avoid claiming that the checkbox alone guarantees legal compliance.
5. Verify with `git diff --check`.

## Proposed wording

I confirm this submission does not contain personal data as defined under the
Digital Personal Data Protection Act, 2023, including PANs, passwords, taxpayer
records, or any other confidential information.
