# Development Log — ITD Docs Downloader

This document records the major design decisions, the problems encountered while
automating the Income Tax Department (ITD) e-Filing and Insight/AIS portals, and
the root-cause fixes that finally made AIS/TIS downloads reliable. It is meant as
a reference so the hard-won knowledge is not lost or re-learned.

---

## 1. Goal

A standalone desktop utility (PyQt6 + Playwright) that logs into the ITD
e-Filing portal and bulk-downloads, for many clients in one run:

- **Form 26AS** (via the TRACES portal)
- **AIS** — Annual Information Statement (PDF) via the Insight Compliance Portal
- **TIS** — Taxpayer Information Summary (PDF) via the same portal

Credentials (PAN, DOB, portal password) are stored in a local encrypted vault.

---

## 2. Architecture

app.py                       PyQt6 GUI, batch orchestration, progress dialog
vault.py                     Encrypted credential vault (openpyxl + csv, no pandas)
automation/
  browser.py                 Playwright browser manager (launches real Chrome)
  auth.py                    ITD login / logout
  downloader_26as.py         Form 26AS (TRACES) flow
  downloader_ais_tis.py      AIS / TIS (Insight portal) flow
  downloader.py              Shared helpers (status badge, step logger)

The GUI runs the batch in a background thread; per-client status is pushed to a
live **Batch Progress** dialog via Qt signals. Each client is processed in its
own `try/except`, so one client's failure never aborts the batch.

---

## 3. Key Design Decisions

### 3.1 Run dropdown (replaced three buttons)

The action bar uses a single **▶ Run** split-button (`QToolButton` + `QMenu`):

- Download 26AS
- Download / Request TIS & AIS
- Download Previously Requested AIS

The old per-document checkboxes ("26AS / AIS / TIS" tick boxes) were removed as
redundant — the menu choice itself expresses intent. AIS and TIS always download
together when "Download / Request TIS & AIS" is chosen.

### 3.2 Stop button lives on the progress popup

The Stop control was moved from the main toolbar into the Batch Progress dialog
footer. It calls `stop_automation()` on the main window, then hides itself when
the batch finishes (Close button takes over).

### 3.3 Live per-client progress dialog

`BatchProgressDialog` shows one row per assessee (Name | Status). Status updates
arrive from the worker thread via `pyqtSignal`. It is **window-modal**
(`Qt.WindowModality.WindowModal`) and uses `Qt.WindowType.Dialog` so it blocks
the parent window and renders an active title bar, while `show()` (not `exec()`)
keeps the event loop alive for live updates.

#### Table layouts (Batch Progress and Main Screen Client List)

Both the **Batch Progress** dialog and the **Main Client List** on the main screen use a true `QTableWidget` to display information in a clean, professional grid:

- **Batch Progress Table:**
  - Name column: **Interactive** width (drag to resize), default 250 px.
  - Status column: **Stretch** — fills remaining space automatically.
  - Grid lines and alternating row colours (`#FFFFFF` / `#F8FAFC`) are enabled.

- **Main Client List Table:**
  - Header is part of the table widget itself (ensuring perfect column alignment).
  - Columns: Checkbox (Select, width 45, interactive), Name (Stretch), PAN (width 140, interactive), Date of Birth (width 130, interactive), Actions (width 90, interactive).
  - Drag-to-resize is fully supported on all column headers.
  - Grid lines and alternating row colours (`#FFFFFF` / `#F8FAFC`) are enabled.
  - Clicking on any text cell (Name, PAN, or DOB) toggles the select checkbox for that client.
  - Row filtering/searching hides/shows matching rows dynamically via `setRowHidden()`.
  - **Interactive Sorting:** Users can click the **Name** or **PAN** headers to sort alphabetically (ascending/descending). Sorting indicators are shown dynamically and only for these two allowed columns. Sort state is preserved and re-applied automatically whenever the grid is refreshed.
  - **Header Select-All Checkbox:** The first column (checkbox) header contains an interactive `QCheckBox` widget centered overlays. Checking/unchecking this box instantly toggles all clients. The dedicated checkbox at the bottom has been removed to maximize interface cleanliness.

#### Per-client status lifecycle

Every assessee row cycles through these status values during a batch run:

| Status | Meaning |
|---|---|
| `⬜ Waiting` | Not yet started |
| `⏳ Logging in to ITD...` | Browser opening ITD login page |
| `✅ Logged in — loading portal...` | Dashboard reached |
| `⏳ Opening AIS portal...` | Navigating to Insight compliance portal |
| `⏳ Selecting Financial Year...` | FY dropdown interaction |
| `⏳ Downloading AIS PDF...` | AIS download button clicked, waiting for file |
| `✅ AIS downloaded — fetching TIS...` | AIS saved, now opening TIS modal |
| `🕐 AIS queued — fetching TIS...` | AIS is a large file, queued server-side |
| `⚠️ AIS issue — fetching TIS...` | AIS attempt had an issue but continuing |
| `✅ TIS downloaded — wrapping up...` | TIS saved, about to log out |
| `⚠️ TIS could not be downloaded` | TIS download failed |
| `⏳ Downloading 26AS...` | 26AS mode — TRACES download in progress |
| `⏳ Logging out...` | Clearing ITD session |
| `✅ AIS Downloaded instantly` | Final success (instant AIS) |
| `✅ 26AS Downloaded` | Final success (26AS mode) |
| `🕐 AIS request placed (Ref: …)` | AIS queued — retry with Download mode later |
| `⬜ Skipped — AIS not available for this FY` | FY pre-dates AIS availability |
| `❌ Failed — <reason>` | Error with short description |
| `⏸ Cooling down... 5s / 4s / … / 1s` | Live countdown between clients |

#### Inter-client isolation and cooldown

Each client gets a **fresh, isolated `BrowserContext`** (separate cookies,
localStorage, and session state) created just before login and destroyed
immediately after logout. This prevents session bleed between clients.

After each client (except the last), a **5-second cooldown** is applied with a
live countdown visible in the Batch Progress window. This reduces the risk of
triggering ITD's `loginMaxAttemptsPopup` rate-limit on rapid consecutive logins.

If the rate-limit popup *does* fire and is handled, an additional **6-second
recovery pause** is applied inside `auth.py` before returning the page, giving
the Angular router time to fully re-initialise before navigation events are sent.

### 3.4 Vault without pandas

Import/export/template use `openpyxl` + `csv` directly (pandas was removed to cut
binary size). `import_bulk()` returns `(added, updated, errors)`.

---

## 4. The Long Debugging Saga — AIS/TIS Downloads

For a long time AIS/TIS "succeeded" in logs but **no file ever downloaded** and
nothing appeared in the portal's Activity History. Many click strategies were
tried and all appeared to fail:

- plain Playwright `.click()`
- `element.click()` via `page.evaluate`
- `dispatch_event("click")`
- raw `page.mouse.click(x, y)` at `bounding_box()` coordinates
- `getBoundingClientRect()` viewport coordinates
- keyboard `focus()` + `Enter`
- `Zone.current.run(() => btn.click())` (Angular NgZone)
- ARIA `get_by_role("button", name="Download")`

### 4.1 Root cause #1 — `expect_download` on the wrong object (THE bug)

```python
# WRONG — raised "'BrowserContext' object has no attribute 'expect_download'"
async with portal.context.expect_download(...) as dl_info:
    ...
# CORRECT
async with portal.expect_download(...) as dl_info:
    ...
```

`expect_download` exists only on **Page**, never on **BrowserContext**. The wrong
call raised an `AttributeError` *before the click result could be captured*. A
bare `except` swallowed it and the code fell through to "queued / Reference ID:
N/A". **The download was never actually attempted.** This single mistake masked
every click strategy above — none of them ever had a chance.

Fixed in all 7 call sites across `downloader_ais_tis.py` and `downloader.py`.
Once fixed, AIS downloaded **instantly for every year tested** (2025-26, 2023-24),
so the elaborate "Request → wait → Activity History" two-phase flow is rarely
needed in practice.

### 4.2 Root cause #2 — must use real Google Chrome

The Insight/AIS portal's Angular handlers/downloads behave correctly only on the
user's installed Google Chrome, not Playwright's bundled Chromium.

```python
# browser.py — prefer real Chrome, fall back to bundled Chromium
await self._playwright.chromium.launch(headless=headless, channel="chrome", ...)
```

This was confirmed against a competitor app (Node/Electron) whose own log proved
AIS only downloaded **after** `npx playwright install chrome` installed real
Chrome. If Chrome is absent we fall back to bundled Chromium and warn the user:
26AS works, but AIS/TIS downloads need Chrome.

**Note:** the requirement is the *engine* (`channel="chrome"`), not a visible
window. AIS/TIS download correctly in **headless** real-Chrome too (tested), so
the app defaults to headless ("Run in background"); the user can uncheck it to
watch the browser or handle a CAPTCHA.

### 4.3 Root cause #3 — viewport / window sizing

`--start-maximized` **conflicts** with a fixed Playwright viewport and distorts
the aspect ratio, collapsing the ITD nav and pushing it off-screen. Fix:

```python
# browser.py context
viewport={"width": 1600, "height": 900}   # no --start-maximized, no bypass_csp
```

Even at 1600px the dashboard nav can collapse into a hamburger, so before
clicking `a#AIS` (or `e-File` for 26AS) we:

1. `window.scrollTo(0,0)` + reset every scrollable container (nav can be scrolled
   out of view),
2. click `#hamburgerOpen` (with fallback selectors) if present.

---

## 5. ITD / Insight Portal Flow (verified against live HTML)

### 5.1 Login (`auth.py`)

1. Navigate to `#/login`, wait for Angular hydration.
2. Fill `#panAdhaarUserId`, click **Continue**.
3. Wait for SAM (Secure Access Message) checkbox `#passwordCheckBox-input`, tick it.
4. Click **Continue** → portal shows method-selection page (`#/login/otpOptions`).
5. Select the **Password** radio using a 3-level fallback selector chain; click **Continue**.
6. If URL is already `otpOptions` at this point → **fail fast** with 2FA error.
7. Fill `#loginPasswordField`, click **Continue** (up to 4 attempts).
8. On each poll tick: if URL is `otpOptions` → **fail fast** with 2FA error.
9. Handle `#loginMaxAttemptsPopup` → "Login Here".
10. Detect wrong password from inline error text (portal says
    *"Error : Invalid Password, Please retry."*) and **fail fast** with that
    message rather than retrying.
11. Dashboard success = URL no longer contains `/login`.
12. On any failure the login page is closed (no orphan-tab leaks across clients).
13. `is_running` callback checked before each submit retry — honours Stop/Abort.

### 5.2 Opening the AIS portal (`_open_ais_portal`)

- Open hamburger, click `a#AIS`.
- Arm a new-tab listener **before** the click; dismiss an optional "Yes"
  confirmation; race between a new tab opening and the same tab navigating to
  `ais.insight.gov.in`.

### 5.3 AIS portal navigation

- Portal lands on `/complianceportal/ais/instructions`.
- FY selection: go to `/ais/home` via the sub-navbar AIS tab, open
  `.fy-dropdown button#dropdownMenuButton`, pick `F.Y. YYYY-YY`
  (`button.dropdown-item`).

- *Important Fix (2026-06-04)*: We previously used a combined "Download AIS/TIS" 
  button on the Instructions tab. This had a portal-side bug where it ignored 
  the selected FY and always generated 2025-26 documents. 

- The reliable entry point is now clicking the specific download icons on the 
  `ais/home` tiles themselves using `img[title='Download AIS related documents']` 
  and `img[title='Download TIS related documents']`. This correctly preserves 
  the selected FY context.

### 5.4 Download modal (`mat-dialog-container`)

- AIS modal rows (each `div.d-flex` with `p.dialog-sub-head` + one
  `button.dialog-outline-btn`):
  - "Annual Information Statement (AIS) - PDF" ← downloaded
  - "Annual Information Statement (AIS) - JSON (for AIS Utility)" ← skipped (CAPTCHA)
  - "AIS Consolidated Feedback (ACF) - PDF" ← skipped
- TIS is a **separate** modal/row: "Taxpayer Information Summary (TIS) - PDF".
- `request_ais()` downloads AIS PDF, then `download_tis()` downloads TIS PDF in
  the same portal session.
- Files saved as `<PAN>-AIS-<FY>.pdf` and `<PAN>-TIS-<FY>.pdf`.

### 5.5 Activity History (two-phase fallback, rarely needed)

For genuinely large files that queue instead of downloading instantly:

- Row = `tr.example-element-row`; columns by class
  (`mat-column-activityType`, `mat-column-description`, `mat-column-referenceId`,
  `mat-column-download`).
- Pending state: `img[alt="Progress"]` (`title="File in progress"`).
- Ready state: `a[title="Download file"]` → click to download.
- Poll every 30s up to 10 min.

---

## 6. Step Logging

`make_step_logger(log_callback, prefix)` in `downloader.py` returns a
`step(msg, page=None)` that emits numbered, URL-tagged progress lines, e.g.:

[AIS-OPEN] (6) Clicking a#AIS  |  url: https://eportal.incometax.gov.in/...
[AIS-DL]   (5) Download saved: AABCP1234F-AIS-2025_26.pdf

Comprehensive step logs are deliberately **kept permanently** across login, 26AS,
and AIS/TIS — they make any future portal change trivially diagnosable.

---

## 7. Error Handling & Mixed Batches

- Each client runs in its own `try/except` — failures are isolated.
- A failed client records `_ais_results[pan] = "failed"` and the error string in
  `_last_errors[pan]`; the progress row shows `❌ Failed — <reason>` and the
  results dialog lists the distinct reasons.
- Example mixed batch (one wrong password, one correct): the wrong one fails fast
  with the portal's message and its tab is closed; the correct one downloads
  normally; the summary dialog reports both.

---

## 8. Security Constraints (must preserve)

- **PAN is never logged or shown in error messages** — always masked as
  `pan[:3] + "XXXXXXX"`.
- Credentials stored locally, AES-128 (Fernet), PBKDF2HMAC-SHA256.
- Credentials only ever submitted to the official ITD portal.

---

## 9. Environment Notes

- **WSLg blank window / `WARN:COPY MODE`**: a WSLg compositor glitch, not a code
  bug. Fix with `wsl --shutdown` (Windows PowerShell) and relaunch, or force the
  X11 backend (`QT_QPA_PLATFORM=xcb`). Not caused by the app.
- Build uses **Nuitka** (compiles to native code) + Inno Setup, not PyInstaller.

---

## 10. Corporate Network / Proxy Support

### 10.1 Problem

On corporate machines (CA firms, etc.) Windows may route all traffic through a
proxy server configured in Internet Explorer / Windows Settings. Without picking
this up, Playwright's Chromium connects directly and gets blocked.

### 10.2 Fix — `_get_system_proxy()` in `browser.py`

Reads the Windows registry at launch:

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings
  ProxyEnable  (DWORD)  — 1 = proxy active
  ProxyServer  (String) — "host:port"  or  "http=host:port;https=host:port"
```

The per-protocol format (`http=…;https=…`) is parsed; `https=` takes priority,
then `http=`. If no scheme prefix present, `http://` is prepended. The resulting
`{"server": "http://host:port"}` dict is passed directly to `chromium.launch(proxy=…)`.

No proxy is set on non-Windows platforms (Linux / WSL dev environment).

---

## 11. Slow Network / Timeout Increases

### 11.1 Problem

On slow broadband or congested networks the ITD portal returns
`net::ERR_EMPTY_RESPONSE` or simply times out before the previous shorter
timeouts expired, causing premature failures.

### 11.2 Fix

All timeouts in the login and download flows were doubled:

| File | What changed |
|---|---|
| `auth.py` | Portal `goto`: 60s→90s; networkidle: 30s→60s; SAM loop: 30s→60s; Continue buttons: 10s→20s / 5s→15s; password field: 5s→15s |
| `downloader_26as.py` | All element waits and timeouts doubled |
| `downloader_ais_tis.py` | All element waits and timeouts doubled |

---

## 12. Startup Diagnostics

### 12.1 Problem

A colleague's machine silently crashed on double-click with no `app.log` created.
The exe was dying before `AayDocCapioApp.__init__()` ran — before any Qt or
logging code could execute.

### 12.2 Fixes in `app.py`

**Module import guard:** Wrapped the top-level `from vault import …` / `from automation …`
imports in a `try/except`. On failure, a `ctypes.windll.user32.MessageBoxW` dialog
is shown (works before Qt is initialised) with the full traceback.

**`startup_diag.log`:** Written using only Python builtins (no logging module,
no Qt) to `%LOCALAPPDATA%\AayDocCapio\startup_diag.log`. Records 8 numbered
steps from import success through to `QApplication` creation, so the exact
crash point is always visible even when `app.log` is never created.

**`_fatal()` helper:** Falls back from `QMessageBox` → `ctypes.MessageBoxW` → silent
`sys.exit(1)`, so a visible error is always shown regardless of whether Qt is up.

### 12.3 VC++ Redistributable (installer fix)

Added `VCRedistInstalled()` registry check in `installer.iss`. If not present,
the installer silently downloads `vc_redist.x64.exe` from Microsoft's official
CDN and runs it before the Chromium install step.

---

## 13. Login Flow Updates

### 13.1 Password method selection (robustness fix)

The original selector `//label[normalize-space(text())='Password']` was fragile
on Angular Material — the label text may contain nested spans or extra whitespace.
It silently failed, leaving the portal on the OTP path.

**Fix:** 3-level fallback selector chain:
1. `//label[contains(normalize-space(.), 'Password') and not(contains(…, 'OTP'))]`
2. `input[type='radio']#mat-radio-0-input` (Password is always the first radio)
3. `input[type='radio']:first-of-type`

Additionally, a **second Continue click** is now made after selecting the Password
radio — this was the missing step that caused the portal to never advance to the
password field.

### 13.2 2FA / OTP detection (fast-fail)

Some client accounts have two-factor authentication enabled on the ITD portal.
After entering the password the portal navigates to `#/login/otpOptions` and
presents a 6-digit OTP entry form (Aadhaar-registered mobile). This cannot be
automated.

**Previous behaviour:** Code kept clicking Continue on the OTP page through all 4
retry attempts, taking ~3 minutes before failing with a cryptic message.

**Fix:** URL is checked for `otpOptions` at two points:
1. Immediately after the method-selection step (before filling the password field)
2. Inside `_submit_once` on every 0.5s poll tick

On detection a `RuntimeError` is raised immediately:
```
AUTHENTICATION FAILED: This account has 2FA (OTP) enabled on the ITD portal.
Automated login is not possible. The client must disable 2FA or log in manually.
```

**Resolution for affected clients:** Go to ITD portal → Profile → Login Settings
→ disable Two-Step Authentication.

### 13.3 Abort mid-login (Stop button fix)

The Stop button set `is_running = False` on the main window but `auth.py` had
no access to this flag. The batch would only check it *between* clients, so
pressing Stop mid-login still waited up to 3 minutes for all 4 submit attempts
to exhaust.

**Fix:** `login_itd()` now accepts an optional `is_running` callable. The submit
retry loop checks `is_running()` before each attempt and raises
`RuntimeError("Aborted by user.")` immediately if it returns `False`.

---

## 14. Status (as of 2026-06-10)

Working end to end:

- Login with robust error handling and fast-fail on bad password
- 2FA/OTP accounts detected immediately with a clear, actionable error message
- Stop/Abort respected mid-login (not just between clients)
- 26AS download (TRACES) — robustly handles full-screen loader intercepts and slow new-tab spawning
- AIS + TIS download for all years (instant) — respects FY selection
- FY switching
- Mixed batches with per-client isolation and clear error reporting
- Permanent step logging
- Automated PDF Unlocking (`pikepdf` decrypts using PAN+DOB seamlessly)
- Headless Automation by default (with UI checkbox for visual debug mode)
- Corporate proxy auto-detection from Windows registry
- Startup diagnostics written before Qt initialises (helps diagnose silent crashes)
- VC++ Redistributable auto-installed by the setup wizard if missing

Pending / optional:

- Large-file queued path (Activity History) — implemented but seldom exercised
  since files download instantly
- Windows build with all latest changes (rebuild required to deploy to clients)

---

## 15. v1.4.4 Fixes — Login & Dashboard Reliability (2026-06-15)

Several issues observed during live 93-client batch runs prompted a round of
reliability fixes.

### 15.1 First-client timeout after long idle (portal warm-up)

**Problem:** After a substantial idle period the ITD portal's Angular bundle,
CDN assets and cookies are cold. The first client's dashboard took 60s+ to
render the nav menu, causing the `e-File` hover to time out. Clients 2 onwards
were consistently faster because the assets were cached.

**Fix:** Added a portal warm-up step in `_execute_batch()` (`app.py`) before
the first client loop. Opens `#/login`, waits 5s for the Angular bundle to load,
then closes the tab. Costs ~5s per batch start; eliminates the cold-start timeout.

### 15.2 e-File menu hover timeout on slow dashboards

**Problem:** Even after the loader overlay cleared, the Angular nav menu was
sometimes not interactive. A single 30s `wait_for(visible)` + 30s hover timeout
meant the entire 60s was wasted before failing. HUF and company accounts were
most affected (slower dashboard render).

**Fix:** In `downloader_26as.py`, replaced the single wait+hover with a retry
loop (4 attempts × 30s wait + 10s hover). Between attempts: presses Escape and
scrolls to top to nudge Angular re-rendering. Also increased dashboard sentinel
timeout from 20s → 40s in `auth.py`, plus an 8s extra buffer when the sentinel
fires late.

### 15.3 Active session dialog (B-04)

**Problem:** If a client was already logged in on another device the ITD portal
showed an "already logged in / active session exists" dialog after the Continue
click on the PAN screen. The SAM-wait loop (200 × 300ms = 60s) exhausted without
ever finding `passwordCheckBox-input`.

**Fix:** Inside the SAM-wait loop in `auth.py`, scan the page body for
active-session keywords every iteration. When detected, click the first visible
Continue/Proceed/Yes/OK button to dismiss the dialog, then continue waiting for
the SAM checkbox normally.

### 15.4 Locked account — no fast-fail

**Problem:** When an account was locked the portal showed an inline error
("e-filing account has been locked due to security reasons") on the PAN screen.
The code didn't detect it and waited the full 60s SAM timeout before failing with
a cryptic "SAM page did not appear" message.

**Fix:** Added a locked-account check immediately after the Continue click (and
again inside the SAM-wait loop as a belt-and-suspenders). Raises
`RuntimeError("ACCOUNT LOCKED: …")` immediately. `errors.py` maps this to a
clean status column message.

### 15.5 26AS conversion status not reflected in batch dialog

**Problem:** After moving conversion to run immediately per-client (v1.4.0→v1.4.4
refactor), the status column was never updated — it stayed at `✅ 26AS Downloaded`
even though Excel + HTML were generated successfully.

**Fix:** Added `set_status(pan, "⏳ Converting to Excel...")` before conversion
and `set_status(pan, "✅ 26AS + Excel + HTML")` on success in `app.py`, matching
the strings used by the old `_auto_convert_26as()` end-of-batch path.

### 15.6 "Open Folder" fails on SUBST / mapped drives

**Problem:** On Windows, clicking "Open Folder" in the batch progress dialog
showed: *"D:\Trackers is not available. The path cannot be traversed because it
contains an untrusted mount point."* The user's output directory was set to a
virtual drive created with `SUBST D: C:\...`. Windows Explorer resolves SUBST
drives fine, but `os.startfile()` calls `ShellExecuteW` which rejects paths
through untrusted mount points.

**Fix:** In `config.py`, added `_resolve_win_path()` which runs `subst` and
parses its output to detect virtual drives and map them back to their real `C:\`
path. `_open_path()` now calls this resolver and passes the real path to
`explorer.exe` via `subprocess.Popen`, with `os.startfile()` as a fallback.

---

## 16. Status (as of 2026-06-19)

All major improvements for v1.6.4 have been implemented and verified.
- **B-02, B-05, B-06, B-07** — Closed.
- **B-08** — Fixed: "PAN does not exist" handled gracefully.
- **F-02** — Done: "Last Download Time" column in main client table.
- **F-15** — Done: Help Manual restored, completely redesigned with a left navigation sidebar, scrollspy highlighting, and a sticky top navbar featuring a 'Contact us' link to `deepak.bholusaria.com`.

Current known open items:
- **F-08** — AIS JSON download for oversized AIS (P3)
- **F-11–F-14** — Client groups, auto-update, log history, multi-AY download (backlog)

---

## 17. AIS Documentation Update — Security Class Enum Mappings (2026-06-18)

### 17.1 Context
In the Compliance Portal / AIS JSON schema, the `info_code` (e.g. `SFT-17-LES(M)` vs `SFT-17-EMF(M)`) and the `Security Class` enum codes (such as `LES`, `LPS`, `EMF`, etc.) are coupled. A specific transaction block under an `info_code` only consumes a subset of the security class enums. For example, `SFT-17-EMF(M)` only contains unit transactions (Security Class `EMF`), whereas Listed Equity Shares (`LES`) and Preference Shares (`LPS`) are strictly mapped under `SFT-17-LES(M)`.

### 17.2 Fix
Updated `Documentation/AIS_JSON_Tree.html` to add a new column "Consumed By (SFT Code)" to the "Security Class (SFT-17 & 18)" table, mapping each of the 10 enum codes to its corresponding SFT label.

---

## 18. User Manual Layout Overhaul & Navigation Panel (2026-06-19)

### 18.1 Context
The offline User Manual (accessible inside the app) was completely reconstructed across 13 sections, utilizing base64-encoded application screenshots to keep the document self-contained. To improve readability, the user requested adding a sticky top navbar and a left-side persistent sidebar navigator panel.

### 18.2 Fix
- **Two-Column Split Design:** Re-designed the layout using CSS Grid/Flexbox (`max-width: 1280px`) to place a 280px sticky sidebar on the left and the main content on the right.
- **Scrollspy:** Added a native JavaScript `IntersectionObserver` or scroll tracker to dynamically toggle the `active` class on sidebar items, highlighting the current section in blue as the user scrolls.
- **Sticky Navbar:** Cleaned up the top navigation bar to feature only the brand logo on the left and a "Contact us" link pointing to `deepak.bholusaria.com` on the right (opening in a new tab).

---

## 19. ITD Portal Login Resilience for Non-Existent PANs (2026-06-19)

### 19.1 Context
If a user initiates a batch run containing a PAN that does not exist or is not registered on the ITD portal, the automation would previously click "Continue" and hang waiting for the password/SAM checkbox to appear, eventually timing out after 60 seconds.

### 19.2 Fix
Updated `automation/auth.py` to check for inline error messages (e.g. "PAN does not exist" or "PAN is not registered") immediately after entering the PAN. If detected, it throws a `RuntimeError` immediately, allowing the orchestrator to fail fast, close the browser context, and proceed to the next client in the batch.

---

## 20. Client Table "Last Download Time" Column (2026-06-19)

### 20.1 Context
To improve tracking of client downloads, a column indicating when the last successful download occurred was added to the main client list grid.

### 20.2 Fix
- Added `Last Download Time` to the table column headers and adjusted cell widths.
- Updated `vault.py` and `tax_vault.json` to store the date/time of successful runs.
- Populated the column dynamically on table initialization, displaying a dash ("-") if no history exists.

---

## 21. Help Manual Content & Navigation Expansion (2026-06-19)

### 21.1 Context
Following the layout overhaul, the user requested an expansion of the help manual content to cover client management, bulk download procedures (26AS and AIS/TIS), SMTP email configuration, and software update instructions. The sidebar navigator was also required to support deep sub-section highlights.

### 21.2 Fix
- **Renamed Client Vault to Managing Clients:** Rebranded all references to "Client Vault" to "Managing Clients" and nested a detailed section on bulk Excel importing and exporting directly beneath profile creation instructions.
- **Bulk Download Step-by-Step Guides:** Added comprehensive instructions explaining how to select clients and Assessment Years, how to run bulk downloads for Form 26AS, AIS, and TIS, and specific menu option commands (toolbar dropdown, run dropdown, right-click context menu).
- **SMTP Setup and Reference Panel:** Detailed the exact email setup flow, specifying Gmail App Passwords, Office 365 port settings (587 with STARTTLS), CC/BCC backups, and how to use placeholders like `{client_name}`, `{pan}`, and `{documents}` in the template editor.
- **Auto-Update Documentation:** Included guidelines explaining the built-in auto-updater check on startup and manual update checks via the Help menu.
- **Granular Sidebar Navigation & Sub-sections:** Extended the left sidebar layout to support 37 interactive sections and sub-sections, styling them with nested indentation, and updated the JavaScript scrollspy tracker to resolve target IDs dynamically.

---

## 22. e-Proceedings Documents Download & Viewer (F-60) (2026-11-18)

### 22.1 Context
The ITD e-Filing portal exposes an **e-Proceedings** section (top bar "Pending
Actions" hover menu → "e-Proceedings") listing all notices/communications
issued to a taxpayer — assessment notices, letters, orders — plus the
taxpayer's own submitted responses with their attachments and acknowledgements.
Until now the app ignored this section entirely, so a CA had to log in manually
per client to collect these PDFs. F-60 adds it as a first-class document type
with the uniform handler contract, and a viewer inside the app.

Key facts confirmed live (Playwright exploration on 3 test PANs, 2026-11-18):

- Navigation must click the hover-menu **button** (`.cdk-overlay-pane button`
  containing "e-Proceedings"), not the `<span>` — the span does nothing.
  In-page SPA route: `#/dashboard/eProceedings`.
- Two tabs: "For your Action (n)" / "For your Information (n)"; proceeding
  cards (`.mat-mdc-card`) render only for the active tab and re-render on
  tab switch. Name `.heading5.mNoWrap.mEclipse`, AY
  `.ass_yr_spacing .heading5`, status `.stepperStatus`. Mat-paginator
  paginates at 10/page — must page through.
- Per proceeding: "View Notices/Orders (n)" →
  `#/dashboard/eProceedings/viewNotices/all` — one block per notice
  (Reference ID, section, DIN, issued/due dates) with buttons
  "Notice/Letter Pdf", optional "View Response", optional
  "Seek/View Adjournment" (never clicked).
- "Notice/Letter Pdf" → in-page `viewDetailedNotice` route; filename in
  `.subtitle2.fileName`, download via `button.downloadPdf` (one per
  attachment card). "View Response" → `viewResponse` route; attachments are
  `span.hyperLink` entries plus an "Acknowledgement" button
  (`aria-label="Download Acknowledgement"`).
- **PDFs are NOT password-protected** — except a couple of client-uploaded
  response attachments which are owner-encrypted; the downloader strips the
  owner encryption in-place with pikepdf (`_strip_owner_encryption`).
- AY is often "Not Available" on proceedings — e-Proceedings is not
  year-scoped, so the download is one pass per client and the terminal status
  is recorded against **every** selected year.
- Empty state: "No e-Proceedings records are found" → ⬜ status.
- Portal popups ("account deactivated", Outstanding Demand, Disclaimer) are
  dismissed defensively during the flow.

### 22.2 Fix
- **`automation/downloader_e_proceedings.py`** (new):
  `download_e_proceedings(page, download_root, log_callback, pan,
  is_running=None) -> (ok, msg, saved[])` following the Filed Returns module
  pattern (step logger, per-artifact download, never aborts the batch on one
  failure). Both tabs are iterated, per-proceeding "View Notices/Orders"
  opened, per-notice "Notice/Letter Pdf" → Detailed Notices →
  `button.downloadPdf`, "View Response" → `span.hyperLink` attachments +
  Acknowledgement. Files land in
  `<client>/<AY>/e-Proceedings/<NN>-<ProcName>/notice-NN|response-NN/`
  keeping portal-suggested filenames. Hardened during live testing:
  `.card-container` anchoring, disabled-button filtering,
  popup-vs-in-page viewer resolution (`_resolve_viewer_page`), and
  `wait_for_selector` resilience for slow re-renders.
- **`automation/batch_handlers.py`**: `handle_e_proceedings` (uniform handler
  contract), registered in `HANDLERS["e_proceedings"]`; `HANDLER_ORDER` runs
  it after Challans and before Request Previously-Filed AIS.
- **`automation/doc_types.py`**: `e_proceedings_pdf` entry
  (`emailable=False` until the emailer gains a 2-level glob).
- **Statuses**: "✅ e-Proceedings Downloaded (n file(s))" / "⬜ e-Proceedings
  — No e-Proceedings found" / "⚠ Partially Completed — <warn>" /
  "❌ e-Proceedings Failed — <msg>".
- **UI**: DownloadPickerDialog checkbox "e-Proceedings Documents"; inline
  Download Documents tab card; BatchProgressDialog + grid tooltip label maps
  updated.
- **Viewer (`EProceedingsDialog`, `ui/dialogs.py` ~4467)**: header (icon +
  "e-Proceedings — <client>" + PAN/root subtitle), summary strip
  (proceedings/files/total size), left list of proceedings
  ("NN-<Name> — N files"), right file list (name • human size •
  Notice/Response tag from notice-*/response-* subfolders), Open File
  (double-click) / Open Folder / Refresh, empty state with guidance.
  Scanning is pure `os.walk` over *.pdf/*.jpg/*.jpeg/*.png; theme tokens
  (`_t()`) only; opening via `config._open_path`. Wired into app.py:
  Tools menu "View e-Proceedings" (app.py:539), client-grid right-click
  entry (app.py:1374), launcher `_open_eproceedings_viewer` (app.py:3040)
  resolving the year folder exactly like `_execute_batch`.
- **Verification (live, 2026-11-18)**: [REDACTED_PAN] → ok, 73 files
  (70 PDF + 3 JPG), 18 proceedings, ~15 MB, one portal data-gap warning
  (a notice with no attachment); [REDACTED_PAN] → ok, 87 files, 7 proceedings,
  clean; [REDACTED_PAN] → 1 proceeding (account changed since exploration);
  the "No e-Proceedings records are found" → ⬜ branch verified. Offline:
  `test_e_proceedings_parse.py` 9/9 PASS; viewer smoke test 27/27 PASS;
  app restarted on DISPLAY=:1 with picker + viewer screenshots captured
  against real downloaded data (18 proceedings • 73 files • 13.9 MB).

---

## 23. e-Proceedings Incremental (Diff) Sync (F-2) (2026-11-19)

### 23.1 Context
The F-60 downloader re-downloaded **every** e-Proceedings notice and response
on each run (`_process_proceeding` clicked every "Notice/Letter Pdf" and
"View Response" button unconditionally), and `_dedupe_path` only avoided
overwriting — repeated syncs wasted time and accumulated duplicate files
("Notice (1).pdf", "Notice (2).pdf"…).

### 23.2 Fix
- **Diff-first sync** (`automation/downloader_e_proceedings.py`): before
  downloading, each proceeding's `_meta.json` is loaded and compared to the
  portal's current notice list by `(ref_id, issued_on)`. A notice/response
  already recorded there **and** still present on disk is skipped — no portal
  click, no download. Unknown/blank `ref_id` is never treated as present, so
  it always re-fetches (safe fallback).
- **New pure helpers** (stdlib only, unit-tested): `_notice_key`,
  `_load_existing_meta`, `_meta_entries_by_key`, `_files_present`,
  `_synced_keys`, `_merge_rel_files`, `_diff_build_meta`.
- **Merged `_meta.json`**: `_diff_build_meta` preserves previously-synced
  entries (existing file paths, plus `response_files`) and only fills in the
  fresh paths for new/changed notices. Entries the portal no longer shows are
  kept (renumbered past the current list so doc ids stay unique).
- **Correct response mapping**: "View Response" buttons render only for
  responded notices, so button `j` now maps to the `j`-th responded notice
  and files land in `response-NN/` keyed by the matching notice — previously
  the loop used the raw button index, which could mismatch folders when not
  every notice had a response.
- **Entry point / handler**: `download_e_proceedings` returns
  `ok=True, msg="Up to date (N unchanged)", saved=[]` when nothing new was
  fetched; `handle_e_proceedings` shows
  `✅ e-Proceedings — Up to date (N unchanged)` instead of a failure.
- **Log line**: `Sync summary: X new file(s), Y unchanged (skipped), Z warning(s)`.

### 23.3 Verification
- `test_e_proceedings_parse.py` → 16/16 PASS (7 new tests: notice key,
  corrupt/missing meta, files-present, synced keys, merge, diff-build for
  new+reused+hidden notices and appended response attachment).
- Simulated two-run scenario against a fake tree: run 2 over unchanged data
  queued **0** downloads; run 3 with one new notice queued **only** that
  notice's `ref_id`. `py_compile` clean on all touched files.

---

## 24. TDS/TCS Challan Generation (F-4)

Deductor-side TAN login → e-Pay Tax → Income-tax Act 2025 → New Payment →
Tax Year → Pay TDS/TCS. The wizard differs from the Income Tax challan flow:
deductee type + residence radios, a section-code dropdown (64 codes for
Other than Company + Resident), per-section Tax/Surcharge/Cess with Add,
then a read-only summary before payment mode. Payment-mode selection, CRN
parsing and artifact download are shared with F-64 via
`automation/challan_common.py`.

### 24.1 Live findings worth keeping

- A TAN never sees the "Income Tax" tile; the tiles page has its own
  mandatory Tax Year dropdown (`mat-select[formcontrolname='assessmentYear']`).
- The deductee radios must be checked through `input[value='0021']` /
  `input[value='resident']` — clicking the `mat-radio-button` host did not
  register live.
- A page-wide "Proceed" click hits the hidden `#okBtnNav3` modal button.
  Scope to `div.matcard` filtered by "Pay TDS/TCS".
- Section codes must be matched by the trailing numeric code
  (`re.search(r"-\s*1002$", option_text)`), never by label.
- Section amount inputs are three `input[formcontrolname='amount']` in order
  Tax, Surcharge, Education Cess. Common other payments are `interest`,
  `fee` (Late Fee u/s 427), `penalty`, `others`.
- The summary step reuses `taxAmt/surchargeAmt/cessAmt/interestAmt/
  feeAmt/penaltyAmt/othersAmt`, but read-only.
- Payment modes are the same five tabs and bank radios as F-64.

### 24.2 Implementation notes

- `vault.py` now accepts TANs as a second identity type (`id_type`), and
  DOB is optional for a TAN client.
- The 64-section list is a captured snapshot in
  `automation/data/tds_sections_other_than_company_resident.txt`; the
  generator maps by code against the live dropdown and fails a row with a
  clear reason if a code is no longer offered.
- v1 supports Other than Company + Resident only; Company / Non-Resident
  and Act 1961 move to a follow-up.

---

## 25. TDS/TCS Challan Download (F-8)

The existing F-61 downloader (`automation/downloader_challans.py`) was already
identity-agnostic: login → e-File > e-Pay Tax → Act from year type → Payment
History → filter by year → download PDFs. F-8 adds only a UI entry point and
TAN credentials — no portal-flow changes.

- `batch_handlers` registers a `tds_challans` doc-type alias pointing at the
  same `handle_challans` handler, so the existing batch runner,
  retry/resume and per-(client, year) progress rows are reused unchanged.
- The TDS hub gets a "Download TDS / TCS Challans" card. Its picker lists only
  TAN clients and the same year list as the Income Tax download.
- `BatchProgressDialog` takes an `id_label` so the identity column reads TAN.
- Files land in `{TAN}-{Name}/{AY|TY}_{year}/Tax Challans (Paid)/`, exactly
  like the Income Tax challan download.



---

## 26. Skip already-downloaded files on every flow (F-14 / #14)

**Problem:** e-Proceedings got an incremental diff sync in F-2, and Filed IT
Forms already skipped per artifact, but every other document type re-clicked
the portal and re-downloaded the same file on each run — 26AS, Form 168,
Filed Returns (Form/Receipt/JSON/Intimation and the ITR-Status Excel), Tax
Challans, and AIS/TIS Phase 1.

**Decision:** an issued ITD document is immutable — 26AS/168 for a closed
year, a challan keyed by CIN, a filed return keyed by Acknowledgement Number,
an intimation keyed by date. So a non-empty file at the deterministic output
path is treated as already downloaded. No hashing or content comparison.

**Implementation:**
- `automation/fs_util.py` — `is_present(path)` = exists AND size > 0;
  `skip_missing_required(path, log, label)` logs `[Skip] …`.
- `downloader_26as.py` — paths computed before the portal click; PDF and TXT
  guarded independently; both present returns early with "Already present
  (PDF + TXT)".
- `downloader_168.py` — per-artifact guards for PDF / ITD Excel / TXT.
- `downloader_challans.py` — deterministic `<pan>-Challan-<year>-<CIN>-<type>.pdf`
  checked before opening the ⋮ actions menu.
- `downloader_filed_returns.py` — `_download_one_file` now returns
  "downloaded" / "already_present" / "failed"; ITR-Status Excel guarded too;
  a year with nothing new reports "Up to date (N file(s) already present)".
- `downloader_ais_tis.py` — `download_tis`, `request_ais` and
  `download_ais_from_activity_history` return `already_present` before opening
  a modal, navigating Activity History, or unlocking.
- `batch_handlers.py` — "Already present" and "Up to date" map to a green
  ✅ status instead of a partial-failure warning.

**Trade-off:** if the portal ever re-issues a document for the same year, the
presence check will keep the old copy. Mitigation: delete the file to force a
re-download (documented in the changelog).

**Tests:** `test_fs_util.py` (5) and `test_f14_skip.py` (8) — empty file is
not "present", AIS/TIS/request/activity-history short-circuit before touching
Playwright, Filed Return artifact skips when present.

---

## 27. View Saved Challans (F-12)

Adds a read-only way to reopen challans already saved in earlier sessions.
The vault is deliberately not the source of truth: `record_download()` is
only written by the batch download pipeline, and both challan generators
(F-64 and F-4) never record their artifacts. The filesystem therefore backs
the index.

- `automation/challan_index.py` walks the configured download root and
  classifies files by their containing folder: `Tax Challans (Paid)` (and
  legacy `Challans` / `Tax Challans`) -> Paid; `Tax Challans (Payable)` (and
  legacy `Tax Challans (Generated)`) -> Unpaid. Client identity comes from the
  `{PAN|TAN}-{Name}` folder and is resolved to the current vault name; year
  comes from the `AY_/TY_` path segment, with a filename fallback for
  downloaded challans.
- `ui/challan_viewer.py` — `ViewChallansDialog`: client / status / year
  filters plus a search box, table (client, year, status, type, file, date,
  size), double-click to open, Open Folder, Refresh, and an empty state.
  Nothing is written and no portal login happens.
- `app.py` — entry points: E-Pay Tax menu -> View Challans..., Income Tax ->
  E-Pay Tax tab (secondary button), and the TDS hub (action card).
- `test_challan_viewer.py` — 5 test functions, all passing: folder
  classification, legacy names, TDS vs Income Tax filenames, year/identity
  parsing, sort order, filters, empty state, and open-file/open-folder
  routing (with `_open_path` patched).

---

## 28. Filed IT Forms Download — F-63 (2026-11-20)

Adds "Filed IT Forms" as a normal Download Documents option (alongside 26AS,
AIS/TIS, ITR, challans, e-Proceedings). It is a separate flow from
e-Proceedings: e-Proceedings is notices/orders/our replies; this is the forms
the assessee (or their CA) actually filed.

### Verified live (2026-11-20, assessee logins)

Evidence and per-client inventories: `PlansofThisProject/F-63_evidence/`.

- Path: e-File -> hover "Income Tax Forms" -> "View Filed Forms"
  (`#/dashboard/statForms/viewFiledForms`).
- Three Act tabs: 2025 / 1961 / Other Acts. Each tab shows category cards
  (`.eachMatCardStyle`) with the form description, code, filing count and
  latest AY/FY; 6 per page, paginated.
- Opening a category lists filings (`.subCard`), paginated. Each filing has
  Download Form, Download Receipt, and sometimes Download Attachments,
  Download JSON, Download XML.
- Form 3CD arrives inside the `3CB-3CD` / `3CA-3CD` "Download Form" ZIP
  (`form.pdf`, sometimes a generated CSV). Form 146 follows the same shape
  wherever it is filed, so no per-form code is needed.
- Portal filenames repeat across clients (`Form 35_Filed Form.pdf`), so
  every saved file is prefixed with the form code and acknowledgement number.
- The security modal ("browser Back/Refresh disabled — logout?") appears if
  the SPA route is changed via `window.location.hash`. Navigation therefore
  always uses menu clicks, and the modal is answered with **No** (never YES).
- Long scans can raise a "Session Timeout — Continue to stay logged in"
  modal; it is refreshed by clicking Continue, which previously caused a
  cascade of click timeouts on later filings.

### Implementation

- `automation/downloader_filed_forms.py`
  - Pure helpers (unit-tested): `form_code_from_text`, `filing_year_from_text`
    (FY for 15CA, AY otherwise), `parse_filing_text`, `filing_stem`,
    `artifact_path`, `existing_artifact`.
  - UI flow: `navigate_to_filed_forms`, act-tab loop, `_collect_categories`
    (both levels paginated), `_open_category`, `_process_category`,
    `_process_filing`, `_download_click`, `_download_attachments`.
  - Resilience: `_refresh_session` (Session Timeout), `_dismiss_modal`
    (never YES), `_stuck_reason` (detects a portal overlay and aborts the
    category instead of burning 45 s per remaining button).
  - Incremental: any artifact already on disk is skipped, so a re-run
    reports "✅ Filed IT Forms — Up to date (N file(s) already present)".
  - Output: `<client>/Filed IT Forms/<FormCode>/<AY|FY>/<FormCode>_<AckNo>_<Artifact>.<ext>`
    (attachments keep their portal extension under `_Attachments`, `_2`, ...).
- `automation/batch_handlers.py` — `handle_filed_forms` (not year-scoped;
  records the same status against every selected year) plus
  `DOC_TYPE_LABELS["filed_forms"]`; `HANDLER_ORDER` runs it immediately after
  Filed Returns, before 26AS (same e-File menu).
- `ui/dialogs.py` — "Filed IT Forms" checkbox in `DownloadPickerDialog`.
- `app.py` — "Filed IT Forms" card on the Download Documents tab and the grid
  status tooltip label.

### Live verification

- `AAAPL1234C` (placeholder): 15CA (1 filing) + 35 (2 filings) → 14 files, second run
  reports "Up to date (8 file(s) already present)", 0 downloads.
- `AAAPL5678F` (placeholder): 10IE (1) + 3CB-3CD (13) → ZIP forms, JSON, receipts and
  attachments downloaded; labelled "⚠ Partially Completed" for older 3CB-3CD
  filings whose buttons the portal itself blocks after the Session Timeout.
- Offline: `test_filed_forms.py` (9 tests) plus the existing
  `test_tds_challan.py` (18) and `test_e_proceedings_parse.py` (16) pass.

---

## 29. Scheduled e-Proceedings Auto-Fetch — F-13 (2026-11-21)

Adds an optional background scheduler for e-Proceedings, built on the
incremental sync from F-2 so repeat runs only fetch new/changed documents.

### Implementation

- `automation/eproc_scheduler.py` (new) — pure, no Qt/Playwright:
  - `normalise_config` (all settings validated and clamped; off by default)
  - `is_due` / `compute_next_run` (run time, active days, back-off window)
  - `in_scope` (all / group / selected PANs; excludes password-flagged clients)
  - `assign_split` (1–3 day cycle, balanced by client count or whole groups)
  - `assign_rotation` / `build_queue` (alternate starting cases, clients-per-day
    cap, persisted remainder, distribution phase)
  - `cooldown_for` (jitter), `should_backoff`, `is_timeout`,
    `interruptible_sleep` (pause-aware), `estimate_nights`.
- `vault.py` — per-client `credential_invalid`; preserved when a client is
  edited with the same password and cleared when the password actually changes.
  Config accessors store the scheduler state in `settings.eproc_autofetch`.
- `ui/dialogs.py` — `EAutoFetchSettingsDialog` (time, days, scope, clients per
  day with a nights estimate, distribution, split boundary, alternate cases,
  cooldowns, retries, back-off choice, Stop behaviour) and
  `BatchProgressDialog` controls: Pause/Resume, Restart, Skip Future, countdown
  line.
- `app.py` — 60-second `QTimer` tick, per-client background worker (login,
  e-Proceedings handler, cooldown, timeout retry), credential flagging with
  notification, rate-limit back-off, queue persistence after every client,
  restart/skip/pause controls, settings status line and grid warning.
- `automation/downloader_e_proceedings.py`, `automation/batch_handlers.py` —
  optional `before_download` hook so the document cooldown is honoured; manual
  runs pass nothing and behave exactly as before.

### Verification

- `test_eproc_scheduler.py` (new): 21 checks — config defaults/clamps, due time,
  back-off, next-run day skipping, scope filtering, credential exclusion,
  1/2/3-day split, group boundary, clients-per-day cap, queue continuation,
  rotation, alternate cases, cooldown range, rate-limit/timeout detection,
  nights estimate, vault flag and password-clear.
- Existing `test_e_proceedings_parse.py` (16) and `test_tds_challan.py` pass.
- `compileall` clean; `git diff --check` clean.
- Offscreen UI checks: main window builds, settings dialog saves without losing
  queue/rotation state, progress controls render, auto-fetch start/finish.
- Simulated worker runs (no browser): successful sync, wrong-password flag +
  notification, timeout retry, and rate-limit back-off with queue retention.

### Not yet verified

A supervised real-portal auto-fetch run with live client credentials. All
browser interaction paths are the existing manual e-Proceedings code.

---

## Virtual hearings (VC) in e-Proceedings — F-118 (#118)

**Goal.** Capture the virtual-conferencing (video hearing) data some faceless
proceedings expose, alongside notices/orders/responses.

**Confirmed live (2026-11-23, AABCP1234F & AABCP1235G).** Virtual hearings
appear only in faceless proceedings (assessment u/s 147/148A, first appeals,
penalties). On the View Notices screen a notice may carry a third button
`Seek Video Conferencing` (non-faceless shows `Seek/View Adjournment`). It
opens `#/dashboard/eProceedings/viewNotices/seekVideoConferencing`, an ag-Grid
request table with columns `date` (request date), `rfsvca` (reason),
`vcdt` (VC date & time), `sa` (status), `itdrd` (ITD response date),
`vcld` (VC Recording link), `itdR` (VC Schedule Notice / Status and VC
recording). Each hyperlink opens an `#attachmentsPopup` modal; the recording
modal shows a `.webm` URL; the Schedule Notice / Minutes-of-Meeting modals
download PDFs. The live join link + password live in `#linkPassModal` and are
only populated within 2 hours of the scheduled time. Three states observed:
(a) request form only (can apply), (b) open request awaiting schedule (VC date
"-"), (c) scheduled/completed (full details + recording).

**Design.**
- `automation/downloader_e_proceedings.py`: pure `_parse_vc_table` (normalizes
  '-' placeholders), `_hearing_key` (ref + VC date, falling back to request
  date), `_merge_hearings`, `_synced_hearing_*`; async readers
  `_vc_button_notice_refs`, `_read_vc_rows`, `_vc_recording_url`,
  `_vc_join_credentials`, `_download_vc_pdf`, `_sync_notice_hearing`. Integrated
  into `_process_proceeding` after the notice-PDF loop; meta gains `hearings[]`
  and `vc_requestable`. Recording is stored as a link only.
- `ui/eproceedings_model.py`: new `Hearing` dataclass; `Case.hearings` and
  `Case.vc_requestable` parsed from `_meta.json`.
- `ui/eproceedings.py`: Overview "Virtual hearings" card — date/time/status,
  recording + join buttons (open in browser), schedule/Minutes PDFs, and a
  banner when a VC can still be requested. Open requests show
  "Requested … — awaiting schedule".
- Navigation robustness: `navigate_to_e_proceedings` now no-ops when already on
  the e-Proceedings route (resumed sessions), fixing a hover-menu failure.

**Verification.**
- `test_e_proceedings_parse.py` extended with VC parser, key, sync-helper,
  merge and model tests — 23/23 pass.
- Live AABCP1235G: VC buttons located on First Appeal (open request), Penalty
  (open request), Assessment u/s 147 (scheduled 07-Mar-2024, Approved → past)
  and 148A (request form). Targeted run on 147 captured the hearing row and
  downloaded its VC Schedule Notice PDF into `vc-01/`.

**Deferred.** Downloading the `.webm` recording file (link only, per decision);
the join link/password appear only inside the 2-hour window.

## 30. Order attachments visible in the timeline — B-123 (2026-11-24)

Issue #123: clicking an order in the e-Proceedings timeline showed no
documents, even though an order normally carries an Order/Assessment Order,
a Demand Notice and a Computation Sheet.

### Root cause

The downloader already saved every document from one "Closure Order" modal
into the order entry's `files` list, and the model put that whole list on one
`Doc`. The UI lost them: `EprocDocModal` had no documents section and the
timeline card only linked `doc.files[0]`.

### Implementation

- `automation/doc_types.py` — new `e_proceeding_doc_label()` (filename ->
  Order / Demand Notice / Computation Sheet) and
  `e_proceeding_attachment_text()` (one-line card summary).
- `automation/downloader_e_proceedings.py` — `_order_title` now delegates to
  the shared label helper, so stored titles and displayed labels cannot drift.
- `ui/eproc_doc_modal.py` — new Documents section lists every file on the
  document, with its type label, filename and an Open button.
- `ui/eproc_timeline.py` — multi-file documents show
  "N documents: Order · Demand Notice · Computation Sheet" on the card.
- `ui/eproceedings_model.py` — a `_meta.json` with orders but no notices now
  builds from meta instead of falling back to the legacy scan, so its
  attachments stay grouped.

### Verification

- New tests: `test_eproc_order_labels.py`, `test_eproc_doc_modal.py`,
  `test_eproc_order_grouping.py`.
- Passing: the three new files plus `test_e_proceedings_parse.py`,
  `test_eproc_case_open.py`, `test_eproc_viewed_by_ao.py`,
  `test_litigation_store.py`, `test_litigation_adapter.py` and
  `test_no_real_identifiers.py` (60 tests).
- Offscreen check: an order doc with three files renders three modal rows and
  the timeline summary lists all three labels.

### Not yet verified

A live portal download after this change. Existing downloads already contain
the files, so no re-download is needed.

## 31. Closure-order modal saves every document — B-126 (2026-11-25)

Issue #126: the "Download Closure Order" modal can list several documents
(Order / Demand Notice / Computation Sheet, or the penalty equivalents), but
the downloader saved only the first one and dropped the rest.

### Root cause

`_download_proceeding_orders` clicked `_visible_download_button(page)` in a
loop. That helper always returns the _first_ visible Download button, so after
the first download it returned the same button again; the duplicate-filename
guard then ended the loop and the other rows were never clicked.

### Implementation

- `automation/downloader_e_proceedings.py` — new pure
  `_order_download_targets()` (dedupes blank/repeated filenames, keeps printed
  order) and `_read_order_modal_rows()` (reads `#downloadClosurePopup`
  `.row.marginTopModel` → `.modelName` + its button). The order loop now clicks
  each row's own Download button by index, with a generic all-buttons fallback
  for overlays without rows. Modal closing now targets
  `#downloadClosurePopup` first so the overlay cannot block the next card.

### Verification

- New `test_eproc_order_download_rows.py`; together with the #123 tests,
  `test_e_proceedings_parse.py`, `test_eproc_case_open.py`,
  `test_eproc_viewed_by_ao.py` and `test_no_real_identifiers.py`: 57 pass.
- Live portal run into a clean folder: the 3-document assessment and penalty
  modals each saved all three files; single-document modals saved one. A second
  run reported every order document "Cached (unchanged)" — no duplicates.

### Not yet verified

The "For your Information" tab click still occasionally times out at the end
of a run when a lingering overlay blocks it (order downloads themselves were
verified). Folders downloaded before this fix still lack their extra order
documents — re-running e-Proceedings for those clients will fill them in.
