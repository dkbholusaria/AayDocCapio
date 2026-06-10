# Issues & Feature Backlog

Tracked here before being moved to GitHub Issues. Add new items at the bottom
of the relevant section. Each item has a priority tag: **P1** (blocking / data
loss risk), **P2** (significant UX friction), **P3** (nice-to-have).

---

## Bugs

### ~~B-01 — Assessment Year dropdown closes immediately on click~~ ✅ FIXED

**Reported:** 2026-06-10 · **Fixed:** 2026-06-10 (merged from dhruvdua88/macos-support)  
**Fix:** 300ms debounce in `StyledComboBox.showPopup()` / `_ComboListView.mouseReleaseEvent`.
Records `_popup_opened_at = time.monotonic()` on open; ignores mouse releases
within 300ms. Fixes all platforms.

---

### B-02 — PDF unlock fails for some TIS/AIS files `P1`

**Reported:** 2026-06-10  
**Log evidence:**
```
[PDF Unlock] None of the 3 password candidates matched ANZPB6179P-TIS-2025_26.pdf.
```
**Current password candidates tried:** PAN+DOB combinations (uppercase, lowercase,
mixed). Some ITD PDFs use a different password formula — e.g. PAN in lowercase +
DOB in DDMMYYYY format without separators, or DOB year only.  
**Impact:** File is saved but remains password-protected. User must unlock manually.  
**Fix direction:** Expand candidate list; log which candidates were tried; consider
saving the locked PDF with a `-locked` suffix and attempting to save an unlocked
copy alongside it rather than replacing.

---

### B-03 — Wrong PAN not validated before batch run `P1`

**Reported:** 2026-06-10  
**Symptom:** If a PAN entered in the vault is malformed (wrong length, invalid
format), the batch proceeds, fails at the ITD portal with a cryptic error, and
wastes time on that client.  
**Expected:** Validate PAN format (10 chars: 5 alpha + 4 digit + 1 alpha, e.g.
`AAAPT0001A`) at vault save time and optionally at batch-start time. Show a clear
inline error rather than a portal-level failure.  
**Fix direction:** Add regex `^[A-Z]{5}[0-9]{4}[A-Z]$` validation in `vault.py`
`save_client()` and in the Single Profile form's Save button handler.

---

### B-04 — Login fails on already-active ITD session `P2`

**Reported:** 2026-06-10  
**Symptom:** If the client is already logged in on another browser/device, the
ITD portal may show a "You are already logged in" or "Active session exists"
prompt instead of the normal login page. The current flow does not handle this
and times out or fails.  
**Fix direction:** Detect the "already logged in" dialog/message after the first
Continue click and dismiss it (click "Continue" or "Proceed" on that dialog)
before resuming the normal flow.

---

### B-05 — Duplicate records imported on re-import `P2`

**Reported:** 2026-06-10  
**Symptom:** Running Import CSV/Excel a second time with the same file (or a file
containing already-saved PANs) adds duplicate rows instead of updating the
existing record.  
**Current behaviour:** `import_bulk()` returns `(added, updated, errors)` — the
`updated` count suggests upsert logic exists, but duplicates are still appearing
in practice.  
**Fix direction:** Audit `vault.py` `import_bulk()` — ensure the upsert key is
PAN (case-insensitive) and that the existing record is fully overwritten, not
appended. Add a duplicate-count line to the import result dialog.

---

## Feature Requests

### F-01 — Date picker for DOB field `P2`

**Reported:** 2026-06-10  
**Request:** Replace the free-text DOB input with a `QDateEdit` calendar picker.
Add real-time validation showing "Invalid date" inline if the user types a
non-existent date.  
**Notes:** The existing multi-format parser (`DD-MM-YYYY`, `DD/MM/YYYY`,
`DDMMYYYY`, ISO) should be preserved for bulk import via Excel — the date picker
only applies to the Single Profile form.

---

### F-02 — Per-client status columns in main client list `P2`

**Reported:** 2026-06-10 (colleague review)  
**Request:** Add columns to the main client table showing the last-run result for
each client — e.g. Last Run, Status (✅ / ❌ / 🕐), Last Error. This lets the
user see at a glance which clients failed in the last batch without opening the
log panel.  
**Notes:** Persist these values in `tax_vault.json` so they survive app restart.
Clear them when a new batch starts for that client.

---

### F-03 — "Open folder" button per client `P2`

**Reported:** 2026-06-10 (colleague review)  
**Request:** Add a small folder icon button in the Actions column of the client
list. Clicking it opens `<output_dir>/<PAN>-<Name>/` in Windows Explorer
(or the OS file manager on Linux).  
**Implementation:** `os.startfile(path)` on Windows; `subprocess.Popen(["xdg-open", path])`
on Linux.  
**Notes:** Button should be disabled (greyed) if no output folder exists yet for
that client.

---

### F-04 — Inline edit for individual client records `P2`

**Reported:** 2026-06-10 (colleague review)  
**Request:** An Edit button (pencil icon) in the Actions column that opens the
Single Profile form pre-filled with that client's data. Saving overwrites the
existing record (upsert by PAN).  
**Current workaround:** User must correct the Excel and re-import, which is
cumbersome for a single field change.

---

### F-05 — Detailed per-client log panel `P3`

**Reported:** 2026-06-10  
**Request:** In addition to the global live log, show per-client log output
accessible from the client list (e.g. expandable row or a "View Log" button).
Useful in bulk batches to trace exactly what happened for one client without
scrolling through the full log.  
**Notes:** Could be as simple as storing the log lines emitted during each
client's run (between the `──` dividers) and showing them in a popup on demand.

---

### F-06 — Bulk processing progress improvements `P3`

**Reported:** 2026-06-10  
**Request:** During a large batch (85+ clients), show overall progress more
prominently — e.g. "Client 12 of 85" in the dialog title bar, and a progress
bar at the bottom of the Batch Progress dialog.

---

### F-07 — Convert 26AS TXT to Excel `P2`

**Reported:** 2026-06-10  
**Request:** Form 26AS is downloaded as a `.txt` file (fixed-width / pipe-delimited format
from TRACES). Users want an Excel file they can open and filter directly.  
**Implementation direction:** After download, parse the TXT using Python's `csv` or
pandas, map the known 26AS sections (Part A, Part B, etc.) to named sheets in an
`.xlsx` file using `openpyxl`. Save alongside the existing TXT as
`<PAN>-26AS-<AY>.xlsx`.  
**Notes:** The TXT format occasionally changes when TRACES updates — parser should
fail gracefully and leave the TXT intact if parsing fails.

---

## Notes

- **B-02 (PDF unlock)** is the highest-priority bug — files appear to download
  successfully but are unusable without manual unlocking.
- **B-03 (PAN validation)** should be implemented at vault-save time so bad data
  never enters the vault in the first place.
- Items marked **P1** should be addressed before the next release.
- Add more issues below as they are discovered; assign GitHub Issue numbers once
  filed.
