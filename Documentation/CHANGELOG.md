# Changelog

All notable changes to AayDocCapio are documented here.

## [1.7.6] — 2026-06-20

### New Features

#### Run History (F-13)
- **View Log** — right-click any client to see the last 20 download statuses per Assessment Year, with timestamps and colour-coded results (green/red/amber)
- **Email events in log** — successful email sends recorded in run history showing which document types were mailed

#### Named Email Templates (F-17)
- **Multiple templates** — create named email templates each with its own subject, body and document type selection (26AS PDF, 26AS Excel, AIS PDF, AIS Excel, TIS)
- **Template picker in Mail Docs** — choose which template to use when sending; doc filtering applied automatically at send time
- **Set as Default** — mark any template as default; Mail Docs pre-selects it on open
- **Copy from existing** — new templates can be created by copying an existing one
- **Legacy migration** — existing subject/body auto-migrated to "Legacy Template" on first run

### Improvements
- **Email Settings redesign** — Templates tab now comes first; SMTP tab opens automatically for first-time users
- **Inline doc-not-found status** — clients with no matching documents for the selected template show "Docs not found" inline instead of a blocking dialog
- **Selected count in status bar** — Mail Docs status bar shows how many clients are currently selected
- **Menu border visibility** — menus now have a distinct border in both light and dark themes
- **Form alignment in Mail Docs** — Template / Folder / Filter rows now pixel-aligned using QFormLayout

---

## [1.7.2] — 2026-06-19

### New Features

#### Auto Update
- **In-app update checks** — Added the auto-update workflow so AayDocCapio can surface newer releases from inside the application.

#### Help Manual
- **Integrated help manual** — Added a detailed in-app help manual with structured navigation for bulk downloads, client management, settings, SMTP/email setup, and update guidance.

### Improvements

#### AIS JSON → Excel Workbook
- **More reliable AIS extraction** — Fixed skipped `l1` transaction rows when `l2` summary data is empty, including SFT purchase rows, and added TCS-specific aliases for amount, tax collected, deposited amount, and receipt/debit dates.
- **General Info sheet refresh** — AIS workbooks now capture Part A assessee fields (PAN, Aadhaar, name, DOB, mobile, email, address) with a 26AS-style header and notes section.
- **Summary sheet navigation** — Summary rows are grouped by Info Code with meaningful subtotal labels such as `Subtotal: Dividend (TDS-194)`, internal links to destination sheets, and no unnecessary grand total.
- **Capital Market (All) polish** — The consolidated capital market sheet now freezes only the first four header rows and adds Excel outline grouping below each SFT-code subtotal.
- **Workbook metadata** — AIS Excel files now include Windows/Office document properties for title, subject, author, keywords, and generated comments.

### Bug Fixes
- **26AS Excel generation fixes** — Fixed minor 26AS Excel generation issues, including summary/detail accuracy and audit-trail polish.
- **SFT-18(Pur) amounts** — `Total Purchase Amount` and `Total Sales Value` now populate correctly in the SFT-18(Pur) sheet.
- **TDS/TCS dates** — 194K and TCS rows now populate date fields from `Date of Receipt/ Debit` when `Date of Payment/Credit` is absent.
- **Summary hyperlink styling** — Summary cells remain internally linked but no longer appear blue and underlined.

---

## [1.6.4] — 2026-06-19

### New Features

#### Help Manual Overhaul & Granular Navigation
- **Expanded Sidebar Navigation** — Redesigned the left sidebar navigator with 37 interactive sections and sub-sections, using nested visual indentation and robust JavaScript Scrollspy tracking.
- **Managing Clients Rebranding** — Rebranded "Client Vault" to "Managing Clients" and grouped the Excel bulk import/export guidelines directly under it.
- **Bulk 26AS & AIS Download Guides** — Added step-by-step guides for initiating bulk downloads, specifically detailing the required toolbar options and dropdown menu items.
- **SMTP Email & Mailing Setup** — Included complete SMTP email configuration instructions (covering provider presets, Google App Passwords, and test connections) alongside document-mailing templates.
- **Settings Sub-sections** — Organized all client and application preferences under dedicated sections for Download Folder, Assessment Years, and Visual Themes.
- **Inbuilt Auto-Update Guidelines** — Added documentation detailing the application's built-in update check on startup and manual update checks via the Help menu.
- **Clean Sticky Navbar** — Replaced links in the top navbar with a simplified sticky header containing the AayDocCapio branding and a "Contact us" link pointing to `deepak.bholusaria.com`.

#### Download History Columns
- **Last Download Time Column** — Added a dedicated column in the main client table to display the timestamp of the last successful download.
- **Persistent Metadata** — Vault file (`tax_vault.json`) now records and populates timestamp details per client per Assessment Year.

### Bug Fixes / Improvements
- **Non-existent PAN detection (B-08)** — Detects "PAN does not exist" or "PAN is not registered" errors immediately after entering the PAN on the ITD portal, failing fast with a clean message instead of timing out on the SAM page.

---

## [1.6.3] — 2026-06-18

### New Features

#### AIS JSON → Excel Conversion
- **Convert AIS JSON → Excel** — pick a single AIS JSON file via Tools → Convert AIS JSON → Excel…; the file is decrypted and converted to a fully-formatted Excel workbook in one pass
- **Per-category sheets** — one sheet per AIS/TIS section (TDS/TCS, Salary, Dividend, Interest, SFT transactions, Demand & Refund, Proceedings, etc.) with flat-table layout, Indian numeric formatting, and per-deductor subtotals
- **Capital Market (All) — consolidated sheet** — aggregates all SFT-17 and SFT-18 capital market sales across every individual category sheet into a single view; live linked formulas auto-compute STCG, LTCG (without indexation), and LTCG (with indexation) including Section 55(2)(ac) grandfathering adjustments for assets acquired before 31-Jan-2018
- **Audit Trail sheet** — per-SFT-code reconciliation of sales consideration and capital gain summaries with formula links back to individual sheets
- **ReadMe — Capital Gains sheet** — plain-English column guide with tax section references (112A, 112, 55(2)(ac)) and indexation-abolition disclaimer (23-Jul-2024)
- **Brand row + decrypted companion** — every workbook includes an assessee name/PAN/FY header row and saves a `_decrypted.json` alongside for audit

---

## [1.5.6] — 2026-06-16

### New Features
- **Mail Docs to Clients** — batch email AIS/TIS/26AS files to clients; scan folder, match PANs, select recipients, send in one click with per-row live status
- **Email provider presets** — Gmail, Outlook.com, Microsoft 365/Office 365, Exchange, Yahoo, iCloud, Custom; one click auto-fills SMTP settings and shows provider-specific help
- **Rich text email composer** — font, size, Bold/Italic/Underline toolbar, CC/BCC, HTML templates with `{client_name}`, `{pan}`, `{ay}`, `{firm_name}`, `{documents}` placeholders
- **Numbered document list** — `{documents}` renders as a numbered HTML list of actual attached files (26AS PDF, 26AS Excel, AIS, TIS)
- **"Powered by AayDocCapio"** footer on every outgoing email
- **Email Docs + Exit buttons** on main toolbar; "Run" renamed to "Download"
- **Session dividers** in email activity log; client name logged on every send attempt

### UI Improvements
- Mail Docs table: sortable all columns, filter with × clear button, Select All/None respects filter, resizable columns
- Fluency multicolor icons on all buttons, menus, context menus across the app
- Premium blue left-bordered help notes with clickable links in Email Settings
- Dropdown arrow visible in dark theme

### Bug Fixes
- Batch send silent crash on HTML bodies with CSS `{}` braces
- Mail Docs sorting now moves all row widgets correctly
- Checkbox backgrounds match table row color (no white flash)
- Font combo non-editable; Qt font warnings suppressed

---

## [1.4.4] — 2026-06-15

### Improvements
- **26AS conversion now runs immediately** after each client's TXT download instead of waiting for the full batch to complete — Excel/HTML files are ready while the next client logs in
- **Dashboard settling improved** — sentinel timeout increased from 20s to 40s; slow accounts that miss the sentinel now get an extra 8s buffer before the nav menu is used, preventing e-File hover timeouts
- **e-File menu hover retry** — full wait+hover cycle retried up to 4 times with a 5s pause and page nudge between attempts if the Angular nav menu isn't interactive yet
- **Portal warm-up before first client** — opens the ITD login page once before the batch loop so the Angular bundle, CDN assets and cookies are preloaded; eliminates the slower first-client load that caused hover timeouts after long idle periods
- **Batch progress dialog shows both AY/TY and FY** — header now reads e.g. `AY 2026-27 (FY 2025-26)` for all modes instead of showing only the AY
- **TIS "no data" detected in ~1.5 s** — previously burned the full 60 s `expect_download` timeout before reading the portal's "no data" banner; now checks inside the download wait and exits immediately

### Bug Fixes
- **Account locked fast-fail** — inline "e-filing account has been locked" error on the PAN screen is now detected immediately, failing fast with a clear message instead of waiting 60s for SAM page
- **Active session dialog handled (B-04)** — "already logged in / active session" portal dialog during login is now detected and auto-dismissed (Continue/Proceed/Yes/OK), allowing login to proceed normally
- **Conversion status not updated in batch dialog** — status column now shows `⏳ Converting to Excel…` during conversion and `✅ 26AS + Excel + HTML` on completion (was stuck at `✅ 26AS Downloaded`)
- **"Open Folder" fails on junctions/SUBST drives** — `_log_open` was silently failing because the main `logging.FileHandler` held an exclusive write lock on `app.log` on Windows, swallowing all diagnostics; diagnostics now written to a separate `open_folder.log`; `_is_reparse_point` upgraded to `ctypes.windll.kernel32.GetFileAttributesW` for reliability under Nuitka/Python 3.14
- **Stale browser object crashes next batch** — if Chrome was closed between batches, `is_connected()` returned True on the stale object but `new_context()` threw `'NoneType' has no attribute 'send'`; browser manager now catches context-creation failures, forces a full restart, and retries transparently
- **`net::ERR_EMPTY_RESPONSE` fails entire batch** — transient portal network error on the initial `page.goto` to the ITD login URL was not retried and aborted the client immediately; now retried up to 3 times with a 5 s backoff before giving up

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
