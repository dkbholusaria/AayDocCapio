# B-123 — Show all documents attached to an order in e-Proceedings

Issue: #123 (https://github.com/dkbholusaria/AayDocCapio/issues/123)
Reported: 2026-11-24
Branch: `fix/123_order_attachments`

## Goal

When a user clicks an order in the e-Proceedings timeline, show every document
that was saved with that order — normally the Order / Assessment Order, the
Demand Notice and the Computation Sheet. Fewer documents must work too.

## Root cause

The data is already captured. `_download_proceeding_orders` in
`automation/downloader_e_proceedings.py` saves every document from one
"Closure Order" modal and records all of them in the order entry's `files`
list. `_build_meta_docs` in `ui/eproceedings_model.py` puts that whole list on
one `Doc`.

The loss happens in the UI:

- `ui/eproc_doc_modal.py` has no documents/attachments section at all.
- `ui/eproc_timeline.py:303` only links `doc.files[0]`.

So only the first file is ever reachable, and even that only from the small
"Open file" link on the card.

## Chosen approach (display-only)

No downloader, schema or model changes. Use the existing `Doc.files` list.

1. Add a pure helper that turns a portal filename into a readable document
   type label:
   - "computation" -> `Computation Sheet`
   - "demand" -> `Demand Notice`
   - "order" -> `Order u/s NNN` when a section is present, else `Order`
   - anything else -> the filename itself
   Place it in a pure module so both UI and downloader can share it.
2. In `EprocDocModal`, add a **Documents** section listing every entry in
   `doc.files`. Each row shows the type label, the file name, and an
   **Open** button. Resolve relative paths against `case.proc_dir`.
3. In the timeline card, replace the single "Open file" link with:
   - one attachment -> the existing "Open file" link;
   - more than one -> a line such as
     `3 documents: Order u/s 147 · Demand Notice · Computation Sheet`.
4. Keep the modal accessible for notices/replies too; the section appears
   whenever `doc.files` is non-empty.

## Files to change

- `automation/doc_types.py` — add `e_proceeding_doc_label(filename)`.
- `automation/downloader_e_proceedings.py` — `_order_title` delegates to the
  helper so downloader and UI labels cannot drift (behaviour unchanged).
- `ui/eproc_doc_modal.py` — add the Documents section and open action.
- `ui/eproc_timeline.py` — show an attachment summary for multi-file docs.
- `test_e_proceedings_parse.py` — tests for the label helper.
- `test_eproc_doc_modal.py` (new) — tests that the modal exposes every file.
- `Documentation/ISSUES_BACKLOG.md` / `Documentation/DEVELOPMENT_LOG.md` —
  record the change.

## Tests

- Label helper: computation sheet, demand notice, order with section, order
  without section, unknown filename.
- Modal: a `Doc` with three files produces three rows; one file produces one;
  no files produces no section.
- Guard: `pytest test_no_real_identifiers.py`.
- Full e-Proceedings tests.

## Out of scope

- Re-downloading old cases that only saved one document.
- Merging separate order entries into one synthetic timeline node.
- Changing `_meta.json` or document ids.

## Verification

- Run the new tests plus `test_e_proceedings_parse.py`,
  `test_eproc_case_open.py`, `test_eproc_viewed_by_ao.py`.
- Open the demo workspace and confirm an order with multiple files lists all
  of them and each opens.
