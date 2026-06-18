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
[AIS-DL]   (5) Download saved: AEKPB0205L-AIS-2025_26.pdf

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

## 16. Status (as of 2026-06-15)

All v1.4.4 fixes shipped. Current known open items:

- **B-02** — PDF unlock fails for some TIS/AIS files (non-standard password formulas)
- **B-05** — Duplicate records on re-import (vault upsert audit needed)
- **B-06** — Wrong DOB causes 26AS ZIP extraction to fail silently
- **B-07 / F-10** — Large 26AS on-demand flow via tdscpc.gov.in not yet automated
- **F-08** — AIS JSON download for oversized AIS (P3)
- **F-11–F-14** — Client groups, auto-update, log history, multi-AY download (backlog)

---

## 17. AIS Documentation Update — Security Class Enum Mappings (2026-06-18)

### 17.1 Context
In the Compliance Portal / AIS JSON schema, the `info_code` (e.g. `SFT-17-LES(M)` vs `SFT-17-EMF(M)`) and the `Security Class` enum codes (such as `LES`, `LPS`, `EMF`, etc.) are coupled. A specific transaction block under an `info_code` only consumes a subset of the security class enums. For example, `SFT-17-EMF(M)` only contains unit transactions (Security Class `EMF`), whereas Listed Equity Shares (`LES`) and Preference Shares (`LPS`) are strictly mapped under `SFT-17-LES(M)`.

### 17.2 Fix
Updated `Documentation/AIS_JSON_Tree.html` to add a new column "Consumed By (SFT Code)" to the "Security Class (SFT-17 & 18)" table, mapping each of the 10 enum codes to its corresponding SFT label.
