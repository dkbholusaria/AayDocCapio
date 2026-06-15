# Changelog

All notable changes to AayDocCapio are documented here.

---

## [1.4.4] — 2026-06-15

### Improvements
- **26AS conversion now runs immediately** after each client's TXT download instead of waiting for the full batch to complete — Excel/HTML files are ready while the next client logs in
- **Dashboard settling improved** — sentinel timeout increased from 20s to 40s; slow accounts that miss the sentinel now get an extra 8s buffer before the nav menu is used, preventing e-File hover timeouts
- **e-File menu hover retry** — retries up to 3 times with a 3s pause between attempts if the Angular nav menu isn't interactive yet after the overlay clears

### Bug Fixes
- **Account locked fast-fail** — inline "e-filing account has been locked" error on the PAN screen is now detected immediately, failing fast with a clear message instead of waiting 60s for SAM page
- **Active session dialog handled (B-04)** — "already logged in / active session" portal dialog during login is now detected and auto-dismissed (Continue/Proceed/Yes/OK), allowing login to proceed normally
- **Conversion status not updated in batch dialog** — status column now shows `⏳ Converting to Excel…` during conversion and `✅ 26AS + Excel + HTML` on completion (was stuck at `✅ 26AS Downloaded`)

---

## [1.4.3] — 2026-06-14

### Improvements
- **Windows installer** — Windows installer packages are now built and distributed as part of each release


## [1.4.0] — 2026-06-11

### New Features
- **Status filter dropdown** — filter client grid by All / Downloaded / Partially Completed / Failed / Queued / Not run yet
- **26AS TXT → Excel + HTML converter** — auto-runs after each 26AS batch; also available via Tools menu. Handles 200K+ row files via xlsxwriter streaming writer
- **Form 26AS Excel workbook** — Assessee Details sheet, one sheet per Part (I–IX), Summary sheet with hyperlinks to each deductor row
- **Locked-file fallback** — if Excel is open when converter tries to save, file is written to a timestamped alternate name and a warning shown in the completion dialog
- **26AS TXT download** — after PDF, switches TRACES to Text format and downloads the ZIP-protected TXT file
- **Tools menu** — manual "Convert 26AS TXT to Excel…" file picker
- **Batch progress dialog** — per-client status, Save Path column, Open Folder / Download Report buttons
- **Assessment Year management** — add/remove/reorder AYs via ⚙ Manage Years dialog
- **AIS status bar** — shows queued count and wait-time reminder after AIS request batch

### Improvements
- **Auto-convert scoped to batch** — converter now only processes TXT files downloaded in the current batch, not all TXT files in the output folder
- **Auto-convert after batch** — `_auto_convert_26as()` triggered on batch completion
- **Per-client conversion status** in batch progress dialog (⏳ Converting → ✅ 26AS + Excel + HTML)
- **Truncated status tooltip** — hovering over a clipped Last Download Status cell shows the full text
- **Large 26AS detection** — TRACES "on-demand" message (`div#message`) is detected and surfaces a clear actionable error instead of crashing on missing pdfBtn
- **ITD login fix for real Chrome** — replaced `networkidle` wait (never fires in real Chrome due to background connections) with a fixed 3 s sleep after `domcontentloaded`

### Bug Fixes
- **26AS TXT ZIP unlock failure now surfaced** — logs the attempted password, shows `⚠ Partially Completed` status instead of `✅ 26AS Downloaded`, leaves the encrypted file as `.zip` (not `.download`) for manual extraction
- **AIS/TIS PDF unlock failure now surfaced** — `_unlock_and_warn()` emits `[Warning]` with filename and used DOB when no password candidate matched
- **Auto-convert ran on wrong files** — was walking entire `download_root_dir`; now only converts files from the current batch (tracked via `_batch_26as_txts`)
- **26AS Part-VI Amount Paid showing 0.00** — detail rows use key `Amount Paid / Debited(Rs.)` (no "Total" prefix); fixed in both HTML and Excel
- **Summary sheet alternate-row text invisible** — `td.pbadge` CSS needed `!important` to override `tr.alt td` on alternating rows
- **Address fields shifted** (State = PIN, PIN = blank) — header parser was stripping empty fields, shifting subsequent positional values; fixed by preserving empty fields in the zip
- **Notes cell black background** — 8-digit openpyxl-era hex (`#fffff9f0`) is invalid in xlsxwriter; fixed to 6-digit `#fffde7`
- **Subtitle row text clipped** — added `wrap=True` to subtitle format, increased row height to 22 pt
- **Assessment Year dropdown closes immediately** — 300 ms debounce in `StyledComboBox` (B-01, fixed)
- **AIS/TIS downloads silently failing** — `expect_download` was called on `BrowserContext` instead of `Page`; fixed all 7 call sites
- **Hamburger nav collapse** — `_open_hamburger()` scrolls to top and clicks `#hamburgerOpen` before navigating

### Internal
- Migrated 26AS Excel writer from openpyxl to xlsxwriter (streaming, constant memory, ~10× faster)
- `downloader_26as.py` returns `(ok, err_msg, txt_path)` tuple so callers know exactly which TXT was saved
- `_safe_move()` — atomic write via temp file, fallback to timestamped filename on `PermissionError`
- Real Google Chrome (`channel="chrome"`) required for AIS/TIS; bundled Chromium fallback with warning
- Fixed `viewport={"width":1600,"height":900}`, removed `--start-maximized` conflict

---

## [1.1.0] — 2026-06-04

### New Features
- AIS / TIS download support (instant + queued flows)
- PDF password removal via pikepdf (`pdf_unlocker.py`)
- Encrypted vault (`cryptography` Fernet/AES-128)
- Bulk import from Excel/CSV

---

## [1.0.0] — 2026-05-15

- Initial release: 26AS PDF download, single-client and batch modes, PyQt6 GUI
