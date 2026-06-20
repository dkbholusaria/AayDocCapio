# F-30: Add branded headers and follow-up guidance to issue forms

GitHub issue: https://github.com/dkbholusaria/AayDocCapio/issues/38

## Goal

Improve the GitHub issue forms with AayDocCapio branding, clearer form titles,
and guidance on how maintainers will ask follow-up questions.

## Plan

1. Update `.github/ISSUE_TEMPLATE/bug_report.yml`.
2. Update `.github/ISSUE_TEMPLATE/feature_request.yml`.
3. Add the public logo URL to each form's opening Markdown block.
4. Add large Markdown headings:
   - `# Bug Report`
   - `# New Feature Request`
5. Add follow-up guidance:
   - maintainer questions happen in the public GitHub issue thread;
   - do not post sensitive information;
   - use official support/contact channel if private discussion is required.
6. Keep blank issues disabled and privacy checkbox wording unchanged.
7. Verify with `git diff --check`.

## Constraints

GitHub issue forms support Markdown content blocks, but do not support custom
CSS, custom fonts, or a fully branded page layout.
