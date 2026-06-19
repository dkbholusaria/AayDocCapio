# Changelog

All notable changes to AayDocCapio are documented here.

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

#### Email Delivery
- **Mail Docs to Clients dialog** — scan a download folder, match client PANs, select recipients, and send tax documents in bulk. Accessible via the new **Email Docs** button on the main toolbar or Tools → Mail Docs to Clients
- **Batch email with live status** — per-row progress: ⏳ Sending → ✅ Sent / ❌ Failed with friendly SMTP error messages
- **Inline email editing** — type or correct a client's email address directly in the table; saved to vault before sending
- **Numbered document list** — `{documents}` placeholder in email body renders as a numbered HTML list identifying each attached file by type (Form 26AS PDF, Form 26AS Excel, AIS, TIS)
- **"Powered by AayDocCapio"** footer appended automatically to every outgoing email with a clickable link to the download page
- **Session log dividers** — email log now shows `── SESSION STARTED ──` / `── SESSION ENDED ──` separators between app sessions
- **Client name in email log** — every send attempt logs the client name and PAN for easy audit

#### Email Provider Presets
One-click SMTP configuration for all major providers — selecting a tile auto-fills host, port, encryption, and shows provider-specific setup help with clickable links:

| Provider | SMTP Host | Port |
|---|---|---|
| Gmail | smtp.gmail.com | 587 |
| Outlook.com / Hotmail | smtp-mail.outlook.com | 587 |
| Microsoft 365 / Office 365 | smtp.office365.com | 587 |
| Exchange (on-premise) | configurable | 587 |
| Yahoo Mail | smtp.mail.yahoo.com | 587 |
| iCloud Mail | smtp.mail.me.com | 587 |
| Custom / Other | any | any |

#### Rich Text Email Composer
- Font family picker, font size, Bold / Italic / Underline toolbar
- Placeholder chips: `{client_name}`, `{pan}`, `{ay}`, `{firm_name}`, `{documents}`
- CC and BCC fields; BCC added to SMTP envelope but not email headers
- Send Test Email button to verify settings before bulk send

### UI Improvements
- **Download button** — "Run" renamed to "Download" for clarity
- **Email Docs button** — quick-launch on main toolbar (no menu navigation)
- **Exit button** — one-click close on main toolbar with clean session-end logging
- **Mail Docs table** — sortable on all columns, filter bar with one-click clear (×), Select All/None respects active filter, resizable columns
- **Fluency multicolor icons** — all buttons, menus, and context menus across the entire app now have icons
- **Premium help notes** — blue left-bordered info panels with clickable links in Email Settings
- **Dropdown arrow** — visible in dark theme via CSS triangle fallback

### Bug Fixes
- **Batch send silent crash** — `format_map()` crashed on HTML bodies containing CSS `{}` braces; switched to explicit per-placeholder `.replace()` 
- **Mail Docs sorting** — sorting now correctly moves checkboxes, email fields, CC fields, and send status together with the row (previously only text items moved)
- **Checkbox backgrounds** — white flash in Mail Docs table fixed; checkbox container background now matches alternating row color
- **Font combo editable** — `QFontComboBox` no longer accepts typed input (dropdown-only)
- **Qt font warnings** — `qt.text.font.db: OpenType support missing` console spam suppressed via `qInstallMessageHandler`

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
